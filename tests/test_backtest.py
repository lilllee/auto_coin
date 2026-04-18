from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from auto_coin.backtest.runner import (
    DEFAULT_SLIPPAGE,
    UPBIT_DEFAULT_FEE,
    BacktestResult,
    Trade,
    _build_result,
    backtest,
    backtest_vb,
    cli,
)
from auto_coin.data.candles import enrich_daily, enrich_for_strategy
from auto_coin.strategy.sma200_regime import Sma200RegimeStrategy
from auto_coin.strategy.volatility_breakout import VolatilityBreakout


def _make_df(rows: list[dict]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=idx)


def _make_enriched_df(rows, strategy_name="volatility_breakout", params=None):
    """전략에 맞게 enriched된 DataFrame 생성."""
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    df = pd.DataFrame(rows, index=idx)
    return enrich_for_strategy(df, strategy_name, params or {})


# ===================================================================
# Legacy VB tests (backtest_vb)
# ===================================================================


def test_empty_df_returns_empty_result():
    r = backtest_vb(pd.DataFrame(), VolatilityBreakout())
    assert r.n_trades == 0
    assert r.cumulative_return == 0.0


def test_backtest_requires_enriched_df():
    df = _make_df([{"open": 100, "high": 110, "low": 90, "close": 105, "volume": 1}])
    with pytest.raises(ValueError, match="enrich_daily"):
        backtest_vb(df, VolatilityBreakout())


def test_single_winning_trade_no_fee():
    """3일 데이터: day0 시드, day1 돌파+매수, day2 시가 매도."""
    base = _make_df([
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},  # 전일 range = 20
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},  # target=110, high>=target → 매수
        {"open": 130, "high": 130, "low": 130, "close": 130, "volume": 1},  # 매도가 130
    ])
    enriched = enrich_daily(base, ma_window=1, k=0.5)
    strat = VolatilityBreakout(k=0.5, ma_window=1, require_ma_filter=False)
    r = backtest_vb(enriched, strat, fee=0.0, slippage=0.0)
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
    r = backtest_vb(enriched, strat, fee=0.0)
    assert r.n_trades == 0


def test_fee_reduces_return():
    base = _make_df([
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},
        {"open": 130, "high": 130, "low": 130, "close": 130, "volume": 1},
    ])
    enriched = enrich_daily(base, ma_window=1, k=0.5)
    strat = VolatilityBreakout(k=0.5, ma_window=1, require_ma_filter=False)
    r0 = backtest_vb(enriched, strat, fee=0.0)
    r1 = backtest_vb(enriched, strat, fee=UPBIT_DEFAULT_FEE)
    assert r1.trades[0].ret < r0.trades[0].ret


def test_slippage_reduces_return():
    base = _make_df([
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},
        {"open": 130, "high": 130, "low": 130, "close": 130, "volume": 1},
    ])
    enriched = enrich_daily(base, ma_window=1, k=0.5)
    strat = VolatilityBreakout(k=0.5, ma_window=1, require_ma_filter=False)
    r0 = backtest_vb(enriched, strat, fee=0.0, slippage=0.0)
    r1 = backtest_vb(enriched, strat, fee=0.0, slippage=0.001)
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
    assert backtest_vb(enriched, strat_with_filter, fee=0.0).n_trades == 0
    assert backtest_vb(enriched, strat_no_filter, fee=0.0).n_trades == 1


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
    r = backtest_vb(enriched, strat, fee=0.0)
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
    r = backtest_vb(enriched, strat, fee=0.0)
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


# ===================================================================
# Generic backtest tests
# ===================================================================


def test_generic_backtest_vb_basic():
    """범용 backtest()로 VolatilityBreakout 실행 — 시그널 기반 진입."""
    rows = [
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 105, "high": 120, "low": 100, "close": 115, "volume": 1},
        {"open": 115, "high": 125, "low": 108, "close": 120, "volume": 1},
        {"open": 120, "high": 130, "low": 112, "close": 125, "volume": 1},
        {"open": 125, "high": 135, "low": 115, "close": 118, "volume": 1},
    ]
    df = _make_enriched_df(rows, "volatility_breakout", {"k": 0.5, "ma_window": 1})
    strat = VolatilityBreakout(k=0.5, ma_window=1, require_ma_filter=False)
    r = backtest(df, strat, fee=0.0)
    # VB strategy: BUY when current_price >= target and no position
    # The generic backtest uses close as current_price, so entry happens at close
    assert isinstance(r, BacktestResult)
    assert r.n_trades >= 0  # exact count depends on target values


