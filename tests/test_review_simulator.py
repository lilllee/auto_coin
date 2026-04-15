from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from auto_coin.review.reasons import derive_review_reason
from auto_coin.review.simulator import ReviewValidationError, run_review_simulation
from auto_coin.strategy import create_strategy
from auto_coin.strategy.base import Signal


def _composite_review_df() -> pd.DataFrame:
    idx = pd.date_range("2026-03-30", periods=7, freq="D")
    return pd.DataFrame(
        {
            "open": [100, 100, 99, 110, 118, 119, 117],
            "high": [101, 101, 100, 111, 119, 120, 118],
            "low": [99, 99, 98, 109, 117, 118, 116],
            "close": [100, 100, 99, 110, 118, 119, 117],
            "volume": [1, 1, 1, 1, 1, 1, 1],
            "target": [None, None, None, None, None, None, None],
            "ma5": [100, 100, 100, 100, 100, 100, 100],
            "sma200": [120, 120, 120, 100, 100, 120, 120],
            "ema27": [90, 90, 90, 130, 132, 133, 120],
            "ema125": [100, 100, 100, 120, 121, 122, 121],
            "adx90": [10, 10, 10, 20, 22, 18, 17],
        },
        index=idx,
    )


def test_review_simulator_validates_max_range():
    with pytest.raises(ReviewValidationError, match="<= 90 days"):
        run_review_simulation(
            client=object(),  # type: ignore[arg-type]
            ticker="KRW-BTC",
            start_date="2026-04-01",
            end_date="2026-07-01",
            strategy_name="volatility_breakout",
        )


def test_review_simulator_fetches_with_warmup_and_to(mocker):
    df = _composite_review_df()
    fetch_daily = mocker.patch(
        "auto_coin.review.simulator.fetch_daily",
        return_value=df,
    )

    result = run_review_simulation(
        client=object(),  # type: ignore[arg-type]
        ticker="KRW-BTC",
        start_date="2026-04-01",
        end_date="2026-04-05",
        strategy_name="sma200_ema_adx_composite",
        strategy_params={
            "sma_window": 200,
            "ema_fast_window": 27,
            "ema_slow_window": 125,
            "adx_window": 90,
            "adx_threshold": 14.0,
        },
    )

    assert result.range["history_days"] == 250
    fetch_daily.assert_called_once()
    kwargs = fetch_daily.call_args.kwargs
    assert kwargs["count"] == 254
    assert kwargs["to"] == datetime(2026, 4, 6, 0, 0)


def test_review_simulator_replays_composite_and_builds_summary(mocker):
    mocker.patch("auto_coin.review.simulator.fetch_daily", return_value=_composite_review_df())

    result = run_review_simulation(
        client=object(),  # type: ignore[arg-type]
        ticker="krw-btc",
        start_date="2026-04-01",
        end_date="2026-04-05",
        strategy_name="sma200_ema_adx_composite",
        strategy_params={
            "sma_window": 200,
            "ema_fast_window": 27,
            "ema_slow_window": 125,
            "adx_window": 90,
            "adx_threshold": 14.0,
        },
    )

    assert result.ticker == "KRW-BTC"
    assert result.summary.buy_count == 1
    assert result.summary.sell_count == 1
    assert result.summary.event_count == 2
    assert result.summary.last_position["state"] == "flat"
    assert result.summary.realized_pnl_ratio == pytest.approx((119 - 110) / 110)
    assert result.summary.total_pnl_ratio == pytest.approx((119 - 110) / 110)

    assert [row.signal for row in result.rows] == ["hold", "buy", "hold", "sell", "hold"]
    assert result.rows[0].reason == "price<sma200, stay out"
    assert (
        result.rows[1].reason
        == "price>=sma200 and ema27>ema125 and adx90>=14.0"
    )
    assert result.rows[2].reason == "risk-on and already in position"
    assert result.rows[3].reason == "price<sma200 (risk-off while holding)"

    assert result.events[0].signal == "buy"
    assert result.events[0].position_before == "flat"
    assert result.events[0].position_after == "long"
    assert result.events[1].signal == "sell"
    assert result.events[1].trade_pnl_ratio == pytest.approx((119 - 110) / 110)


def test_review_simulator_to_dict_is_json_friendly(mocker):
    mocker.patch("auto_coin.review.simulator.fetch_daily", return_value=_composite_review_df())

    payload = run_review_simulation(
        client=object(),  # type: ignore[arg-type]
        ticker="KRW-BTC",
        start_date="2026-04-01",
        end_date="2026-04-05",
        strategy_name="sma200_ema_adx_composite",
        strategy_params={
            "sma_window": 200,
            "ema_fast_window": 27,
            "ema_slow_window": 125,
            "adx_window": 90,
            "adx_threshold": 14.0,
        },
    ).to_dict()

    assert payload["summary"]["buy_count"] == 1
    assert payload["events"][1]["signal"] == "sell"


