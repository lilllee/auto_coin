"""Walk-forward diagnostics for ``regime_relative_breakout_30m`` (0004).

Analysis-only.  No strategy code change, no paper/live, no UI/KPI/settings,
no parameter tuning, no re-backtesting of new candidates.

Goal per Codex 0004:

> Determine whether the zero/negative OOS folds seen in the 0003 walk-forward
> are caused by correct regime stand-off or by over-tight entry filters.

For every OOS fold × ticker (ETH, XRP):

- Count how many 30m bars survive each entry-filter stage (the funnel).
- Compute ratios vs total bars and identify the stage with the largest
  marginal drop (``primary_blocker``).
- Count near-misses that are blocked by exactly one remaining filter
  (volume / breakout / rs_7d / hourly_trend).

For folds where the selected candidate produced trades but negative
expectancy, pull the per-reason exit mix from the existing walk-forward
report and summarize whether losses came from initial stops (strategy
caught wrong-side breakouts quickly) or from trailing/time exits
(strategy held through reversals).

MFE/MAE per trade is not reconstructed — trade objects do not carry those
fields and the cost of re-running path tracking was deemed not justified
per the 0004 spec "skip if expensive".

Verdict is one of:

- ``STANDOFF_VALID``  — zero/negative folds mostly caused by absent regime
  / RS / trend; the strategy correctly stands down when those are off.
- ``OVERFILTERED``    — many near-misses exist, a late-stage tight filter
  (volume or breakout) repeatedly blocks otherwise aligned setups.
- ``MIXED``           — both stand-off and overfiltered patterns appear.
- ``INCONCLUSIVE``    — problem-sample counts too sparse or signals contradict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from regime_relative_breakout_30m_walk_forward import (  # noqa: E402
    ALT_TICKERS,
    BASE_PARAMS,
    FETCH_DAYS,
    REGIME_TICKER,
    TICKERS,
    _fetch_ohlcv,
)

from auto_coin.data.candles import enrich_regime_relative_breakout_30m  # noqa: E402

AS_OF = "2026-04-23"
DIAG_REPORT_PATH = Path("reports/2026-04-23-regime-relative-breakout-30m-wf-diagnostics.json")
WF_REPORT_PATH = Path("reports/2026-04-23-regime-relative-breakout-30m-walk-forward.json")


# ---------------------------------------------------------------------------
# Funnel counting (pure, over an enriched test-window slice)
# ---------------------------------------------------------------------------


def _slice_range(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return df.loc[(df.index >= start) & (df.index < end)].copy()


def _condition_series(df: pd.DataFrame) -> dict[str, pd.Series]:
    regime = df["btc_daily_regime_on"].astype("boolean").fillna(False).astype(bool)
    rs24 = (df["target_rs_24h_vs_btc"] > 0).fillna(False)
    rs7 = (df["target_rs_7d_vs_btc"] > 0).fillna(False)
    rs_both = rs24 & rs7
    hourly_trend = (
        (df["hourly_close"] > df["hourly_ema20"])
        & (df["hourly_ema20"] > df["hourly_ema60"])
        & (df["hourly_ema20_slope_3"] >= 0)
    ).fillna(False)
    breakout = (
        (df["close"] > df["prior_high_6"]) & (df["close_location_value"] >= 0.55)
    ).fillna(False)
    volume = (df["volume"] > df["volume_ma_20"] * BASE_PARAMS["volume_mult"]).fillna(False)
    return {
        "regime": regime,
        "rs_24h": rs24,
        "rs_7d": rs7,
        "rs_both": rs_both,
        "hourly_trend": hourly_trend,
        "breakout": breakout,
        "volume": volume,
    }


def compute_funnel(df: pd.DataFrame) -> dict[str, Any]:
    """Stage + near-miss counts for one ticker's test-window slice."""
    cs = _condition_series(df)
    regime = cs["regime"]
    rs_both = cs["rs_both"]
    hourly_trend = cs["hourly_trend"]
    breakout = cs["breakout"]
    volume = cs["volume"]

    stage_regime_rs = regime & rs_both
    stage_regime_rs_trend = stage_regime_rs & hourly_trend
    stage_regime_rs_trend_breakout = stage_regime_rs_trend & breakout
    stage_full = stage_regime_rs_trend_breakout & volume

    bars_total = int(len(df))
    counts: dict[str, int] = {
        "bars_total": bars_total,
        "btc_daily_regime_on_count": int(regime.sum()),
        "rs_24h_positive_count": int(cs["rs_24h"].sum()),
        "rs_7d_positive_count": int(cs["rs_7d"].sum()),
        "rs_both_positive_count": int(rs_both.sum()),
        "hourly_trend_count": int(hourly_trend.sum()),
        "breakout_count": int(breakout.sum()),
        "volume_count": int(volume.sum()),
        "regime_and_rs_count": int(stage_regime_rs.sum()),
        "regime_rs_trend_count": int(stage_regime_rs_trend.sum()),
        "regime_rs_trend_breakout_count": int(stage_regime_rs_trend_breakout.sum()),
        "full_entry_count": int(stage_full.sum()),
    }

    # Near-miss: qualifying for everything except one specific filter.
    stage_regime_rs_trend_volume = stage_regime_rs_trend & volume
    near_miss_volume = stage_regime_rs_trend_breakout & (~volume)
    near_miss_breakout = stage_regime_rs_trend_volume & (~breakout)
    stage_regime_rs24_trend_breakout_volume = (
        regime & cs["rs_24h"] & hourly_trend & breakout & volume
    )
    near_miss_rs7 = stage_regime_rs24_trend_breakout_volume & (~cs["rs_7d"])
    near_miss_trend = (regime & rs_both & breakout & volume) & (~hourly_trend)

    counts["full_entry_except_volume"] = int(near_miss_volume.sum())
    counts["full_entry_except_breakout"] = int(near_miss_breakout.sum())
    counts["full_entry_except_rs_7d"] = int(near_miss_rs7.sum())
    counts["full_entry_except_hourly_trend"] = int(near_miss_trend.sum())

    ratios: dict[str, float] = {}
    if bars_total > 0:
        for key in (
            "btc_daily_regime_on_count",
            "rs_24h_positive_count",
            "rs_7d_positive_count",
            "rs_both_positive_count",
            "hourly_trend_count",
            "breakout_count",
            "volume_count",
            "regime_and_rs_count",
            "regime_rs_trend_count",
            "regime_rs_trend_breakout_count",
            "full_entry_count",
            "full_entry_except_volume",
            "full_entry_except_breakout",
            "full_entry_except_rs_7d",
            "full_entry_except_hourly_trend",
        ):
            ratios[key + "_ratio"] = counts[key] / bars_total

    stage_drops = _stage_drops(counts)
    primary = _primary_blocker(counts, stage_drops)
    return {
        "counts": counts,
        "ratios": ratios,
        "stage_drops": stage_drops,
        "primary_blocker": primary,
    }