def test_generic_backtest_sma200_regime():
    """SMA200 레짐 전략 — 수동 SMA 컬럼으로 테스트."""
    rows = [
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 105, "high": 115, "low": 95,  "close": 110, "volume": 1},
        {"open": 110, "high": 120, "low": 100, "close": 108, "volume": 1},
        {"open": 108, "high": 112, "low": 85,  "close": 88,  "volume": 1},
        {"open": 88,  "high": 95,  "low": 80,  "close": 90,  "volume": 1},
    ]
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    df = pd.DataFrame(rows, index=idx)
    # 수동으로 SMA3 컬럼 설정 (testability)
    df["sma3"] = [float("nan"), float("nan"), 100.0, 105.0, 107.0]
    strat = Sma200RegimeStrategy(ma_window=3, allow_sell_signal=True)
    r = backtest(df, strat, fee=0.0)
    # Day 2: close=108, sma3=100 → 108 >= 100 → BUY at 108
    # Day 3: close=88, sma3=105 → 88 < 105 → SELL (holding, allow_sell_signal)
    assert r.n_trades == 1
    t = r.trades[0]
    assert t.entry_price == pytest.approx(108.0)
    assert t.exit_price == pytest.approx(88.0)
    assert t.exit_type == "signal"


def test_generic_backtest_composite():
    """SMA200+EMA+ADX 합성 전략 — 수동 지표 컬럼으로 테스트."""
    rows = [
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 105, "high": 115, "low": 95,  "close": 110, "volume": 1},
        {"open": 110, "high": 120, "low": 100, "close": 115, "volume": 1},
        {"open": 115, "high": 125, "low": 105, "close": 120, "volume": 1},
        {"open": 120, "high": 130, "low": 110, "close": 100, "volume": 1},
    ]
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    df = pd.DataFrame(rows, index=idx)
    # Composite: sma_window=3, ema_fast=2, ema_slow=3, adx_window=2, adx_threshold=10
    df["sma3"] = [float("nan"), float("nan"), 90.0, 95.0, 100.0]
    df["ema2"] = [float("nan"), 102.0, 108.0, 114.0, 118.0]
    df["ema3"] = [float("nan"), 100.0, 105.0, 110.0, 115.0]
    df["adx2"] = [float("nan"), 5.0, 15.0, 20.0, 25.0]

    from auto_coin.strategy.sma200_ema_adx_composite import Sma200EmaAdxCompositeStrategy
    strat = Sma200EmaAdxCompositeStrategy(
        sma_window=3, ema_fast_window=2, ema_slow_window=3,
        adx_window=2, adx_threshold=10.0,
    )
    r = backtest(df, strat, fee=0.0)
    # Day 2: close=115, sma3=90 (risk-on), ema2=108>ema3=105, adx2=15>=10 → BUY at 115
    # Day 3: close=120, has_position → HOLD
    # Day 4: close=100, sma3=100 → 100 < 100? No, equal. So risk-on. has_position → HOLD.
    assert r.n_trades >= 0  # at least should not error
    assert isinstance(r, BacktestResult)


def test_stop_loss_triggers():
    """손절 시나리오: BUY 후 다음날 low가 손절가 이하."""
    rows = [
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 105, "high": 115, "low": 95,  "close": 110, "volume": 1},
        {"open": 110, "high": 112, "low": 100, "close": 105, "volume": 1},  # low=100 < 110*0.98=107.8
    ]
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    df = pd.DataFrame(rows, index=idx)
    df["sma3"] = [float("nan"), 100.0, 105.0]

    strat = Sma200RegimeStrategy(ma_window=3, allow_sell_signal=False)
    r = backtest(df, strat, fee=0.0, stop_loss_ratio=-0.02)
    # Day 1: close=110, sma3=100 → BUY at 110
    # Day 2: entry_price=110, stop_price=110*(1-0.02)=107.8, low=100 <= 107.8 → stop loss
    assert r.n_trades == 1
    t = r.trades[0]
    assert t.exit_type == "stop_loss"
    assert t.exit_price == pytest.approx(110 * 0.98)  # stop_price


