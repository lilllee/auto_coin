from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.backtest.runner import (
    UPBIT_DEFAULT_FEE,
    BacktestResult,
    backtest,
    cli,
)
from auto_coin.data.candles import enrich_daily
from auto_coin.strategy.volatility_breakout import VolatilityBreakout


def _make_df(rows: list[dict]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=idx)


def test_empty_df_returns_empty_result():
    r = backtest(pd.DataFrame(), VolatilityBreakout())
    assert r.n_trades == 0
    assert r.cumulative_return == 0.0


def test_backtest_requires_enriched_df():
    df = _make_df([{"open": 100, "high": 110, "low": 90, "close": 105, "volume": 1}])
    with pytest.raises(ValueError, match="enrich_daily"):
        backtest(df, VolatilityBreakout())


def test_single_winning_trade_no_fee():
    """3일 데이터: day0 시드, day1 돌파+매수, day2 시가 매도."""
    base = _make_df([
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},  # 전일 range = 20
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},  # target=110, high>=target → 매수
        {"open": 130, "high": 130, "low": 130, "close": 130, "volume": 1},  # 매도가 130
    ])
    enriched = enrich_daily(base, ma_window=1, k=0.5)
    strat = VolatilityBreakout(k=0.5, ma_window=1, require_ma_filter=False)
    r = backtest(enriched, strat, fee=0.0, slippage=0.0)
    assert r.n_trades == 1
    assert r.n_wins == 1
    t = r.trades[0]
    assert t.entry_price == pytest.approx(110.0)
    assert t.exit_price == pytest.approx(130.0)
    assert t.ret == pytest.approx(130.0 / 110.0 - 1.0)
    assert r.cumulative_return == pytest.approx(t.ret)
    assert r.win_rate == 1.0
    assert r.mdd == pytest.approx(0.0)


def test_no_breakout_no_trade():
    base = _make_df([
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 100, "high": 105, "low": 95,  "close": 102, "volume": 1},  # high<target → no trade
        {"open": 102, "high": 105, "low": 100, "close": 103, "volume": 1},
    ])
    enriched = enrich_daily(base, ma_window=1, k=0.5)
    strat = VolatilityBreakout(k=0.5, ma_window=1, require_ma_filter=False)
    r = backtest(enriched, strat, fee=0.0)
    assert r.n_trades == 0


def test_fee_reduces_return():
    base = _make_df([
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},
        {"open": 130, "high": 130, "low": 130, "close": 130, "volume": 1},
    ])
    enriched = enrich_daily(base, ma_window=1, k=0.5)
    strat = VolatilityBreakout(k=0.5, ma_window=1, require_ma_filter=False)
    r0 = backtest(enriched, strat, fee=0.0)
    r1 = backtest(enriched, strat, fee=UPBIT_DEFAULT_FEE)
    assert r1.trades[0].ret < r0.trades[0].ret


def test_slippage_reduces_return():
    base = _make_df([
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},
        {"open": 130, "high": 130, "low": 130, "close": 130, "volume": 1},
    ])
    enriched = enrich_daily(base, ma_window=1, k=0.5)
    strat = VolatilityBreakout(k=0.5, ma_window=1, require_ma_filter=False)
    r0 = backtest(enriched, strat, fee=0.0, slippage=0.0)
    r1 = backtest(enriched, strat, fee=0.0, slippage=0.001)
    assert r1.trades[0].ret < r0.trades[0].ret


def test_ma_filter_blocks_trade():
    """target 통과해도 target <= ma 면 진입 차단."""
    base = _make_df([
        {"open": 100, "high": 110, "low": 90,  "close": 1000, "volume": 1},  # close 매우 큼 → ma1 큼
        {"open": 100, "high": 200, "low": 100, "close": 150,  "volume": 1},  # target=110 < ma1=1000
        {"open": 130, "high": 130, "low": 130, "close": 130,  "volume": 1},
    ])
    enriched = enrich_daily(base, ma_window=1, k=0.5)
    strat_with_filter = VolatilityBreakout(k=0.5, ma_window=1, require_ma_filter=True)
    strat_no_filter = VolatilityBreakout(k=0.5, ma_window=1, require_ma_filter=False)
    assert backtest(enriched, strat_with_filter, fee=0.0).n_trades == 0
    assert backtest(enriched, strat_no_filter, fee=0.0).n_trades == 1


