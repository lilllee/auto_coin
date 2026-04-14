from __future__ import annotations

from datetime import UTC, datetime, timedelta

from auto_coin.executor.store import OrderRecord, Position, State
from auto_coin.reporter import build_daily_report


def _record(side: str, price: float, *, hours_ago: float, uuid: str = "u") -> OrderRecord:
    placed = datetime.now(UTC) - timedelta(hours=hours_ago)
    return OrderRecord(
        uuid=uuid,
        side=side,
        market="KRW-BTC",
        krw_amount=10_000 if side == "buy" else None,
        volume=0.001 if side == "sell" else None,
        price=price,
        placed_at=placed.isoformat(timespec="seconds"),
        status="paper",
    )


def test_empty_state_report():
    text = build_daily_report(State())
    assert "orders: 0" in text
    assert "position: flat" in text
    assert "daily_pnl:" in text


def test_ignores_orders_older_than_window():
    old = _record("buy", 100.0, hours_ago=48, uuid="old")
    fresh = _record("buy", 100.0, hours_ago=1, uuid="new")
    text = build_daily_report(State(orders=[old, fresh]), hours=24)
    assert "orders: 1" in text  # 오래된 것 제외


def test_cycle_return_computed_for_paired_buy_sell():
    buy = _record("buy", 100.0, hours_ago=2, uuid="b1")
    sell = _record("sell", 110.0, hours_ago=1, uuid="s1")
    text = build_daily_report(State(orders=[buy, sell]))
    assert "closed cycles: 1" in text
    assert "wins=1" in text
    assert "win_rate=100.0%" in text
    assert "+10.00%" in text  # best cycle


def test_losing_cycle_reduces_win_rate():
    orders = [
        _record("buy",  100.0, hours_ago=4, uuid="b1"),
        _record("sell", 90.0,  hours_ago=3, uuid="s1"),  # -10%
        _record("buy",  100.0, hours_ago=2, uuid="b2"),
        _record("sell", 120.0, hours_ago=1, uuid="s2"),  # +20%
    ]
    text = build_daily_report(State(orders=orders))
    assert "closed cycles: 2" in text
    assert "wins=1" in text
    assert "win_rate=50.0%" in text
    assert "+20.00%" in text
    assert "-10.00%" in text


def test_open_position_rendered():
    pos = Position(ticker="KRW-BTC", volume=0.002, avg_entry_price=50_000_000.0,
                   entry_uuid="u1", entry_at=datetime.now(UTC).isoformat())
    text = build_daily_report(State(position=pos))
    assert "KRW-BTC" in text
    assert "0.00200000" in text
    assert "50,000,000" in text


def test_malformed_timestamp_safely_skipped():
    bad = OrderRecord(uuid="b", side="buy", market="KRW-BTC", krw_amount=1, volume=None,
                      price=100.0, placed_at="not-a-date", status="paper")
    text = build_daily_report(State(orders=[bad]))
    assert "orders: 0" in text


def test_daily_pnl_rendered():
    state = State(daily_pnl_ratio=-0.0123, daily_pnl_date="2026-04-13")
    text = build_daily_report(state)
    assert "-1.23%" in text
    assert "2026-04-13" in text


def test_multi_ticker_report_shows_sum_and_average():
    """When avg_daily_pnl and n_tickers > 1, report includes both values."""
    # 3 tickers each +2% → sum +6%, avg +2%
    state = State(daily_pnl_ratio=0.06, daily_pnl_date="2026-04-14")
    text = build_daily_report(state, avg_daily_pnl=0.02, n_tickers=3)
    assert "daily_pnl_avg" in text
    assert "+2.00%" in text   # average
    assert "+6.00%" in text   # sum
    assert "3종목" in text


def test_single_ticker_report_omits_average():
    """When n_tickers == 1, the avg line should not appear."""
    state = State(daily_pnl_ratio=0.02, daily_pnl_date="2026-04-14")
    text = build_daily_report(state, avg_daily_pnl=0.02, n_tickers=1)
    assert "daily_pnl_avg" not in text


def test_no_avg_kwarg_omits_average():
    """When avg_daily_pnl is not provided, the avg line should not appear."""
    state = State(daily_pnl_ratio=0.06)
    text = build_daily_report(state)
    assert "daily_pnl_avg" not in text
