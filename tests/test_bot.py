from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from auto_coin.bot import TradingBot
from auto_coin.config import Settings
from auto_coin.data.candles import recommended_history_days
from auto_coin.exchange.upbit_client import UpbitClient, UpbitError
from auto_coin.executor.order import OrderExecutor
from auto_coin.executor.store import OrderStore, Position
from auto_coin.main import main
from auto_coin.notifier.telegram import TelegramNotifier
from auto_coin.risk.manager import RiskManager
from auto_coin.runtime_guard import RuntimeGuardError
from auto_coin.strategy import STRATEGY_ENTRY_CONFIRMATION, create_strategy
from auto_coin.strategy.base import Signal
from auto_coin.strategy.volatility_breakout import VolatilityBreakout


def _settings(**overrides) -> Settings:
    base = {
        "ticker": "KRW-BTC",
        "strategy_k": 0.5,
        "ma_filter_window": 1,
        "max_position_ratio": 0.20,
        "min_order_krw": 5000,
        "paper_initial_krw": 1_000_000.0,
        "max_concurrent_positions": 1,  # 단일 종목 테스트의 슬롯
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _enriched_df(target_reachable: bool, ma_window: int = 1) -> pd.DataFrame:
    n = 5
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {
            "open":   np.full(n, 100.0),
            "high":   np.full(n, 110.0),
            "low":    np.full(n, 90.0),
            "close":  np.full(n, 105.0),
            "volume": np.ones(n),
            "range":  np.full(n, 20.0),
            "target": np.full(n, 110.0 if target_reachable else 200.0),
            f"ma{ma_window}": np.full(n, 100.0),
        },
        index=idx,
    )
    return df


@pytest.fixture
def store(tmp_path):
    return OrderStore(tmp_path / "KRW-BTC.json")


def _make_bot(store, settings, mocker, *, fetch_df=None, current_price=120.0):
    client = UpbitClient(access_key="", secret_key="", max_retries=1, backoff_base=0.0,
                        min_request_interval=0.0)
    if fetch_df is not None:
        mocker.patch("auto_coin.data.candle_cache.fetch_daily", return_value=fetch_df)
    ticker = settings.ticker
    mocker.patch.object(client, "get_current_price", return_value=current_price)
    mocker.patch.object(client, "get_current_prices", return_value={ticker: current_price})
    notifier = TelegramNotifier(bot_token="", chat_id="")
    executor = OrderExecutor(client, store, ticker, live=False)
    bot = TradingBot(
        settings=settings, client=client,
        strategy=VolatilityBreakout(k=settings.strategy_k, ma_window=settings.ma_filter_window),
        risk_manager=RiskManager(settings),
        stores={ticker: store}, executors={ticker: executor},
        notifier=notifier,
    )
    return bot, client


def test_tick_buys_when_strategy_signals_and_risk_approves(store, mocker):
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    recs = bot.tick()
    assert len(recs) == 1
    assert recs[0].side == "buy"
    state = store.load()
    assert state.position is not None
    assert state.position.avg_entry_price == 120.0


def test_tick_holds_when_no_breakout(store, mocker):
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(False), current_price=120.0)
    assert bot.tick() == []
    assert store.load().position is None


def test_tick_swallows_market_data_error(store, mocker):
    s = _settings()
    client = UpbitClient(access_key="", secret_key="", max_retries=1, backoff_base=0.0,
                        min_request_interval=0.0)
    mocker.patch("auto_coin.data.candle_cache.fetch_daily", side_effect=UpbitError("network"))
    notifier = TelegramNotifier(bot_token="", chat_id="")
    executor = OrderExecutor(client, store, s.ticker, live=False)
    bot = TradingBot(
        settings=s, client=client,
        strategy=VolatilityBreakout(k=s.strategy_k, ma_window=s.ma_filter_window),
        risk_manager=RiskManager(s),
        stores={s.ticker: store}, executors={s.ticker: executor},
        notifier=notifier,
    )
    assert bot.tick() == []


def test_tick_uses_paper_balance_when_unauth(store, mocker):
    s = _settings(paper_initial_krw=100_000.0, max_position_ratio=0.20)
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    recs = bot.tick()
    assert recs[0].krw_amount == pytest.approx(20_000.0)


def test_tick_rejected_when_paper_balance_below_min(store, mocker):
    s = _settings(paper_initial_krw=10_000.0, max_position_ratio=0.20, min_order_krw=5000)
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    assert bot.tick() == []


def test_daily_reset_clears_pnl(store, mocker):
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(False), current_price=100.0)
    state = store.load()
    state.daily_pnl_ratio = -0.025
    store.save(state)
    bot.daily_reset()
    assert store.load().daily_pnl_ratio == 0.0


def test_force_exit_noop_when_flat(store, mocker):
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(False), current_price=100.0)
    assert bot.force_exit_if_holding() == []


