from __future__ import annotations

import argparse
import json
import math
import pickle
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pyupbit

from auto_coin.backtest.runner import DEFAULT_SLIPPAGE, UPBIT_DEFAULT_FEE
from auto_coin.data.candles import enrich_for_strategy
from auto_coin.strategy import create_strategy
from auto_coin.strategy.base import MarketSnapshot, Signal

TICKERS = ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP"]
INTERVALS = {
    "30m": {"pyupbit": "minute30", "count": 17520, "bar_hours": 0.5},
    "1h": {"pyupbit": "minute60", "count": 8760, "bar_hours": 1.0},
    "day": {"pyupbit": "day", "count": 365, "bar_hours": 24.0},
}
PERIODS = {"3m": 90, "6m": 180, "1y": 365}
DEFAULT_PARAMS = {
    "ema_period": 9,
    "vwap_period": 48,
    "ema_touch_tolerance": 0.003,
    "sideways_lookback": 12,
    "max_vwap_cross_count": 3,
    "min_ema_slope_ratio": 0.001,
    "require_bullish_candle": True,
    "use_volume_profile": False,
}


@dataclass
class SignalStats:
    ticker: str
    interval: str
    period: str
    start: str
    end: str
    candles: int
    buy: int
    sell: int
    hold: int
    trades: int
    avg_hold_bars: float
    avg_hold_time: str


@dataclass
class BacktestStats:
    ticker: str
    interval: str
    period: str
    total_return: float
    bh_return: float
    mdd: float
    win_rate: float
    trades: int
    avg_profit: float
    avg_loss: float
    profit_factor: float
    avg_hold_days: float
    fee: float
    slippage: float


def _cache_path(cache_dir: Path, ticker: str, interval: str, count: int) -> Path:
    safe = ticker.replace("-", "_")
    return cache_dir / f"{safe}_{interval}_{count}.pkl"


def fetch_ohlcv(ticker: str, interval: str, count: int, cache_dir: Path, refresh: bool = False) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, ticker, interval, count)
    if path.exists() and not refresh:
        with path.open("rb") as f:
            return pickle.load(f)
    st = time.time()
    df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
    if df is None or df.empty:
        raise RuntimeError(f"failed to fetch {ticker} {interval} count={count}")
    with path.open("wb") as f:
        pickle.dump(df, f)
    print(f"fetched {ticker} {interval} {len(df)} rows in {time.time()-st:.1f}s")
    return df