def _stage_drops(counts: dict[str, int]) -> dict[str, int]:
    return {
        "btc_regime_off": counts["bars_total"] - counts["btc_daily_regime_on_count"],
        "relative_strength_absent": (
            counts["btc_daily_regime_on_count"] - counts["regime_and_rs_count"]
        ),
        "hourly_trend_absent": (
            counts["regime_and_rs_count"] - counts["regime_rs_trend_count"]
        ),
        "breakout_absent": (
            counts["regime_rs_trend_count"] - counts["regime_rs_trend_breakout_count"]
        ),
        "volume_absent": (
            counts["regime_rs_trend_breakout_count"] - counts["full_entry_count"]
        ),
    }


def _primary_blocker(counts: dict[str, int], drops: dict[str, int]) -> str:
    if counts["full_entry_count"] > 0:
        return "no_problem_entries_exist"
    total = sum(drops.values())
    if total <= 0:
        return "no_problem_entries_exist"
    largest_name, largest_val = max(drops.items(), key=lambda kv: kv[1])
    if largest_val / total < 0.5:
        return "combined_filter_too_tight"
    return largest_name


# ---------------------------------------------------------------------------
# Verdict classifier
# ---------------------------------------------------------------------------


STANDOFF_BLOCKERS = {
    "btc_regime_off",
    "relative_strength_absent",
    "hourly_trend_absent",
}
OVERFILTER_BLOCKERS = {
    "breakout_absent",
    "volume_absent",
}


