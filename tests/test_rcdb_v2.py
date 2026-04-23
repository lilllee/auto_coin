from __future__ import annotations

import pandas as pd
import pytest

from auto_coin.backtest.runner import BacktestResult, backtest
from auto_coin.data.candles import enrich_for_strategy
from auto_coin.strategy import create_strategy
from auto_coin.strategy.base import MarketSnapshot, Signal
from auto_coin.strategy.rcdb_v2 import RcdbV2Strategy


def _signal_df(
    *,
    regime_on: bool = True,
    dip_score: float = -2.0,
    rsi: float = 30.0,
    reversal_ema: float = 95.0,
    closes: tuple[float, float] = (90.0, 100.0),
    atr: float = 3.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [89.0, 91.0],
            "high": [91.0, 101.0],
            "low": [88.0, 90.0],
            "close": [closes[0], closes[1]],
            "volume": [1.0, 1.0],
            "regime_on": [regime_on, regime_on],
            "dip_score_5_20": [float("nan"), dip_score],
            "rsi14": [float("nan"), rsi],
            "reversal_ema5": [float("nan"), reversal_ema],
            "atr14": [float("nan"), atr],
        }
    )


def test_regime_off_blocks_entry():
    df = _signal_df(regime_on=False)
    snap = MarketSnapshot(df=df, current_price=100.0, has_position=False)
    assert RcdbV2Strategy().generate_signal(snap) is Signal.HOLD


def test_normalized_dip_rsi_and_reversal_trigger_buy():
    df = _signal_df(regime_on=True, dip_score=-2.0, rsi=30.0, reversal_ema=95.0)
    snap = MarketSnapshot(df=df, current_price=100.0, has_position=False)
    assert RcdbV2Strategy().generate_signal(snap) is Signal.BUY


def test_no_buy_without_reversal_confirmation():
    df = _signal_df(
        regime_on=True,
        dip_score=-2.0,
        rsi=30.0,
        reversal_ema=101.0,
        closes=(100.0, 99.0),
    )
    snap = MarketSnapshot(df=df, current_price=99.0, has_position=False)
    assert RcdbV2Strategy().generate_signal(snap) is Signal.HOLD


@pytest.mark.parametrize(
    ("rows", "strategy", "expected_exit_type", "expected_exit_price"),
    [
        (
            [
                {
                    "open": 89, "high": 91, "low": 88, "close": 90, "volume": 1,
                    "regime_on": True, "dip_score_5_20": float("nan"), "rsi14": float("nan"),
                    "reversal_ema5": float("nan"), "atr14": float("nan"),
                },
                {
                    "open": 91, "high": 101, "low": 90, "close": 100, "volume": 1,
                    "regime_on": True, "dip_score_5_20": -2.0, "rsi14": 30.0,
                    "reversal_ema5": 95.0, "atr14": 3.0,
                },
                {
                    "open": 100, "high": 106, "low": 99, "close": 104, "volume": 1,
                    "regime_on": True, "dip_score_5_20": 0.2, "rsi14": 48.0,
                    "reversal_ema5": 98.0, "atr14": 3.0,
                },
            ],
            RcdbV2Strategy(),
            "rcdb_v2_reversion_exit",
            104.0,
        ),
        (
            [
                {
                    "open": 89, "high": 91, "low": 88, "close": 90, "volume": 1,
                    "regime_on": True, "dip_score_5_20": float("nan"), "rsi14": float("nan"),
                    "reversal_ema5": float("nan"), "atr14": float("nan"),
                },
                {
                    "open": 91, "high": 110, "low": 90, "close": 100, "volume": 1,
                    "regime_on": True, "dip_score_5_20": -2.0, "rsi14": 30.0,
                    "reversal_ema5": 95.0, "atr14": 3.0,
                },
                {
                    "open": 100, "high": 103, "low": 102, "close": 103, "volume": 1,
                    "regime_on": True, "dip_score_5_20": -1.0, "rsi14": 40.0,
                    "reversal_ema5": 97.0, "atr14": 3.0,
                },
            ],
            RcdbV2Strategy(atr_trailing_mult=2.0),
            "rcdb_v2_trailing_exit",
            104.0,
        ),
        (
            [
                {
                    "open": 89, "high": 91, "low": 88, "close": 90, "volume": 1,
                    "regime_on": True, "dip_score_5_20": float("nan"), "rsi14": float("nan"),
                    "reversal_ema5": float("nan"), "atr14": float("nan"),
                },
                {
                    "open": 91, "high": 101, "low": 90, "close": 100, "volume": 1,
                    "regime_on": True, "dip_score_5_20": -2.0, "rsi14": 30.0,
                    "reversal_ema5": 95.0, "atr14": 3.0,
                },
                {
                    "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1,
                    "regime_on": False, "dip_score_5_20": -1.0, "rsi14": 38.0,
                    "reversal_ema5": 98.0, "atr14": 3.0,
                },
            ],
            RcdbV2Strategy(),
            "rcdb_v2_regime_off",
            101.0,
        ),
        (
            [
                {
                    "open": 89, "high": 91, "low": 88, "close": 90, "volume": 1,
                    "regime_on": True, "dip_score_5_20": float("nan"), "rsi14": float("nan"),
                    "reversal_ema5": float("nan"), "atr14": float("nan"),
                },
                {
                    "open": 91, "high": 101, "low": 90, "close": 100, "volume": 1,
                    "regime_on": True, "dip_score_5_20": -2.0, "rsi14": 30.0,
                    "reversal_ema5": 95.0, "atr14": 3.0,
                },
                {
                    "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1,
                    "regime_on": True, "dip_score_5_20": -1.0, "rsi14": 38.0,
                    "reversal_ema5": 98.0, "atr14": 3.0,
                },
            ],
            RcdbV2Strategy(max_hold_days=1),
            "rcdb_v2_time_exit",
            101.0,
        ),
    ],
)
def test_exit_reasons_are_distinguished(rows, strategy, expected_exit_type, expected_exit_price):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    df = pd.DataFrame(rows, index=idx)

    result = backtest(df, strategy, fee=0.0, slippage=0.0, mark_to_market=False)

    assert result.n_trades == 1
    trade = result.trades[0]
    assert trade.exit_type == expected_exit_type
    assert trade.exit_price == pytest.approx(expected_exit_price)


def test_backtest_runs_through_generic_engine():
    rows = []
    price = 100.0
    for i in range(40):
        price = price + (1 if i % 4 else -3)
        rows.append(
            {
                "open": price - 1,
                "high": price + 2,
                "low": price - 2,
                "close": price,
                "volume": 1.0,
            }
        )
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    raw = pd.DataFrame(rows, index=idx)
    params = {
        "regime_ma_window": 10,
        "dip_lookback_days": 5,
        "vol_window": 10,
        "dip_z_threshold": -1.5,
        "rsi_window": 14,
        "rsi_threshold": 40.0,
        "reversal_ema_window": 5,
        "max_hold_days": 5,
        "atr_window": 14,
        "atr_trailing_mult": 2.0,
    }
    enriched = enrich_for_strategy(raw, "rcdb_v2", params)
    strategy = create_strategy("rcdb_v2", params)

    result = backtest(enriched, strategy, fee=0.0, slippage=0.0)

    assert isinstance(result, BacktestResult)
    assert result.n_trades >= 0