def test_force_exit_sells_when_holding(store, mocker):
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    bot.tick()
    assert store.load().position is not None
    recs = bot.force_exit_if_holding()
    assert len(recs) == 1
    assert recs[0].side == "sell"
    assert store.load().position is None


def test_stop_loss_overrides_signal_in_tick(store, mocker):
    s = _settings(stop_loss_ratio=-0.02)
    bot, client = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    bot.tick()
    assert store.load().position is not None
    mocker.patch.object(client, "get_current_price", return_value=116.0)
    mocker.patch.object(client, "get_current_prices", return_value={s.ticker: 116.0})
    recs = bot.tick()
    assert len(recs) == 1
    assert recs[0].side == "sell"
    assert store.load().position is None


def test_heartbeat_sends_status(store, mocker):
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(False), current_price=100.0)
    send = mocker.patch.object(bot._notifier, "send", return_value=False)
    bot.heartbeat()
    send.assert_called_once()
    sent = send.call_args.args[0]
    assert "heartbeat" in sent
    assert "positions 0/1" in sent


def test_tick_unexpected_exception_alerts(store, mocker):
    s = _settings()
    client = UpbitClient(access_key="", secret_key="", max_retries=1, backoff_base=0.0,
                        min_request_interval=0.0)
    # _tick_impl 자체가 터지도록 내부에 mock 주입
    mocker.patch.object(TradingBot, "_tick_impl", side_effect=RuntimeError("boom"))
    notifier = TelegramNotifier(bot_token="", chat_id="")
    send = mocker.patch.object(notifier, "send", return_value=False)
    executor = OrderExecutor(client, store, s.ticker, live=False)
    bot = TradingBot(
        settings=s, client=client,
        strategy=VolatilityBreakout(k=s.strategy_k, ma_window=s.ma_filter_window),
        risk_manager=RiskManager(s),
        stores={s.ticker: store}, executors={s.ticker: executor},
        notifier=notifier,
    )
    assert bot.tick() == []
    assert any("crashed" in (c.args[0] if c.args else "") for c in send.call_args_list)


def test_daily_report_returns_text_and_sends(store, mocker):
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(False), current_price=100.0)
    send = mocker.patch.object(bot._notifier, "send", return_value=False)
    text = bot.daily_report()
    assert "Portfolio" in text or "no activity" in text
    send.assert_called_once()


def test_cooldown_blocks_reentry_after_exit(store, mocker):
    """강제 청산 후 쿨다운 기간 내에 재진입이 차단된다."""
    s = _settings(cooldown_minutes=30)
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    # 1) 매수
    recs = bot.tick()
    assert len(recs) == 1
    assert recs[0].side == "buy"
    # 2) 강제 청산 — last_exit_at이 기록됨
    exit_recs = bot.force_exit_if_holding()
    assert len(exit_recs) == 1
    assert exit_recs[0].side == "sell"
    state = store.load()
    assert state.last_exit_at != ""
    # 3) 즉시 다음 tick — 쿨다운으로 차단되어야 함
    recs2 = bot.tick()
    assert recs2 == []
    assert store.load().position is None


def test_daily_reset_clears_cooldown(store, mocker):
    """daily_reset이 last_exit_at을 초기화하여 쿨다운을 해제한다."""
    s = _settings(cooldown_minutes=30)
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    # 매수 후 강제 청산
    bot.tick()
    bot.force_exit_if_holding()
    assert store.load().last_exit_at != ""
    # daily_reset 실행
    bot.daily_reset()
    assert store.load().last_exit_at == ""
    # 리셋 후 재진입 가능
    recs = bot.tick()
    assert len(recs) == 1
    assert recs[0].side == "buy"


def test_cooldown_zero_disabled(store, mocker):
    """cooldown_minutes=0이면 쿨다운이 비활성이므로 즉시 재진입 가능."""
    s = _settings(cooldown_minutes=0)
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    bot.tick()
    bot.force_exit_if_holding()
    assert store.load().last_exit_at != ""
    # 쿨다운 비활성이므로 즉시 재진입
    recs = bot.tick()
    assert len(recs) == 1
    assert recs[0].side == "buy"


def test_tick_uses_position_from_store(store, mocker):
    """포지션이 이미 있으면 BUY 차단 (이중 진입 방지)."""
    s = _settings()
    state = store.load()
    state.position = Position(
        ticker="KRW-BTC", volume=0.001, avg_entry_price=120.0,
        entry_uuid="prev-uuid", entry_at="2026-04-13T00:00:00+00:00",
    )
    store.save(state)
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    assert bot.tick() == []