def test_review_include_sell_overrides_allow_sell_signal(mocker):
    """include_strategy_sell=True면 atr_channel_breakout에서 SELL 이벤트가 발생해야 한다."""
    # BUY 후 lower_channel 아래로 떨어지는 데이터
    idx = pd.date_range("2026-03-28", periods=9, freq="D")
    df = pd.DataFrame(
        {
            "open": [100, 100, 100, 100, 100, 100, 120, 115, 90],
            "high": [101, 101, 101, 101, 101, 101, 121, 116, 91],
            "low": [99, 99, 99, 99, 99, 99, 119, 114, 89],
            "close": [100, 100, 100, 100, 100, 100, 120, 115, 90],
            "volume": [1] * 9,
            "upper_channel": [95, 95, 95, 95, 95, 95, 95, 95, 95],
            "lower_channel": [80, 80, 80, 80, 80, 80, 80, 80, 100],
            "atr14": [5, 5, 5, 5, 5, 5, 5, 5, 5],
        },
        index=idx,
    )
    mocker.patch("auto_coin.review.simulator.fetch_daily", return_value=df)

    result = run_review_simulation(
        client=object(),  # type: ignore[arg-type]
        ticker="KRW-BTC",
        start_date="2026-04-01",
        end_date="2026-04-05",
        strategy_name="atr_channel_breakout",
        strategy_params={"atr_window": 14, "channel_multiplier": 1.0},
        include_strategy_sell=True,
    )

    signals = [row.signal for row in result.rows]
    assert "sell" in signals, f"Expected sell in signals, got {signals}"
    assert result.summary.sell_count >= 1


def test_review_include_sell_false_keeps_default(mocker):
    """include_strategy_sell=False면 atr_channel_breakout에서 SELL 안 나와야 한다."""
    idx = pd.date_range("2026-03-28", periods=9, freq="D")
    df = pd.DataFrame(
        {
            "open": [100, 100, 100, 100, 100, 100, 120, 115, 90],
            "high": [101, 101, 101, 101, 101, 101, 121, 116, 91],
            "low": [99, 99, 99, 99, 99, 99, 119, 114, 89],
            "close": [100, 100, 100, 100, 100, 100, 120, 115, 90],
            "volume": [1] * 9,
            "upper_channel": [95, 95, 95, 95, 95, 95, 95, 95, 95],
            "lower_channel": [80, 80, 80, 80, 80, 80, 80, 80, 100],
            "atr14": [5, 5, 5, 5, 5, 5, 5, 5, 5],
        },
        index=idx,
    )
    mocker.patch("auto_coin.review.simulator.fetch_daily", return_value=df)

    result = run_review_simulation(
        client=object(),  # type: ignore[arg-type]
        ticker="KRW-BTC",
        start_date="2026-04-01",
        end_date="2026-04-05",
        strategy_name="atr_channel_breakout",
        strategy_params={"atr_window": 14, "channel_multiplier": 1.0},
        include_strategy_sell=False,
    )

    assert result.summary.sell_count == 0


def test_review_include_sell_no_effect_on_entry_only(mocker):
    """volatility_breakout은 SELL 코드가 없으므로 include_sell=True여도 영향 없다."""
    idx = pd.date_range("2026-03-28", periods=9, freq="D")
    df = pd.DataFrame(
        {
            "open": [100, 100, 100, 100, 100, 100, 100, 100, 100],
            "high": [101, 101, 101, 101, 101, 101, 101, 101, 101],
            "low": [99, 99, 99, 99, 99, 99, 99, 99, 99],
            "close": [100, 100, 100, 100, 100, 100, 100, 100, 100],
            "volume": [1] * 9,
            "target": [None, None, None, None, 95, 95, 95, 95, 95],
            "ma5": [100, 100, 100, 100, 100, 100, 100, 100, 100],
        },
        index=idx,
    )
    mocker.patch("auto_coin.review.simulator.fetch_daily", return_value=df)

    result = run_review_simulation(
        client=object(),  # type: ignore[arg-type]
        ticker="KRW-BTC",
        start_date="2026-04-01",
        end_date="2026-04-05",
        strategy_name="volatility_breakout",
        strategy_params={"k": 0.5, "ma_window": 5},
        include_strategy_sell=True,
    )

    assert result.summary.sell_count == 0


