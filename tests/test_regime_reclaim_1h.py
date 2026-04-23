from __future__ import annotations

import pandas as pd
import pytest

from auto_coin.backtest.runner import BacktestResult, backtest
from auto_coin.data.candles import enrich_for_strategy
from auto_coin.strategy import create_strategy
from auto_coin.strategy.base import MarketSnapshot, Signal
from auto_coin.strategy.regime_reclaim_1h import RegimeReclaim1HStrategy


def _signal_df(
    *,
    regime_on: bool = True,
    pullback: float = -0.03,
    rsi: float = 30.0,
    reclaim_ema: float = 98.0,
    closes: tuple[float, float] = (95.0, 100.0),
    reversion_sma: float = 103.0,
    atr: float = 2.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [94.0, 96.0],
            "high": [96.0, 101.0],
            "low": [93.0, 95.0],
            "close": [closes[0], closes[1]],
            "volume": [1.0, 1.0],
            "daily_regime_on": [regime_on, regime_on],
            "pullback_return_8": [float("nan"), pullback],
            "rsi14": [float("nan"), rsi],
            "reclaim_ema6": [float("nan"), reclaim_ema],
            "reversion_sma8": [float("nan"), reversion_sma],
            "atr14": [float("nan"), atr],
        }
    )


def test_daily_regime_off_blocks_entry():
    df = _signal_df(regime_on=False)
    snap = MarketSnapshot(df=df, current_price=100.0, has_position=False, interval="minute60")
    assert RegimeReclaim1HStrategy().generate_signal(snap) is Signal.HOLD


def test_reclaim_condition_triggers_buy():
    df = _signal_df(regime_on=True, pullback=-0.04, rsi=28.0, reclaim_ema=98.0)
    snap = MarketSnapshot(df=df, current_price=100.0, has_position=False, interval="minute60")
    assert RegimeReclaim1HStrategy().generate_signal(snap) is Signal.BUY


def test_no_buy_without_reclaim_confirmation():
    df = _signal_df(regime_on=True, pullback=-0.04, rsi=28.0, reclaim_ema=101.0, closes=(100.0, 99.0))
    snap = MarketSnapshot(df=df, current_price=99.0, has_position=False, interval="minute60")
    assert RegimeReclaim1HStrategy().generate_signal(snap) is Signal.HOLD


@pytest.mark.parametrize(
    ("rows", "strategy", "expected_exit_type", "expected_exit_price"),
    [
        (
            [
                {
                    "open": 94, "high": 96, "low": 93, "close": 95, "volume": 1,
                    "daily_regime_on": True, "pullback_return_8": float("nan"), "rsi14": float("nan"),
                    "reclaim_ema6": float("nan"), "reversion_sma8": float("nan"), "atr14": float("nan"),
                },
                {
                    "open": 96, "high": 101, "low": 95, "close": 100, "volume": 1,
                    "daily_regime_on": True, "pullback_return_8": -0.04, "rsi14": 28.0,
                    "reclaim_ema6": 98.0, "reversion_sma8": 103.0, "atr14": 2.0,
                },
                {
                    "open": 100, "high": 105, "low": 99, "close": 104, "volume": 1,
                    "daily_regime_on": True, "pullback_return_8": -0.01, "rsi14": 45.0,
                    "reclaim_ema6": 99.0, "reversion_sma8": 103.0, "atr14": 2.0,
                },
            ],
            RegimeReclaim1HStrategy(),
            "regime_reclaim_1h_reversion_exit",
            104.0,
        ),
        (
            [
                {
                    "open": 94, "high": 96, "low": 93, "close": 95, "volume": 1,
                    "daily_regime_on": True, "pullback_return_8": float("nan"), "rsi14": float("nan"),
                    "reclaim_ema6": float("nan"), "reversion_sma8": float("nan"), "atr14": float("nan"),
                },
                {
                    "open": 96, "high": 110, "low": 95, "close": 100, "volume": 1,
                    "daily_regime_on": True, "pullback_return_8": -0.04, "rsi14": 28.0,
                    "reclaim_ema6": 98.0, "reversion_sma8": 103.0, "atr14": 2.0,
                },
                {
                    "open": 100, "high": 102, "low": 105, "close": 106, "volume": 1,
                    "daily_regime_on": True, "pullback_return_8": -0.01, "rsi14": 45.0,
                    "reclaim_ema6": 99.0, "reversion_sma8": 120.0, "atr14": 2.0,
                },
            ],
            RegimeReclaim1HStrategy(atr_trailing_mult=2.0),
            "regime_reclaim_1h_trailing_exit",
            106.0,
        ),
        (
            [
                {
                    "open": 94, "high": 96, "low": 93, "close": 95, "volume": 1,
                    "daily_regime_on": True, "pullback_return_8": float("nan"), "rsi14": float("nan"),
                    "reclaim_ema6": float("nan"), "reversion_sma8": float("nan"), "atr14": float("nan"),
                },
                {
                    "open": 96, "high": 101, "low": 95, "close": 100, "volume": 1,
                    "daily_regime_on": True, "pullback_return_8": -0.04, "rsi14": 28.0,
                    "reclaim_ema6": 98.0, "reversion_sma8": 130.0, "atr14": 2.0,
                },
                {
                    "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1,
                    "daily_regime_on": False, "pullback_return_8": -0.02, "rsi14": 40.0,
                    "reclaim_ema6": 99.0, "reversion_sma8": 130.0, "atr14": 2.0,
                },
            ],
            RegimeReclaim1HStrategy(),
            "regime_reclaim_1h_regime_off_exit",
            100.0,
        ),
        (
            [
                {
                    "open": 94, "high": 96, "low": 93, "close": 95, "volume": 1,
                    "daily_regime_on": True, "pullback_return_8": float("nan"), "rsi14": float("nan"),
                    "reclaim_ema6": float("nan"), "reversion_sma8": float("nan"), "atr14": float("nan"),
                },
                {
                    "open": 96, "high": 101, "low": 95, "close": 100, "volume": 1,
                    "daily_regime_on": True, "pullback_return_8": -0.04, "rsi14": 28.0,
                    "reclaim_ema6": 98.0, "reversion_sma8": 130.0, "atr14": 2.0,
                },
                {
                    "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1,
                    "daily_regime_on": True, "pullback_return_8": -0.02, "rsi14": 40.0,
                    "reclaim_ema6": 99.0, "reversion_sma8": 130.0, "atr14": 2.0,
                },
            ],
            RegimeReclaim1HStrategy(max_hold_bars=1),
            "regime_reclaim_1h_time_exit",
            100.0,
        ),
    ],
)
def test_exit_reasons_are_distinguished(rows, strategy, expected_exit_type, expected_exit_price):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="h")
    df = pd.DataFrame(rows, index=idx)

    result = backtest(df, strategy, fee=0.0, slippage=0.0, mark_to_market=False, interval="minute60")

    assert result.n_trades == 1
    trade = result.trades[0]
    assert trade.exit_type == expected_exit_type
    assert trade.exit_price == pytest.approx(expected_exit_price)