def test_extra_candle_count_uses_shared_recommended_history_days(tmp_path):
    settings = _settings(
        ticker="KRW-BTC",
        strategy_name="sma200_ema_adx_composite",
        strategy_params_json=json.dumps(
            {
                "sma_window": 200,
                "ema_fast_window": 27,
                "ema_slow_window": 125,
                "adx_window": 90,
                "adx_threshold": 14.0,
            }
        ),
    )
    store = OrderStore(tmp_path / "KRW-BTC.json")
    client = UpbitClient(access_key="", secret_key="", max_retries=1, backoff_base=0.0,
                         min_request_interval=0.0)
    notifier = TelegramNotifier(bot_token="", chat_id="")
    executor = OrderExecutor(client, store, settings.ticker, live=False)
    params = json.loads(settings.strategy_params_json)
    bot = TradingBot(
        settings=settings,
        client=client,
        strategy=create_strategy(settings.strategy_name, params),
        risk_manager=RiskManager(settings),
        stores={settings.ticker: store},
        executors={settings.ticker: executor},
        notifier=notifier,
    )

    assert bot._extra_candle_count() == recommended_history_days(
        settings.strategy_name,
        params,
        ma_window=settings.ma_filter_window,
    )


def test_main_exits_when_other_runtime_is_active(mocker):
    mocker.patch("auto_coin.main.load_settings", return_value=_settings())
    mocker.patch(
        "auto_coin.main.acquire_runtime_guard",
        side_effect=RuntimeGuardError("another auto_coin runtime is already active"),
    )

    assert main([]) == 1


def test_tick_uses_batch_price_fetch(store, mocker):
    """tick이 get_current_prices로 한 번에 현재가를 조회하는지 확인."""
    s = _settings()
    bot, client = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    spy = mocker.spy(client, "get_current_prices")
    bot.tick()
    spy.assert_called_once_with([s.ticker])


# ──────────────────────────────────────────────
# 진입 확인 메커니즘 (entry confirmation) 테스트
# ──────────────────────────────────────────────

def test_entry_confirmation_zero_immediate_buy(store, mocker):
    """confirmation=0 (VB)이면 첫 BUY 신호에 즉시 진입해야 한다."""
    assert STRATEGY_ENTRY_CONFIRMATION["volatility_breakout"] == 0

    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    # VB는 confirmation=0 — 첫 tick에 바로 주문이 나와야 함
    recs = bot.tick()
    assert len(recs) == 1
    assert recs[0].side == "buy"


def test_entry_confirmation_requires_consecutive_buys(store, mocker):
    """confirmation=2이면 2연속 BUY 신호 후에야 실제 진입해야 한다."""
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    bot._entry_confirmation_ticks = 2

    # tick 1: BUY 신호 → pending (1/2), 주문 없음
    recs1 = bot.tick()
    assert recs1 == []
    assert store.load().position is None

    # tick 2: BUY 신호 → confirmed (2/2), 주문 발생
    recs2 = bot.tick()
    assert len(recs2) == 1
    assert recs2[0].side == "buy"
    assert store.load().position is not None


def test_entry_confirmation_resets_on_non_buy(store, mocker):
    """BUY → HOLD → BUY 패턴이면 pending이 리셋되어야 한다."""
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    bot._entry_confirmation_ticks = 2

    # tick 1: BUY → pending=1
    recs1 = bot.tick()
    assert recs1 == []
    assert bot._pending_buys.get(s.ticker, 0) == 1

    # tick 2: HOLD 신호 → pending 리셋
    # VolatilityBreakout은 frozen dataclass이므로 클래스 레벨로 패치
    mocker.patch.object(VolatilityBreakout, "generate_signal", return_value=Signal.HOLD)
    recs2 = bot.tick()
    assert recs2 == []
    assert bot._pending_buys.get(s.ticker, 0) == 0

    # tick 3: BUY 신호 복귀 → pending=1 (리셋 후 재시작), 주문 없음
    mocker.patch.object(VolatilityBreakout, "generate_signal", return_value=Signal.BUY)
    recs3 = bot.tick()
    assert recs3 == []
    assert bot._pending_buys.get(s.ticker, 0) == 1


def test_entry_confirmation_does_not_affect_stop_loss(store, mocker):
    """confirmation이 있어도 손절은 즉시 실행되어야 한다."""
    s = _settings(stop_loss_ratio=-0.02)
    bot, client = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)

    # 먼저 포지션 진입 (confirmation=0인 상태에서)
    recs = bot.tick()
    assert len(recs) == 1 and recs[0].side == "buy"
    assert store.load().position is not None

    # 이제 confirmation=2 설정 — 손절에는 영향 없어야 함
    bot._entry_confirmation_ticks = 2

    # 현재가가 손절선 아래 (진입가 120 × (1 - 0.02) = 117.6)
    mocker.patch.object(client, "get_current_price", return_value=116.0)
    mocker.patch.object(client, "get_current_prices", return_value={s.ticker: 116.0})
    recs2 = bot.tick()
    assert len(recs2) == 1
    assert recs2[0].side == "sell"
    assert store.load().position is None