def classify_diagnostic_verdict(
    problem_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate problem-sample blocker types and label the diagnostic verdict."""
    if not problem_samples:
        return {
            "label": "INCONCLUSIVE",
            "reason": "no problem samples",
            "counts": {},
        }
    categories = {
        "standoff": 0,
        "overfiltered": 0,
        "combined": 0,
        "has_entries_but_negative": 0,
    }
    for sample in problem_samples:
        blocker = sample["primary_blocker"]
        near_miss_total = (
            sample["counts"]["full_entry_except_volume"]
            + sample["counts"]["full_entry_except_breakout"]
            + sample["counts"]["full_entry_except_rs_7d"]
            + sample["counts"]["full_entry_except_hourly_trend"]
        )
        if blocker == "no_problem_entries_exist":
            categories["has_entries_but_negative"] += 1
        elif blocker == "combined_filter_too_tight":
            categories["combined"] += 1
        elif blocker in STANDOFF_BLOCKERS:
            categories["standoff"] += 1
        elif blocker in OVERFILTER_BLOCKERS and near_miss_total >= 3:
            categories["overfiltered"] += 1
        elif blocker in OVERFILTER_BLOCKERS:
            categories["combined"] += 1
        else:
            categories["combined"] += 1

    total = len(problem_samples)
    standoff_ratio = categories["standoff"] / total if total else 0.0
    overfiltered_ratio = categories["overfiltered"] / total if total else 0.0
    # Threshold: majority (>= 0.60) of a single category decides.
    if total < 4:
        label = "INCONCLUSIVE"
    elif standoff_ratio >= 0.60:
        label = "STANDOFF_VALID"
    elif overfiltered_ratio >= 0.60:
        label = "OVERFILTERED"
    elif standoff_ratio >= 0.30 and overfiltered_ratio >= 0.30:
        label = "MIXED"
    elif standoff_ratio > overfiltered_ratio and standoff_ratio >= 0.40:
        label = "STANDOFF_VALID"
    elif overfiltered_ratio > standoff_ratio and overfiltered_ratio >= 0.40:
        label = "OVERFILTERED"
    else:
        label = "MIXED" if categories["standoff"] + categories["overfiltered"] else "INCONCLUSIVE"
    return {
        "label": label,
        "counts": categories,
        "ratios": {
            "standoff": standoff_ratio,
            "overfiltered": overfiltered_ratio,
            "combined": categories["combined"] / total if total else 0.0,
            "has_entries_but_negative": categories["has_entries_but_negative"] / total if total else 0.0,
        },
        "problem_sample_count": total,
    }


# ---------------------------------------------------------------------------
# Exit-reason breakdown for negative-expectancy (fold, ticker) samples
# ---------------------------------------------------------------------------


def _classify_exit_category(reason: str) -> str:
    if reason.endswith("_initial_stop"):
        return "initial_stop"
    if reason.endswith("_trailing_exit"):
        return "trailing_exit"
    if reason.endswith("_trend_exit"):
        return "trend_exit"
    if reason.endswith("_regime_off_exit"):
        return "regime_off_exit"
    if reason.endswith("_time_exit"):
        return "time_exit"
    return "other"


def _summarize_exit_mix(exit_mix: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[str, dict[str, float]] = {}
    total_trades = sum(int(mix["trade_count"]) for mix in exit_mix.values())
    for reason, mix in exit_mix.items():
        cat = _classify_exit_category(reason)
        bucket = grouped.setdefault(
            cat,
            {
                "trade_count": 0,
                "ratio": 0.0,
                "avg_return_weighted": 0.0,
                "avg_hold_bars_weighted": 0.0,
                "_sum_ret_count": 0.0,
                "_sum_hold_count": 0.0,
            },
        )
        bucket["trade_count"] += int(mix["trade_count"])
        bucket["_sum_ret_count"] += float(mix["avg_return"]) * int(mix["trade_count"])
        bucket["_sum_hold_count"] += float(mix["avg_hold_bars"]) * int(mix["trade_count"])
    for bucket in grouped.values():
        tc = bucket["trade_count"]
        bucket["ratio"] = tc / total_trades if total_trades else 0.0
        bucket["avg_return_weighted"] = bucket["_sum_ret_count"] / tc if tc else 0.0
        bucket["avg_hold_bars_weighted"] = bucket["_sum_hold_count"] / tc if tc else 0.0
        del bucket["_sum_ret_count"]
        del bucket["_sum_hold_count"]
    return {"total_trades": total_trades, "by_category": grouped}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _load_wf_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(
            f"walk-forward report not found: {path}. Run the walk-forward script first."
        )
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-days", type=int, default=FETCH_DAYS)
    parser.add_argument("--out", type=Path, default=DIAG_REPORT_PATH)
    parser.add_argument("--wf-report", type=Path, default=WF_REPORT_PATH)
    args = parser.parse_args(argv)

    wf_report = _load_wf_report(args.wf_report)
    fold_records = wf_report["folds"]

    print(f"fetch minute30 for {TICKERS}")
    thirty = {t: _fetch_ohlcv(t, "minute30", args.fetch_days) for t in TICKERS}
    print(f"fetch minute60 for {TICKERS}")
    hourly = {t: _fetch_ohlcv(t, "minute60", args.fetch_days) for t in TICKERS}
    print(f"fetch day for {REGIME_TICKER}")
    btc_daily = _fetch_ohlcv(REGIME_TICKER, "day", args.fetch_days)
    btc_30m = thirty[REGIME_TICKER]

    enriched: dict[str, pd.DataFrame] = {}
    for ticker in ALT_TICKERS:
        enriched[ticker] = enrich_regime_relative_breakout_30m(
            thirty[ticker],
            daily_regime_df=btc_daily,
            daily_regime_ma_window=BASE_PARAMS["daily_regime_ma_window"],
            hourly_setup_df=hourly[ticker],
            hourly_ema_fast=BASE_PARAMS["hourly_ema_fast"],
            hourly_ema_slow=BASE_PARAMS["hourly_ema_slow"],
            hourly_slope_lookback=BASE_PARAMS["hourly_slope_lookback"],
            rs_reference_df=btc_30m,
            rs_24h_bars_30m=BASE_PARAMS["rs_24h_bars_30m"],
            rs_7d_bars_30m=BASE_PARAMS["rs_7d_bars_30m"],
            breakout_lookback_30m=BASE_PARAMS["breakout_lookback_30m"],
            volume_window_30m=BASE_PARAMS["volume_window_30m"],
            atr_window=BASE_PARAMS["atr_window"],
        )

    fold_diagnostics: list[dict[str, Any]] = []
    problem_samples: list[dict[str, Any]] = []
    negative_fold_breakdowns: list[dict[str, Any]] = []
    zero_trade_focus: dict[str, dict[str, Any]] = {}

    for fold in fold_records:
        fold_id = fold["fold"]
        test_start = pd.Timestamp(fold["test_start"])
        test_end = pd.Timestamp(fold["test_end"])
        selected = fold["selected_candidate"]
        per_ticker: dict[str, Any] = {}
        for ticker in ALT_TICKERS:
            sample = _slice_range(enriched[ticker], test_start, test_end)
            funnel = compute_funnel(sample)
            test_m = fold["test_metrics"][selected][ticker]
            trades = int(test_m["total_trades"])
            expectancy = float(test_m["expectancy"])
            sample_status: str
            if trades == 0:
                sample_status = "zero_trade"
            elif expectancy > 0:
                sample_status = "positive_expectancy"
            else:
                sample_status = "negative_expectancy"
            per_ticker[ticker] = {
                "selected_candidate": selected,
                "trades": trades,
                "expectancy": expectancy,
                "cumulative_return": float(test_m["cumulative_return"]),
                "benchmark_return": float(test_m["benchmark_return"]),
                "status": sample_status,
                **funnel,
            }
            if sample_status in {"zero_trade", "negative_expectancy"}:
                problem_samples.append(
                    {
                        "fold": fold_id,
                        "ticker": ticker,
                        "status": sample_status,
                        **funnel,
                    }
                )
            if sample_status == "negative_expectancy":
                negative_fold_breakdowns.append(
                    {
                        "fold": fold_id,
                        "ticker": ticker,
                        "selected_candidate": selected,
                        "trades": trades,
                        "expectancy": expectancy,
                        "cumulative_return": float(test_m["cumulative_return"]),
                        "exit_summary": _summarize_exit_mix(test_m.get("exit_mix", {})),
                    }
                )
        fold_diagnostics.append(
            {
                "fold": fold_id,
                "test_start": fold["test_start"],
                "test_end": fold["test_end"],
                "selected_candidate": selected,
                "per_ticker": per_ticker,
            }
        )
        if fold_id in (7, 8):
            zero_trade_focus[f"fold_{fold_id}"] = {
                "test_start": fold["test_start"],
                "test_end": fold["test_end"],
                "selected_candidate": selected,
                "eth": per_ticker["KRW-ETH"],
                "xrp": per_ticker["KRW-XRP"],
                "explanation": _human_readable_zero_trade(
                    per_ticker["KRW-ETH"], per_ticker["KRW-XRP"]
                ),
            }

    verdict = classify_diagnostic_verdict(problem_samples)

    report = {
        "as_of": AS_OF,
        "strategy": "regime_relative_breakout_30m",
        "scope": "walk-forward diagnostics only; no strategy/paper/live changes",
        "wf_report_path": str(args.wf_report),
        "num_folds": len(fold_diagnostics),
        "num_problem_samples": len(problem_samples),
        "mfe_mae_skipped_reason": (
            "trade objects do not carry per-trade MFE/MAE and reconstructing "
            "them from OHLCV windows adds cost for little diagnostic signal "
            "beyond the exit-reason breakdown"
        ),
        "fold_diagnostics": fold_diagnostics,
        "negative_fold_breakdowns": negative_fold_breakdowns,
        "zero_trade_fold_focus": zero_trade_focus,
        "diagnostic_verdict": verdict,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(args.out)
    print(
        json.dumps(
            {
                "num_problem_samples": len(problem_samples),
                "verdict": verdict,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


def _human_readable_zero_trade(eth: dict[str, Any], xrp: dict[str, Any]) -> dict[str, Any]:
    """Produce a short prose explanation for fold 7 / 8 where both alts had 0 trades."""
    lines: list[str] = []
    for ticker, payload in (("KRW-ETH", eth), ("KRW-XRP", xrp)):
        c = payload["counts"]
        r = payload["ratios"]
        lines.append(
            f"{ticker}: bars={c['bars_total']}, "
            f"btc_regime_on={c['btc_daily_regime_on_count']} "
            f"({r.get('btc_daily_regime_on_count_ratio', 0.0):.1%}), "
            f"rs_both={c['rs_both_positive_count']} "
            f"({r.get('rs_both_positive_count_ratio', 0.0):.1%}), "
            f"trend={c['hourly_trend_count']} "
            f"({r.get('hourly_trend_count_ratio', 0.0):.1%}), "
            f"breakout={c['breakout_count']} "
            f"({r.get('breakout_count_ratio', 0.0):.1%}), "
            f"volume={c['volume_count']} "
            f"({r.get('volume_count_ratio', 0.0):.1%}), "
            f"full={c['full_entry_count']}, "
            f"near-miss "
            f"(-vol={c['full_entry_except_volume']}, "
            f"-brk={c['full_entry_except_breakout']}, "
            f"-rs7={c['full_entry_except_rs_7d']}, "
            f"-trend={c['full_entry_except_hourly_trend']}), "
            f"blocker={payload['primary_blocker']}"
        )
    return {"summary_lines": lines}


if __name__ == "__main__":
    raise SystemExit(main())