def test_enrich_for_strategy_projects_daily_regime_to_hourly_index():
    hourly_idx = pd.date_range("2026-01-01", periods=48, freq="h")
    hourly = pd.DataFrame(
        {
            "open": [100.0] * 48,
            "high": [101.0] * 48,
            "low": [99.0] * 48,
            "close": [100.0 + (i % 3) for i in range(48)],
            "volume": [1.0] * 48,
        },
        index=hourly_idx,
    )
    daily_idx = pd.date_range("2025-09-01", periods=123, freq="D")
    daily_close = [100.0] * 122 + [200.0]
    regime_df = pd.DataFrame(
        {
            "open": daily_close,
            "high": [c + 1 for c in daily_close],
            "low": [c - 1 for c in daily_close],
            "close": daily_close,
            "volume": [1.0] * len(daily_close),
        },
        index=daily_idx,
    )

    out = enrich_for_strategy(
        hourly,
        "regime_reclaim_1h",
        {
            "daily_regime_ma_window": 120,
            "dip_lookback_bars": 8,
            "pullback_threshold_pct": -0.025,
            "rsi_window": 14,
            "reclaim_ema_window": 6,
            "atr_window": 14,
        },
        regime_df=regime_df,
        interval="minute60",
    )

    assert "daily_regime_on" in out.columns
    assert "reclaim_ema6" in out.columns
    assert out.loc["2026-01-02 12:00:00", "daily_regime_on"] == True  # noqa: E712


def test_backtest_runs_through_generic_engine_on_minute60():
    rows = []
    price = 100.0
    for i in range(72):
        price = price + (1.2 if i % 9 else -3.0)
        rows.append(
            {
                "open": price - 1,
                "high": price + 2,
                "low": price - 2,
                "close": price,
                "volume": 1.0,
            }
        )
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="h")
    hourly = pd.DataFrame(rows, index=idx)

    daily_idx = pd.date_range("2025-09-01", periods=140, freq="D")
    daily_close = [100 + (i * 0.2) for i in range(len(daily_idx))]
    regime_df = pd.DataFrame(
        {
            "open": daily_close,
            "high": [c + 1 for c in daily_close],
            "low": [c - 1 for c in daily_close],
            "close": daily_close,
            "volume": [1.0] * len(daily_close),
        },
        index=daily_idx,
    )

    params = {
        "daily_regime_ma_window": 120,
        "dip_lookback_bars": 8,
        "pullback_threshold_pct": -0.02,
        "rsi_window": 14,
        "rsi_threshold": 40.0,
        "reclaim_ema_window": 6,
        "max_hold_bars": 36,
        "atr_window": 14,
        "atr_trailing_mult": 2.0,
    }
    enriched = enrich_for_strategy(
        hourly,
        "regime_reclaim_1h",
        params,
        regime_df=regime_df,
        interval="minute60",
    )
    strategy = create_strategy("regime_reclaim_1h", params)

    result = backtest(enriched, strategy, fee=0.0, slippage=0.0, interval="minute60")

    assert isinstance(result, BacktestResult)
    assert result.n_trades >= 0
