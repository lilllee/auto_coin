"""P2 entry-side validation runner for vwap_ema_pullback strategy.

PRD: ``.omx/plans/prd-vwap-ema-pullback-p2-2026-05-04.md``
Test spec: ``.omx/plans/test-spec-vwap-ema-pullback-p2-2026-05-04.md``

평가 축 (PRD §1):
1. Higher-timeframe trend filter (4h direction).
2. RSI floor / overextension avoidance.
3. Volume participation gate.
4. Daily regime filter (self-asset SMA).

Anchor (PRD §3.1) — P1 best `combined_atr`:
  exit_mode=atr_buffer_exit, exit_atr_multiplier=0.3, slope=0.002, cross=2,
  cooldown_bars=2, all entry filters off.

**Out of scope** — Volume Profile Phase 2, cross-asset BTC daily regime,
walk-forward, paper/live activation, registry changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# CLI 실행 시 repo root 를 sys.path 에 추가 (pytest 는 pythonpath 로 자동 처리됨).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402

from auto_coin.data.candles import enrich_vwap_ema_pullback  # noqa: E402
from scripts.verify_vwap_ema_pullback import (  # noqa: E402
    DEFAULT_PARAMS,
    fetch_ohlcv,
    period_slice,
    simulate_execution_trades,
)
from scripts.vwap_ema_pullback_p1_runner import (  # noqa: E402
    HARD_FLOOR_AVG_HOLD_BARS,
    HARD_FLOOR_TIME_EXIT_SHARE,
    HARD_FLOOR_TRADES,
    PASS_INTERVAL,
    PASS_PERIODS,
    PASS_TICKERS,
    PERF_MDD_OVERHANG_PP,
    PERF_PF_MIN,
    PERF_WIN_RATE_MIN,
    CellMetrics,
    _bh_mdd,
)

DEFAULT_TICKERS = ("KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP")
DEFAULT_INTERVALS = ("1h", "30m")
DEFAULT_PERIODS: tuple[tuple[str, int], ...] = (("6m", 180), ("1y", 365))

# PRD §3 — interval to next-higher TF (HTF) and pyupbit fetch keys.
INTERVAL_META: dict[str, dict[str, Any]] = {
    "1h":  {"pyupbit": "minute60", "count": 8760,  "htf": "minute240", "htf_count": 8760},
    "30m": {"pyupbit": "minute30", "count": 17520, "htf": "minute60",  "htf_count": 8760},
}
DAILY_PYUPBIT = "day"
DAILY_COUNT = 730

ANCHOR_ID = "anchor"
ANCHOR_PARAM_OVERRIDES = {
    "exit_mode": "atr_buffer_exit",
    "exit_atr_multiplier": 0.3,
    "min_ema_slope_ratio": 0.002,
    "max_vwap_cross_count": 2,
    "ema_touch_tolerance": 0.003,
    "cooldown_bars": 2,
}

# PRD §6 P2-additional hard floor.
HARD_FLOOR_TRADES_6M = 30

# PRD §6 anchor improvement check.
ANCHOR_IMPROVEMENT_PP = 3.0


@dataclass
class P2Candidate:
    """P1 anchor + entry-side filter overrides."""

    id: str
    # Inherited from anchor — kept on the candidate so each P2Candidate is
    # self-contained for serialization.
    exit_mode: str = ANCHOR_PARAM_OVERRIDES["exit_mode"]
    exit_atr_multiplier: float = ANCHOR_PARAM_OVERRIDES["exit_atr_multiplier"]
    exit_confirm_bars: int = 2
    min_ema_slope_ratio: float = ANCHOR_PARAM_OVERRIDES["min_ema_slope_ratio"]
    max_vwap_cross_count: int = ANCHOR_PARAM_OVERRIDES["max_vwap_cross_count"]
    ema_touch_tolerance: float = ANCHOR_PARAM_OVERRIDES["ema_touch_tolerance"]
    cooldown_bars: int = ANCHOR_PARAM_OVERRIDES["cooldown_bars"]
    # Entry-side filters
    htf_trend_filter_mode: str = "off"
    rsi_filter_mode: str = "off"
    rsi_window: int = 14
    volume_filter_mode: str = "off"
    volume_mean_window: int = 20
    daily_regime_filter_mode: str = "off"
    daily_regime_ma_window: int = 200

    def strategy_params(self) -> dict[str, Any]:
        return {
            **DEFAULT_PARAMS,
            "exit_mode": self.exit_mode,
            "exit_confirm_bars": self.exit_confirm_bars,
            "exit_atr_multiplier": self.exit_atr_multiplier,
            "min_ema_slope_ratio": self.min_ema_slope_ratio,
            "max_vwap_cross_count": self.max_vwap_cross_count,
            "ema_touch_tolerance": self.ema_touch_tolerance,
            "htf_trend_filter_mode": self.htf_trend_filter_mode,
            "rsi_filter_mode": self.rsi_filter_mode,
            "rsi_window": self.rsi_window,
            "volume_filter_mode": self.volume_filter_mode,
            "volume_mean_window": self.volume_mean_window,
            "daily_regime_filter_mode": self.daily_regime_filter_mode,
            "daily_regime_ma_window": self.daily_regime_ma_window,
        }

    def enrich_key(self) -> tuple:
        """enricher cache key — strategy 가 어떤 컬럼을 필요로 하는지 결정."""
        return (
            self.min_ema_slope_ratio,
            self.max_vwap_cross_count,
            self.rsi_filter_mode != "off",
            self.rsi_window if self.rsi_filter_mode != "off" else None,
            self.volume_filter_mode != "off",
            self.volume_mean_window if self.volume_filter_mode != "off" else None,
            self.htf_trend_filter_mode != "off",
            self.daily_regime_filter_mode != "off",
            self.daily_regime_ma_window if self.daily_regime_filter_mode != "off" else None,
        )


def build_p2_candidate_grid() -> list[P2Candidate]:
    """PRD §4 의 18 candidates."""
    grid: list[P2Candidate] = []

    # (1) P2 anchor — P1 combined_atr 와 동일.
    grid.append(P2Candidate(id=ANCHOR_ID))

    # (2) Single-axis sweep — 10
    grid.append(P2Candidate(id="A_htf_close",
                            htf_trend_filter_mode="htf_close_above_ema"))
    grid.append(P2Candidate(id="A_htf_fast_slow",
                            htf_trend_filter_mode="htf_ema_fast_slow"))

    grid.append(P2Candidate(id="B_rsi_lt_70",
                            rsi_filter_mode="lt_70"))
    grid.append(P2Candidate(id="B_rsi_in_30_70",
                            rsi_filter_mode="in_30_70"))
    grid.append(P2Candidate(id="B_rsi_in_40_70",
                            rsi_filter_mode="in_40_70"))

    grid.append(P2Candidate(id="C_vol_1_0",
                            volume_filter_mode="ge_1_0"))
    grid.append(P2Candidate(id="C_vol_1_2",
                            volume_filter_mode="ge_1_2"))

    grid.append(P2Candidate(id="D_daily_sma200",
                            daily_regime_filter_mode="self_above_sma200",
                            daily_regime_ma_window=200))
    grid.append(P2Candidate(id="D_daily_sma100",
                            daily_regime_filter_mode="self_above_sma100",
                            daily_regime_ma_window=100))

    # cooldown interaction sanity (PRD §4.2 — anchor with cooldown=0 baseline)
    grid.append(P2Candidate(id="cooldown_off_check", cooldown_bars=0))

    # (3) Two-axis combos — 5
    grid.append(P2Candidate(id="AB",
                            htf_trend_filter_mode="htf_close_above_ema",
                            rsi_filter_mode="lt_70"))
    grid.append(P2Candidate(id="AC",
                            htf_trend_filter_mode="htf_close_above_ema",
                            volume_filter_mode="ge_1_0"))
    grid.append(P2Candidate(id="AD",
                            htf_trend_filter_mode="htf_close_above_ema",
                            daily_regime_filter_mode="self_above_sma200",
                            daily_regime_ma_window=200))
    grid.append(P2Candidate(id="BD",
                            rsi_filter_mode="in_40_70",
                            daily_regime_filter_mode="self_above_sma200",
                            daily_regime_ma_window=200))
    grid.append(P2Candidate(id="CD",
                            volume_filter_mode="ge_1_0",
                            daily_regime_filter_mode="self_above_sma200",
                            daily_regime_ma_window=200))

    # (4) Three-/four-axis kitchen-sink — 2
    grid.append(P2Candidate(id="ABCD_relaxed",
                            htf_trend_filter_mode="htf_close_above_ema",
                            rsi_filter_mode="lt_70",
                            volume_filter_mode="ge_1_0",
                            daily_regime_filter_mode="self_above_sma200",
                            daily_regime_ma_window=200))
    grid.append(P2Candidate(id="ABCD_strict",
                            htf_trend_filter_mode="htf_ema_fast_slow",
                            rsi_filter_mode="in_40_70",
                            volume_filter_mode="ge_1_2",
                            daily_regime_filter_mode="self_above_sma200",
                            daily_regime_ma_window=200))

    return grid


def _enrich_for_candidate(
    candidate: P2Candidate,
    raw: pd.DataFrame,
    *,
    htf_df: pd.DataFrame | None,
    daily_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """Candidate 의 enricher 필요 컬럼 산출."""
    kwargs: dict[str, Any] = {
        "ema_period": DEFAULT_PARAMS["ema_period"],
        "vwap_period": DEFAULT_PARAMS["vwap_period"],
        "sideways_lookback": DEFAULT_PARAMS["sideways_lookback"],
        "max_vwap_cross_count": candidate.max_vwap_cross_count,
        "min_ema_slope_ratio": candidate.min_ema_slope_ratio,
    }
    if candidate.rsi_filter_mode != "off":
        kwargs["rsi_window"] = candidate.rsi_window
    if candidate.volume_filter_mode != "off":
        kwargs["volume_mean_window"] = candidate.volume_mean_window
    if candidate.htf_trend_filter_mode != "off" and htf_df is not None:
        kwargs["htf_df"] = htf_df
    if candidate.daily_regime_filter_mode != "off" and daily_df is not None:
        kwargs["daily_df"] = daily_df
        kwargs["daily_regime_ma_window"] = candidate.daily_regime_ma_window
    return enrich_vwap_ema_pullback(raw, **kwargs)


def evaluate_cell_p2(
    candidate: P2Candidate, ticker: str, interval: str, period: str,
    enriched_full: pd.DataFrame, days: int,
) -> CellMetrics:
    """단일 cell backtest. P1 evaluate_cell 의 P2 변형 (anchor diff 위해 재구현)."""
    sliced = period_slice(enriched_full, days)
    params = candidate.strategy_params()
    trades = simulate_execution_trades(
        sliced, params,
        execution_mode="next_open",
        mark_to_market=True,
        cooldown_bars=candidate.cooldown_bars,
    )
    rets = [t["ret"] for t in trades]
    n = len(rets)

    cur = 1.0
    equity: list[float] = []
    for r in rets:
        cur *= 1.0 + r
        equity.append(cur)
    total_return = (cur - 1.0) if equity else 0.0

    if equity:
        peak: list[float] = []
        p = equity[0]
        for e in equity:
            p = max(p, e)
            peak.append(p)
        mdd = min((e - p) / p for e, p in zip(equity, peak, strict=True))
    else:
        mdd = 0.0

    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    win_rate = len(wins) / n if n else 0.0
    avg_profit = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    gross_wins = sum(wins)
    gross_losses = abs(sum(losses))
    if gross_losses > 1e-10:
        profit_factor = gross_wins / gross_losses
    elif gross_wins > 0:
        profit_factor = 99.99
    else:
        profit_factor = 0.0
    expectancy = sum(rets) / n if n else 0.0
    avg_hold_bars = sum(t["hold_bars"] for t in trades) / n if n else 0.0

    closes = sliced["close"].dropna()
    bh_return = float(closes.iloc[-1] / closes.iloc[0] - 1.0) if len(closes) >= 2 else 0.0
    bh_mdd = _bh_mdd(closes)
    time_exit_share = 0.0  # vwap_ema_pullback time_exit_disabled

    return CellMetrics(
        candidate_id=candidate.id, ticker=ticker, interval=interval, period=period,
        candles=len(sliced), trades=n,
        total_return=total_return, bh_return=bh_return,
        mdd=mdd, bh_mdd=bh_mdd,
        win_rate=win_rate, profit_factor=profit_factor,
        avg_hold_bars=avg_hold_bars, avg_profit=avg_profit, avg_loss=avg_loss,
        expectancy=expectancy, time_exit_share=time_exit_share,
    )


# ---------------------------------------------------------------------------
# Verdict — P1 derive_verdict + P2 추가 hard floor + anchor improvement check
# ---------------------------------------------------------------------------


def hard_floor_passes_p2(m: CellMetrics) -> bool:
    """P1 hard floor + P2 추가 6m hard floor (PRD §6).

    P1 의 hard floor 는 1y 기준 였지만 P2 는 6m 도 같이 본다.
    """
    if m.period == "6m":
        if m.trades < HARD_FLOOR_TRADES_6M:
            return False
        if m.avg_hold_bars < HARD_FLOOR_AVG_HOLD_BARS:
            return False
        return m.time_exit_share <= HARD_FLOOR_TIME_EXIT_SHARE
    # 1y — P1 floor 와 동일
    return (
        m.trades >= HARD_FLOOR_TRADES
        and m.avg_hold_bars >= HARD_FLOOR_AVG_HOLD_BARS
        and m.time_exit_share <= HARD_FLOOR_TIME_EXIT_SHARE
    )


def perf_gates_pass_p2(m: CellMetrics) -> bool:
    """PRD §6 perf gates — P1 과 동일."""
    return (
        m.profit_factor >= PERF_PF_MIN
        and m.total_return >= m.bh_return
        and (m.mdd - m.bh_mdd) >= -PERF_MDD_OVERHANG_PP
        and m.win_rate >= PERF_WIN_RATE_MIN
        and m.expectancy > 0
    )


def derive_verdict_p2(rollup: dict) -> tuple[str, dict]:
    """P1 verdict logic 호환 — P2 추가 hard floor 를 적용하는 wrapper.

    P1 derive_verdict 는 1y 기준 floor 만 보지만 P2 는 6m 도 floor 검사.
    여기서 P2-specific floor + perf gate 로직을 직접 구현.
    """
    interval_data = rollup.get(PASS_INTERVAL, {})
    candidate_ids: list[str] = []
    for period_data in interval_data.get("KRW-BTC", {}).values():
        candidate_ids = list(period_data.keys())
        break

    cell_pass_summary: dict[str, dict[str, Any]] = {}
    pass_candidates: list[str] = []

    for cid in candidate_ids:
        cells_pass = 0
        cells_total = 0
        all_hard_floors = True
        for ticker in PASS_TICKERS:
            for period in PASS_PERIODS:
                m = (
                    interval_data.get(ticker, {})
                    .get(period, {})
                    .get(cid)
                )
                if m is None:
                    all_hard_floors = False
                    continue
                cells_total += 1
                if not hard_floor_passes_p2(m):
                    all_hard_floors = False
                    continue
                if perf_gates_pass_p2(m):
                    cells_pass += 1
        cell_pass_summary[cid] = {
            "cells_pass": cells_pass,
            "cells_total": cells_total,
            "hard_floor_pass": all_hard_floors,
        }
        if cells_total == 4 and cells_pass == 4:
            pass_candidates.append(cid)

    if pass_candidates:
        return "PASS", {"pass_candidates": pass_candidates,
                        "details": cell_pass_summary}

    partial = [cid for cid, s in cell_pass_summary.items() if s["cells_pass"] > 0]
    if partial:
        return "HOLD", {"partial_candidates": partial,
                        "details": cell_pass_summary}

    hard_pass = [cid for cid, s in cell_pass_summary.items() if s["hard_floor_pass"]]
    if hard_pass:
        return "REVISE", {"hard_pass_candidates": hard_pass,
                          "details": cell_pass_summary}

    return "STOP", {"details": cell_pass_summary}


def compute_anchor_diff(rollup: dict) -> dict[str, dict[str, float]]:
    """각 candidate 별로 anchor 대비 BTC/ETH 1y/6m ret diff (pp) 계산.

    PRD §6 anchor improvement check — PASS quality 표시 용.
    """
    interval_data = rollup.get(PASS_INTERVAL, {})
    out: dict[str, dict[str, float]] = {}
    for ticker in PASS_TICKERS:
        for period in PASS_PERIODS:
            cell_map = interval_data.get(ticker, {}).get(period, {})
            anchor_cell = cell_map.get(ANCHOR_ID)
            if anchor_cell is None:
                continue
            for cid, cell in cell_map.items():
                if cid == ANCHOR_ID:
                    continue
                key = f"{ticker.replace('KRW-', '')}_{period}_ret_diff_pp"
                out.setdefault(cid, {})[key] = (cell.total_return - anchor_cell.total_return) * 100.0
    return out


def derive_paper_recommendation(verdict: str, anchor_diff: dict[str, dict[str, float]],
                                pass_candidates: list[str]) -> str:
    """PASS quality 평가 — anchor 대비 BTC/ETH 평균 ret diff 가 충분한지.

    Returns:
      - "n/a" — verdict != "PASS"
      - "recommend_separate_pr" — PASS + anchor 평균 +ANCHOR_IMPROVEMENT_PP 이상
      - "hold" — PASS 인데 anchor 대비 marginal (<+ANCHOR_IMPROVEMENT_PP)
    """
    if verdict != "PASS":
        return "n/a"
    for cid in pass_candidates:
        diffs = anchor_diff.get(cid, {})
        if not diffs:
            continue
        relevant = [v for k, v in diffs.items() if k.endswith("_ret_diff_pp")]
        if relevant and (sum(relevant) / len(relevant)) >= ANCHOR_IMPROVEMENT_PP:
            return "recommend_separate_pr"
    return "hold"


def _rollup_to_dict(rollup: dict) -> dict:
    out: dict = {}
    for interval, ticker_data in rollup.items():
        out[interval] = {}
        for ticker, period_data in ticker_data.items():
            out[interval][ticker] = {}
            for period, candidate_data in period_data.items():
                out[interval][ticker][period] = {
                    cid: asdict(m) for cid, m in candidate_data.items()
                }
    return out


def run_p2(
    *,
    tickers: tuple[str, ...] = DEFAULT_TICKERS,
    intervals: tuple[str, ...] = DEFAULT_INTERVALS,
    periods: tuple[tuple[str, int], ...] = DEFAULT_PERIODS,
    cache_dir: Path = Path("data/validation_vwap"),
    refresh: bool = False,
    candidate_grid: list[P2Candidate] | None = None,
    fetch_fn: Callable[..., pd.DataFrame] | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """P2 sweep — fetch base + HTF + daily, enrich per candidate, evaluate, verdict."""
    grid = candidate_grid or build_p2_candidate_grid()
    fetch = fetch_fn or fetch_ohlcv

    # rollup[interval][ticker][period][candidate_id] = CellMetrics
    rollup: dict = {}
    per_run: list[dict] = []

    # candidate axes 가 어떤 외부 데이터를 요구하는지
    needs_htf = any(c.htf_trend_filter_mode != "off" for c in grid)
    needs_daily = any(c.daily_regime_filter_mode != "off" for c in grid)

    for interval in intervals:
        meta = INTERVAL_META[interval]
        if verbose:
            print(f"[interval] {interval} (count={meta['count']}, htf={meta['htf']})")
        for ticker in tickers:
            raw = fetch(ticker, meta["pyupbit"], meta["count"], cache_dir, refresh)
            htf_df = None
            if needs_htf:
                htf_df = fetch(ticker, meta["htf"], meta["htf_count"], cache_dir, refresh)
            daily_df = None
            if needs_daily:
                daily_df = fetch(ticker, DAILY_PYUPBIT, DAILY_COUNT, cache_dir, refresh)
            if verbose:
                print(f"  [ticker] {ticker} base={len(raw)} "
                      f"htf={'-' if htf_df is None else len(htf_df)} "
                      f"daily={'-' if daily_df is None else len(daily_df)}")

            # Enrichment cache: candidate.enrich_key() → enriched_full
            enrich_cache: dict[tuple, pd.DataFrame] = {}
            for cand in grid:
                key = cand.enrich_key()
                if key not in enrich_cache:
                    enrich_cache[key] = _enrich_for_candidate(
                        cand, raw,
                        htf_df=htf_df if cand.htf_trend_filter_mode != "off" else None,
                        daily_df=daily_df if cand.daily_regime_filter_mode != "off" else None,
                    )
                enriched_full = enrich_cache[key]
                for period_label, days in periods:
                    cell = evaluate_cell_p2(
                        cand, ticker, interval, period_label, enriched_full, days,
                    )
                    rollup.setdefault(interval, {}) \
                          .setdefault(ticker, {}) \
                          .setdefault(period_label, {})[cand.id] = cell
                    per_run.append(asdict(cell))
            if verbose:
                print(f"    enriched {len(enrich_cache)} variants")

    verdict, vdetails = derive_verdict_p2(rollup)
    anchor_diff = compute_anchor_diff(rollup)
    pass_candidates = vdetails.get("pass_candidates", []) if verdict == "PASS" else []
    paper_recommendation = derive_paper_recommendation(verdict, anchor_diff, pass_candidates)

    return {
        "rollup": _rollup_to_dict(rollup),
        "verdict": verdict,
        "verdict_details": vdetails,
        "anchor_id": ANCHOR_ID,
        "anchor_diff_pp": anchor_diff,
        "paper_recommendation": paper_recommendation,
        "per_run": per_run,
        "candidate_grid_size": len(grid),
    }


def render_md_p2(result: dict[str, Any]) -> str:
    """JSON 결과 → 사람이 읽는 markdown 보고서."""
    lines: list[str] = []
    lines.append("# vwap_ema_pullback P2 entry-side validation")
    lines.append("")
    lines.append("Scope: PRD `.omx/plans/prd-vwap-ema-pullback-p2-2026-05-04.md`.")
    lines.append("Anchor: P1 best `combined_atr` (atr_buffer 0.3 / slope 0.002 / cross 2 / cooldown 2).")
    lines.append("Execution: `next_open` only · fee=`UPBIT_DEFAULT_FEE` · "
                 "slippage=`DEFAULT_SLIPPAGE`. Volume Profile Phase 2 미포함.")
    lines.append("")
    verdict = result["verdict"]
    paper_rec = result["paper_recommendation"]
    lines.append(f"## Verdict: **{verdict}**")
    lines.append("")
    details = result["verdict_details"]
    if verdict == "PASS":
        lines.append(f"PASS candidates: `{', '.join(details['pass_candidates'])}`")
        lines.append(f"Paper activation recommendation: **{paper_rec}**")
    elif verdict == "HOLD":
        lines.append(f"Partial-pass candidates: `{', '.join(details['partial_candidates'])}`")
    elif verdict == "REVISE":
        lines.append(f"Hard-floor-only candidates: `{', '.join(details['hard_pass_candidates'])}`")
    else:
        lines.append("No candidate passed any cell.")
    lines.append("")

    rollup = result["rollup"]
    grid = build_p2_candidate_grid()
    anchor_diff = result.get("anchor_diff_pp", {})

    headers = ["candidate", "ticker", "period", "trades", "ret", "B&H", "MDD", "BH_MDD",
               "PF", "win", "exp", "avg_hold", "anchor_diff_pp", "hard", "perf"]

    def _row(cid: str, ticker: str, period: str, m: dict) -> str:
        cell = CellMetrics(**m)
        hard = "✓" if hard_floor_passes_p2(cell) else "✗"
        perf = "✓" if perf_gates_pass_p2(cell) else "✗"
        diff_key = f"{ticker.replace('KRW-', '')}_{period}_ret_diff_pp"
        diff_val = anchor_diff.get(cid, {}).get(diff_key)
        diff_str = f"{diff_val:+.2f}" if diff_val is not None else "—"
        return (
            f"| {cid} | {ticker.replace('KRW-', '')} | {period} | {cell.trades} | "
            f"{cell.total_return*100:+.2f}% | {cell.bh_return*100:+.2f}% | "
            f"{cell.mdd*100:+.2f}% | {cell.bh_mdd*100:+.2f}% | "
            f"{cell.profit_factor:.2f} | {cell.win_rate*100:.1f}% | "
            f"{cell.expectancy*100:+.3f}% | {cell.avg_hold_bars:.1f} | "
            f"{diff_str} | {hard} | {perf} |"
        )

    # Primary — BTC/ETH 1h
    lines.append("## 1h primary — BTC/ETH per period (anchor_diff in pp)")
    lines.append("")
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for cid in [c.id for c in grid]:
        for ticker in PASS_TICKERS:
            for period in PASS_PERIODS:
                m = rollup.get(PASS_INTERVAL, {}).get(ticker, {}).get(period, {}).get(cid)
                if not m:
                    continue
                lines.append(_row(cid, ticker, period, m))
    lines.append("")

    # SOL/XRP info
    info_tickers = [t for t in DEFAULT_TICKERS if t not in PASS_TICKERS]
    if info_tickers:
        lines.append("## 1h secondary — SOL/XRP (informational only, verdict 비참여)")
        lines.append("")
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for cid in [c.id for c in grid]:
            for ticker in info_tickers:
                for period in PASS_PERIODS:
                    m = rollup.get(PASS_INTERVAL, {}).get(ticker, {}).get(period, {}).get(cid)
                    if not m:
                        continue
                    lines.append(_row(cid, ticker, period, m))
        lines.append("")

    # 30m sanity
    if "30m" in rollup:
        lines.append("## 30m sanity — BTC/ETH (informational only, verdict 비참여)")
        lines.append("")
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for cid in [c.id for c in grid]:
            for ticker in PASS_TICKERS:
                for period in PASS_PERIODS:
                    m = rollup.get("30m", {}).get(ticker, {}).get(period, {}).get(cid)
                    if not m:
                        continue
                    lines.append(_row(cid, ticker, period, m))
        lines.append("")

    # Per-candidate cell-pass summary
    lines.append("## Per-candidate cell-pass count (1h, BTC+ETH × 6m+1y, max=4)")
    lines.append("")
    lines.append("| candidate | cells_pass | cells_total | hard_floor |")
    lines.append("|---|---:|---:|---|")
    summary = result["verdict_details"].get("details", {})
    for cid in [c.id for c in grid]:
        s = summary.get(cid, {"cells_pass": 0, "cells_total": 0, "hard_floor_pass": False})
        lines.append(
            f"| {cid} | {s['cells_pass']} | {s['cells_total']} | "
            f"{'✓' if s['hard_floor_pass'] else '✗'} |"
        )
    lines.append("")

    # ADR
    lines.append("## ADR — Verdict rationale")
    lines.append("")
    lines.append(f"Verdict: **{verdict}** · Paper activation: **{paper_rec}**")
    lines.append("")
    lines.append("Decision rule (PRD §6):")
    lines.append("- PASS: 한 candidate 가 BTC/ETH × 1y/6m 모든 4 cell hard floor + perf gate 통과.")
    lines.append("- HOLD: 어떤 candidate 가 일부 cell perf gate 통과.")
    lines.append("- REVISE: 모든 candidate hard floor 통과하지만 perf gate 0건. P2 도 fail 이면 retire 검토.")
    lines.append("- STOP: hard floor 1+ fail or 모든 candidate 가 anchor 보다 나쁨.")
    lines.append("")
    lines.append(f"Hard floors: 1y trades>=`{HARD_FLOOR_TRADES}` · 6m trades>=`{HARD_FLOOR_TRADES_6M}` · "
                 f"avg_hold_bars>=`{HARD_FLOOR_AVG_HOLD_BARS}` · time_exit_share<=`0`.")
    lines.append(f"Perf gates: PF>=`{PERF_PF_MIN}` · ret>=B&H · "
                 f"MDD-BH_MDD>=`-{int(PERF_MDD_OVERHANG_PP*100)}pp` · "
                 f"win>=`{int(PERF_WIN_RATE_MIN*100)}%` · expectancy>0.")
    lines.append(f"Anchor improvement check: PASS 시 BTC/ETH 평균 ret diff >= "
                 f"+`{int(ANCHOR_IMPROVEMENT_PP)}pp` 이어야 paper 활성 권고. 미달이면 hold.")
    lines.append("")

    if verdict == "PASS" and paper_rec == "recommend_separate_pr":
        lines.append("Follow-up: 별도 PR 로 paper 활성 검토. RiskManager `cooldown_minutes` 매핑 명시.")
    elif verdict == "PASS":
        lines.append("Follow-up: PASS 이지만 anchor 대비 marginal — paper 활성 보류, P2.5 quality 검증 plan.")
    elif verdict == "HOLD":
        lines.append("Follow-up: P2.5 — 통과 cell candidate 의 단일 axis 추가 sweep.")
    elif verdict == "REVISE":
        lines.append("Follow-up: **strategy retire 검토 PR** — P1/P2 모두 perf gate 0 이면 entry-side axis "
                     "도 alpha 부족 의미. registry 제거 또는 EXPERIMENTAL 영구 유지 결정.")
    else:
        lines.append("Follow-up: **strategy retire 권고** — hard floor 자체를 통과 못함. "
                     "filter 가 trade 를 너무 죽임 또는 entry signal 자체가 작동 안 함.")
    lines.append("")
    lines.append("Constraints honored: registry/UI 노출 변경 0건 · live/paper 활성 변경 0건 · "
                 "Volume Profile Phase 2 미포함 · KPI/ledger 코드 미수정.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", default=",".join(DEFAULT_TICKERS),
                    help="comma-separated ticker list")
    ap.add_argument("--intervals", default=",".join(DEFAULT_INTERVALS),
                    help="comma-separated interval list (e.g. 1h,30m)")
    ap.add_argument("--out", default="reports/2026-05-04-vwap-ema-pullback-p2.json",
                    help="JSON output path")
    ap.add_argument("--md-out", default=None,
                    help="Markdown output path (default: same stem with .md)")
    ap.add_argument("--cache-dir", default="data/validation_vwap")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore OHLCV cache + refetch")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    tickers = tuple(t.strip() for t in args.tickers.split(",") if t.strip())
    intervals = tuple(i.strip() for i in args.intervals.split(",") if i.strip())

    result = run_p2(
        tickers=tickers,
        intervals=intervals,
        cache_dir=Path(args.cache_dir),
        refresh=args.refresh,
        verbose=args.verbose,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    md_path = Path(args.md_out) if args.md_out else out_path.with_suffix(".md")
    md_path.write_text(render_md_p2(result), encoding="utf-8")
    print(f"wrote {out_path} ({result['candidate_grid_size']} candidates × "
          f"{len(tickers)} tickers × {len(intervals)} intervals × "
          f"{len(DEFAULT_PERIODS)} periods)")
    print(f"wrote {md_path}")
    print(f"verdict: {result['verdict']} · paper: {result['paper_recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
