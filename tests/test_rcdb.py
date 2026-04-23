from __future__ import annotations

import pandas as pd
import pytest

from auto_coin.backtest.runner import BacktestResult, backtest
from auto_coin.data.candles import enrich_for_strategy
from auto_coin.strategy import create_strategy
from auto_coin.strategy.base import MarketSnapshot, Signal
from auto_coin.strategy.rcdb import RcdbStrategy


def _rcdb_signal_df(
    *,
    regime_on: bool = True,
    dip_return: float = -0.1,
    rsi: float = 25.0,
    atr: float = 5.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [95.0],
            "close": [100.0],
            "volume": [1.0],
            "regime_on": [regime_on],
            "dip_return_5": [dip_return],
            "rsi14": [rsi],
            "atr14": [atr],
        }
    )


def test_regime_off_blocks_entry():
    df = _rcdb_signal_df(regime_on=False, dip_return=-0.2, rsi=20.0)
    snap = MarketSnapshot(df=df, current_price=100.0, has_position=False)
    assert RcdbStrategy().generate_signal(snap) is Signal.HOLD


def test_dip_and_rsi_trigger_buy():
    df = _rcdb_signal_df(regime_on=True, dip_return=-0.1, rsi=25.0)
    snap = MarketSnapshot(df=df, current_price=100.0, has_position=False)
    assert RcdbStrategy().generate_signal(snap) is Signal.BUY


def test_rsi_threshold_blocks_buy():
    df = _rcdb_signal_df(regime_on=True, dip_return=-0.1, rsi=35.0)
    snap = MarketSnapshot(df=df, current_price=100.0, has_position=False)
    assert RcdbStrategy().generate_signal(snap) is Signal.HOLD


@pytest.mark.parametrize(
    ("rows", "expected_exit_type", "expected_exit_price"),
    [
        (
            [
                {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1,
                 "regime_on": True, "dip_return_5": -0.1, "rsi14": 25.0, "atr14": 8.0},
                {"open": 100, "high": 101, "low": 70, "close": 82, "volume": 1,
                 "regime_on": True, "dip_return_5": -0.12, "rsi14": 22.0, "atr14": 8.0},
            ],
            "rcdb_trailing_exit",
            81.0,
        ),
        (
            [
                {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1,
                 "regime_on": True, "dip_return_5": -0.1, "rsi14": 25.0, "atr14": 5.0},
                {"open": 100, "high": 104, "low": 98, "close": 103, "volume": 1,
                 "regime_on": True, "dip_return_5": -0.02, "rsi14": 40.0, "atr14": 5.0},
                {"open": 103, "high": 105, "low": 101, "close": 104, "volume": 1,
                 "regime_on": True, "dip_return_5": -0.01, "rsi14": 45.0, "atr14": 5.0},
            ],
            "rcdb_time_exit",
            104.0,
        ),
        (
            [
                {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1,
                 "regime_on": True, "dip_return_5": -0.1, "rsi14": 25.0, "atr14": 5.0},
                {"open": 100, "high": 102, "low": 98, "close": 101, "volume": 1,
                 "regime_on": False, "dip_return_5": -0.02, "rsi14": 45.0, "atr14": 5.0},
            ],
            "rcdb_regime_off",
            101.0,
        ),
    ],
)
def test_exit_reasons_are_distinguished(rows, expected_exit_type, expected_exit_price):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    df = pd.DataFrame(rows, index=idx)
    strat = RcdbStrategy(max_hold_days=2)
    result = backtest(df, strat, fee=0.0, slippage=0.0, mark_to_market=False)

    assert result.n_trades == 1
    trade = result.trades[0]
    assert trade.exit_type == expected_exit_type
    assert trade.exit_price == pytest.approx(expected_exit_price)


def test_backtest_runs_through_generic_engine():
    rows = [
        {"open": 100, "high": 102, "low": 98, "close": 100, "volume": 1},
        {"open": 100, "high": 103, "low": 97, "close": 99, "volume": 1},
        {"open": 99, "high": 101, "low": 94, "close": 95, "volume": 1},
        {"open": 95, "high": 98, "low": 93, "close": 97, "volume": 1},
        {"open": 97, "high": 99, "low": 96, "close": 98, "volume": 1},
        {"open": 98, "high": 100, "low": 95, "close": 96, "volume": 1},
        {"open": 96, "high": 101, "low": 95, "close": 100, "volume": 1},
        {"open": 100, "high": 105, "low": 99, "close": 104, "volume": 1},
        {"open": 104, "high": 106, "low": 101, "close": 102, "volume": 1},
        {"open": 102, "high": 104, "low": 100, "close": 101, "volume": 1},
        {"open": 101, "high": 102, "low": 98, "close": 99, "volume": 1},
        {"open": 99, "high": 100, "low": 95, "close": 96, "volume": 1},
        {"open": 96, "high": 97, "low": 92, "close": 93, "volume": 1},
        {"open": 93, "high": 95, "low": 90, "close": 91, "volume": 1},
        {"open": 91, "high": 94, "low": 89, "close": 92, "volume": 1},
        {"open": 92, "high": 96, "low": 91, "close": 95, "volume": 1},
        {"open": 95, "high": 98, "low": 94, "close": 97, "volume": 1},
        {"open": 97, "high": 99, "low": 96, "close": 98, "volume": 1},
        {"open": 98, "high": 100, "low": 97, "close": 99, "volume": 1},
        {"open": 99, "high": 101, "low": 98, "close": 100, "volume": 1},
    ]
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    raw = pd.DataFrame(rows, index=idx)
    params = {
        "regime_ma_window": 5,
        "dip_lookback_days": 5,
        "dip_threshold_pct": -0.08,
        "rsi_window": 14,
        "rsi_threshold": 35.0,
        "max_hold_days": 5,
        "atr_window": 14,
        "atr_trailing_mult": 2.5,
    }
    enriched = enrich_for_strategy(raw, "rcdb", params)
    strategy = create_strategy("rcdb", params)

    result = backtest(enriched, strategy, fee=0.0, slippage=0.0)

    assert isinstance(result, BacktestResult)
    assert result.n_trades >= 0


def test_trailing_exit_uses_highest_high_not_highest_close():
    rows = [
        {"open": 100, "high": 110, "low": 99, "close": 100, "volume": 1,
         "regime_on": True, "dip_return_5": -0.1, "rsi14": 25.0, "atr14": 8.0},
        {"open": 100, "high": 102, "low": 93, "close": 96, "volume": 1,
         "regime_on": True, "dip_return_5": -0.02, "rsi14": 40.0, "atr14": 8.0},
    ]
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    df = pd.DataFrame(rows, index=idx)

    result = backtest(
        df,
        RcdbStrategy(max_hold_days=5, atr_trailing_mult=2.0),
        fee=0.0,
        slippage=0.0,
        mark_to_market=False,
    )

    assert result.n_trades == 1
    trade = result.trades[0]
    assert trade.exit_type == "rcdb_trailing_exit"
    assert trade.exit_price == pytest.approx(94.0)  # 110 - 8*2.0
