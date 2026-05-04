"""P2.5 fine-grid validation runner for vwap_ema_pullback strategy.

PRD: ``.omx/plans/prd-vwap-ema-pullback-p25-2026-05-04.md``
Test spec: ``.omx/plans/test-spec-vwap-ema-pullback-p25-2026-05-04.md``

Anchor (PRD §3.1) — P2 partial-pass `C_vol_1_2`:
  exit_mode=atr_buffer_exit, exit_atr_multiplier=0.3, slope=0.002, cross=2,
  cooldown_bars=2, volume_filter_mode=ge_1_2, volume_mean_window=20.

Axes evaluated:
- Volume threshold {1.1, 1.2, 1.3, 1.4} (PRD §3.2 — ge_1_1/3/4 신규)
- Volume mean window {10, 20, 30, 40}
- ETH-specific tweak: C_vol_1_2 + HTF fast_slow 결합
- HTF fast_slow / close_above_ema baseline (P2 sanity 재현)

**Out of scope** — Volume Profile Phase 2, walk-forward, paper/live activation,
새 entry filter axis (RSI/daily 등은 P2 결과 그대로).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

# CLI 실행 시 repo root 를 sys.path 에 추가 (pytest 는 pythonpath 로 자동).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402

from scripts.verify_vwap_ema_pullback import fetch_ohlcv  # noqa: E402
from scripts.vwap_ema_pullback_p1_runner import (  # noqa: E402
    PASS_INTERVAL,
    PASS_PERIODS,
    PASS_TICKERS,
    CellMetrics,
)
from scripts.vwap_ema_pullback_p2_runner import (  # noqa: E402
    ANCHOR_IMPROVEMENT_PP,
    DAILY_COUNT,
    DAILY_PYUPBIT,
    HARD_FLOOR_AVG_HOLD_BARS,
    HARD_FLOOR_TIME_EXIT_SHARE,
    HARD_FLOOR_TRADES,
    HARD_FLOOR_TRADES_6M,
    INTERVAL_META,
    PERF_MDD_OVERHANG_PP,
    PERF_PF_MIN,
    PERF_WIN_RATE_MIN,
    P2Candidate,
    _enrich_for_candidate,
    _rollup_to_dict,
    derive_paper_recommendation,
    derive_verdict_p2,
    evaluate_cell_p2,
    hard_floor_passes_p2,
    perf_gates_pass_p2,
)

DEFAULT_TICKERS = ("KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP")
DEFAULT_INTERVALS = ("1h", "30m")
DEFAULT_PERIODS: tuple[tuple[str, int], ...] = (("6m", 180), ("1y", 365))

P25_ANCHOR_ID = "anchor"


def build_p25_candidate_grid() -> list[P2Candidate]:
    """PRD §4 의 12 candidates."""
    grid: list[P2Candidate] = []

    # (1) anchor — P2 의 C_vol_1_2 와 정확히 동일.
    grid.append(P2Candidate(id=P25_ANCHOR_ID,
                            volume_filter_mode="ge_1_2",
                            volume_mean_window=20))

    # (2) Volume threshold sweep (window=20 고정) — 3
    grid.append(P2Candidate(id="vol_1_1",
                            volume_filter_mode="ge_1_1",
                            volume_mean_window=20))
    grid.append(P2Candidate(id="vol_1_3",
                            volume_filter_mode="ge_1_3",
                            volume_mean_window=20))
    grid.append(P2Candidate(id="vol_1_4",
                            volume_filter_mode="ge_1_4",
                            volume_mean_window=20))

    # (3) Volume window sweep (threshold=1.2 고정) — 3
    grid.append(P2Candidate(id="vol_w10",
                            volume_filter_mode="ge_1_2",
                            volume_mean_window=10))
    grid.append(P2Candidate(id="vol_w30",
                            volume_filter_mode="ge_1_2",
                            volume_mean_window=30))
    grid.append(P2Candidate(id="vol_w40",
                            volume_filter_mode="ge_1_2",
                            volume_mean_window=40))

    # (4) Combined fine-grid — 1
    grid.append(P2Candidate(id="vol_1_3_w30",
                            volume_filter_mode="ge_1_3",
                            volume_mean_window=30))

    # (5) ETH-specific tweak (HTF fast_slow + volume) — 2
    grid.append(P2Candidate(id="vol_1_2_htf_fs",
                            volume_filter_mode="ge_1_2",
                            volume_mean_window=20,
                            htf_trend_filter_mode="htf_ema_fast_slow"))
    grid.append(P2Candidate(id="vol_1_3_htf_fs",
                            volume_filter_mode="ge_1_3",
                            volume_mean_window=20,
                            htf_trend_filter_mode="htf_ema_fast_slow"))

    # (6) HTF baseline (P2 sanity 재현) — 2
    grid.append(P2Candidate(id="htf_fs_only",
                            volume_filter_mode="off",
                            htf_trend_filter_mode="htf_ema_fast_slow"))
    grid.append(P2Candidate(id="htf_close_only",
                            volume_filter_mode="off",
                            htf_trend_filter_mode="htf_close_above_ema"))

    return grid


# ---------------------------------------------------------------------------
# Per-ticker paper recommendation (PRD §6 신규)
# ---------------------------------------------------------------------------

def derive_per_ticker_paper_recommendation(
    rollup: dict,
    anchor_diff: dict,
    verdict: str,
    pass_candidates: list[str],
) -> dict[str, str]:
    """Per-ticker {BTC, ETH} → recommendation string.

    PRD §6 매핑:
    - PASS + anchor diff +3pp 이상 → recommend_separate_pr
    - PASS + anchor diff < +3pp → hold (marginal)
    - HOLD + BTC 4/4 perf_gates_pass + ETH 적어도 1 cell ret 이 anchor BTC ret 보다 개선
        → BTC: recommend_btc_only_paper · ETH: hold
    - HOLD + 위 조건 미충족 → both: hold
    - REVISE → both: consider_retire
    - STOP → both: retire
    """
    out = {"BTC": "hold", "ETH": "hold"}

    if verdict == "REVISE":
        return {"BTC": "consider_retire", "ETH": "consider_retire"}
    if verdict == "STOP":
        return {"BTC": "retire", "ETH": "retire"}

    if verdict == "PASS":
        # PASS — P2 derive_paper_recommendation 호환.
        rec = derive_paper_recommendation(verdict, anchor_diff, pass_candidates)
        return {"BTC": rec, "ETH": rec}

    # verdict == "HOLD" — BTC-only 분기 검사.
    # 권고 조건: 동일 candidate 가 BTC 4/4 perf_gates_pass + ETH 적어도 1 cell ret 이
    # P25 anchor 의 ETH ret 보다 개선. 두 조건을 별개 candidate 에 분리해서 적용하면
    # "어떤 후보로 BTC-only 운영" 권고가 의미를 잃으므로 same-candidate 강제.
    interval_data = rollup.get(PASS_INTERVAL, {})
    btc_data = interval_data.get("KRW-BTC", {})
    eth_data = interval_data.get("KRW-ETH", {})

    candidate_ids: list[str] = []
    for period_data in btc_data.values():
        candidate_ids = list(period_data.keys())
        break

    anchor_eth_returns: dict[str, float] = {}
    for period in PASS_PERIODS:
        anchor_cell = eth_data.get(period, {}).get(P25_ANCHOR_ID)
        if anchor_cell is not None:
            anchor_eth_returns[period] = anchor_cell.total_return

    for cid in candidate_ids:
        # 동일 candidate 의 BTC 양 cell 모두 perf_gates_pass?
        btc_pass = True
        seen = 0
        for period in PASS_PERIODS:
            m = btc_data.get(period, {}).get(cid)
            if m is None:
                btc_pass = False
                break
            seen += 1
            if not (hard_floor_passes_p2(m) and perf_gates_pass_p2(m)):
                btc_pass = False
                break
        if not btc_pass or seen != len(PASS_PERIODS):
            continue

        # 동일 candidate 의 ETH 가 anchor 대비 개선?
        # (anchor 자체는 자기 자신과 비교 시 항상 False — 자동 제외)
        for period in PASS_PERIODS:
            cand_cell = eth_data.get(period, {}).get(cid)
            anchor_ret = anchor_eth_returns.get(period)
            if cand_cell is None or anchor_ret is None:
                continue
            if cand_cell.total_return > anchor_ret + 1e-6:
                return {"BTC": "recommend_btc_only_paper", "ETH": "hold"}

    return out  # both hold


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_p25(
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
    """P2.5 sweep — fetch base + HTF + daily, enrich per candidate, evaluate, verdict."""
    grid = candidate_grid or build_p25_candidate_grid()
    fetch = fetch_fn or fetch_ohlcv

    rollup: dict = {}
    per_run: list[dict] = []

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
    anchor_diff = compute_anchor_diff_p25(rollup)
    pass_candidates = vdetails.get("pass_candidates", []) if verdict == "PASS" else []
    paper_recommendation = derive_paper_recommendation(verdict, anchor_diff, pass_candidates)
    per_ticker_recommendation = derive_per_ticker_paper_recommendation(
        rollup, anchor_diff, verdict, pass_candidates,
    )

    return {
        "rollup": _rollup_to_dict(rollup),
        "verdict": verdict,
        "verdict_details": vdetails,
        "anchor_id": P25_ANCHOR_ID,
        "anchor_diff_pp": anchor_diff,
        "paper_recommendation": paper_recommendation,
        "per_ticker_recommendation": per_ticker_recommendation,
        "per_run": per_run,
        "candidate_grid_size": len(grid),
    }


def compute_anchor_diff_p25(rollup: dict) -> dict[str, dict[str, float]]:
    """P25 anchor 기준 ret diff (pp). P2 의 compute_anchor_diff 와 같은 구조 — anchor_id 만 P25 anchor."""
    interval_data = rollup.get(PASS_INTERVAL, {})
    out: dict[str, dict[str, float]] = {}
    for ticker in PASS_TICKERS:
        for period in PASS_PERIODS:
            cell_map = interval_data.get(ticker, {}).get(period, {})
            anchor_cell = cell_map.get(P25_ANCHOR_ID)
            if anchor_cell is None:
                continue
            for cid, cell in cell_map.items():
                if cid == P25_ANCHOR_ID:
                    continue
                key = f"{ticker.replace('KRW-', '')}_{period}_ret_diff_pp"
                out.setdefault(cid, {})[key] = (cell.total_return - anchor_cell.total_return) * 100.0
    return out


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_md_p25(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# vwap_ema_pullback P2.5 fine-grid validation")
    lines.append("")
    lines.append("Scope: PRD `.omx/plans/prd-vwap-ema-pullback-p25-2026-05-04.md`.")
    lines.append("Anchor: P2 partial-pass `C_vol_1_2` (atr_buffer 0.3 / slope 0.002 / cross 2 / "
                 "cooldown 2 / vol_ge_1_2 / vol_window 20).")
    lines.append("Execution: `next_open` only · fee=`UPBIT_DEFAULT_FEE` · "
                 "slippage=`DEFAULT_SLIPPAGE`. Volume Profile Phase 2 미포함.")
    lines.append("")
    verdict = result["verdict"]
    paper_rec = result["paper_recommendation"]
    per_ticker = result["per_ticker_recommendation"]
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

    # Per-ticker recommendation (P2.5 신규)
    lines.append("## Per-ticker paper recommendation")
    lines.append("")
    lines.append(f"- Full recommendation: **{paper_rec}**")
    lines.append(f"- BTC: **{per_ticker.get('BTC', 'n/a')}**")
    lines.append(f"- ETH: **{per_ticker.get('ETH', 'n/a')}**")
    lines.append("")

    rollup = result["rollup"]
    grid = build_p25_candidate_grid()
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
    lines.append("## 1h primary — BTC/ETH per period (anchor_diff in pp vs P25 anchor)")
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
        lines.append("## 1h secondary — SOL/XRP (informational, verdict 비참여)")
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
        lines.append("## 30m sanity — BTC/ETH (informational, verdict 비참여)")
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
    lines.append(f"Verdict: **{verdict}** · Paper: **{paper_rec}** · "
                 f"BTC rec: **{per_ticker.get('BTC', 'n/a')}** · "
                 f"ETH rec: **{per_ticker.get('ETH', 'n/a')}**")
    lines.append("")
    lines.append("Decision rule (PRD §6):")
    lines.append("- PASS: 한 candidate 가 BTC/ETH × 1y/6m 모든 4 cell hard floor + perf gate 통과.")
    lines.append("- HOLD: 어떤 candidate 가 일부 cell perf gate 통과.")
    lines.append("  · BTC 4/4 + ETH 적어도 1 cell ret 개선 → BTC-only paper 권고.")
    lines.append("- REVISE: 모든 candidate hard floor 통과하지만 perf gate 0건. "
                 "**P2.5 도 fail 이면 strategy retire 결정**.")
    lines.append("- STOP: hard floor 1+ fail or 모든 candidate 가 anchor 보다 나쁨.")
    lines.append("")
    lines.append(f"Hard floors: 1y trades>=`{HARD_FLOOR_TRADES}` · 6m trades>=`{HARD_FLOOR_TRADES_6M}` · "
                 f"avg_hold_bars>=`{HARD_FLOOR_AVG_HOLD_BARS}` · "
                 f"time_exit_share<=`{HARD_FLOOR_TIME_EXIT_SHARE}`.")
    lines.append(f"Perf gates: PF>=`{PERF_PF_MIN}` · ret>=B&H · "
                 f"MDD-BH_MDD>=`-{int(PERF_MDD_OVERHANG_PP*100)}pp` · "
                 f"win>=`{int(PERF_WIN_RATE_MIN*100)}%` · expectancy>0.")
    lines.append(f"Anchor improvement check: PASS 시 BTC/ETH 평균 ret diff >= "
                 f"+`{int(ANCHOR_IMPROVEMENT_PP)}pp` 이어야 paper 권고.")
    lines.append("")

    btc_rec = per_ticker.get("BTC", "hold")
    if verdict == "PASS" and paper_rec == "recommend_separate_pr":
        lines.append("Follow-up: 별도 PR 로 paper 활성 검토. RiskManager `cooldown_minutes` 매핑 명시.")
    elif verdict == "PASS":
        lines.append("Follow-up: PASS 이지만 anchor 대비 marginal — paper 보류, P3 quality 재검증.")
    elif btc_rec == "recommend_btc_only_paper":
        lines.append("Follow-up: **BTC-only paper PR 검토** — 별도 PR 에서 slot/capital 정책 + ETH 비활성 지정.")
    elif verdict == "HOLD":
        lines.append("Follow-up: P3 — cross-asset BTC daily regime / 30m 단독 트랙 / 새 entry axis 검토.")
    elif verdict == "REVISE":
        lines.append("Follow-up: **strategy retire 권고** — P2.5 가 entry-side fine-grid 까지 fail. "
                     "registry 제거 또는 EXPERIMENTAL 영구 유지 별도 PR.")
    else:
        lines.append("Follow-up: **strategy retire 권고** — hard floor 통과 자체 못함.")
    lines.append("")
    lines.append("Constraints honored: registry/UI 노출 변경 0건 · live/paper 활성 변경 0건 · "
                 "Volume Profile Phase 2 미포함 · KPI/ledger 코드 미수정 · enricher 변경 0건.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickers", default=",".join(DEFAULT_TICKERS),
                    help="comma-separated ticker list")
    ap.add_argument("--intervals", default=",".join(DEFAULT_INTERVALS),
                    help="comma-separated interval list")
    ap.add_argument("--out", default="reports/vwap_ema_pullback_p25_validation.json",
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

    result = run_p25(
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
    md_path.write_text(render_md_p25(result), encoding="utf-8")
    print(f"wrote {out_path} ({result['candidate_grid_size']} candidates × "
          f"{len(tickers)} tickers × {len(intervals)} intervals × "
          f"{len(DEFAULT_PERIODS)} periods)")
    print(f"wrote {md_path}")
    print(f"verdict: {result['verdict']} · "
          f"paper: {result['paper_recommendation']} · "
          f"BTC: {result['per_ticker_recommendation']['BTC']} · "
          f"ETH: {result['per_ticker_recommendation']['ETH']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