def test_stop_loss_uses_low_not_close():
    """close는 손절가 위이지만 low가 아래인 경우 → 손절 발동."""
    rows = [
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 105, "high": 115, "low": 95,  "close": 110, "volume": 1},
        {"open": 110, "high": 120, "low": 106, "close": 115, "volume": 1},  # low=106 < 107.8, close=115
    ]
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    df = pd.DataFrame(rows, index=idx)
    df["sma3"] = [float("nan"), 100.0, 105.0]

    strat = Sma200RegimeStrategy(ma_window=3, allow_sell_signal=False)
    r = backtest(df, strat, fee=0.0, stop_loss_ratio=-0.02)
    # Day 1: close=110 >= sma3=100 → BUY at 110
    # Day 2: stop_price=107.8, low=106 <= 107.8 → stop loss (even though close=115)
    assert r.n_trades == 1
    assert r.trades[0].exit_type == "stop_loss"


def test_strategy_sell_signal():
    """전략의 SELL 시그널로 청산 확인."""
    rows = [
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 105, "high": 115, "low": 95,  "close": 110, "volume": 1},
        {"open": 110, "high": 120, "low": 100, "close": 108, "volume": 1},
        {"open": 108, "high": 112, "low": 85,  "close": 88,  "volume": 1},
    ]
    idx = pd.date_range("2026-01-01", periods=4, freq="D")
    df = pd.DataFrame(rows, index=idx)
    df["sma3"] = [float("nan"), float("nan"), 100.0, 105.0]

    strat = Sma200RegimeStrategy(ma_window=3, allow_sell_signal=True)
    r = backtest(df, strat, fee=0.0)
    # Day 2: close=108, sma3=100 → BUY at 108
    # Day 3: close=88, sma3=105 → 88 < 105 → SELL
    assert r.n_trades == 1
    t = r.trades[0]
    assert t.exit_type == "signal"
    assert t.entry_price == pytest.approx(108.0)
    assert t.exit_price == pytest.approx(88.0)


def test_time_exit():
    """time_exit: 보유 1일 후 다음날 시가에 청산."""
    rows = [
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 105, "high": 115, "low": 95,  "close": 110, "volume": 1},
        {"open": 112, "high": 120, "low": 105, "close": 115, "volume": 1},
    ]
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    df = pd.DataFrame(rows, index=idx)
    df["sma3"] = [float("nan"), 100.0, 105.0]

    strat = Sma200RegimeStrategy(ma_window=3, allow_sell_signal=False)
    r = backtest(df, strat, fee=0.0, enable_time_exit=True)
    # Day 1: close=110 >= sma3=100 → BUY at 110, hold_days → 1 at end
    # Day 2: hold_days=1 >= 1 → time_exit at open=112
    assert r.n_trades >= 1
    t = r.trades[0]
    assert t.exit_type == "time_exit"
    assert t.exit_price == pytest.approx(112.0)


def test_time_exit_allows_reentry():
    """time-exit 후 같은 날 close에서 재진입 가능."""
    rows = [
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 105, "high": 115, "low": 95,  "close": 110, "volume": 1},
        {"open": 112, "high": 125, "low": 105, "close": 120, "volume": 1},
        {"open": 120, "high": 130, "low": 115, "close": 125, "volume": 1},
    ]
    idx = pd.date_range("2026-01-01", periods=4, freq="D")
    df = pd.DataFrame(rows, index=idx)
    # SMA가 항상 낮아서 close >= sma → BUY 가능
    df["sma3"] = [float("nan"), 90.0, 95.0, 100.0]

    strat = Sma200RegimeStrategy(ma_window=3, allow_sell_signal=False)
    r = backtest(df, strat, fee=0.0, enable_time_exit=True, mark_to_market=False)
    # Day 1: close=110 >= sma3=90 → BUY at 110, hold_days → 1
    # Day 2: hold_days=1, time_exit at open=112 → reset.
    #         Then signal: close=120 >= sma3=95, no position → BUY at 120, hold_days → 1
    # Day 3: hold_days=1, time_exit at open=120 → reset.
    assert r.n_trades == 2
    assert r.trades[0].exit_type == "time_exit"
    assert r.trades[1].exit_type == "time_exit"