def test_mdd_calculation():
    """승, 패, 패 패턴으로 MDD 검증."""
    n_periods = 7
    idx = pd.date_range("2026-01-01", periods=n_periods, freq="D")
    # 직접 trade를 만들어주기 위해 캔들을 인위적으로 구성
    # 매번 target=110, exit가 day별로 다르게: +20%, -10%, -10%
    base = _make_df([
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},  # seed (range=20)
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},  # entry day 1, target=110
        {"open": 132, "high": 132, "low": 90,  "close": 100, "volume": 1},  # exit day 1 = 132 (+20%)
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},  # entry day 2 (range from prev=42)
        {"open": 99,  "high": 99,  "low": 90,  "close": 95,  "volume": 1},  # exit day 2 = 99
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},  # entry day 3
        {"open": 95,  "high": 95,  "low": 90,  "close": 95,  "volume": 1},  # exit day 3
    ])
    base.index = idx[:n_periods]
    enriched = enrich_daily(base, ma_window=1, k=0.5)
    strat = VolatilityBreakout(k=0.5, ma_window=1, require_ma_filter=False)
    r = backtest(enriched, strat, fee=0.0)
    assert r.n_trades >= 2
    # MDD는 음수, 0보다 작아야 한다 (loss trade가 있으므로)
    assert r.mdd < 0.0
    # equity 곡선이 monotonic 감소가 아니므로 MDD는 정점 대비 낙폭
    rets = np.array([t.ret for t in r.trades])
    equity = np.cumprod(1.0 + rets)
    expected_mdd = ((equity - np.maximum.accumulate(equity)) / np.maximum.accumulate(equity)).min()
    assert r.mdd == pytest.approx(expected_mdd)


def test_win_rate():
    base = _make_df([
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},  # entry
        {"open": 130, "high": 130, "low": 130, "close": 130, "volume": 1},  # win
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},  # entry
        {"open": 90,  "high": 90,  "low": 90,  "close": 90,  "volume": 1},  # loss
    ])
    enriched = enrich_daily(base, ma_window=1, k=0.5)
    strat = VolatilityBreakout(k=0.5, ma_window=1, require_ma_filter=False)
    r = backtest(enriched, strat, fee=0.0)
    assert r.n_trades == 2
    assert r.win_rate == 0.5
    assert r.n_wins == 1


def test_summary_format():
    r = BacktestResult(cumulative_return=0.123, mdd=-0.05, win_rate=0.6,
                      n_trades=10, n_wins=6)
    s = r.summary()
    assert "trades=" in s
    assert "+12.30%" in s
    assert "-5.00%" in s
    assert "60.0%" in s


def test_cli_single_run(mocker, capsys):
    base = _make_df([
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},
        {"open": 130, "high": 130, "low": 130, "close": 130, "volume": 1},
    ])
    mocker.patch("auto_coin.backtest.runner.pyupbit.get_ohlcv", return_value=base)
    rc = cli(["--ticker", "KRW-BTC", "--days", "3", "--k", "0.5", "--ma-window", "1",
              "--no-ma-filter", "--fee", "0"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "trades=" in out


def test_cli_sweep(mocker, capsys):
    base = _make_df([
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},
        {"open": 130, "high": 130, "low": 130, "close": 130, "volume": 1},
    ])
    mocker.patch("auto_coin.backtest.runner.pyupbit.get_ohlcv", return_value=base)
    rc = cli(["--ticker", "KRW-BTC", "--days", "3", "--ma-window", "1",
              "--no-ma-filter", "--fee", "0", "--sweep", "0.3", "0.5", "0.1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "K sweep" in out
    assert "0.300" in out
    assert "0.500" in out