def test_review_notes_reflect_sell_mode(mocker):
    """include_strategy_sell=True면 notes에 'strategy sell enabled'가 포함되어야 한다."""
    mocker.patch("auto_coin.review.simulator.fetch_daily", return_value=_composite_review_df())

    result_default = run_review_simulation(
        client=object(),  # type: ignore[arg-type]
        ticker="KRW-BTC",
        start_date="2026-04-01",
        end_date="2026-04-05",
        strategy_name="sma200_ema_adx_composite",
        strategy_params={
            "sma_window": 200,
            "ema_fast_window": 27,
            "ema_slow_window": 125,
            "adx_window": 90,
            "adx_threshold": 14.0,
        },
        include_strategy_sell=False,
    )
    assert result_default.summary.notes[0] == "strategy sell always active"
    assert result_default.summary.mode_label == "SELL 항상 활성"

    result_sell = run_review_simulation(
        client=object(),  # type: ignore[arg-type]
        ticker="KRW-BTC",
        start_date="2026-04-01",
        end_date="2026-04-05",
        strategy_name="sma200_ema_adx_composite",
        strategy_params={
            "sma_window": 200,
            "ema_fast_window": 27,
            "ema_slow_window": 125,
            "adx_window": 90,
            "adx_threshold": 14.0,
        },
        include_strategy_sell=True,
    )
    assert result_sell.summary.notes[0] == "strategy sell always active"


@pytest.mark.parametrize(
    ("strategy_name", "strategy_params", "row_data", "expected_reason"),
    [
        (
            "sma200_regime",
            {"ma_window": 200, "buffer_pct": 0.0, "allow_sell_signal": True},
            {"sma200": 100, "close": 95},
            "price<sma200, strategy exit",
        ),
        (
            "atr_channel_breakout",
            {"atr_window": 14, "channel_multiplier": 1.0, "allow_sell_signal": True},
            {"upper_channel": 120, "lower_channel": 100, "atr14": 5, "close": 95},
            "price<lower_channel, strategy exit",
        ),
        (
            "ema_adx_atr_trend",
            {
                "ema_fast_window": 27,
                "ema_slow_window": 125,
                "adx_window": 90,
                "adx_threshold": 14.0,
                "allow_sell_signal": True,
            },
            {"ema27": 90, "ema125": 100, "adx90": 20, "close": 95},
            "ema27<=ema125, strategy exit",
        ),
        (
            "ad_turtle",
            {"entry_window": 20, "exit_window": 10, "allow_sell_signal": True},
            {"donchian_high_20": 120, "donchian_low_10": 100, "close": 95},
            "price<donchian_low_10, strategy exit",
        ),
    ],
)
def test_review_reasons_explain_strategy_exit_paths(strategy_name, strategy_params, row_data, expected_reason):
    strategy = create_strategy(strategy_name, strategy_params)
    row = pd.Series(row_data)

    reason = derive_review_reason(
        strategy_name,
        strategy,
        row,
        current_price=row_data["close"],
        has_position=True,
        signal=Signal.SELL,
    )

    assert reason == expected_reason


def test_review_summary_exposes_mode_and_interpretation(mocker):
    mocker.patch("auto_coin.review.simulator.fetch_daily", return_value=_composite_review_df())

    result = run_review_simulation(
        client=object(),  # type: ignore[arg-type]
        ticker="KRW-BTC",
        start_date="2026-04-01",
        end_date="2026-04-05",
        strategy_name="sma200_ema_adx_composite",
        strategy_params={
            "sma_window": 200,
            "ema_fast_window": 27,
            "ema_slow_window": 125,
            "adx_window": 90,
            "adx_threshold": 14.0,
        },
        include_strategy_sell=True,
    )

    assert result.summary.mode_label == "SELL 항상 활성"
    assert result.summary.interpretation == "선택 구간에서 전략 기준 청산까지 확인되었습니다. (일봉 종가 기준, 실운영과 차이 가능)"


