"""Unit tests for ``regime_relative_breakout_30m`` strategy + enricher.

All tests are offline: no pyupbit, no network, no persistence.  Tests synth
minimal enriched DataFrames that satisfy the column contract used by
``RegimeRelativeBreakout30mStrategy.generate_signal`` and ``generate_exit``.
Two tests (14, 15) exercise the real ``enrich_regime_relative_breakout_30m``
on synthetic OHLCV to verify no-lookahead shifts on prior_high, volume_ma,
and daily regime.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from auto_coin.data.candles import enrich_regime_relative_breakout_30m
from auto_coin.strategy import create_strategy
from auto_coin.strategy.base import MarketSnapshot, PositionSnapshot, Signal
from auto_coin.strategy.regime_relative_breakout_30m import (
    RegimeRelativeBreakout30mStrategy,
)

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
import regime_relative_breakout_30m_stage2 as stage2  # noqa: E402
import regime_relative_breakout_30m_walk_forward as wf  # noqa: E402

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_enriched_df(n: int = 60, **overrides: object) -> pd.DataFrame:
    """Build a synthetic enriched 30m DataFrame with all columns satisfied
    at the final row by default.  Individual tests flip columns via ``overrides``
    which are assigned to the LAST row only."""
    idx = pd.date_range("2026-03-01", periods=n, freq="30min")
    close = np.linspace(100.0, 120.0, n)
    high = close + 0.5
    low = close - 0.5
    df = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 200.0),
            # breakout features
            "prior_high_6": close - 0.2,  # last close well above prior high
            "volume_ma_20": np.full(n, 100.0),
            "volume_ratio": np.full(n, 2.0),
            "close_location_value": np.full(n, 0.8),
            # 30m / ATR
            "atr14": np.full(n, 1.0),
            # Daily BTC regime projected onto 30m
            "btc_daily_regime_on": [True] * n,
            # 1H projected features
            "hourly_close": close + 2.0,
            "hourly_ema20": close + 1.0,
            "hourly_ema60": close - 1.0,
            "hourly_ema20_slope_3": np.full(n, 0.5),
            "hourly_close_below_ema20": [False] * n,
            "hourly_close_below_ema20_run": np.zeros(n),
            # RS
            "target_rs_24h_vs_btc": np.full(n, 0.02),
            "target_rs_7d_vs_btc": np.full(n, 0.03),
        },
        index=idx,
    )
    for k, v in overrides.items():
        df.iloc[-1, df.columns.get_loc(k)] = v
    return df


def _snap(df: pd.DataFrame, *, price: float | None = None, has_position: bool = False) -> MarketSnapshot:
    return MarketSnapshot(
        df=df,
        current_price=float(df["close"].iloc[-1]) if price is None else price,
        has_position=has_position,
        interval="minute30",
        bar_seconds=1800,
    )


def _position(entry: float = 100.0, *, hold_bars: int = 4, highest_high: float = 110.0) -> PositionSnapshot:
    return PositionSnapshot(
        entry_price=entry,
        hold_days=hold_bars,
        highest_close=highest_high,
        highest_high=highest_high,
        interval="minute30",
        bar_seconds=1800,
        hold_bars=hold_bars,
    )


# ---------------------------------------------------------------------------
# Test 1 — validation
# ---------------------------------------------------------------------------


def test_strategy_validation_rejects_invalid_params() -> None:
    with pytest.raises(ValueError):
        RegimeRelativeBreakout30mStrategy(daily_regime_ma_window=1)
    with pytest.raises(ValueError):
        RegimeRelativeBreakout30mStrategy(hourly_ema_slow=10, hourly_ema_fast=20)
    with pytest.raises(ValueError):
        RegimeRelativeBreakout30mStrategy(volume_mult=0.0)
    with pytest.raises(ValueError):
        RegimeRelativeBreakout30mStrategy(close_location_min=1.5)
    with pytest.raises(ValueError):
        RegimeRelativeBreakout30mStrategy(trend_exit_confirm_bars=0)
    with pytest.raises(ValueError):
        RegimeRelativeBreakout30mStrategy(max_hold_bars_30m=0)
    # registry path also works
    strategy = create_strategy("regime_relative_breakout_30m", {})
    assert strategy.name == "regime_relative_breakout_30m"


# ---------------------------------------------------------------------------
# Tests 2-8 — entry logic
# ---------------------------------------------------------------------------


def test_entry_buy_when_all_conditions_true() -> None:
    df = _make_enriched_df()
    strategy = RegimeRelativeBreakout30mStrategy()
    assert strategy.generate_signal(_snap(df)) == Signal.BUY


def test_entry_hold_when_btc_regime_false() -> None:
    df = _make_enriched_df(btc_daily_regime_on=False)
    strategy = RegimeRelativeBreakout30mStrategy()
    assert strategy.generate_signal(_snap(df)) == Signal.HOLD


def test_entry_hold_when_24h_rs_not_positive() -> None:
    df = _make_enriched_df(target_rs_24h_vs_btc=-0.001)
    strategy = RegimeRelativeBreakout30mStrategy()
    assert strategy.generate_signal(_snap(df)) == Signal.HOLD

    df = _make_enriched_df(target_rs_24h_vs_btc=0.0)
    # strict >, so zero must still HOLD
    assert strategy.generate_signal(_snap(df)) == Signal.HOLD


def test_entry_hold_when_7d_rs_not_positive() -> None:
    df = _make_enriched_df(target_rs_7d_vs_btc=-0.01)
    strategy = RegimeRelativeBreakout30mStrategy()
    assert strategy.generate_signal(_snap(df)) == Signal.HOLD


def test_entry_hold_when_hourly_trend_broken() -> None:
    strategy = RegimeRelativeBreakout30mStrategy()
    # hourly_close <= hourly_ema20
    df1 = _make_enriched_df()
    df1.iloc[-1, df1.columns.get_loc("hourly_close")] = float(df1["hourly_ema20"].iloc[-1]) - 0.1
    assert strategy.generate_signal(_snap(df1)) == Signal.HOLD
    # hourly_ema20 <= hourly_ema60
    df2 = _make_enriched_df()
    df2.iloc[-1, df2.columns.get_loc("hourly_ema20")] = float(df2["hourly_ema60"].iloc[-1]) - 0.1
    assert strategy.generate_signal(_snap(df2)) == Signal.HOLD
    # negative slope
    df3 = _make_enriched_df(hourly_ema20_slope_3=-0.1)
    assert strategy.generate_signal(_snap(df3)) == Signal.HOLD


def test_entry_hold_when_breakout_not_exceeded() -> None:
    df = _make_enriched_df()
    # set prior_high_6 above current close → breakout fails
    df.iloc[-1, df.columns.get_loc("prior_high_6")] = float(df["close"].iloc[-1]) + 0.5
    strategy = RegimeRelativeBreakout30mStrategy()
    assert strategy.generate_signal(_snap(df)) == Signal.HOLD
    # CLV below 0.55 also fails
    df2 = _make_enriched_df(close_location_value=0.40)
    assert strategy.generate_signal(_snap(df2)) == Signal.HOLD


def test_entry_hold_when_volume_below_threshold() -> None:
    df = _make_enriched_df()
    # volume = ma * 1.2 exactly — strict > so must HOLD
    last_ma = float(df["volume_ma_20"].iloc[-1])
    df.iloc[-1, df.columns.get_loc("volume")] = last_ma * 1.2
    strategy = RegimeRelativeBreakout30mStrategy()
    assert strategy.generate_signal(_snap(df)) == Signal.HOLD


# ---------------------------------------------------------------------------
# Tests 9-13 — exit logic (priority order, confirmation, regime-off, time)
# ---------------------------------------------------------------------------


def test_initial_stop_fires_before_trailing_and_trend() -> None:
    # Construct a scenario where BOTH initial stop AND trailing would fire
    # — initial stop should be reported because it is checked first.
    df = _make_enriched_df()
    df.iloc[-1, df.columns.get_loc("low")] = 50.0  # deep low triggers everything
    strategy = RegimeRelativeBreakout30mStrategy(
        initial_stop_atr_mult=2.0,
        atr_trailing_mult=3.0,
    )
    decision = strategy.generate_exit(
        _snap(df, has_position=True),
        _position(entry=100.0, highest_high=115.0),
    )
    assert decision is not None
    assert decision.reason.endswith("_initial_stop")
    # exit price should be entry - atr*mult
    assert decision.exit_price == pytest.approx(100.0 - 1.0 * 2.0)


def test_trailing_exit_fires_when_only_trailing_hit() -> None:
    df = _make_enriched_df()
    # entry=100 atr=1 stop=100-2=98, trailing=highest_high-3*1=115-3=112.
    # Set low between 98 and 112 — only trailing triggers.
    df.iloc[-1, df.columns.get_loc("low")] = 110.0
    strategy = RegimeRelativeBreakout30mStrategy()
    decision = strategy.generate_exit(
        _snap(df, has_position=True),
        _position(entry=100.0, highest_high=115.0),
    )
    assert decision is not None
    assert decision.reason.endswith("_trailing_exit")
    assert decision.exit_price == pytest.approx(115.0 - 1.0 * 3.0)


def test_trend_exit_requires_configured_confirmation() -> None:
    strategy_confirm2 = RegimeRelativeBreakout30mStrategy(trend_exit_confirm_bars=2)
    strategy_confirm3 = RegimeRelativeBreakout30mStrategy(trend_exit_confirm_bars=3)

    # Preserve stops: keep low high enough that initial_stop/trailing do not fire.
    df = _make_enriched_df()
    df.iloc[-1, df.columns.get_loc("low")] = 119.0
    df.iloc[-1, df.columns.get_loc("hourly_close_below_ema20_run")] = 2

    pos = _position(entry=100.0, highest_high=115.0)
    decision = strategy_confirm2.generate_exit(_snap(df, has_position=True), pos)
    assert decision is not None
    assert decision.reason.endswith("_trend_exit")
    # confirm=3 should NOT fire because only 2 consecutive hourly bars below
    decision3 = strategy_confirm3.generate_exit(_snap(df, has_position=True), pos)
    assert decision3 is None or not decision3.reason.endswith("_trend_exit")


def test_regime_off_exit_fires_when_btc_regime_false() -> None:
    df = _make_enriched_df(btc_daily_regime_on=False)
    df.iloc[-1, df.columns.get_loc("low")] = 119.0  # no stop fire
    strategy = RegimeRelativeBreakout30mStrategy()
    decision = strategy.generate_exit(
        _snap(df, has_position=True),
        _position(entry=100.0, highest_high=115.0),
    )
    assert decision is not None
    assert decision.reason.endswith("_regime_off_exit")


def test_time_exit_fires_when_max_hold_reached() -> None:
    df = _make_enriched_df()
    df.iloc[-1, df.columns.get_loc("low")] = 119.0  # no stop fire
    strategy = RegimeRelativeBreakout30mStrategy(max_hold_bars_30m=48)
    decision = strategy.generate_exit(
        _snap(df, has_position=True),
        _position(entry=100.0, hold_bars=48, highest_high=115.0),
    )
    assert decision is not None
    assert decision.reason.endswith("_time_exit")


# ---------------------------------------------------------------------------
# Tests 14-15 — enrichment / no-lookahead proofs
# ---------------------------------------------------------------------------


def _ohlcv(n: int, base: float = 100.0, freq: str = "30min") -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq=freq)
    close = base + np.arange(n, dtype=float) * 0.1
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 100.0),
        },
        index=idx,
    )


def test_enrichment_prior_high_and_volume_mean_are_shifted() -> None:
    # Construct a 30m series where row 10 has a HUGE high and a HUGE volume.
    # prior_high_N at row 10 must NOT include row 10 itself.  volume_ma_N at
    # row 10 must NOT include row 10's volume either.
    n = 60
    df = _ohlcv(n)
    df.iloc[10, df.columns.get_loc("high")] = 999.0
    df.iloc[10, df.columns.get_loc("volume")] = 9999.0

    daily = _ohlcv(30, base=100.0, freq="D")
    hourly = _ohlcv(120, base=100.0, freq="h")

    enriched = enrich_regime_relative_breakout_30m(
        df,
        daily_regime_df=daily,
        hourly_setup_df=hourly,
        rs_reference_df=df,
        breakout_lookback_30m=6,
        volume_window_30m=20,
    )

    prior_high_at_row10 = enriched["prior_high_6"].iloc[10]
    assert prior_high_at_row10 < 999.0  # does not include row 10's 999 spike
    assert enriched["prior_high_6"].iloc[11] == 999.0  # spike reachable from next row

    volume_ma_at_row10 = enriched["volume_ma_20"].iloc[10]
    # rows 0..9 were all 100.0; window of 20 back-shifted by 1 is rows 0..19 shifted(1)
    # at row 10, the volume window covers rows [-10..9] → only 10 points (NaN expected).
    # Require that, whenever finite, it does not equal inclusion of 9999.
    if pd.notna(volume_ma_at_row10):
        assert volume_ma_at_row10 < 9999.0 / 20.0 + 50.0  # still far below the spike's contribution ceiling


def test_enrichment_daily_regime_uses_previous_completed_day_only() -> None:
    # Build a daily series where closes straddle SMA so the regime flips at
    # the last day.  30m intraday bars during day d must see regime for d-1, not d.
    days = 10
    daily_idx = pd.date_range("2026-01-01", periods=days, freq="D")
    daily_close = np.array([100.0] * (days - 1) + [80.0])
    daily = pd.DataFrame(
        {
            "open": daily_close,
            "high": daily_close + 1,
            "low": daily_close - 1,
            "close": daily_close,
            "volume": [1.0] * days,
        },
        index=daily_idx,
    )
    # Build 30m bars covering the last two days (48 bars / day × 2 = 96).
    start = daily_idx[-2]
    thirty_idx = pd.date_range(start, periods=96, freq="30min")
    thirty_close = np.linspace(100.0, 80.0, 96)
    thirty = pd.DataFrame(
        {
            "open": thirty_close,
            "high": thirty_close + 0.1,
            "low": thirty_close - 0.1,
            "close": thirty_close,
            "volume": [100.0] * 96,
        },
        index=thirty_idx,
    )
    hourly_idx = pd.date_range(start, periods=48, freq="h")
    hourly = pd.DataFrame(
        {
            "open": np.linspace(100.0, 80.0, 48),
            "high": np.linspace(100.0, 80.0, 48) + 0.1,
            "low": np.linspace(100.0, 80.0, 48) - 0.1,
            "close": np.linspace(100.0, 80.0, 48),
            "volume": [100.0] * 48,
        },
        index=hourly_idx,
    )

    enriched = enrich_regime_relative_breakout_30m(
        thirty,
        daily_regime_df=daily,
        daily_regime_ma_window=3,
        hourly_setup_df=hourly,
        rs_reference_df=thirty,
    )

    # With shift(1) at the daily level, the regime value at a 30m bar on day d
    # must equal the regime computed FROM day d-1's close (not day d's close).
    # The final 30m bar is on the last daily boundary → it should see the
    # regime value from daily bar (last - 1), which still reflects the 100.0
    # plateau (regime True), NOT the fresh 80.0 drop (which would be False
    # under a no-shift implementation).
    final_regime = enriched["btc_daily_regime_on"].iloc[-1]
    assert bool(final_regime) is True


# ---------------------------------------------------------------------------
# Stage 2 (0002 REVISE) — benchmark MDD + risk-adjusted verdict
# ---------------------------------------------------------------------------


def test_benchmark_mdd_negative_on_drawdown_and_zero_on_flat() -> None:
    # Peak then trough: equity goes 1.0 → 2.0 → 1.0 → MDD = -50 %.
    series = pd.Series([100.0, 150.0, 200.0, 150.0, 120.0, 100.0])
    assert stage2.benchmark_mdd(series) == pytest.approx(-0.5)
    # Flat series (no drawdown) → 0.
    flat = pd.Series([100.0] * 5)
    assert stage2.benchmark_mdd(flat) == pytest.approx(0.0)
    # Empty / one-point series → 0.
    assert stage2.benchmark_mdd(pd.Series([], dtype=float)) == 0.0
    assert stage2.benchmark_mdd(pd.Series([100.0])) == 0.0


def _stage2_ticker_result(
    *,
    total_trades: int,
    cumulative_return: float,
    benchmark_return: float,
    expectancy: float,
    mdd: float,
    benchmark_mdd_value: float,
) -> dict:
    strat_r_over_m = (
        cumulative_return / abs(mdd) if mdd < 0 else 0.0
    )
    bench_r_over_m = (
        benchmark_return / abs(benchmark_mdd_value) if benchmark_mdd_value < 0 else 0.0
    )
    return {
        "total_trades": total_trades,
        "cumulative_return": cumulative_return,
        "benchmark_return": benchmark_return,
        "excess_return": cumulative_return - benchmark_return,
        "expectancy": expectancy,
        "mdd": mdd,
        "benchmark_mdd": benchmark_mdd_value,
        "strategy_return_over_abs_mdd": strat_r_over_m,
        "benchmark_return_over_abs_mdd": bench_r_over_m,
        "mdd_improvement_abs": mdd - benchmark_mdd_value,
        "mdd_improvement_ratio": (
            abs(mdd) / abs(benchmark_mdd_value) if benchmark_mdd_value < 0 else 0.0
        ),
    }


def _stage2_summary(avg_hold_bars: float = 12.0, time_exit_share: float = 0.10) -> dict:
    return {"avg_hold_bars": avg_hold_bars, "time_exit_share": time_exit_share}


def test_classify_verdict_pure_pass_on_positive_excess() -> None:
    eth = _stage2_ticker_result(
        total_trades=100,
        cumulative_return=0.30,
        benchmark_return=0.10,
        expectancy=0.003,
        mdd=-0.10,
        benchmark_mdd_value=-0.50,
    )
    xrp = _stage2_ticker_result(
        total_trades=95,
        cumulative_return=0.25,
        benchmark_return=0.05,
        expectancy=0.004,
        mdd=-0.12,
        benchmark_mdd_value=-0.55,
    )
    out = stage2.classify_verdict(eth, xrp, _stage2_summary())
    assert out["label"] == "PASS"
    assert out["pass_type"] == "pure_excess"
    assert out["gates"]["alt_2y_excess_or_risk_adjusted"] is True
    assert out["gates"]["alt_2y_excess_positive_raw"] is True


def test_classify_verdict_pass_risk_adjusted_label() -> None:
    # Strategy underperforms a strong bull benchmark (negative excess) but
    # delivers a much smaller drawdown with positive expectancy, so the
    # risk-adjusted gate opens even though raw excess is negative.
    eth = _stage2_ticker_result(
        total_trades=100,
        cumulative_return=0.30,
        benchmark_return=0.80,
        expectancy=0.002,
        mdd=-0.10,
        benchmark_mdd_value=-0.60,
    )
    xrp = _stage2_ticker_result(
        total_trades=90,
        cumulative_return=0.70,
        benchmark_return=1.60,
        expectancy=0.006,
        mdd=-0.12,
        benchmark_mdd_value=-0.65,
    )
    out = stage2.classify_verdict(eth, xrp, _stage2_summary())
    assert out["label"] == "PASS_RISK_ADJUSTED"
    assert out["pass_type"] == "risk_adjusted"
    assert out["gates"]["alt_2y_excess_positive_raw"] is False
    assert out["gates"]["alt_2y_risk_adjusted_ok"] is True


def test_classify_verdict_revise_when_mdd_guard_fails() -> None:
    # Risk-adjusted metrics pass on quality but trade counts below the
    # 80-trade mdd guard → must not PASS_RISK_ADJUSTED; should REVISE.
    eth = _stage2_ticker_result(
        total_trades=40,
        cumulative_return=0.20,
        benchmark_return=0.80,
        expectancy=0.002,
        mdd=-0.15,
        benchmark_mdd_value=-0.60,
    )
    xrp = _stage2_ticker_result(
        total_trades=40,
        cumulative_return=0.70,
        benchmark_return=1.60,
        expectancy=0.006,
        mdd=-0.15,
        benchmark_mdd_value=-0.65,
    )
    out = stage2.classify_verdict(eth, xrp, _stage2_summary())
    assert out["label"] == "REVISE"
    assert out["pass_type"] is None


def test_classify_verdict_stop_when_both_alts_negative() -> None:
    eth = _stage2_ticker_result(
        total_trades=60,
        cumulative_return=-0.20,
        benchmark_return=+0.05,
        expectancy=-0.003,
        mdd=-0.25,
        benchmark_mdd_value=-0.40,
    )
    xrp = _stage2_ticker_result(
        total_trades=55,
        cumulative_return=-0.30,
        benchmark_return=+0.02,
        expectancy=-0.005,
        mdd=-0.30,
        benchmark_mdd_value=-0.50,
    )
    out = stage2.classify_verdict(eth, xrp, _stage2_summary())
    assert out["label"] == "STOP"


def test_classify_verdict_hold_when_counts_too_low() -> None:
    eth = _stage2_ticker_result(
        total_trades=5,
        cumulative_return=0.01,
        benchmark_return=0.0,
        expectancy=0.002,
        mdd=-0.02,
        benchmark_mdd_value=-0.30,
    )
    xrp = _stage2_ticker_result(
        total_trades=3,
        cumulative_return=0.0,
        benchmark_return=0.0,
        expectancy=0.0,
        mdd=0.0,
        benchmark_mdd_value=-0.10,
    )
    out = stage2.classify_verdict(eth, xrp, _stage2_summary())
    assert out["label"] == "HOLD"


# ---------------------------------------------------------------------------
# Walk-forward (0003) — fold schedule + OOS verdict classifier
# ---------------------------------------------------------------------------


def test_generate_folds_respects_bounds_and_step() -> None:
    data_start = pd.Timestamp("2024-01-01")
    # 730 days of data total.
    data_end = data_start + pd.Timedelta(days=730)
    folds = wf.generate_folds(
        data_start,
        data_end,
        warmup_days=100,
        train_days=180,
        test_days=60,
        step_days=60,
    )
    # train_start begins at data_start + 100 = 2024-04-10; each fold's
    # test_end must stay inside 730d. Expected fold count is 7:
    # train_start candidates (days offset): 100, 160, 220, 280, 340, 400, 460.
    # test_end for last = 460 + 180 + 60 = 700 ≤ 730. Next (520) would be
    # 520 + 240 = 760 > 730 → stop.
    assert len(folds) == 7
    assert folds[0]["train_start"] == data_start + pd.Timedelta(days=100)
    assert folds[0]["test_end"] == data_start + pd.Timedelta(days=100 + 180 + 60)
    # Step is 60 days between consecutive train_starts.
    for prev, nxt in zip(folds[:-1], folds[1:], strict=False):
        assert (nxt["train_start"] - prev["train_start"]).days == 60
    # Test end strictly inside data window.
    for f in folds:
        assert f["test_end"] <= data_end


def test_generate_folds_returns_empty_when_window_too_short() -> None:
    data_start = pd.Timestamp("2024-01-01")
    data_end = data_start + pd.Timedelta(days=200)  # too short for warmup + 240
    folds = wf.generate_folds(
        data_start,
        data_end,
        warmup_days=100,
        train_days=180,
        test_days=60,
        step_days=60,
    )
    assert folds == []


def _wf_ticker_agg(
    *,
    total_trades: int,
    expectancy: float,
    cum_chained: float,
    bench_chained: float,
    worst_mdd: float,
    worst_bench_mdd: float,
) -> dict:
    return {
        "fold_count": 6,
        "total_trades": total_trades,
        "total_wins": 0,
        "win_rate": 0.0,
        "expectancy": expectancy,
        "cumulative_return_chained": cum_chained,
        "benchmark_return_chained": bench_chained,
        "excess_return_chained": cum_chained - bench_chained,
        "worst_fold_mdd": worst_mdd,
        "worst_fold_benchmark_mdd": worst_bench_mdd,
        "return_over_abs_worst_mdd": (
            cum_chained / abs(worst_mdd) if worst_mdd < 0 else 0.0
        ),
        "benchmark_return_over_abs_worst_mdd": (
            bench_chained / abs(worst_bench_mdd) if worst_bench_mdd < 0 else 0.0
        ),
        "positive_expectancy_fold_ratio": 1.0,
        "positive_cum_fold_ratio": 1.0,
        "positive_risk_adjusted_fold_ratio": 1.0,
        "exit_mix_totals": {},
    }


def _wf_alt_from(eth_agg: dict, xrp_agg: dict) -> dict:
    eth_tr = eth_agg["total_trades"]
    xrp_tr = xrp_agg["total_trades"]
    alt_tr = eth_tr + xrp_tr
    expectancy = (
        (eth_agg["expectancy"] * eth_tr + xrp_agg["expectancy"] * xrp_tr) / alt_tr
        if alt_tr
        else 0.0
    )
    cum = (eth_agg["cumulative_return_chained"] + xrp_agg["cumulative_return_chained"]) / 2.0
    bench = (eth_agg["benchmark_return_chained"] + xrp_agg["benchmark_return_chained"]) / 2.0
    worst_mdd = min(eth_agg["worst_fold_mdd"], xrp_agg["worst_fold_mdd"])
    worst_bench = min(
        eth_agg["worst_fold_benchmark_mdd"], xrp_agg["worst_fold_benchmark_mdd"]
    )
    return {
        "total_trades": alt_tr,
        "eth_trades": eth_tr,
        "xrp_trades": xrp_tr,
        "expectancy": expectancy,
        "cumulative_return_avg": cum,
        "benchmark_return_avg": bench,
        "excess_return_avg": cum - bench,
        "worst_fold_mdd": worst_mdd,
        "worst_fold_benchmark_mdd": worst_bench,
        "return_over_abs_worst_mdd": cum / abs(worst_mdd) if worst_mdd < 0 else 0.0,
        "benchmark_return_over_abs_worst_mdd": (
            bench / abs(worst_bench) if worst_bench < 0 else 0.0
        ),
        "exit_mix_totals": {},
    }


def test_classify_wf_verdict_pass_pure() -> None:
    eth = _wf_ticker_agg(
        total_trades=40, expectancy=0.003, cum_chained=0.30, bench_chained=0.10,
        worst_mdd=-0.10, worst_bench_mdd=-0.30,
    )
    xrp = _wf_ticker_agg(
        total_trades=35, expectancy=0.004, cum_chained=0.20, bench_chained=0.05,
        worst_mdd=-0.12, worst_bench_mdd=-0.35,
    )
    alt = _wf_alt_from(eth, xrp)
    out = wf.classify_wf_verdict(eth, xrp, alt, 0.80, 0.10)
    assert out["label"] == "PASS_WF"
    assert out["pass_type"] == "pure"


def test_classify_wf_verdict_pass_risk_adjusted() -> None:
    # strategy beats benchmark on risk-adjusted R/|MDD| despite negative raw excess.
    eth = _wf_ticker_agg(
        total_trades=40, expectancy=0.002, cum_chained=0.20, bench_chained=0.50,
        worst_mdd=-0.10, worst_bench_mdd=-0.50,
    )
    xrp = _wf_ticker_agg(
        total_trades=35, expectancy=0.003, cum_chained=0.15, bench_chained=0.40,
        worst_mdd=-0.10, worst_bench_mdd=-0.45,
    )
    alt = _wf_alt_from(eth, xrp)
    out = wf.classify_wf_verdict(eth, xrp, alt, 0.70, 0.15)
    assert out["label"] == "PASS_WF_RISK_ADJUSTED"
    assert out["pass_type"] == "risk_adjusted"


def test_classify_wf_verdict_revise_on_low_fold_ratio() -> None:
    eth = _wf_ticker_agg(
        total_trades=40, expectancy=0.002, cum_chained=0.20, bench_chained=0.05,
        worst_mdd=-0.10, worst_bench_mdd=-0.30,
    )
    xrp = _wf_ticker_agg(
        total_trades=35, expectancy=0.003, cum_chained=0.15, bench_chained=0.05,
        worst_mdd=-0.10, worst_bench_mdd=-0.30,
    )
    alt = _wf_alt_from(eth, xrp)
    # positive-expectancy fold ratio below 60% — one performance gate fails.
    out = wf.classify_wf_verdict(eth, xrp, alt, 0.45, 0.15)
    assert out["label"] == "REVISE_WF"


def test_classify_wf_verdict_stop_on_both_alts_negative() -> None:
    eth = _wf_ticker_agg(
        total_trades=40, expectancy=-0.003, cum_chained=-0.20, bench_chained=0.10,
        worst_mdd=-0.30, worst_bench_mdd=-0.30,
    )
    xrp = _wf_ticker_agg(
        total_trades=35, expectancy=-0.004, cum_chained=-0.25, bench_chained=0.05,
        worst_mdd=-0.30, worst_bench_mdd=-0.30,
    )
    alt = _wf_alt_from(eth, xrp)
    out = wf.classify_wf_verdict(eth, xrp, alt, 0.20, 0.30)
    assert out["label"] == "STOP_WF"


def test_classify_wf_verdict_hold_when_trade_counts_too_low() -> None:
    eth = _wf_ticker_agg(
        total_trades=10, expectancy=0.002, cum_chained=0.05, bench_chained=0.02,
        worst_mdd=-0.05, worst_bench_mdd=-0.10,
    )
    xrp = _wf_ticker_agg(
        total_trades=5, expectancy=0.003, cum_chained=0.03, bench_chained=0.01,
        worst_mdd=-0.03, worst_bench_mdd=-0.08,
    )
    alt = _wf_alt_from(eth, xrp)
    out = wf.classify_wf_verdict(eth, xrp, alt, 0.60, 0.10)
    assert out["label"] == "HOLD_WF"