def test_daily_reset_clears_pending_buys(store, mocker):
    """daily_reset 호출 시 pending BUY 상태가 초기화되어야 한다."""
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(False), current_price=100.0)
    bot._entry_confirmation_ticks = 2

    # pending 상태를 수동으로 세팅
    bot._pending_buys[s.ticker] = 1
    assert bot._pending_buys.get(s.ticker, 0) == 1

    bot.daily_reset()

    assert bot._pending_buys == {}


# ──────────────────────────────────────────────
# 실행 모드 (execution mode) 테스트
# ──────────────────────────────────────────────

def test_intraday_mode_allows_buy_any_time(store, mocker):
    """intraday 모드(VB)에서는 시간에 관계없이 BUY가 가능해야 한다."""
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)

    # VB는 기본이 intraday
    assert bot._execution_mode == "intraday"

    # 15:00 KST (entry window 밖) 로 mock해도 BUY 발생해야 함
    mocker.patch.object(bot, "_current_trading_day", return_value="2026-04-16")

    recs = bot.tick()
    assert len(recs) == 1
    assert recs[0].side == "buy"


def test_daily_confirm_first_tick_allows_buy(store, mocker):
    """daily_confirm 모드에서 거래일 첫 tick은 BUY 평가가 가능해야 한다."""
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    bot._execution_mode = "daily_confirm"
    bot._entry_confirmation_ticks = 0  # daily_confirm이 debounce 대체

    mocker.patch.object(bot, "_current_trading_day", return_value="2026-04-16")

    # 첫 tick — _entry_evaluated 비어 있으므로 BUY 평가 허용
    recs = bot.tick()
    assert len(recs) == 1
    assert recs[0].side == "buy"


def test_daily_confirm_second_tick_skips_buy(store, mocker):
    """daily_confirm 모드에서 같은 거래일 두 번째 tick은 BUY 평가를 skip해야 한다."""
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    bot._execution_mode = "daily_confirm"
    bot._entry_confirmation_ticks = 0

    mocker.patch.object(bot, "_current_trading_day", return_value="2026-04-16")

    # tick 1 — 평가 완료 (BUY 또는 HOLD, 여기선 BUY)
    bot.tick()
    # 결과 상관없이 _entry_evaluated에 오늘 날짜가 기록돼야 함
    assert bot._entry_evaluated.get(s.ticker) == "2026-04-16"

    # tick 2 — 같은 거래일, 미보유 상태면 skip
    # 보유 중이면 skip 대상이 아니므로, 포지션 없는 시나리오를 위해 강제 청산
    if store.load().position is not None:
        bot.force_exit_if_holding()

    recs2 = bot.tick()
    assert recs2 == []
    assert store.load().position is None


def test_daily_confirm_holding_still_checks_stop_loss(store, mocker):
    """daily_confirm이어도 보유 중이면 매 tick 손절 체크해야 한다."""
    s = _settings(stop_loss_ratio=-0.02)
    bot, client = _make_bot(store, s, mocker, fetch_df=_enriched_df(True), current_price=120.0)
    bot._execution_mode = "daily_confirm"
    bot._entry_confirmation_ticks = 0

    mocker.patch.object(bot, "_current_trading_day", return_value="2026-04-16")

    # 포지션 진입 (첫 tick)
    recs = bot.tick()
    assert len(recs) == 1 and recs[0].side == "buy"
    assert store.load().position is not None

    # 오늘 이미 평가 완료로 표시 (두 번째 tick은 원래 skip 대상이지만, 보유 중이면 제외)
    assert bot._entry_evaluated.get(s.ticker) == "2026-04-16"

    # 현재가가 손절선 아래 (진입가 120 × (1 - 0.02) = 117.6)
    mocker.patch.object(client, "get_current_price", return_value=116.0)
    mocker.patch.object(client, "get_current_prices", return_value={s.ticker: 116.0})

    # tick 2 — 보유 중(coin_balance > 0)이므로 daily_confirm gate를 통과해 손절 실행
    recs2 = bot.tick()
    assert len(recs2) == 1
    assert recs2[0].side == "sell"
    assert store.load().position is None


def test_daily_reset_clears_entry_evaluated(store, mocker):
    """daily_reset 호출 시 _entry_evaluated가 초기화되어야 한다."""
    s = _settings()
    bot, _ = _make_bot(store, s, mocker, fetch_df=_enriched_df(False), current_price=100.0)

    # 수동으로 평가 완료 상태 세팅
    bot._entry_evaluated = {"KRW-BTC": "2026-04-16"}
    assert bot._entry_evaluated == {"KRW-BTC": "2026-04-16"}

    bot.daily_reset()

    assert bot._entry_evaluated == {}
