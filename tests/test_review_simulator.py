from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from auto_coin.review.simulator import ReviewValidationError, run_review_simulation


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
