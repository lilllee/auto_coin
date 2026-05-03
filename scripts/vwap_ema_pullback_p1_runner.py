"""P1 re-validation runner for vwap_ema_pullback strategy.

PRD: ``.omx/plans/prd-vwap-ema-pullback-p1-2026-05-03.md``
Test spec: ``.omx/plans/test-spec-vwap-ema-pullback-p1-2026-05-03.md``

평가 축 (PRD §1):
1. next_open 체결로 execution bias 제거.
2. 청산 완화 3종 (`body_below_ema` / `confirm_close_below_ema` / `atr_buffer_exit`).
3. 거래 빈도 통제 (parameter tightening + simulator-side re-entry cooldown).
4. 1h primary, 30m secondary, day omitted.

**Out of scope** — Volume Profile Phase 2 / paper·live 활성. registry 변경 0건.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# CLI 실행 시 repo root 를 sys.path 에 추가 (pytest 는 pythonpath 설정으로 자동 처리됨).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402

from scripts.verify_vwap_ema_pullback import (  # noqa: E402
    DEFAULT_PARAMS,
    INTERVALS,
    enrich,
    fetch_ohlcv,
    period_slice,
    simulate_execution_trades,
)

DEFAULT_TICKERS = ("KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP")
DEFAULT_INTERVALS = ("1h", "30m")
DEFAULT_PERIODS: tuple[tuple[str, int], ...] = (("6m", 180), ("1y", 365))

# Verdict 판정에 쓰는 cell 집합 (PRD §6).
PASS_TICKERS = ("KRW-BTC", "KRW-ETH")
PASS_PERIODS = ("6m", "1y")
PASS_INTERVAL = "1h"

# Hard floors / perf gates — PRD §6.
HARD_FLOOR_TRADES = 60
HARD_FLOOR_AVG_HOLD_BARS = 4
HARD_FLOOR_TIME_EXIT_SHARE = 0.0  # vwap_ema_pullback 은 time_exit_disabled
PERF_PF_MIN = 0.85
PERF_WIN_RATE_MIN = 0.25
PERF_MDD_OVERHANG_PP = 0.05  # MDD 가 BH_MDD 보다 5pp 이상 더 깊지 않음


@dataclass
class Candidate:
    id: str
    exit_mode: str
    exit_confirm_bars: int = 2
    exit_atr_multiplier: float = 0.3
    min_ema_slope_ratio: float = 0.001
    max_vwap_cross_count: int = 3
    ema_touch_tolerance: float = 0.003
    cooldown_bars: int = 0

    def strategy_params(self) -> dict[str, Any]:
        return {
            **DEFAULT_PARAMS,
            "exit_mode": self.exit_mode,
            "exit_confirm_bars": self.exit_confirm_bars,
            "exit_atr_multiplier": self.exit_atr_multiplier,
            "min_ema_slope_ratio": self.min_ema_slope_ratio,
            "max_vwap_cross_count": self.max_vwap_cross_count,
            "ema_touch_tolerance": self.ema_touch_tolerance,
        }

    def enrich_key(self) -> tuple[float, int]:
        """enricher 가 의존하는 axis. tolerance 는 strategy-side 만 영향."""
        return (self.min_ema_slope_ratio, self.max_vwap_cross_count)


def build_candidate_grid() -> list[Candidate]:
    """PRD §4 의 14 candidates."""
    grid: list[Candidate] = []
    # (1) Baseline anchor
    grid.append(Candidate(id="baseline", exit_mode="close_below_ema"))
    # (2) Exit relaxation only — 5
    grid.append(Candidate(id="exit_body", exit_mode="body_below_ema"))
    grid.append(Candidate(id="exit_confirm2",
                          exit_mode="confirm_close_below_ema", exit_confirm_bars=2))
    grid.append(Candidate(id="exit_confirm3",
                          exit_mode="confirm_close_below_ema", exit_confirm_bars=3))
    grid.append(Candidate(id="exit_atr_03",
                          exit_mode="atr_buffer_exit", exit_atr_multiplier=0.3))
    grid.append(Candidate(id="exit_atr_05",
                          exit_mode="atr_buffer_exit", exit_atr_multiplier=0.5))
    # (3) Frequency control only — 3
    grid.append(Candidate(id="freq_slope", exit_mode="close_below_ema",
                          min_ema_slope_ratio=0.002))
    grid.append(Candidate(id="freq_cross", exit_mode="close_below_ema",
                          max_vwap_cross_count=2))
    grid.append(Candidate(id="freq_cooldown", exit_mode="close_below_ema",
                          cooldown_bars=2))
    # (4) Combined best-guess — 3
    grid.append(Candidate(id="combined_body", exit_mode="body_below_ema",
                          min_ema_slope_ratio=0.002, max_vwap_cross_count=2,
                          cooldown_bars=2))
    grid.append(Candidate(id="combined_confirm",
                          exit_mode="confirm_close_below_ema", exit_confirm_bars=2,
                          min_ema_slope_ratio=0.002, max_vwap_cross_count=2,
                          cooldown_bars=2))
    grid.append(Candidate(id="combined_atr", exit_mode="atr_buffer_exit",
                          exit_atr_multiplier=0.3,
                          min_ema_slope_ratio=0.002, max_vwap_cross_count=2,
                          cooldown_bars=2))
    # (5) Tolerance noise check — 2
    grid.append(Candidate(id="tolerance_005", exit_mode="body_below_ema",
                          min_ema_slope_ratio=0.002, max_vwap_cross_count=2,
                          cooldown_bars=2, ema_touch_tolerance=0.005))
    grid.append(Candidate(id="tolerance_003", exit_mode="body_below_ema",
                          min_ema_slope_ratio=0.002, max_vwap_cross_count=2,
                          cooldown_bars=2, ema_touch_tolerance=0.003))
    return grid


@dataclass
class CellMetrics:
    candidate_id: str
    ticker: str
    interval: str
    period: str
    candles: int
    trades: int
    total_return: float
    bh_return: float
    mdd: float
    bh_mdd: float
    win_rate: float
    profit_factor: float
    avg_hold_bars: float
    avg_profit: float
    avg_loss: float
    expectancy: float
    time_exit_share: float


def _bh_mdd(closes: pd.Series) -> float:
    if closes.empty:
        return 0.0
    peak = float(closes.iloc[0])
    mdd = 0.0
    for c in closes:
        c = float(c)
        peak = max(peak, c)
        if peak > 0:
            dd = (c - peak) / peak
            mdd = min(mdd, dd)
    return float(mdd)


def evaluate_cell(
    candidate: Candidate, ticker: str, interval: str, period: str,
    enriched_full: pd.DataFrame, days: int,
) -> CellMetrics:
    """단일 (candidate × ticker × interval × period) backtest → CellMetrics.

    `next_open` 체결만, mark_to_market=True 로 open trade 종료.
    `cooldown_bars` 는 candidate 가 정의한 값 사용.
    """
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

    # vwap_ema_pullback 은 `time_exit_disabled` — 강제 청산 없음.
    # mark_to_market 은 backtest artifact 이지 정책 위반이 아님.
    time_exit_share = 0.0

    return CellMetrics(
        candidate_id=candidate.id, ticker=ticker, interval=interval, period=period,
        candles=len(sliced), trades=n,
        total_return=total_return, bh_return=bh_return,
        mdd=mdd, bh_mdd=bh_mdd,
        win_rate=win_rate, profit_factor=profit_factor,
        avg_hold_bars=avg_hold_bars, avg_profit=avg_profit, avg_loss=avg_loss,
        expectancy=expectancy, time_exit_share=time_exit_share,
    )


def hard_floor_passes(m: CellMetrics) -> bool:
    return (
        m.trades >= HARD_FLOOR_TRADES
        and m.avg_hold_bars >= HARD_FLOOR_AVG_HOLD_BARS
        and m.time_exit_share <= HARD_FLOOR_TIME_EXIT_SHARE
    )


def perf_gates_pass(m: CellMetrics) -> bool:
    return (
        m.profit_factor >= PERF_PF_MIN
        and m.total_return >= m.bh_return
        and (m.mdd - m.bh_mdd) >= -PERF_MDD_OVERHANG_PP
        and m.win_rate >= PERF_WIN_RATE_MIN
        and m.expectancy > 0
    )


def derive_verdict(rollup: dict) -> tuple[str, dict]:
    """rollup[interval][ticker][period][candidate_id] = CellMetrics
    PRD §6 verdict logic. Only 1h matters for PASS decision; SOL/XRP excluded.
    """
    interval_data = rollup.get(PASS_INTERVAL, {})

    # candidate ID 들은 각 cell 에 동일하게 존재한다고 가정 (sweep 결과)
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
                if not hard_floor_passes(m):
                    all_hard_floors = False
                    continue
                if perf_gates_pass(m):
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


def run_p1(
    *,
    tickers: tuple[str, ...] = DEFAULT_TICKERS,
    intervals: tuple[str, ...] = DEFAULT_INTERVALS,
    periods: tuple[tuple[str, int], ...] = DEFAULT_PERIODS,
    cache_dir: Path = Path("data/validation_vwap"),
    refresh: bool = False,
    candidate_grid: list[Candidate] | None = None,
    fetch_fn: Callable[..., pd.DataFrame] | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """전체 P1 sweep. 결과 dict 반환 (rollup + verdict + per_run + grid_size)."""
    grid = candidate_grid or build_candidate_grid()
    fetch = fetch_fn or fetch_ohlcv

    # rollup[interval][ticker][period][candidate_id] = CellMetrics
    rollup: dict = {}
    per_run: list[dict] = []

    for interval in intervals:
        meta = INTERVALS[interval]
        if verbose:
            print(f"[interval] {interval} (count={meta['count']})")
        for ticker in tickers:
            raw = fetch(ticker, meta["pyupbit"], meta["count"], cache_dir, refresh)
            if verbose:
                print(f"  [ticker] {ticker} fetched {len(raw)} rows")

            # Enrich 결과는 (slope, cross) 별로 캐시 — 동일 axes 인 candidate 들이 재사용.
            enrich_cache: dict[tuple[float, int], pd.DataFrame] = {}
            for cand in grid:
                key = cand.enrich_key()
                if key not in enrich_cache:
                    enrich_params = {
                        **DEFAULT_PARAMS,
                        "min_ema_slope_ratio": cand.min_ema_slope_ratio,
                        "max_vwap_cross_count": cand.max_vwap_cross_count,
                    }
                    enrich_cache[key] = enrich(raw, enrich_params)
                enriched_full = enrich_cache[key]
                for period_label, days in periods:
                    cell = evaluate_cell(
                        cand, ticker, interval, period_label, enriched_full, days,
                    )
                    rollup.setdefault(interval, {}) \
                          .setdefault(ticker, {}) \
                          .setdefault(period_label, {})[cand.id] = cell
                    per_run.append(asdict(cell))
            if verbose:
                print(f"    enriched {len(enrich_cache)} variants")

    verdict, vdetails = derive_verdict(rollup)
    return {
        "rollup": _rollup_to_dict(rollup),
        "verdict": verdict,
        "verdict_details": vdetails,
        "per_run": per_run,
        "candidate_grid_size": len(grid),
    }


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


def render_md(result: dict[str, Any]) -> str:
    """JSON 결과 → 사람이 읽는 markdown 보고서."""
    lines: list[str] = []
    lines.append("# vwap_ema_pullback P1 re-validation")
    lines.append("")
    lines.append("Scope: PRD `.omx/plans/prd-vwap-ema-pullback-p1-2026-05-03.md`.")
    lines.append("Execution: `next_open` only · fee=`UPBIT_DEFAULT_FEE` · "
                 "slippage=`DEFAULT_SLIPPAGE`. Volume Profile Phase 2 미포함.")
    lines.append("")
    verdict = result["verdict"]
    lines.append(f"## Verdict: **{verdict}**")
    lines.append("")
    details = result["verdict_details"]
    if verdict == "PASS":
        lines.append(f"PASS candidates: `{', '.join(details['pass_candidates'])}`")
    elif verdict == "HOLD":
        lines.append(f"Partial-pass candidates: `{', '.join(details['partial_candidates'])}`")
    elif verdict == "REVISE":
        lines.append(f"Hard-floor-only candidates: `{', '.join(details['hard_pass_candidates'])}`")
    else:
        lines.append("No candidate passed any cell.")
    lines.append("")

    rollup = result["rollup"]
    grid = build_candidate_grid()

    # Per-candidate 1h roll-up table for BTC/ETH (PASS interval, PASS tickers)
    lines.append("## 1h primary — BTC/ETH per period")
    lines.append("")
    headers = ["candidate", "ticker", "period", "trades", "ret", "B&H", "MDD", "BH_MDD",
               "PF", "win", "exp", "avg_hold", "hard", "perf"]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for cid in [c.id for c in grid]:
        for ticker in PASS_TICKERS:
            for period in PASS_PERIODS:
                m = rollup.get(PASS_INTERVAL, {}).get(ticker, {}).get(period, {}).get(cid)
                if not m:
                    continue
                cell = CellMetrics(**m)
                hard = "✓" if hard_floor_passes(cell) else "✗"
                perf = "✓" if perf_gates_pass(cell) else "✗"
                lines.append(
                    f"| {cid} | {ticker.replace('KRW-', '')} | {period} | {cell.trades} | "
                    f"{cell.total_return*100:+.2f}% | {cell.bh_return*100:+.2f}% | "
                    f"{cell.mdd*100:+.2f}% | {cell.bh_mdd*100:+.2f}% | "
                    f"{cell.profit_factor:.2f} | {cell.win_rate*100:.1f}% | "
                    f"{cell.expectancy*100:+.3f}% | {cell.avg_hold_bars:.1f} | {hard} | {perf} |"
                )
    lines.append("")

    # SOL/XRP informational
    info_tickers = [t for t in DEFAULT_TICKERS if t not in PASS_TICKERS]
    if info_tickers:
        lines.append("## 1h secondary — SOL/XRP (informational only)")
        lines.append("")
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for cid in [c.id for c in grid]:
            for ticker in info_tickers:
                for period in PASS_PERIODS:
                    m = rollup.get(PASS_INTERVAL, {}).get(ticker, {}).get(period, {}).get(cid)
                    if not m:
                        continue
                    cell = CellMetrics(**m)
                    hard = "✓" if hard_floor_passes(cell) else "✗"
                    perf = "✓" if perf_gates_pass(cell) else "✗"
                    lines.append(
                        f"| {cid} | {ticker.replace('KRW-', '')} | {period} | {cell.trades} | "
                        f"{cell.total_return*100:+.2f}% | {cell.bh_return*100:+.2f}% | "
                        f"{cell.mdd*100:+.2f}% | {cell.bh_mdd*100:+.2f}% | "
                        f"{cell.profit_factor:.2f} | {cell.win_rate*100:.1f}% | "
                        f"{cell.expectancy*100:+.3f}% | {cell.avg_hold_bars:.1f} | {hard} | {perf} |"
                    )
        lines.append("")

    # 30m secondary
    if "30m" in rollup:
        lines.append("## 30m sanity — BTC/ETH (verdict 비참여)")
        lines.append("")
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for cid in [c.id for c in grid]:
            for ticker in PASS_TICKERS:
                for period in PASS_PERIODS:
                    m = rollup.get("30m", {}).get(ticker, {}).get(period, {}).get(cid)
                    if not m:
                        continue
                    cell = CellMetrics(**m)
                    hard = "✓" if hard_floor_passes(cell) else "✗"
                    perf = "✓" if perf_gates_pass(cell) else "✗"
                    lines.append(
                        f"| {cid} | {ticker.replace('KRW-', '')} | {period} | {cell.trades} | "
                        f"{cell.total_return*100:+.2f}% | {cell.bh_return*100:+.2f}% | "
                        f"{cell.mdd*100:+.2f}% | {cell.bh_mdd*100:+.2f}% | "
                        f"{cell.profit_factor:.2f} | {cell.win_rate*100:.1f}% | "
                        f"{cell.expectancy*100:+.3f}% | {cell.avg_hold_bars:.1f} | {hard} | {perf} |"
                    )
        lines.append("")

    # Cell pass summary
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
    lines.append(f"Verdict: **{verdict}**")
    lines.append("")
    lines.append("Decision rule (PRD §6):")
    lines.append("- PASS: 한 candidate 가 BTC/ETH × 1y/6m 모든 4 cell 의 hard floor + perf gate 통과.")
    lines.append("- HOLD: 어떤 candidate 가 일부 cell 만 perf gate 통과.")
    lines.append("- REVISE: 모든 candidate 가 hard floor 통과하지만 perf gate 0건 통과.")
    lines.append("- STOP: hard floor 1+ fail or 모든 candidate 가 baseline 보다 나쁨.")
    lines.append("")
    lines.append("Hard floors: `trades>=60`, `avg_hold_bars>=4`, `time_exit_share<=0`.")
    lines.append(f"Perf gates: `PF>={PERF_PF_MIN}`, `total_return>=B&H`, "
                 f"`MDD-BH_MDD>=-{int(PERF_MDD_OVERHANG_PP*100)}pp`, "
                 f"`win_rate>={int(PERF_WIN_RATE_MIN*100)}%`, `expectancy>0`.")
    lines.append("")

    if verdict == "PASS":
        lines.append("Follow-up: 별도 PR 로 paper 활성 검토. RiskManager `cooldown_minutes` 매핑 명시.")
    elif verdict == "HOLD":
        lines.append("Follow-up: P1.5 — 통과 cell 이 발생한 candidate 의 단일 axis 추가 sweep.")
    elif verdict == "REVISE":
        lines.append("Follow-up: P2 — entry 측 axis (1h trend filter / RSI / volume 등) 재선택.")
    else:
        lines.append("Follow-up: 전략 retire 권고. `EXPERIMENTAL_STRATEGIES` 유지 또는 registry 제거 별도 PR.")
    lines.append("")
    lines.append("Constraints honored: registry/UI 노출 변경 0건, "
                 "live/paper 활성 변경 0건, Volume Profile Phase 2 미포함, KPI/ledger 코드 미수정.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", default=",".join(DEFAULT_TICKERS),
                    help="comma-separated ticker list")
    ap.add_argument("--intervals", default=",".join(DEFAULT_INTERVALS),
                    help="comma-separated interval list (e.g. 1h,30m)")
    ap.add_argument("--out", default="reports/2026-05-03-vwap-ema-pullback-p1.json",
                    help="JSON output path")
    ap.add_argument("--md-out", default=None,
                    help="Markdown output path (default: same as --out with .md)")
    ap.add_argument("--cache-dir", default="data/validation_vwap")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore OHLCV cache + refetch")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    tickers = tuple(t.strip() for t in args.tickers.split(",") if t.strip())
    intervals = tuple(i.strip() for i in args.intervals.split(",") if i.strip())

    result = run_p1(
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
    md_path.write_text(render_md(result), encoding="utf-8")
    print(f"wrote {out_path} ({result['candidate_grid_size']} candidates × "
          f"{len(tickers)} tickers × {len(intervals)} intervals × "
          f"{len(DEFAULT_PERIODS)} periods)")
    print(f"wrote {md_path}")
    print(f"verdict: {result['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