def test_review_operational_stop_loss(mocker):
    """include_operational_exits=True면 종가가 손절선 아래일 때 SELL 발생."""
    # BUY 후 가격이 손절선 아래로 떨어지는 데이터
    # upper_channel=110으로 close=100 구간에서 BUY 미발생,
    # close=120인 2026-04-03에 upper_channel=95로 전환 → BUY at 120
    # stop_loss_ratio=-0.15 → stop_price=120*0.85=102, close=100(04-05)에서 손절
    idx = pd.date_range("2026-03-28", periods=9, freq="D")
    df = pd.DataFrame(
        {
            "open": [100, 100, 100, 100, 100, 100, 120, 115, 100],
            "high": [101, 101, 101, 101, 101, 101, 121, 116, 101],
            "low": [99, 99, 99, 99, 99, 99, 119, 114, 99],
            "close": [100, 100, 100, 100, 100, 100, 120, 115, 100],
            "volume": [1] * 9,
            "upper_channel": [110, 110, 110, 110, 110, 110, 95, 95, 95],
            "lower_channel": [80, 80, 80, 80, 80, 80, 80, 80, 80],
            "atr14": [5, 5, 5, 5, 5, 5, 5, 5, 5],
        },
        index=idx,
    )
    mocker.patch("auto_coin.review.simulator.fetch_daily", return_value=df)

    result = run_review_simulation(
        client=object(),  # type: ignore[arg-type]
        ticker="KRW-BTC",
        start_date="2026-04-01",
        end_date="2026-04-05",
        strategy_name="atr_channel_breakout",
        strategy_params={"atr_window": 14, "channel_multiplier": 1.0},
        include_strategy_sell=True,
        include_operational_exits=True,
        stop_loss_ratio=-0.15,  # -15% (120 * 0.85 = 102, 가격 100은 손절 대상)
    )

    sell_events = [e for e in result.events if e.signal == "sell"]
    assert len(sell_events) >= 1
    stop_loss_events = [e for e in sell_events if e.exit_type and "stop_loss" in e.exit_type]
    assert len(stop_loss_events) >= 1


def test_review_operational_time_exit_vb(mocker):
    """volatility_breakout은 include_operational_exits=True면 다음 일봉에서 자동 청산."""
    idx = pd.date_range("2026-03-28", periods=9, freq="D")
    df = pd.DataFrame(
        {
            "open": [100, 100, 100, 100, 100, 100, 100, 100, 100],
            "high": [101, 101, 101, 101, 101, 101, 101, 101, 101],
            "low": [99, 99, 99, 99, 99, 99, 99, 99, 99],
            "close": [100, 100, 100, 100, 100, 100, 100, 100, 100],
            "volume": [1] * 9,
            "target": [None, None, None, None, 95, 95, 95, 95, 95],
            "ma5": [90, 90, 90, 90, 90, 90, 90, 90, 90],
        },
        index=idx,
    )
    mocker.patch("auto_coin.review.simulator.fetch_daily", return_value=df)

    result = run_review_simulation(
        client=object(),  # type: ignore[arg-type]
        ticker="KRW-BTC",
        start_date="2026-04-01",
        end_date="2026-04-05",
        strategy_name="volatility_breakout",
        strategy_params={"k": 0.5, "ma_window": 5},
        include_operational_exits=True,
        stop_loss_ratio=-0.02,
    )

    sell_events = [e for e in result.events if e.signal == "sell"]
    time_exits = [e for e in sell_events if e.exit_type and "time_exit" in e.exit_type]
    assert len(time_exits) >= 1


def test_review_operational_exits_disabled_by_default(mocker):
    """include_operational_exits=False(기본값)면 운영 청산 미반영."""
    idx = pd.date_range("2026-03-28", periods=9, freq="D")
    df = pd.DataFrame(
        {
            "open": [100, 100, 100, 100, 100, 100, 120, 115, 100],
            "high": [101, 101, 101, 101, 101, 101, 121, 116, 101],
            "low": [99, 99, 99, 99, 99, 99, 119, 114, 99],
            "close": [100, 100, 100, 100, 100, 100, 120, 115, 100],
            "volume": [1] * 9,
            "upper_channel": [95, 95, 95, 95, 95, 95, 95, 95, 95],
            "lower_channel": [80, 80, 80, 80, 80, 80, 80, 80, 80],
            "atr14": [5, 5, 5, 5, 5, 5, 5, 5, 5],
        },
        index=idx,
    )
    mocker.patch("auto_coin.review.simulator.fetch_daily", return_value=df)

    result = run_review_simulation(
        client=object(),  # type: ignore[arg-type]
        ticker="KRW-BTC",
        start_date="2026-04-01",
        end_date="2026-04-05",
        strategy_name="atr_channel_breakout",
        strategy_params={"atr_window": 14, "channel_multiplier": 1.0},
        include_operational_exits=False,
    )

    op_events = [e for e in result.events if e.exit_type is not None]
    assert len(op_events) == 0


def test_review_notes_operational_mode(mocker):
    """include_operational_exits=True면 notes에 'operational exits enabled' 포함."""
    mocker.patch("auto_coin.review.simulator.fetch_daily", return_value=_composite_review_df())

    result = run_review_simulation(
        client=object(),  # type: ignore[arg-type]
        ticker="KRW-BTC",
        start_date="2026-04-01",
        end_date="2026-04-05",
        strategy_name="sma200_ema_adx_composite",
        strategy_params={
            "sma_window": 200,
            "ema_fast_window": 27,
            "ema_slow_window": 125,
            "adx_window": 90,
            "adx_threshold": 14.0,
        },
        include_operational_exits=True,
    )
    assert result.summary.notes[0] == "operational exits enabled"
