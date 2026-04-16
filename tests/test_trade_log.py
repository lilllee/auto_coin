"""P2-1: TradeLog + DailySnapshot KPI infrastructure tests."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from auto_coin.config import UPBIT_FEE_RATE
from auto_coin.exchange.upbit_client import UpbitClient
from auto_coin.executor.order import OrderExecutor
from auto_coin.executor.store import OrderStore
from auto_coin.risk.manager import Action, Decision

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return OrderStore(tmp_path / "state.json")


@pytest.fixture
def unauth_client():
    return UpbitClient(
        access_key="", secret_key="", max_retries=1,
        backoff_base=0.0, min_request_interval=0.0,
    )


@pytest.fixture
def auth_client():
    return UpbitClient(
        access_key="ak", secret_key="sk", max_retries=1,
        backoff_base=0.0, min_request_interval=0.0,
    )


# ---------------------------------------------------------------------------
# Helper: create executor with callback that captures data
# ---------------------------------------------------------------------------

def _make_executor_with_cb(client, store, *, live=False, strategy_name="vb"):
    captured = []

    def on_trade_closed(data: dict):
        captured.append(data)

    ex = OrderExecutor(
        client, store, "KRW-BTC",
        live=live,
        strategy_name=strategy_name,
        on_trade_closed=on_trade_closed,
    )
    return ex, captured


# ---------------------------------------------------------------------------
# 1. test_trade_log_recorded_on_paper_sell
# ---------------------------------------------------------------------------

def test_trade_log_recorded_on_paper_sell(unauth_client, store):
    """Paper SELL triggers callback with correct fields."""
    ex, captured = _make_executor_with_cb(unauth_client, store, live=False)
    ex.execute(
        Decision(Action.BUY, reason="entry", krw_amount=10_000),
        current_price=100.0,
    )
    ex.execute(
        Decision(Action.SELL, reason="exit signal", volume=100.0, reason_code="signal_sell"),
        current_price=110.0,
    )
    assert len(captured) == 1
    data = captured[0]
    assert data["ticker"] == "KRW-BTC"
    assert data["strategy_name"] == "vb"
    assert data["mode"] == "paper"
    assert data["entry_price"] == 100.0
    assert data["exit_price"] == 110.0
    assert data["quantity"] == pytest.approx(100.0)
    assert data["entry_value_krw"] == pytest.approx(10_000.0)
    assert data["exit_value_krw"] == pytest.approx(11_000.0)
    assert data["fee_krw"] > 0
    assert data["pnl_krw"] > 0
    assert data["exit_reason_code"] == "signal_sell"
    assert data["exit_reason_text"] == "exit signal"
    assert isinstance(data["entry_at"], datetime)
    assert isinstance(data["exit_at"], datetime)
    assert isinstance(data["hold_seconds"], int)
    assert data["hold_seconds"] >= 0


# ---------------------------------------------------------------------------
# 2. test_trade_log_recorded_on_live_sell
# ---------------------------------------------------------------------------

def test_trade_log_recorded_on_live_sell(mocker, auth_client, store):
    """Live SELL triggers callback with mode='live'."""
    mocker.patch.object(
        auth_client._upbit, "buy_market_order",
        return_value={"uuid": "buy-uuid-1", "side": "bid"},
    )
    mocker.patch.object(
        auth_client._upbit, "sell_market_order",
        return_value={"uuid": "sell-uuid-1", "side": "ask"},
    )
    mocker.patch.object(
        auth_client._upbit, "get_order",
        return_value={"state": "wait"},
    )
    ex, captured = _make_executor_with_cb(auth_client, store, live=True)
    ex._fill_poll_interval = 0.01
    ex._fill_poll_timeout = 0.01
    ex.execute(
        Decision(Action.BUY, reason="entry", krw_amount=10_000),
        current_price=100.0,
    )
    ex.execute(
        Decision(Action.SELL, reason="exit", volume=100.0, reason_code="signal_sell"),
        current_price=110.0,
    )
    assert len(captured) == 1
    assert captured[0]["mode"] == "live"


# ---------------------------------------------------------------------------
# 3. test_trade_log_fee_reflected
# ---------------------------------------------------------------------------

def test_trade_log_fee_reflected(unauth_client, store):
    """pnl_ratio includes fee (compare with and without fee)."""
    ex, captured = _make_executor_with_cb(unauth_client, store, live=False)
    ex.execute(
        Decision(Action.BUY, reason="entry", krw_amount=10_000),
        current_price=100.0,
    )
    ex.execute(
        Decision(Action.SELL, reason="exit", volume=100.0),
        current_price=110.0,
    )
    assert len(captured) == 1
    data = captured[0]

    # Fee-adjusted PnL should be less than simple return (10%)
    simple_return = (110.0 - 100.0) / 100.0  # 0.10
    assert data["pnl_ratio"] < simple_return

    # Verify the exact fee-adjusted formula
    fee = UPBIT_FEE_RATE
    expected = (110.0 * (1 - fee)) / (100.0 * (1 + fee)) - 1
    assert data["pnl_ratio"] == pytest.approx(expected)

    # fee_krw should be positive
    assert data["fee_krw"] == pytest.approx((10_000.0 + 11_000.0) * fee)


# ---------------------------------------------------------------------------
# 4. test_trade_log_reason_code_preserved
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reason_code", ["stop_loss", "signal_sell", "time_exit"])
def test_trade_log_reason_code_preserved(unauth_client, store, reason_code):
    """stop_loss, signal_sell, time_exit each recorded correctly."""
    ex, captured = _make_executor_with_cb(unauth_client, store, live=False)
    ex.execute(
        Decision(Action.BUY, reason="entry", krw_amount=10_000),
        current_price=100.0,
    )
    ex.execute(
        Decision(Action.SELL, reason=f"reason for {reason_code}", volume=100.0,
                 reason_code=reason_code),
        current_price=110.0,
    )
    assert len(captured) == 1
    assert captured[0]["exit_reason_code"] == reason_code


# ---------------------------------------------------------------------------
# 5. test_trade_log_reason_code_not_dropped_on_volume_fallback
# ---------------------------------------------------------------------------

def test_trade_log_reason_code_not_dropped_on_volume_fallback(mocker, auth_client, store):
    """Volume fallback preserves reason_code."""
    mocker.patch.object(
        auth_client._upbit, "buy_market_order",
        return_value={"uuid": "buy-fb-uuid", "side": "bid"},
    )
    mocker.patch.object(
        auth_client._upbit, "sell_market_order",
        return_value={"uuid": "sell-fb-uuid", "side": "ask"},
    )
    mocker.patch.object(
        auth_client._upbit, "get_order",
        return_value={"state": "wait"},
    )
    ex, captured = _make_executor_with_cb(auth_client, store, live=True)
    ex._fill_poll_interval = 0.01
    ex._fill_poll_timeout = 0.01

    # BUY first
    ex.execute(
        Decision(Action.BUY, reason="entry", krw_amount=10_000),
        current_price=100.0,
    )
    # SELL with volume=0.0 (triggers fallback) and reason_code
    ex.execute(
        Decision(Action.SELL, reason="stop_loss triggered", volume=0.0,
                 reason_code="stop_loss"),
        current_price=90.0,
    )
    assert len(captured) == 1
    assert captured[0]["exit_reason_code"] == "stop_loss"


# ---------------------------------------------------------------------------
# 6. test_trade_log_hold_seconds_correct
# ---------------------------------------------------------------------------

def test_trade_log_hold_seconds_correct(unauth_client, store):
    """Entry/exit time difference matches hold_seconds."""
    ex, captured = _make_executor_with_cb(unauth_client, store, live=False)
    ex.execute(
        Decision(Action.BUY, reason="entry", krw_amount=10_000),
        current_price=100.0,
    )
    ex.execute(
        Decision(Action.SELL, reason="exit", volume=100.0),
        current_price=110.0,
    )
    assert len(captured) == 1
    data = captured[0]
    expected_seconds = max(
        int((data["exit_at"] - data["entry_at"]).total_seconds()), 0
    )
    assert data["hold_seconds"] == expected_seconds


# ---------------------------------------------------------------------------
# 7. test_trade_log_callback_failure_no_block
# ---------------------------------------------------------------------------

def test_trade_log_callback_failure_no_block(unauth_client, store):
    """Callback raises but sell completes normally."""
    def bad_callback(data):
        raise RuntimeError("callback exploded")

    ex = OrderExecutor(
        unauth_client, store, "KRW-BTC",
        live=False,
        strategy_name="vb",
        on_trade_closed=bad_callback,
    )
    ex.execute(
        Decision(Action.BUY, reason="entry", krw_amount=10_000),
        current_price=100.0,
    )
    # This should NOT raise despite the callback failing
    rec = ex.execute(
        Decision(Action.SELL, reason="exit", volume=100.0),
        current_price=110.0,
    )
    assert rec is not None
    assert rec.side == "sell"
    # Position should be closed
    assert store.load().position is None


# ---------------------------------------------------------------------------
# 8. test_trade_log_no_callback_noop
# ---------------------------------------------------------------------------

def test_trade_log_no_callback_noop(unauth_client, store):
    """callback=None means no error, existing behavior preserved."""
    ex = OrderExecutor(
        unauth_client, store, "KRW-BTC",
        live=False,
        # No on_trade_closed, no strategy_name — defaults
    )
    ex.execute(
        Decision(Action.BUY, reason="entry", krw_amount=10_000),
        current_price=100.0,
    )
    rec = ex.execute(
        Decision(Action.SELL, reason="exit", volume=100.0),
        current_price=110.0,
    )
    assert rec is not None
    assert store.load().position is None


# ---------------------------------------------------------------------------
# 9. test_trade_log_exit_reason_text_recorded
# ---------------------------------------------------------------------------

def test_trade_log_exit_reason_text_recorded(unauth_client, store):
    """exit_reason_text field populated with the full reason string."""
    ex, captured = _make_executor_with_cb(unauth_client, store, live=False)
    ex.execute(
        Decision(Action.BUY, reason="entry", krw_amount=10_000),
        current_price=100.0,
    )
    reason_text = "stop_loss triggered (-2.50% <= -2.00%)"
    ex.execute(
        Decision(Action.SELL, reason=reason_text, volume=100.0,
                 reason_code="stop_loss"),
        current_price=97.5,
    )
    assert len(captured) == 1
    assert captured[0]["exit_reason_text"] == reason_text


# ---------------------------------------------------------------------------
# 10. test_daily_snapshot_model
# ---------------------------------------------------------------------------

def test_daily_snapshot_model():
    """DailySnapshot can be created, snapshot_date not unique."""
    from auto_coin.web.models import DailySnapshot

    snap1 = DailySnapshot(
        snapshot_date=date(2026, 4, 16),
        mode="paper",
        strategy_name="volatility_breakout",
        total_pnl_ratio=0.015,
        open_positions=1,
        closed_trades_count=3,
        win_count=2,
        loss_count=1,
        realized_pnl_krw=15000.0,
    )
    snap2 = DailySnapshot(
        snapshot_date=date(2026, 4, 16),  # same date — NOT unique
        mode="paper",
        strategy_name="other_strategy",
        total_pnl_ratio=-0.005,
        open_positions=0,
        closed_trades_count=1,
        win_count=0,
        loss_count=1,
        realized_pnl_krw=-5000.0,
    )
    assert snap1.snapshot_date == snap2.snapshot_date
    assert snap1.strategy_name != snap2.strategy_name
    # Verify field types
    assert isinstance(snap1.snapshot_date, date)
    assert isinstance(snap1.total_pnl_ratio, float)


# ---------------------------------------------------------------------------
# 11. test_trade_log_model
# ---------------------------------------------------------------------------

def test_trade_log_model():
    """TradeLog can be created with all fields."""
    from auto_coin.web.models import TradeLog

    now = datetime(2026, 4, 16, 12, 0, 0)
    log = TradeLog(
        ticker="KRW-BTC",
        strategy_name="volatility_breakout",
        mode="paper",
        entry_at=now,
        exit_at=now,
        entry_price=50_000_000.0,
        exit_price=51_000_000.0,
        quantity=0.001,
        entry_value_krw=50_000.0,
        exit_value_krw=51_000.0,
        fee_krw=50.5,
        pnl_ratio=0.0189,
        pnl_krw=949.5,
        hold_seconds=3600,
        exit_reason_code="signal_sell",
        exit_reason_text="signal=SELL approved",
    )
    assert log.ticker == "KRW-BTC"
    assert log.pnl_ratio == pytest.approx(0.0189)
    assert log.exit_reason_code == "signal_sell"
    assert log.exit_reason_text == "signal=SELL approved"
    assert log.hold_seconds == 3600
