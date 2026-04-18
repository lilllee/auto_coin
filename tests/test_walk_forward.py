"""Walk-forward 검증 모듈 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.backtest.walk_forward import (
    WalkForwardResult,
    WalkForwardWindow,
    _param_combos,
    cli,
    report,
    walk_forward,
)


def _make_df(n: int, seed: int = 42) -> pd.DataFrame:
    """Generate n days of synthetic OHLCV data."""
    np.random.seed(seed)
    closes = 100.0 + np.cumsum(np.random.randn(n) * 2)
    rows = []
    for c in closes:
        c = max(c, 10.0)
        rows.append(
            {
                "open": c * 0.99,
                "high": c * 1.02,
                "low": c * 0.97,
                "close": c,
                "volume": 1000,
            }
        )
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(rows, index=idx)


# ===================================================================
# _param_combos
# ===================================================================


def test_param_combos():
    """단일 sweep 키 — 리스트 길이만큼 combo 생성."""
    result = _param_combos({"k": [0.3, 0.5]})
    assert result == [{"k": 0.3}, {"k": 0.5}]


def test_param_combos_multi():
    """복수 sweep 키 — 곱집합."""
    result = _param_combos({"a": [1, 2], "b": [3, 4]})
    assert len(result) == 4
    assert {"a": 1, "b": 3} in result
    assert {"a": 2, "b": 4} in result


def test_param_combos_empty():
    """빈 그리드 → 빈 dict 하나."""
    assert _param_combos({}) == [{}]


def test_param_combos_mixed():
    """스칼라 + 리스트 혼합 — 스칼라는 고정, 리스트만 sweep."""
    result = _param_combos({"k": [0.3, 0.5], "ma_window": 5})
    assert len(result) == 2
    for combo in result:
        assert combo["ma_window"] == 5
        assert combo["k"] in (0.3, 0.5)


# ===================================================================
# walk_forward — 기본
# ===================================================================


def test_walk_forward_basic_vb():
    """VB 전략으로 기본 walk-forward 실행."""
    df = _make_df(300)
    result = walk_forward(
        df,
        "volatility_breakout",
        {"k": [0.3, 0.5, 0.7]},
        train_days=120,
        test_days=30,
        fee=0.0,
        slippage=0.0,
    )
    assert result.n_windows >= 2
    assert len(result.windows) == result.n_windows
    for w in result.windows:
        assert "k" in w.best_params
        assert w.best_params["k"] in (0.3, 0.5, 0.7)
        assert w.train_start < w.train_end
        assert w.test_start < w.test_end
    # 요약 통계가 계산되었는지
    assert isinstance(result.avg_train_return, float)
    assert isinstance(result.avg_test_return, float)
    assert isinstance(result.train_test_ratio, float)


def test_walk_forward_composite():
    """합성 전략 — 고정 파라미터 + sweep 혼합."""
    df = _make_df(300)
    result = walk_forward(
        df,
        "sma200_ema_adx_composite",
        {
            "adx_threshold": [10.0, 14.0, 20.0],
            "sma_window": 5,
            "ema_fast_window": 3,
            "ema_slow_window": 7,
            "adx_window": 5,
        },
        train_days=120,
        test_days=30,
        fee=0.0,
        slippage=0.0,
    )
    assert result.n_windows >= 1
    for w in result.windows:
        assert "adx_threshold" in w.best_params
        assert w.best_params["sma_window"] == 5


def test_walk_forward_not_enough_data():
    """데이터 부족 → n_windows == 0."""
    df = _make_df(50)
    result = walk_forward(
        df,
        "volatility_breakout",
        {"k": [0.3, 0.5]},
        train_days=180,
        test_days=30,
    )
    assert result.n_windows == 0
    assert result.windows == []


def test_walk_forward_empty_grid():
    """sweep 대상 없으면 빈 결과."""
    df = _make_df(300)
    result = walk_forward(df, "volatility_breakout", {})
    assert result.n_windows == 0


def test_walk_forward_window_dates():
    """첫 윈도우의 train_start가 df.index[0]과 일치."""
    df = _make_df(300)
    result = walk_forward(
        df,
        "volatility_breakout",
        {"k": [0.3, 0.5]},
        train_days=120,
        test_days=30,
        fee=0.0,
        slippage=0.0,
    )
    assert result.n_windows >= 1
    first = result.windows[0]
    assert first.train_start == df.index[0].date().isoformat()
    # train_end < test_start (순차)
    assert first.train_end < first.test_start


def test_walk_forward_selects_best_params():
    """train 구간에서 최적 k가 선택되는지 확인.

    k=0.01 (매우 작은 값)은 거의 모든 봉에서 돌파 → 많은 트레이드 발생.
    k=0.99 (매우 큰 값)은 거의 돌파 불가 → 수익 0에 가까움.
    충분히 극단적인 값이면 k=0.01이 선택될 가능성이 높다.
    """
    # 상승 추세 데이터 생성
    np.random.seed(123)
    n = 300
    closes = 100.0 + np.arange(n) * 0.5 + np.random.randn(n) * 0.5
    rows = []
    for c in closes:
        c = max(c, 10.0)
        rows.append(
            {
                "open": c * 0.995,
                "high": c * 1.01,
                "low": c * 0.98,
                "close": c,
                "volume": 1000,
            }
        )
    df = pd.DataFrame(rows, index=pd.date_range("2024-01-01", periods=n, freq="D"))

    result = walk_forward(
        df,
        "volatility_breakout",
        {"k": [0.01, 0.99]},
        train_days=120,
        test_days=30,
        fee=0.0,
        slippage=0.0,
    )
    # 최소 1개 윈도우에서 k=0.01이 선택되어야 함
    selected_ks = [w.best_params["k"] for w in result.windows]
    assert 0.01 in selected_ks


# ===================================================================
# 요약 통계 검증
# ===================================================================


def test_positive_excess_ratio():
    """positive_excess_ratio 계산 검증."""
    df = _make_df(300)
    result = walk_forward(
        df,
        "volatility_breakout",
        {"k": [0.3, 0.5, 0.7]},
        train_days=120,
        test_days=30,
        fee=0.0,
        slippage=0.0,
    )
    if result.n_windows > 0:
        expected = sum(1 for w in result.windows if w.test_excess > 0) / result.n_windows
        assert result.positive_excess_ratio == pytest.approx(expected)


def test_train_test_ratio():
    """train/test ratio 수동 계산 검증."""
    # avg_train=0.10, avg_test=0.02 → ratio=5.0
    w = WalkForwardWindow(
        window_id=0,
        train_start="2024-01-01",
        train_end="2024-06-30",
        test_start="2024-07-01",
        test_end="2024-07-30",
        best_params={"k": 0.5},
        train_return=0.10,
        test_return=0.02,
        test_benchmark=0.01,
        test_excess=0.01,
        test_mdd=-0.01,
        test_trades=3,
        test_sharpe=1.0,
    )
    r = WalkForwardResult(
        strategy_name="volatility_breakout",
        param_grid={"k": [0.3, 0.5]},
        n_windows=1,
        avg_train_return=0.10,
        avg_test_return=0.02,
        avg_test_benchmark=0.01,
        avg_test_excess=0.01,
        positive_excess_ratio=1.0,
        train_test_ratio=abs(0.10 / 0.02),
        windows=[w],
    )
    assert r.train_test_ratio == pytest.approx(5.0)


# ===================================================================
# 리포트
# ===================================================================


def test_report_format():
    """report() 출력에 주요 섹션 헤더 포함."""
    df = _make_df(300)
    result = walk_forward(
        df,
        "volatility_breakout",
        {"k": [0.3, 0.5, 0.7]},
        train_days=120,
        test_days=30,
        fee=0.0,
        slippage=0.0,
    )
    output = report(result)
    assert "WALK-FORWARD REPORT" in output
    assert "SUMMARY" in output
    assert "Avg Train Return" in output
    assert "Positive Excess" in output
    assert "Train/Test Ratio" in output


def test_report_empty():
    """윈도우 없는 결과의 report는 에러 없이 동작."""
    r = WalkForwardResult(
        strategy_name="volatility_breakout",
        param_grid={},
    )
    output = report(r)
    assert "WALK-FORWARD REPORT" in output
    assert "윈도우 없음" in output


def test_report_verdict_stable():
    """ratio < 2 → 안정적."""
    w = WalkForwardWindow(
        window_id=0,
        train_start="2024-01-01",
        train_end="2024-06-30",
        test_start="2024-07-01",
        test_end="2024-07-30",
        best_params={"k": 0.5},
        train_return=0.05,
        test_return=0.04,
        test_benchmark=0.02,
        test_excess=0.02,
        test_mdd=-0.01,
        test_trades=3,
        test_sharpe=1.0,
    )
    r = WalkForwardResult(
        strategy_name="volatility_breakout",
        param_grid={"k": [0.3, 0.5]},
        n_windows=1,
        avg_train_return=0.05,
        avg_test_return=0.04,
        avg_test_benchmark=0.02,
        avg_test_excess=0.02,
        positive_excess_ratio=1.0,
        train_test_ratio=1.25,
        windows=[w],
    )
    output = report(r)
    assert "안정적" in output


def test_report_verdict_overfit():
    """ratio > 3 → 과적합 의심."""
    w = WalkForwardWindow(
        window_id=0,
        train_start="2024-01-01",
        train_end="2024-06-30",
        test_start="2024-07-01",
        test_end="2024-07-30",
        best_params={"k": 0.5},
        train_return=0.30,
        test_return=0.02,
        test_benchmark=0.01,
        test_excess=0.01,
        test_mdd=-0.01,
        test_trades=3,
        test_sharpe=0.5,
    )
    r = WalkForwardResult(
        strategy_name="volatility_breakout",
        param_grid={"k": [0.3, 0.5]},
        n_windows=1,
        avg_train_return=0.30,
        avg_test_return=0.02,
        avg_test_benchmark=0.01,
        avg_test_excess=0.01,
        positive_excess_ratio=1.0,
        train_test_ratio=15.0,
        windows=[w],
    )
    output = report(r)
    assert "과적합 의심" in output


# ===================================================================
# CLI
# ===================================================================


def test_cli_basic(mocker, capsys):
    """CLI 기본 실행 — pyupbit mock."""
    df = _make_df(300)
    mocker.patch("auto_coin.backtest.walk_forward.pyupbit.get_ohlcv", return_value=df)
    rc = cli([
        "--strategy", "volatility_breakout",
        "--ticker", "KRW-BTC",
        "--days", "300",
        "--train-days", "120",
        "--test-days", "30",
        "--fee", "0",
        "--slippage", "0",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WALK-FORWARD REPORT" in out
    assert "SUMMARY" in out
    assert "strategy=volatility_breakout" in out


def test_cli_no_candles(mocker, capsys):
    """캔들 조회 실패 → rc=1."""
    mocker.patch("auto_coin.backtest.walk_forward.pyupbit.get_ohlcv", return_value=None)
    rc = cli([
        "--strategy", "volatility_breakout",
        "--ticker", "KRW-FAKE",
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "ERROR" in err


def test_cli_param_grid_json(mocker, capsys):
    """CLI --param-grid JSON 파싱."""
    df = _make_df(300)
    mocker.patch("auto_coin.backtest.walk_forward.pyupbit.get_ohlcv", return_value=df)
    rc = cli([
        "--strategy", "volatility_breakout",
        "--ticker", "KRW-BTC",
        "--days", "300",
        "--train-days", "120",
        "--test-days", "30",
        "--param-grid", '{"k": [0.3, 0.7]}',
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WALK-FORWARD REPORT" in out
