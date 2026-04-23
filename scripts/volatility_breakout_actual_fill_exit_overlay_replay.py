"""Actual-fill replay for volatility_breakout intraday exit overlay.

Codex 0008 analysis-only task. Lives under ``scripts/`` like the other
replay/analysis tools. Absolutely does not:

- call Upbit account/private endpoints
- place orders
- modify live bot / strategy / UI / KPI / settings
- enable paper/live

Input priority (first non-empty wins):

1. ``--orders-file <path>`` — a CSV exported by the user with columns
   ``timestamp,ticker,side,volume,price,gross_krw,fee_krw,net_krw``.
   Extra columns are ignored; blank ``net_krw`` is imputed from
   ``gross_krw ± fee_krw`` (``+`` for buy, ``-`` for sell).
2. Local ``state/*.json`` files. These files carry real bot orders but
   sells have ``price = null``; when the order note contains
   ``reason=stop_loss triggered (-X.XX%)`` we reconstruct the sell price
   from the matched buy using that percentage. Unreconstructable sells
   are reported as incomplete and skipped from the matched comparison.
3. Nothing — the script prints a clear instruction and exits without
   producing a report.

Per spec, logs are NOT scanned: ``logs/auto_coin_*.log`` mixes paper and
live entries in a way that would require brittle filters to reliably
distinguish. The CSV path is the recommended ground truth.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pyupbit

from auto_coin.data.candles import history_days_to_candles

AS_OF = "2026-04-24"
REPORT_PATH = Path(
    "reports/2026-04-24-volatility-breakout-actual-fill-exit-overlay-replay.json"
)
STATE_DIR = Path("state")

FEE_DEFAULT = 0.0005
SLIPPAGE_DEFAULT = 0.0005
CANDLE_WINDOW_BUFFER_DAYS = 2  # fetch buffer before first buy / after last sell
ATR_WINDOW = 14
MIN_TRADES_FOR_DECISION = 20  # per spec: "< 20 closed trades → RETEST_WITH_MORE_FILLS"
PNL_IMPROVEMENT_MIN_RATIO = 0.005  # 0.5% of total allocated cost

# Decision rules operate on relative improvement only; worst/best trade
# thresholds encoded here to keep classify_recommendation testable.
WORST_TRADE_DEGRADATION_MAX = 0.005  # worst trade may not worsen by more than +0.5% pct
BEST_TRADE_CUT_MAX = 0.02  # best trade may not lose more than 2 pct absolute


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Order:
    ts: pd.Timestamp  # naive KST local
    ticker: str
    side: str  # "buy" or "sell"
    volume: float
    price: float
    gross_krw: float
    fee_krw: float
    net_krw: float
    source: str  # "csv" | "state_file" | ...
    note: str = ""


@dataclass
class MatchedTrade:
    ticker: str
    buy_ts: pd.Timestamp
    sell_ts: pd.Timestamp
    volume: float
    buy_price: float
    sell_price: float
    buy_net_krw: float
    sell_net_krw: float
    baseline_pnl_krw: float
    baseline_return: float
    buy_note: str = ""
    sell_note: str = ""


@dataclass
class OverlayTradeResult:
    overlay: str
    trade_index: int
    ticker: str
    buy_ts: str
    sell_ts_baseline: str
    exit_ts_overlay: str
    exit_reason: str
    exit_price: float
    baseline_pnl_krw: float
    baseline_return: float
    overlay_pnl_krw: float
    overlay_return: float
    delta_pnl_krw: float
    delta_return: float


@dataclass
class OverlayAggregate:
    overlay: str
    total_trades: int = 0
    total_allocated_cost_krw: float = 0.0
    total_baseline_pnl_krw: float = 0.0
    total_overlay_pnl_krw: float = 0.0
    total_baseline_return_on_cost: float = 0.0
    total_overlay_return_on_cost: float = 0.0
    delta_pnl_krw: float = 0.0
    delta_return_on_cost: float = 0.0
    win_rate: float = 0.0
    avg_win_return: float = 0.0
    avg_loss_return: float = 0.0
    worst_trade_return: float = 0.0
    best_trade_return: float = 0.0
    early_exit_count: int = 0
    missed_gain_sum_krw: float = 0.0  # sum over trades where overlay exited earlier and baseline was better
    saved_loss_sum_krw: float = 0.0  # sum over trades where overlay exited earlier and avoided worse loss
    by_ticker: dict[str, dict[str, Any]] = field(default_factory=dict)
    exit_reason_counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Overlay configurations
# ---------------------------------------------------------------------------


OVERLAYS: dict[str, dict[str, Any]] = {
    "failed_breakout_60m": {
        "failed_breakout": True,
        "failed_breakout_min_minutes": 60,
        "trailing": False,
        "time_decay": False,
    },
    "failed_breakout_120m": {
        "failed_breakout": True,
        "failed_breakout_min_minutes": 120,
        "trailing": False,
        "time_decay": False,
    },
    "trailing_1p5_atr25": {
        "failed_breakout": False,
        "trailing": True,
        "trailing_activate": 0.015,
        "trailing_atr_mult": 2.5,
        "time_decay": False,
    },
    "trailing_2p0_atr30": {
        "failed_breakout": False,
        "trailing": True,
        "trailing_activate": 0.020,
        "trailing_atr_mult": 3.0,
        "time_decay": False,
    },
    "time_decay_4h_flat": {
        "failed_breakout": False,
        "trailing": False,
        "time_decay": True,
        "time_decay_hours": 4,
        "time_decay_profit_min": -0.003,
        "time_decay_profit_max": 0.002,
    },
    "all_conservative": {
        "failed_breakout": True,
        "failed_breakout_min_minutes": 120,
        "trailing": True,
        "trailing_activate": 0.015,
        "trailing_atr_mult": 2.5,
        "time_decay": True,
        "time_decay_hours": 4,
        "time_decay_profit_min": -0.003,
        "time_decay_profit_max": 0.002,
    },
}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _to_kst_naive(ts_str: str) -> pd.Timestamp:
    """Parse an ISO-like timestamp and convert to naive KST.

    Handles:
        2026-04-22 11:30
        2026-04-16T03:55:32+00:00
        2026-04-22 11:30:15
    """
    ts = pd.Timestamp(ts_str)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("Asia/Seoul").tz_localize(None)
    return ts


def parse_csv_orders(path: Path) -> list[Order]:
    content = path.read_text()
    reader = csv.DictReader(io.StringIO(content))
    orders: list[Order] = []
    for row in reader:
        side = (row.get("side") or "").strip().lower()
        if side not in {"buy", "sell"}:
            continue
        ticker = (row.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        ts = _to_kst_naive((row.get("timestamp") or "").strip())
        volume = float((row.get("volume") or "0").replace(",", "") or 0)
        price = float((row.get("price") or "0").replace(",", "") or 0)
        gross = float((row.get("gross_krw") or "0").replace(",", "") or 0)
        fee = float((row.get("fee_krw") or "0").replace(",", "") or 0)
        net_raw = (row.get("net_krw") or "").replace(",", "").strip()
        net = float(net_raw) if net_raw else (gross + fee if side == "buy" else gross - fee)
        orders.append(
            Order(
                ts=ts,
                ticker=ticker,
                side=side,
                volume=volume,
                price=price,
                gross_krw=gross,
                fee_krw=fee,
                net_krw=net,
                source="csv",
                note=str(row.get("note") or ""),
            )
        )
    return orders


_STOP_LOSS_PCT_RE = re.compile(r"reason=stop_loss[^()]*\(([-+]?\d+(?:\.\d+)?)%")


def parse_state_dir_orders(state_dir: Path, fee: float) -> tuple[list[Order], list[dict]]:
    """Parse all state/*.json files. Sells with null price are reconstructed
    from the note's stop-loss percentage where available; otherwise left
    out and reported as incomplete."""
    orders: list[Order] = []
    incomplete: list[dict] = []
    if not state_dir.exists():
        return orders, incomplete
    for json_path in sorted(state_dir.glob("*.json")):
        try:
            payload = json.loads(json_path.read_text())
        except json.JSONDecodeError:
            continue
        raw_orders = payload.get("orders") or []
        # Track cost basis of prior buys to derive sell prices for null-price
        # sells via stop-loss percentage (matched 1:1 FIFO inside the file).
        buy_queue: list[dict] = []
        for raw in raw_orders:
            side = (raw.get("side") or "").lower()
            ticker = raw.get("market") or ""
            ts = _to_kst_naive(raw.get("placed_at") or "")
            volume = float(raw.get("volume") or 0) or 0.0
            price = raw.get("price")
            krw = raw.get("krw_amount")
            note = str(raw.get("note") or "")
            if side == "buy":
                if price is None or krw is None:
                    incomplete.append({"file": json_path.name, "order": raw})
                    continue
                gross = float(krw)
                fee_krw = gross * fee
                orders.append(
                    Order(
                        ts=ts,
                        ticker=ticker,
                        side="buy",
                        volume=volume,
                        price=float(price),
                        gross_krw=gross,
                        fee_krw=fee_krw,
                        net_krw=gross + fee_krw,
                        source="state_file",
                        note=note,
                    )
                )
                buy_queue.append({"ts": ts, "price": float(price), "volume": volume})
                continue
            if side == "sell":
                reconstructed_price: float | None = None
                if price is not None:
                    reconstructed_price = float(price)
                else:
                    m = _STOP_LOSS_PCT_RE.search(note)
                    if m and buy_queue:
                        pct = float(m.group(1)) / 100.0
                        reconstructed_price = buy_queue[0]["price"] * (1.0 + pct)
                if reconstructed_price is None or volume <= 0:
                    incomplete.append({"file": json_path.name, "order": raw})
                    continue
                gross = reconstructed_price * volume
                fee_krw = gross * fee
                orders.append(
                    Order(
                        ts=ts,
                        ticker=ticker,
                        side="sell",
                        volume=volume,
                        price=reconstructed_price,
                        gross_krw=gross,
                        fee_krw=fee_krw,
                        net_krw=gross - fee_krw,
                        source="state_file_reconstructed",
                        note=note,
                    )
                )
                # Consume matched buy head for price reconstruction only.
                if buy_queue:
                    remaining = volume
                    while remaining > 1e-12 and buy_queue:
                        head = buy_queue[0]
                        take = min(head["volume"], remaining)
                        head["volume"] -= take
                        remaining -= take
                        if head["volume"] <= 1e-12:
                            buy_queue.pop(0)
    return orders, incomplete


def load_orders(
    orders_file: Path | None,
    state_dir: Path,
    fee: float,
) -> tuple[list[Order], list[dict], str]:
    if orders_file is not None:
        if not orders_file.exists():
            raise SystemExit(f"orders file not found: {orders_file}")
        return parse_csv_orders(orders_file), [], "csv"
    orders, incomplete = parse_state_dir_orders(state_dir, fee)
    source = "state_files" if orders else "none"
    return orders, incomplete, source


# ---------------------------------------------------------------------------
# FIFO match
# ---------------------------------------------------------------------------


def fifo_match(orders: list[Order]) -> tuple[list[MatchedTrade], list[Order], list[Order]]:
    """Match BUY → SELL by ticker using FIFO lots.

    Returns (matched_trades, unmatched_sells, open_buys).
    """
    matched: list[MatchedTrade] = []
    unmatched_sells: list[Order] = []
    buy_queue: dict[str, list[list[Any]]] = defaultdict(list)  # ticker → [[Order, remaining_volume], ...]
    for order in sorted(orders, key=lambda o: o.ts):
        if order.side == "buy":
            buy_queue[order.ticker].append([order, order.volume])
            continue
        remaining = order.volume
        any_match = False
        while remaining > 1e-12 and buy_queue[order.ticker]:
            buy, buy_remaining = buy_queue[order.ticker][0]
            take = min(buy_remaining, remaining)
            buy_cost_alloc = buy.net_krw * (take / buy.volume)
            sell_proceeds_alloc = order.net_krw * (take / order.volume)
            matched.append(
                MatchedTrade(
                    ticker=order.ticker,
                    buy_ts=buy.ts,
                    sell_ts=order.ts,
                    volume=take,
                    buy_price=buy.price,
                    sell_price=order.price,
                    buy_net_krw=buy_cost_alloc,
                    sell_net_krw=sell_proceeds_alloc,
                    baseline_pnl_krw=sell_proceeds_alloc - buy_cost_alloc,
                    baseline_return=(sell_proceeds_alloc - buy_cost_alloc) / buy_cost_alloc,
                    buy_note=buy.note,
                    sell_note=order.note,
                )
            )
            any_match = True
            remaining -= take
            buy_queue[order.ticker][0][1] -= take
            if buy_queue[order.ticker][0][1] <= 1e-12:
                buy_queue[order.ticker].pop(0)
        if remaining > 1e-12 and not any_match:
            unmatched_sells.append(order)
        elif remaining > 1e-12:
            # Partial unmatched — record remaining as unmatched sell for
            # transparency (the matched portion is already captured above).
            unmatched_sells.append(
                Order(
                    ts=order.ts,
                    ticker=order.ticker,
                    side="sell",
                    volume=remaining,
                    price=order.price,
                    gross_krw=order.gross_krw * (remaining / order.volume),
                    fee_krw=order.fee_krw * (remaining / order.volume),
                    net_krw=order.net_krw * (remaining / order.volume),
                    source=order.source,
                    note=order.note + " | partial-unmatched",
                )
            )
    open_buys: list[Order] = []
    for lots in buy_queue.values():
        for buy, remaining_vol in lots:
            if remaining_vol > 1e-12:
                remaining_order = Order(
                    ts=buy.ts,
                    ticker=buy.ticker,
                    side="buy",
                    volume=remaining_vol,
                    price=buy.price,
                    gross_krw=buy.gross_krw * (remaining_vol / buy.volume),
                    fee_krw=buy.fee_krw * (remaining_vol / buy.volume),
                    net_krw=buy.net_krw * (remaining_vol / buy.volume),
                    source=buy.source,
                    note=buy.note + " | open-lot",
                )
                open_buys.append(remaining_order)
    return matched, unmatched_sells, open_buys


# ---------------------------------------------------------------------------
# Candle fetch + ATR
# ---------------------------------------------------------------------------


def _fetch_candles(ticker: str, interval: str, days: int) -> pd.DataFrame:
    count = history_days_to_candles(days, interval)
    chunks: list[pd.DataFrame] = []
    to: str | None = None
    chunk_size = min(count, 5000)
    while sum(len(c) for c in chunks) < count:
        remaining = count - sum(len(c) for c in chunks)
        request_count = min(chunk_size, remaining)
        df = None
        for attempt in range(3):
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=request_count, to=to)
            if df is not None and not df.empty:
                break
            print(f"retry fetch {ticker} {interval} attempt={attempt + 2}/3")
            time.sleep(0.25)
        if df is None or df.empty:
            if chunks:
                break
            raise SystemExit(f"failed to fetch {interval} candles for {ticker}")
        chunks.append(df)
        oldest = df.index[0]
        to = oldest.strftime("%Y-%m-%d %H:%M:%S")
        time.sleep(0.12)
        if len(df) < request_count:
            break
    out = pd.concat(chunks).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out.tail(count)


def _atr_series(thirty: pd.DataFrame, window: int) -> pd.Series:
    high = thirty["high"]
    low = thirty["low"]
    prev_close = thirty["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window).mean()


# ---------------------------------------------------------------------------
# Overlay per-trade simulation
# ---------------------------------------------------------------------------


def simulate_overlay_on_trade(
    trade: MatchedTrade,
    candles: pd.DataFrame,
    atr_series: pd.Series,
    overlay_name: str,
    overlay_cfg: dict[str, Any],
    fee: float,
    slippage: float,
) -> OverlayTradeResult:
    """Walk 30m bars strictly between buy_ts and sell_ts; earliest overlay wins.

    If no overlay triggers, return the actual baseline sell result unchanged
    (exit_reason = "actual_sell", no hypothetical frictions applied).
    """
    bars = candles.loc[(candles.index > trade.buy_ts) & (candles.index < trade.sell_ts)]
    entry_price = trade.buy_price
    failure_line = trade.buy_price
    highest_high = entry_price
    exit_reason = "actual_sell"
    exit_ts: pd.Timestamp = trade.sell_ts
    exit_price: float = trade.sell_price

    for ts, bar in bars.iterrows():
        hold_minutes = (ts - trade.buy_ts).total_seconds() / 60.0
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        highest_high = max(highest_high, high)
        intra_max_profit = (highest_high / entry_price) - 1.0
        intra_close_profit = (close / entry_price) - 1.0

        if (
            overlay_cfg.get("failed_breakout")
            and hold_minutes >= overlay_cfg.get("failed_breakout_min_minutes", 60)
            and close < failure_line
        ):
            exit_reason = f"failed_breakout_{int(overlay_cfg['failed_breakout_min_minutes'])}m"
            exit_ts = ts
            exit_price = close
            break

        if (
            overlay_cfg.get("trailing")
            and intra_max_profit >= overlay_cfg.get("trailing_activate", 0.015)
        ):
            atr_val = atr_series.get(ts)
            if atr_val is not None and pd.notna(atr_val):
                trailing_stop = highest_high - float(atr_val) * overlay_cfg.get(
                    "trailing_atr_mult", 2.5
                )
            else:
                trailing_stop = highest_high * (1.0 - 0.01)
            if low <= trailing_stop:
                exit_reason = (
                    f"trailing_{int(round(overlay_cfg['trailing_activate'] * 1000))}"
                    f"permil_atr{int(round(overlay_cfg['trailing_atr_mult'] * 10))}"
                )
                exit_ts = ts
                exit_price = min(max(trailing_stop, low), high)
                break

        if (
            overlay_cfg.get("time_decay")
            and hold_minutes >= overlay_cfg.get("time_decay_hours", 4) * 60
            and overlay_cfg.get("time_decay_profit_min", -0.003)
            <= intra_close_profit
            <= overlay_cfg.get("time_decay_profit_max", 0.002)
        ):
            exit_reason = f"time_decay_{int(overlay_cfg['time_decay_hours'])}h_flat"
            exit_ts = ts
            exit_price = close
            break

    if exit_reason == "actual_sell":
        overlay_pnl_krw = trade.baseline_pnl_krw
        overlay_return = trade.baseline_return
        overlay_exit_price = trade.sell_price
    else:
        sell_fill = exit_price * (1.0 - slippage)
        sell_gross = sell_fill * trade.volume
        sell_fee = sell_gross * fee
        overlay_sell_net = sell_gross - sell_fee
        overlay_pnl_krw = overlay_sell_net - trade.buy_net_krw
        overlay_return = overlay_pnl_krw / trade.buy_net_krw
        overlay_exit_price = exit_price

    return OverlayTradeResult(
        overlay=overlay_name,
        trade_index=0,  # populated by caller
        ticker=trade.ticker,
        buy_ts=trade.buy_ts.isoformat(),
        sell_ts_baseline=trade.sell_ts.isoformat(),
        exit_ts_overlay=exit_ts.isoformat() if exit_reason != "actual_sell" else trade.sell_ts.isoformat(),
        exit_reason=exit_reason,
        exit_price=overlay_exit_price,
        baseline_pnl_krw=trade.baseline_pnl_krw,
        baseline_return=trade.baseline_return,
        overlay_pnl_krw=overlay_pnl_krw,
        overlay_return=overlay_return,
        delta_pnl_krw=overlay_pnl_krw - trade.baseline_pnl_krw,
        delta_return=overlay_return - trade.baseline_return,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_overlay(
    overlay_name: str,
    results: list[OverlayTradeResult],
    trades: list[MatchedTrade],
) -> OverlayAggregate:
    agg = OverlayAggregate(overlay=overlay_name)
    if not results:
        return agg
    agg.total_trades = len(results)
    agg.total_allocated_cost_krw = sum(t.buy_net_krw for t in trades)
    agg.total_baseline_pnl_krw = sum(r.baseline_pnl_krw for r in results)
    agg.total_overlay_pnl_krw = sum(r.overlay_pnl_krw for r in results)
    cost = agg.total_allocated_cost_krw or 1.0
    agg.total_baseline_return_on_cost = agg.total_baseline_pnl_krw / cost
    agg.total_overlay_return_on_cost = agg.total_overlay_pnl_krw / cost
    agg.delta_pnl_krw = agg.total_overlay_pnl_krw - agg.total_baseline_pnl_krw
    agg.delta_return_on_cost = agg.delta_pnl_krw / cost
    overlay_returns = [r.overlay_return for r in results]
    wins = [r for r in results if r.overlay_return > 0]
    losses = [r for r in results if r.overlay_return <= 0]
    agg.win_rate = len(wins) / len(results)
    agg.avg_win_return = sum(r.overlay_return for r in wins) / len(wins) if wins else 0.0
    agg.avg_loss_return = sum(r.overlay_return for r in losses) / len(losses) if losses else 0.0
    agg.worst_trade_return = min(overlay_returns)
    agg.best_trade_return = max(overlay_returns)
    agg.early_exit_count = sum(1 for r in results if r.exit_reason != "actual_sell")
    for r in results:
        if r.exit_reason == "actual_sell":
            continue
        d_pnl = r.overlay_pnl_krw - r.baseline_pnl_krw
        if d_pnl < 0:
            agg.missed_gain_sum_krw += -d_pnl  # positive magnitude of forgone gain
        else:
            agg.saved_loss_sum_krw += d_pnl
    by_ticker: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "trades": 0,
            "total_overlay_pnl_krw": 0.0,
            "total_baseline_pnl_krw": 0.0,
            "delta_pnl_krw": 0.0,
            "early_exits": 0,
        }
    )
    for r in results:
        bucket = by_ticker[r.ticker]
        bucket["trades"] += 1
        bucket["total_overlay_pnl_krw"] += r.overlay_pnl_krw
        bucket["total_baseline_pnl_krw"] += r.baseline_pnl_krw
        bucket["delta_pnl_krw"] += r.overlay_pnl_krw - r.baseline_pnl_krw
        if r.exit_reason != "actual_sell":
            bucket["early_exits"] += 1
    agg.by_ticker = dict(by_ticker)
    reason_counts: dict[str, int] = defaultdict(int)
    for r in results:
        reason_counts[r.exit_reason] += 1
    agg.exit_reason_counts = dict(reason_counts)
    return agg


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------


def classify_recommendation(
    baseline_cost: float,
    aggregates: dict[str, OverlayAggregate],
    matched_count: int,
) -> dict[str, Any]:
    if matched_count < MIN_TRADES_FOR_DECISION:
        return {
            "label": "RETEST_WITH_MORE_FILLS",
            "reason": (
                f"Only {matched_count} matched closed trades available "
                f"(< {MIN_TRADES_FOR_DECISION}). Codex 0008 decision rule "
                "requires more fills before an overlay verdict can be issued."
            ),
            "matched_count": matched_count,
        }
    if not aggregates:
        return {
            "label": "RETEST_WITH_MORE_FILLS",
            "reason": "no overlay aggregates computed",
            "matched_count": matched_count,
        }
    # Baseline is the same across overlays — use any single aggregate's baseline
    # return/worst/best. Pick the first deterministically.
    ref = next(iter(aggregates.values()))
    baseline_return_on_cost = ref.total_baseline_return_on_cost
    baseline_trades_returns = [
        # baseline per-trade returns are embedded inside per-overlay results;
        # approximate here from aggregate values for worst/best.
        ref.worst_trade_return - ref.delta_return_on_cost,
        ref.best_trade_return - ref.delta_return_on_cost,
    ]
    baseline_worst = min(baseline_trades_returns)
    baseline_best = max(baseline_trades_returns)

    qualifying: list[tuple[str, OverlayAggregate]] = []
    trailing_improves_worst: list[tuple[str, OverlayAggregate]] = []
    for name, agg in aggregates.items():
        d_return = agg.delta_return_on_cost
        worst_delta = agg.worst_trade_return - baseline_worst
        best_delta = agg.best_trade_return - baseline_best
        if (
            d_return >= PNL_IMPROVEMENT_MIN_RATIO
            and worst_delta >= -WORST_TRADE_DEGRADATION_MAX
            and best_delta >= -BEST_TRADE_CUT_MAX
        ):
            qualifying.append((name, agg))
        if (
            "trailing" in name
            and worst_delta >= abs(WORST_TRADE_DEGRADATION_MAX)
            and agg.missed_gain_sum_krw <= 0.3 * baseline_cost
        ):
            trailing_improves_worst.append((name, agg))

    worse_pnl_count = sum(
        1 for a in aggregates.values() if a.total_overlay_pnl_krw < a.total_baseline_pnl_krw
    )
    total = len(aggregates)
    all_worse = worse_pnl_count == total

    if qualifying:
        qualifying.sort(key=lambda kv: kv[1].delta_pnl_krw, reverse=True)
        winner_name = qualifying[0][0]
        label = "CONSIDER_CONSERVATIVE_TRAILING" if "trailing" in winner_name else "ADD_SHADOW_ONLY"
        return {
            "label": label,
            "reason": (
                f"{winner_name} improves total PnL by "
                f"{qualifying[0][1].delta_return_on_cost:+.4%} of allocated cost "
                "without worsening worst/best trade beyond tolerance. This is "
                "analysis evidence only; live enable requires a Codex decision."
            ),
            "winner_overlay": winner_name,
            "baseline_return_on_cost": baseline_return_on_cost,
        }
    if trailing_improves_worst:
        trailing_improves_worst.sort(
            key=lambda kv: kv[1].worst_trade_return, reverse=True
        )
        winner = trailing_improves_worst[0][0]
        return {
            "label": "CONSIDER_CONSERVATIVE_TRAILING",
            "reason": (
                f"{winner} does not improve total PnL to the required threshold "
                "but materially improves worst trade with small missed gain "
                "— consider shadow-mode monitoring first."
            ),
            "winner_overlay": winner,
        }
    if all_worse:
        return {
            "label": "REJECT_OVERLAY",
            "reason": "Every tested overlay underperformed the actual-fill baseline.",
        }
    return {
        "label": "KEEP_ACTUAL_EXIT",
        "reason": (
            "No overlay improves total PnL by the 0.5% threshold without "
            "worsening worst/best trade. Keep actual-exit behaviour; revisit "
            "with more fills or narrower overlay variants if Codex issues a "
            "new spec."
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _instructions_for_missing_input() -> str:
    example = (
        "timestamp,ticker,side,volume,price,gross_krw,fee_krw,net_krw\n"
        "2026-04-22 11:30,KRW-ETH,buy,0.00731209,3483000,25468,12.73,25481\n"
        "2026-04-23 08:55,KRW-ETH,sell,0.00731209,3522000,25753,12.87,25740\n"
    )
    return (
        "No orders found.\n\n"
        "Place a CSV at data/manual/upbit_orders_<range>.csv with columns:\n\n"
        f"{example}\n"
        "Then rerun with --orders-file data/manual/upbit_orders_<range>.csv.\n"
        "The state/*.json fallback is also accepted; no orders means nothing "
        "to analyze."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--orders-file",
        type=Path,
        default=None,
        help="CSV export of real Upbit fills; see script docstring for schema.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=STATE_DIR,
        help="Fallback directory scanned for bot state JSON order history.",
    )
    parser.add_argument("--fee", type=float, default=FEE_DEFAULT)
    parser.add_argument("--slippage", type=float, default=SLIPPAGE_DEFAULT)
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)

    orders, incomplete, source = load_orders(args.orders_file, args.state_dir, args.fee)
    if not orders:
        print(_instructions_for_missing_input())
        return 2

    orders_by_ticker: dict[str, list[Order]] = defaultdict(list)
    for order in orders:
        orders_by_ticker[order.ticker].append(order)

    matched, unmatched_sells, open_buys = fifo_match(orders)
    period_start = min(o.ts for o in orders) if orders else None
    period_end = max(o.ts for o in orders) if orders else None
    tickers = sorted(orders_by_ticker.keys())
    days_span = (
        int((period_end - period_start).total_seconds() / 86400) + CANDLE_WINDOW_BUFFER_DAYS * 2
        if period_start is not None and period_end is not None
        else CANDLE_WINDOW_BUFFER_DAYS * 2
    )
    fetch_days = max(days_span + CANDLE_WINDOW_BUFFER_DAYS * 2, 14)

    print(
        f"parsed {len(orders)} orders ({source}) — "
        f"matched {len(matched)} closed trades, unmatched sells {len(unmatched_sells)}, "
        f"open buys {len(open_buys)}"
    )
    print(f"fetching 30m candles for {tickers} over ~{fetch_days}d")
    candles: dict[str, pd.DataFrame] = {}
    atrs: dict[str, pd.Series] = {}
    for ticker in tickers:
        candles[ticker] = _fetch_candles(ticker, "minute30", fetch_days)
        atrs[ticker] = _atr_series(candles[ticker], ATR_WINDOW)

    overlay_results: dict[str, list[OverlayTradeResult]] = {name: [] for name in OVERLAYS}
    for idx, trade in enumerate(matched):
        ticker = trade.ticker
        if ticker not in candles:
            continue
        for overlay_name, cfg in OVERLAYS.items():
            r = simulate_overlay_on_trade(
                trade=trade,
                candles=candles[ticker],
                atr_series=atrs[ticker],
                overlay_name=overlay_name,
                overlay_cfg=cfg,
                fee=args.fee,
                slippage=args.slippage,
            )
            r.trade_index = idx
            overlay_results[overlay_name].append(r)

    aggregates = {
        name: aggregate_overlay(name, results, matched)
        for name, results in overlay_results.items()
    }
    total_cost = sum(t.buy_net_krw for t in matched)
    total_baseline_pnl = sum(t.baseline_pnl_krw for t in matched)
    baseline_return_on_cost = total_baseline_pnl / total_cost if total_cost else 0.0
    recommendation = classify_recommendation(total_cost, aggregates, len(matched))

    report = {
        "as_of": AS_OF,
        "strategy": "volatility_breakout",
        "scope": (
            "actual-fill replay only; no strategy/live/paper/UI/KPI/settings changes"
        ),
        "input_source": source,
        "orders_file": str(args.orders_file) if args.orders_file else None,
        "fee": args.fee,
        "slippage": args.slippage,
        "period_start": period_start.isoformat() if period_start is not None else None,
        "period_end": period_end.isoformat() if period_end is not None else None,
        "tickers": tickers,
        "orders_parsed": len(orders),
        "matched_closed_trades": len(matched),
        "unmatched_sells": [asdict(o) for o in unmatched_sells],
        "open_buys": [asdict(o) for o in open_buys],
        "incomplete_orders_from_state": incomplete,
        "baseline_totals": {
            "total_allocated_cost_krw": total_cost,
            "total_baseline_pnl_krw": total_baseline_pnl,
            "total_baseline_return_on_cost": baseline_return_on_cost,
            "wins": sum(1 for t in matched if t.baseline_pnl_krw > 0),
            "losses": sum(1 for t in matched if t.baseline_pnl_krw <= 0),
        },
        "overlay_aggregates": {name: asdict(agg) for name, agg in aggregates.items()},
        "per_overlay_trades": {
            name: [asdict(r) for r in results]
            for name, results in overlay_results.items()
        },
        "recommendation": recommendation,
        "caveat": (
            "Actual-fill replay assumes hypothetical overlay sells would "
            "have been filled at the rule price with configured fee + "
            "slippage; real market conditions at overlay times may differ "
            "from the 30m OHLCV close/high/low snapshots."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(args.out)
    print(
        json.dumps(
            {
                "input_source": source,
                "matched_trades": len(matched),
                "baseline_return_on_cost": baseline_return_on_cost,
                "recommendation": recommendation,
                "overlay_summary": {
                    name: {
                        "total_overlay_pnl_krw": agg.total_overlay_pnl_krw,
                        "delta_pnl_krw": agg.delta_pnl_krw,
                        "delta_return_on_cost": agg.delta_return_on_cost,
                        "early_exit_count": agg.early_exit_count,
                        "missed_gain_sum_krw": agg.missed_gain_sum_krw,
                        "saved_loss_sum_krw": agg.saved_loss_sum_krw,
                        "worst_trade_return": agg.worst_trade_return,
                        "best_trade_return": agg.best_trade_return,
                    }
                    for name, agg in aggregates.items()
                },
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