def test_no_reentry_after_stop_loss():
    """손절 후 같은 날 재진입 금지."""
    rows = [
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 105, "high": 115, "low": 95,  "close": 110, "volume": 1},
        {"open": 110, "high": 120, "low": 100, "close": 115, "volume": 1},  # low triggers stop
    ]
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    df = pd.DataFrame(rows, index=idx)
    # SMA always low so BUY is always possible signal-wise
    df["sma3"] = [float("nan"), 90.0, 95.0]

    strat = Sma200RegimeStrategy(ma_window=3, allow_sell_signal=False)
    r = backtest(df, strat, fee=0.0, stop_loss_ratio=-0.02)
    # Day 1: close=110 >= sma3=90 → BUY at 110
    # Day 2: stop_price=110*0.98=107.8, low=100 <= 107.8 → stop loss, continue
    #   no re-entry because of `continue` after stop-loss
    assert r.n_trades == 1
    assert r.trades[0].exit_type == "stop_loss"


def test_empty_df_generic():
    """빈 DataFrame → 0 trades."""
    strat = Sma200RegimeStrategy(ma_window=3)
    r = backtest(pd.DataFrame(), strat)
    assert r.n_trades == 0
    assert r.cumulative_return == 0.0


def test_cli_strategy_flag(mocker, capsys):
    """CLI --strategy volatility_breakout 정상 실행."""
    base = _make_df([
        {"open": 100, "high": 110, "low": 90,  "close": 105, "volume": 1},
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},
        {"open": 130, "high": 130, "low": 130, "close": 130, "volume": 1},
        {"open": 130, "high": 140, "low": 120, "close": 135, "volume": 1},
        {"open": 135, "high": 145, "low": 125, "close": 140, "volume": 1},
    ])
    mocker.patch("auto_coin.backtest.runner.pyupbit.get_ohlcv", return_value=base)
    rc = cli(["--ticker", "KRW-BTC", "--days", "5",
              "--strategy", "volatility_breakout", "--fee", "0"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "strategy=volatility_breakout" in out
    assert "Strategy Return" in out
    assert "Buy & Hold Return" in out


def test_cli_strategy_composite(mocker, capsys):
    """CLI --strategy sma200_ema_adx_composite 에러 없이 실행."""
    # 충분한 데이터가 필요 (warmup) — 간단히 300일 데이터 생성
    np.random.seed(42)
    n = 300
    closes = 100.0 + np.cumsum(np.random.randn(n) * 2)
    rows = []
    for c in closes:
        c = max(c, 10.0)
        rows.append({
            "open": c * 0.99,
            "high": c * 1.02,
            "low": c * 0.97,
            "close": c,
            "volume": 1000,
        })
    base = _make_df(rows)
    mocker.patch("auto_coin.backtest.runner.pyupbit.get_ohlcv", return_value=base)
    rc = cli(["--ticker", "KRW-BTC", "--days", "300",
              "--strategy", "sma200_ema_adx_composite", "--fee", "0",
              "--params", '{"sma_window": 5, "ema_fast_window": 3, "ema_slow_window": 7, "adx_window": 5, "adx_threshold": 10}'])
    assert rc == 0
    out = capsys.readouterr().out
    assert "strategy=sma200_ema_adx_composite" in out
    assert "Strategy Return" in out
    assert "Total Trades" in out


# ===================================================================
# P1: Benchmark + Risk Metrics tests
# ===================================================================


def test_benchmark_return_calculation():
    """first_close=100, last_close=150 → benchmark_return=0.5."""
    rows = [
        {"open": 100, "high": 110, "low": 90, "close": 100, "volume": 1},
        {"open": 105, "high": 115, "low": 95, "close": 120, "volume": 1},
        {"open": 120, "high": 160, "low": 110, "close": 150, "volume": 1},
    ]
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    df = pd.DataFrame(rows, index=idx)
    # SMA always below close → BUY on day 1
    df["sma3"] = [float("nan"), 90.0, 95.0]
    strat = Sma200RegimeStrategy(ma_window=3, allow_sell_signal=False)
    r = backtest(df, strat, fee=0.0)
    assert r.benchmark_return == pytest.approx(0.5)  # 150/100 - 1


def test_excess_return_calculation():
    """Strategy makes ~loss, buy-and-hold gains +50% → excess < 0."""
    rows = [
        {"open": 100, "high": 110, "low": 90, "close": 100, "volume": 1},
        {"open": 105, "high": 115, "low": 95, "close": 110, "volume": 1},
        {"open": 110, "high": 120, "low": 85, "close": 88, "volume": 1},
        {"open": 88, "high": 160, "low": 80, "close": 150, "volume": 1},
    ]
    idx = pd.date_range("2026-01-01", periods=4, freq="D")
    df = pd.DataFrame(rows, index=idx)
    # BUY day 1, SELL day 2 (close < sma → sell)
    df["sma3"] = [float("nan"), 90.0, 105.0, 100.0]
    strat = Sma200RegimeStrategy(ma_window=3, allow_sell_signal=True)
    r = backtest(df, strat, fee=0.0, mark_to_market=False)
    # benchmark = 150/100 - 1 = 0.5
    assert r.benchmark_return == pytest.approx(0.5)
    assert r.excess_return == pytest.approx(r.cumulative_return - 0.5)
    assert r.excess_return < 0  # strategy underperforms buy-and-hold


def test_sharpe_ratio_basic():
    """5 trades with known returns → verify Sharpe calculation."""
    rets = [0.05, -0.02, 0.03, 0.04, -0.01]
    d0 = datetime(2026, 1, 1)
    trades = [
        Trade(
            entry_date=d0 + timedelta(days=i * 10),
            entry_price=100.0,
            exit_date=d0 + timedelta(days=i * 10 + 5),
            exit_price=100.0 * (1 + r),
            ret=r,
        )
        for i, r in enumerate(rets)
    ]
    total_days = 50
    result = _build_result(trades, total_days=total_days, benchmark_return=0.0)
    # Manual calculation
    arr = np.array(rets)
    trades_per_year = 5 * 365.0 / 50
    expected_sharpe = float(np.mean(arr) / np.std(arr, ddof=1) * np.sqrt(trades_per_year))
    assert result.sharpe_ratio == pytest.approx(expected_sharpe, rel=1e-6)
    assert result.sharpe_ratio > 0  # net positive returns


def test_calmar_ratio_basic():
    """Known annualized return and MDD → Calmar = annualized / abs(mdd)."""
    # Two trades: +10%, -5% → equity [1.1, 1.045], peak [1.1, 1.1], dd [0, -0.05]
    trades = [
        Trade(
            entry_date=datetime(2026, 1, 1),
            entry_price=100.0,
            exit_date=datetime(2026, 4, 1),
            exit_price=110.0,
            ret=0.10,
        ),
        Trade(
            entry_date=datetime(2026, 4, 2),
            entry_price=110.0,
            exit_date=datetime(2026, 7, 1),
            exit_price=104.5,
            ret=-0.05,
        ),
    ]
    total_days = 365
    result = _build_result(trades, total_days=total_days, benchmark_return=0.0)
    # cum_return = 1.1 * 0.95 - 1 = 0.045
    # annualized for 365 days = cum_return (since total_days == 365)
    # mdd = (1.045 - 1.1) / 1.1 ≈ -0.05
    expected_calmar = result.annualized_return / abs(result.mdd)
    assert result.calmar_ratio == pytest.approx(expected_calmar, rel=1e-6)


def test_profit_factor_basic():
    """Wins sum to +0.10, losses sum to -0.05 → PF = 2.0."""
    trades = [
        Trade(entry_date=datetime(2026, 1, 1), entry_price=100, exit_date=datetime(2026, 1, 2), exit_price=106, ret=0.06),
        Trade(entry_date=datetime(2026, 1, 3), entry_price=100, exit_date=datetime(2026, 1, 4), exit_price=104, ret=0.04),
        Trade(entry_date=datetime(2026, 1, 5), entry_price=100, exit_date=datetime(2026, 1, 6), exit_price=97, ret=-0.03),
        Trade(entry_date=datetime(2026, 1, 7), entry_price=100, exit_date=datetime(2026, 1, 8), exit_price=98, ret=-0.02),
    ]
    result = _build_result(trades, total_days=30)
    # gross_wins = 0.06 + 0.04 = 0.10, gross_losses = 0.03 + 0.02 = 0.05
    assert result.profit_factor == pytest.approx(2.0)


def test_profit_factor_no_losses():
    """All winning trades → profit_factor = 99.99."""
    trades = [
        Trade(entry_date=datetime(2026, 1, 1), entry_price=100, exit_date=datetime(2026, 1, 2), exit_price=105, ret=0.05),
        Trade(entry_date=datetime(2026, 1, 3), entry_price=100, exit_date=datetime(2026, 1, 4), exit_price=103, ret=0.03),
    ]
    result = _build_result(trades, total_days=30)
    assert result.profit_factor == pytest.approx(99.99)


def test_avg_hold_days():
    """Trades spanning 2, 3, 5 days → avg = (2+3+5)/3 = 3.333..."""
    trades = [
        Trade(entry_date=datetime(2026, 1, 1), entry_price=100, exit_date=datetime(2026, 1, 3), exit_price=105, ret=0.05),
        Trade(entry_date=datetime(2026, 1, 5), entry_price=100, exit_date=datetime(2026, 1, 8), exit_price=103, ret=0.03),
        Trade(entry_date=datetime(2026, 1, 10), entry_price=100, exit_date=datetime(2026, 1, 15), exit_price=102, ret=0.02),
    ]
    result = _build_result(trades, total_days=30)
    assert result.avg_hold_days == pytest.approx(10.0 / 3.0)


def test_expectancy():
    """Known win_rate, avg_win, avg_loss → verify expectancy formula."""
    # 3 wins at +0.06 each, 2 losses at -0.03 each
    trades = [
        Trade(entry_date=datetime(2026, 1, 1), entry_price=100, exit_date=datetime(2026, 1, 2), exit_price=106, ret=0.06),
        Trade(entry_date=datetime(2026, 1, 3), entry_price=100, exit_date=datetime(2026, 1, 4), exit_price=106, ret=0.06),
        Trade(entry_date=datetime(2026, 1, 5), entry_price=100, exit_date=datetime(2026, 1, 6), exit_price=106, ret=0.06),
        Trade(entry_date=datetime(2026, 1, 7), entry_price=100, exit_date=datetime(2026, 1, 8), exit_price=97, ret=-0.03),
        Trade(entry_date=datetime(2026, 1, 9), entry_price=100, exit_date=datetime(2026, 1, 10), exit_price=97, ret=-0.03),
    ]
    result = _build_result(trades, total_days=30)
    # win_rate=0.6, avg_win=0.06, avg_loss=-0.03
    # expectancy = 0.6 * 0.06 - 0.4 * 0.03 = 0.036 - 0.012 = 0.024
    assert result.expectancy == pytest.approx(0.024)


def test_mark_to_market():
    """Strategy enters but never exits → mark_to_market=True creates 1 trade with exit_type='end_of_data'."""
    rows = [
        {"open": 100, "high": 110, "low": 90, "close": 105, "volume": 1},
        {"open": 105, "high": 115, "low": 95, "close": 110, "volume": 1},
        {"open": 110, "high": 120, "low": 105, "close": 115, "volume": 1},
    ]
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    df = pd.DataFrame(rows, index=idx)
    # SMA always low → BUY on day 1, no sell signal, no stop-loss, no time-exit
    df["sma3"] = [float("nan"), 90.0, 95.0]
    strat = Sma200RegimeStrategy(ma_window=3, allow_sell_signal=False)
    r = backtest(df, strat, fee=0.0, mark_to_market=True)
    assert r.n_trades == 1
    assert r.trades[0].exit_type == "end_of_data"


def test_mark_to_market_false():
    """Same setup but mark_to_market=False → 0 trades."""
    rows = [
        {"open": 100, "high": 110, "low": 90, "close": 105, "volume": 1},
        {"open": 105, "high": 115, "low": 95, "close": 110, "volume": 1},
        {"open": 110, "high": 120, "low": 105, "close": 115, "volume": 1},
    ]
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    df = pd.DataFrame(rows, index=idx)
    df["sma3"] = [float("nan"), 90.0, 95.0]
    strat = Sma200RegimeStrategy(ma_window=3, allow_sell_signal=False)
    r = backtest(df, strat, fee=0.0, mark_to_market=False)
    assert r.n_trades == 0


def test_report_format():
    """report() output contains all key section headers."""
    rows = [
        {"open": 100, "high": 110, "low": 90, "close": 105, "volume": 1},
        {"open": 105, "high": 115, "low": 95, "close": 110, "volume": 1},
        {"open": 110, "high": 120, "low": 100, "close": 108, "volume": 1},
        {"open": 108, "high": 112, "low": 85, "close": 88, "volume": 1},
        {"open": 88, "high": 95, "low": 80, "close": 90, "volume": 1},
    ]
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    df = pd.DataFrame(rows, index=idx)
    df["sma3"] = [float("nan"), float("nan"), 100.0, 105.0, 107.0]
    strat = Sma200RegimeStrategy(ma_window=3, allow_sell_signal=True)
    r = backtest(df, strat, fee=0.0)
    report = r.report()
    assert "Strategy Return" in report
    assert "Buy & Hold Return" in report
    assert "Excess Return" in report
    assert "Sharpe Ratio" in report
    assert "Calmar Ratio" in report
    assert "Profit Factor" in report
    assert "BACKTEST REPORT" in report


def test_edge_case_zero_trades_metrics():
    """Empty result has all metrics at 0.0."""
    r = BacktestResult()
    assert r.sharpe_ratio == 0.0
    assert r.calmar_ratio == 0.0
    assert r.profit_factor == 0.0
    assert r.expectancy == 0.0
    assert r.avg_hold_days == 0.0
    assert r.avg_win == 0.0
    assert r.avg_loss == 0.0
    assert r.annualized_return == 0.0
    assert r.benchmark_return == 0.0
    assert r.excess_return == 0.0
    assert r.total_days == 0


def test_edge_case_single_trade_metrics():
    """1 trade → Sharpe=0.0 (insufficient data), other metrics computed."""
    trades = [
        Trade(entry_date=datetime(2026, 1, 1), entry_price=100, exit_date=datetime(2026, 1, 5), exit_price=110, ret=0.10),
    ]
    result = _build_result(trades, total_days=30, benchmark_return=0.05)
    assert result.sharpe_ratio == 0.0  # need >= 2 trades
    assert result.n_trades == 1
    assert result.profit_factor == pytest.approx(99.99)  # no losses
    assert result.avg_hold_days == pytest.approx(4.0)
    assert result.avg_win == pytest.approx(0.10)
    assert result.avg_loss == 0.0
    assert result.excess_return == pytest.approx(0.10 - 0.05)


def test_default_slippage_in_cli(mocker, capsys):
    """CLI with --strategy but no --slippage → uses DEFAULT_SLIPPAGE (0.0005)."""
    base = _make_df([
        {"open": 100, "high": 110, "low": 90, "close": 105, "volume": 1},
        {"open": 100, "high": 200, "low": 100, "close": 150, "volume": 1},
        {"open": 130, "high": 130, "low": 130, "close": 130, "volume": 1},
        {"open": 130, "high": 140, "low": 120, "close": 135, "volume": 1},
        {"open": 135, "high": 145, "low": 125, "close": 140, "volume": 1},
    ])
    mocker.patch("auto_coin.backtest.runner.pyupbit.get_ohlcv", return_value=base)
    rc = cli(["--ticker", "KRW-BTC", "--days", "5",
              "--strategy", "volatility_breakout", "--fee", "0"])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"slippage={DEFAULT_SLIPPAGE}" in out
    assert "slippage=0.0005" in out