def enrich(raw: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    return enrich_for_strategy(raw, "vwap_ema_pullback", params)


def period_slice(df: pd.DataFrame, days: int) -> pd.DataFrame:
    end = df.index.max()
    start = end - pd.Timedelta(days=days)
    return df.loc[df.index >= start]


def _fmt_time(bars: float, bar_hours: float) -> str:
    if not math.isfinite(bars) or bars <= 0:
        return "0"
    hours = bars * bar_hours
    if hours < 48:
        return f"{hours:.1f}h"
    return f"{hours/24:.1f}d"


def simulate_signals(enriched: pd.DataFrame, params: dict[str, Any], ticker: str, interval: str, period: str, bar_hours: float):
    strategy = create_strategy("vwap_ema_pullback", params)
    has_position = False
    entry_price = None
    entry_ts = None
    entry_i = None
    counts = {Signal.BUY: 0, Signal.SELL: 0, Signal.HOLD: 0}
    trades = []
    buy_samples = []
    sell_samples = []

    for i, (ts, row) in enumerate(enriched.iterrows()):
        close = _finite(row.get("close"))
        if close is None:
            counts[Signal.HOLD] += 1
            continue
        snap = MarketSnapshot(df=enriched.iloc[: i + 1], current_price=close, has_position=has_position)
        sig = strategy.generate_signal(snap)
        counts[sig] += 1
        if sig is Signal.BUY and not has_position:
            has_position = True
            entry_price = close
            entry_ts = ts
            entry_i = i
            buy_samples.append({
                "timestamp": str(ts), "ticker": ticker, "interval": interval,
                "close": close, "vwap": _finite(row.get("vwap")), "ema9": _finite(row.get("ema9")),
                "low": _finite(row.get("low")), "open": _finite(row.get("open")),
                "is_bullish": bool(close > float(row.get("open"))),
                "vwap_cross_count": _finite(row.get("vwap_cross_count")),
                "ema_slope_ratio": _finite(row.get("ema_slope_ratio")),
                "is_sideways": bool(row.get("is_sideways")),
                "reason": "close>vwap, not sideways, EMA touch, bullish" if params.get("require_bullish_candle", True) else "close>vwap, not sideways, EMA touch",
            })
        elif sig is Signal.SELL and has_position and entry_price is not None and entry_i is not None:
            hold_bars = i - entry_i
            pnl = close / entry_price - 1.0
            trades.append({"entry_ts": str(entry_ts), "exit_ts": str(ts), "entry": entry_price, "exit": close, "hold_bars": hold_bars, "pnl": pnl})
            sell_samples.append({
                "timestamp": str(ts), "ticker": ticker, "interval": interval,
                "close": close, "ema9": _finite(row.get("ema9")), "entry_price": entry_price,
                "hold_bars": hold_bars, "pnl_ratio": pnl,
                "reason": "close<ema9",
            })
            has_position = False
            entry_price = None
            entry_ts = None
            entry_i = None
    avg_hold = sum(t["hold_bars"] for t in trades) / len(trades) if trades else 0.0
    stats = SignalStats(
        ticker=ticker, interval=interval, period=period,
        start=str(enriched.index.min()), end=str(enriched.index.max()), candles=len(enriched),
        buy=counts[Signal.BUY], sell=counts[Signal.SELL], hold=counts[Signal.HOLD],
        trades=len(trades), avg_hold_bars=avg_hold, avg_hold_time=_fmt_time(avg_hold, bar_hours),
    )
    return stats, trades, buy_samples, sell_samples


def backtest_stats(
    enriched: pd.DataFrame,
    params: dict[str, Any],
    ticker: str,
    interval: str,
    period: str,
    *,
    execution_mode: str = "same_close",
    cooldown_bars: int = 0,
) -> BacktestStats:
    trades = simulate_execution_trades(
        enriched, params, execution_mode=execution_mode, cooldown_bars=cooldown_bars,
    )
    rets = [t["ret"] for t in trades]
    equity = []
    cur = 1.0
    for r in rets:
        cur *= 1.0 + r
        equity.append(cur)
    total_return = cur - 1.0 if equity else 0.0
    if equity:
        peak = []
        p = equity[0]
        for e in equity:
            p = max(p, e)
            peak.append(p)
        mdd = min((e - p) / p for e, p in zip(equity, peak, strict=True))
    else:
        mdd = 0.0
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    win_rate = len(wins) / len(rets) if rets else 0.0
    avg_profit = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    gross_wins = sum(wins)
    gross_losses = abs(sum(losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 1e-10 else 99.99 if gross_wins > 0 else 0.0
    hold_days = [t["hold_bars"] * INTERVALS[interval]["bar_hours"] / 24.0 for t in trades]
    avg_hold_days = sum(hold_days) / len(hold_days) if hold_days else 0.0
    first_close = _finite(enriched.iloc[0].get("close"))
    last_close = _finite(enriched.iloc[-1].get("close"))
    benchmark = last_close / first_close - 1.0 if first_close and last_close else 0.0
    return BacktestStats(
        ticker=ticker, interval=interval, period=period,
        total_return=total_return, bh_return=benchmark, mdd=mdd,
        win_rate=win_rate, trades=len(trades), avg_profit=avg_profit, avg_loss=avg_loss,
        profit_factor=profit_factor, avg_hold_days=avg_hold_days,
        fee=UPBIT_DEFAULT_FEE, slippage=DEFAULT_SLIPPAGE,
    )


def simulate_execution_trades(
    enriched: pd.DataFrame,
    params: dict[str, Any],
    *,
    execution_mode: str = "same_close",
    mark_to_market: bool = True,
    cooldown_bars: int = 0,
) -> list[dict[str, Any]]:
    """Backtest 시뮬레이터.

    ``cooldown_bars > 0`` 일 때 직전 SELL exit 이후 N 캔들 동안 BUY 신호를 무시한다.
    live `cooldown_minutes` 정책의 backtest 등가물. ``cooldown_bars=0`` (기본) 이면
    기존 동작과 완전 동일 — 회귀 영향 없음.
    """
    if execution_mode not in {"same_close", "next_open"}:
        raise ValueError("execution_mode must be same_close or next_open")
    if cooldown_bars < 0:
        raise ValueError("cooldown_bars must be >= 0")
    strategy = create_strategy("vwap_ema_pullback", params)
    has_position = False
    entry_price: float | None = None
    entry_i: int | None = None
    entry_ts = None
    pending: Signal | None = None
    pending_i: int | None = None
    pending_ts = None
    last_exit_i: int | None = None
    trades: list[dict[str, Any]] = []

    for i, (ts, row) in enumerate(enriched.iterrows()):
        open_ = _finite(row.get("open"))
        close = _finite(row.get("close"))
        if close is None:
            continue

        if execution_mode == "next_open" and pending is not None:
            # Execute the previous candle's signal at this candle's open.
            if open_ is not None:
                if pending is Signal.BUY and not has_position:
                    entry_price = open_ * (1.0 + DEFAULT_SLIPPAGE)
                    entry_i = i
                    entry_ts = ts
                    has_position = True
                elif pending is Signal.SELL and has_position and entry_price is not None and entry_i is not None:
                    exit_price = open_ * (1.0 - DEFAULT_SLIPPAGE)
                    ret = (exit_price * (1.0 - UPBIT_DEFAULT_FEE)) / (entry_price * (1.0 + UPBIT_DEFAULT_FEE)) - 1.0
                    trades.append({
                        "entry_ts": str(entry_ts), "exit_ts": str(ts),
                        "entry": entry_price, "exit": exit_price,
                        "hold_bars": i - entry_i, "ret": ret,
                        "signal_ts": str(pending_ts), "signal_i": pending_i,
                    })
                    has_position = False
                    last_exit_i = i
                    entry_price = None
                    entry_i = None
                    entry_ts = None
            pending = None
            pending_i = None
            pending_ts = None

        snap = MarketSnapshot(df=enriched.iloc[: i + 1], current_price=close, has_position=has_position)
        sig = strategy.generate_signal(snap)

        # Re-entry cooldown: 직전 SELL exit 이후 N 캔들은 BUY 무시. flat 일 때만 적용.
        if (
            cooldown_bars > 0
            and sig is Signal.BUY
            and not has_position
            and last_exit_i is not None
            and (i - last_exit_i) <= cooldown_bars
        ):
            sig = Signal.HOLD

        if execution_mode == "same_close":
            if sig is Signal.BUY and not has_position:
                entry_price = close * (1.0 + DEFAULT_SLIPPAGE)
                entry_i = i
                entry_ts = ts
                has_position = True
            elif sig is Signal.SELL and has_position and entry_price is not None and entry_i is not None:
                exit_price = close * (1.0 - DEFAULT_SLIPPAGE)
                ret = (exit_price * (1.0 - UPBIT_DEFAULT_FEE)) / (entry_price * (1.0 + UPBIT_DEFAULT_FEE)) - 1.0
                trades.append({
                    "entry_ts": str(entry_ts), "exit_ts": str(ts),
                    "entry": entry_price, "exit": exit_price,
                    "hold_bars": i - entry_i, "ret": ret,
                    "signal_ts": str(ts), "signal_i": i,
                })
                has_position = False
                last_exit_i = i
                entry_price = None
                entry_i = None
                entry_ts = None
        elif i < len(enriched) - 1 and sig in {Signal.BUY, Signal.SELL}:
            # Last-candle signal is ignored because there is no next open.
            pending = sig
            pending_i = i
            pending_ts = ts

    if mark_to_market and has_position and entry_price is not None and entry_i is not None and len(enriched) > 0:
        ts = enriched.index[-1]
        close = _finite(enriched.iloc[-1].get("close"))
        if close is not None:
            exit_price = close * (1.0 - DEFAULT_SLIPPAGE)
            ret = (exit_price * (1.0 - UPBIT_DEFAULT_FEE)) / (entry_price * (1.0 + UPBIT_DEFAULT_FEE)) - 1.0
            trades.append({
                "entry_ts": str(entry_ts), "exit_ts": str(ts),
                "entry": entry_price, "exit": exit_price,
                "hold_bars": (len(enriched) - 1) - entry_i, "ret": ret,
                "signal_ts": str(ts), "signal_i": len(enriched) - 1,
                "exit_type": "mark_to_market",
            })

    return trades


def _finite(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def pct(v: float) -> str:
    return f"{v*100:+.2f}%"


def num(v: float, nd=3) -> str:
    if v is None or not math.isfinite(v):
        return ""
    return f"{v:.{nd}f}"


def markdown_table(rows: list[dict[str, Any]], headers: list[str]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |")
    return "\n".join(out)


def sensitivity(enriched_by_key: dict[tuple[str, str], pd.DataFrame]) -> list[dict[str, Any]]:
    tests = []
    specs = [
        ("ema_touch_tolerance", [0.003, 0.005, 0.01]),
        ("min_ema_slope_ratio", [0.0005, 0.001, 0.002]),
        ("max_vwap_cross_count", [2, 3, 5]),
        ("require_bullish_candle", [True, False]),
    ]
    for ticker in ["KRW-BTC", "KRW-ETH"]:
        for interval in ["30m", "1h"]:
            base_raw = enriched_by_key.get((ticker, interval))
            if base_raw is None:
                continue
            # Re-enrich for each param because slope/cross columns depend on params.
            raw = base_raw.attrs["raw"]
            for name, values in specs:
                for value in values:
                    params = dict(DEFAULT_PARAMS)
                    params[name] = value
                    e = period_slice(enrich(raw, params), 180)
                    sig, _, _, _ = simulate_signals(e, params, ticker, interval, "6m", INTERVALS[interval]["bar_hours"])
                    bt = backtest_stats(e, params, ticker, interval, "6m")
                    tests.append({
                        "scope": f"{ticker}/{interval}/6m", "param": name, "value": value,
                        "BUY": sig.buy, "SELL": sig.sell, "trades": bt.trades,
                        "return": pct(bt.total_return), "MDD": pct(bt.mdd), "PF": num(bt.profit_factor, 2),
                    })
    return tests


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--out", default="reports/vwap_ema_pullback_validation.md")
    ap.add_argument("--cache-dir", default="data/validation_vwap")
    ap.add_argument("--execution-mode", choices=["same_close", "next_open"], default="same_close")
    ap.add_argument("--exit-mode", choices=["close_below_ema", "body_below_ema", "confirm_close_below_ema", "atr_buffer_exit"], default="close_below_ema")
    ap.add_argument("--cooldown-bars", type=int, default=0,
                    help="SELL exit 후 N 캔들 BUY 신호 무시 (live cooldown_minutes 의 backtest 등가물)")
    args = ap.parse_args()
    if args.cooldown_bars < 0:
        ap.error("--cooldown-bars must be >= 0")

    cache_dir = Path(args.cache_dir)
    run_params = {**DEFAULT_PARAMS, "exit_mode": args.exit_mode}
    all_signal_stats: list[SignalStats] = []
    all_bt_stats: list[BacktestStats] = []
    buy_samples: list[dict[str, Any]] = []
    sell_samples: list[dict[str, Any]] = []
    enriched_by_key: dict[tuple[str, str], pd.DataFrame] = {}

    for ticker in TICKERS:
        for label, meta in INTERVALS.items():
            raw = fetch_ohlcv(ticker, meta["pyupbit"], meta["count"], cache_dir, refresh=args.refresh)
            enriched_full = enrich(raw, run_params)
            enriched_full.attrs["raw"] = raw
            enriched_by_key[(ticker, label)] = enriched_full
            for period, days in PERIODS.items():
                sliced = period_slice(enriched_full, days)
                # 30m has 1y available because count=17520; day has 1y; all ok.
                sig, trades, buys, sells = simulate_signals(sliced, run_params, ticker, label, period, meta["bar_hours"])
                bt = backtest_stats(
                    sliced, run_params, ticker, label, period,
                    execution_mode=args.execution_mode,
                    cooldown_bars=args.cooldown_bars,
                )
                all_signal_stats.append(sig)
                all_bt_stats.append(bt)
                buy_samples.extend(buys)
                sell_samples.extend(sells)

    sens = sensitivity(enriched_by_key)

    signal_rows = [
        {"ticker": s.ticker, "interval": s.interval, "기간": s.period, "candles": s.candles,
         "BUY": s.buy, "SELL": s.sell, "HOLD": s.hold, "trades": s.trades,
         "avg_hold": f"{s.avg_hold_bars:.1f} bars / {s.avg_hold_time}"}
        for s in all_signal_stats
    ]
    bt_rows = [
        {"ticker": b.ticker, "interval": b.interval, "기간": b.period,
         "total": pct(b.total_return), "B&H": pct(b.bh_return), "MDD": pct(b.mdd),
         "win": pct(b.win_rate), "trades": b.trades, "PF": num(b.profit_factor, 2),
         "avg_hold": f"{b.avg_hold_days:.2f}d"}
        for b in all_bt_stats
    ]
    recent_buys = sorted(buy_samples, key=lambda r: r["timestamp"], reverse=True)[:5]
    recent_sells = sorted(sell_samples, key=lambda r: r["timestamp"], reverse=True)[:5]
    buy_rows = [
        {"timestamp": r["timestamp"], "ticker": r["ticker"], "interval": r["interval"],
         "close": num(r["close"], 2), "vwap": num(r["vwap"], 2), "ema9": num(r["ema9"], 2),
         "low": num(r["low"], 2), "is_sideways": r["is_sideways"], "reason": r["reason"]}
        for r in recent_buys
    ]
    sell_rows = [
        {"timestamp": r["timestamp"], "ticker": r["ticker"], "interval": r["interval"],
         "close": num(r["close"], 2), "ema9": num(r["ema9"], 2), "entry": num(r["entry_price"], 2),
         "pnl": pct(r["pnl_ratio"]), "reason": r["reason"]}
        for r in recent_sells
    ]

    # Compact interpretation helpers.
    by_interval = {}
    for b in all_bt_stats:
        if b.period == "6m":
            by_interval.setdefault(b.interval, []).append(b)
    interval_summary = []
    for interval, vals in by_interval.items():
        avg_trades = sum(v.trades for v in vals) / len(vals)
        avg_return = sum(v.total_return for v in vals) / len(vals)
        avg_mdd = sum(v.mdd for v in vals) / len(vals)
        interval_summary.append({"interval": interval, "avg_trades_6m": f"{avg_trades:.1f}", "avg_return_6m": pct(avg_return), "avg_MDD_6m": pct(avg_mdd)})

    doc = []
    doc.append("# vwap_ema_pullback validation raw report")
    doc.append(f"Generated at: {pd.Timestamp.now()}  ")
    doc.append(f"execution_mode={args.execution_mode}, exit_mode={args.exit_mode}\n")
    doc.append("## Signal stats")
    doc.append(markdown_table(signal_rows, ["ticker", "interval", "기간", "candles", "BUY", "SELL", "HOLD", "trades", "avg_hold"]))
    doc.append("\n## Backtest stats (custom execution simulator; fee=0.0005, slippage=0.0005)")
    doc.append(markdown_table(bt_rows, ["ticker", "interval", "기간", "total", "B&H", "MDD", "win", "trades", "PF", "avg_hold"]))
    doc.append("\n## Interval aggregate, 6m")
    doc.append(markdown_table(interval_summary, ["interval", "avg_trades_6m", "avg_return_6m", "avg_MDD_6m"]))
    doc.append("\n## Recent BUY samples")
    doc.append(markdown_table(buy_rows, ["timestamp", "ticker", "interval", "close", "vwap", "ema9", "low", "is_sideways", "reason"]))
    doc.append("\n## Recent SELL samples")
    doc.append(markdown_table(sell_rows, ["timestamp", "ticker", "interval", "close", "ema9", "entry", "pnl", "reason"]))
    doc.append("\n## Sensitivity (one-at-a-time, BTC/ETH, 6m)")
    doc.append(markdown_table(sens, ["scope", "param", "value", "BUY", "SELL", "trades", "return", "MDD", "PF"]))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(doc), encoding="utf-8")
    json_out = out.with_suffix(".json")
    json_out.write_text(json.dumps({
        "signal_stats": [asdict(x) for x in all_signal_stats],
        "backtest_stats": [asdict(x) for x in all_bt_stats],
        "execution_mode": args.execution_mode,
        "exit_mode": args.exit_mode,
        "buy_samples": recent_buys,
        "sell_samples": recent_sells,
        "sensitivity": sens,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    print(json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
