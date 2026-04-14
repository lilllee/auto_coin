"""멀티 종목 포트폴리오 동작 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.bot import TradingBot
from auto_coin.config import Settings
from auto_coin.exchange.upbit_client import UpbitClient
from auto_coin.executor.order import OrderExecutor
from auto_coin.executor.store import OrderStore, Position
from auto_coin.notifier.telegram import TelegramNotifier
from auto_coin.risk.manager import RiskManager
from auto_coin.strategy.volatility_breakout import VolatilityBreakout


def _enriched(*, target: float, ma: float, ma_window: int = 1) -> pd.DataFrame:
    n = 3
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open":   np.full(n, 100.0),
            "high":   np.full(n, 110.0),
            "low":    np.full(n, 90.0),
            "close":  np.full(n, 105.0),
            "volume": np.ones(n),
            "range":  np.full(n, 20.0),
            "target": np.full(n, target),
            f"ma{ma_window}": np.full(n, ma),
        },
        index=idx,
    )


def _bot(tmp_path, *, tickers, max_concurrent=3, paper_krw=1_000_000.0,
         max_pos_ratio=0.20):
    s = Settings(
        _env_file=None,
        ticker="", tickers=",".join(tickers),
        max_concurrent_positions=max_concurrent,
        strategy_k=0.5, ma_filter_window=1,
        max_position_ratio=max_pos_ratio, min_order_krw=5000,
        paper_initial_krw=paper_krw,
    )
    client = UpbitClient(access_key="", secret_key="", max_retries=1, backoff_base=0.0,
                         min_request_interval=0.0)
    stores = {t: OrderStore(tmp_path / f"{t}.json") for t in s.portfolio_ticker_list}
    executors = {t: OrderExecutor(client, stores[t], t, live=False) for t in stores}
    notifier = TelegramNotifier(bot_token="", chat_id="")
    bot = TradingBot(
        settings=s, client=client,
        strategy=VolatilityBreakout(k=s.strategy_k, ma_window=s.ma_filter_window),
        risk_manager=RiskManager(s),
        stores=stores, executors=executors, notifier=notifier,
    )
    return bot, client, stores, s


def test_multi_ticker_all_buy_when_slots_available(tmp_path, mocker):
    bot, client, stores, _ = _bot(tmp_path, tickers=["KRW-BTC", "KRW-ETH", "KRW-XRP"],
                                  max_concurrent=3)
    mocker.patch("auto_coin.bot.fetch_daily",
                 return_value=_enriched(target=110.0, ma=100.0))
    mocker.patch.object(client, "get_current_price", return_value=120.0)
    recs = bot.tick()
    assert len(recs) == 3
    assert {r.market for r in recs} == {"KRW-BTC", "KRW-ETH", "KRW-XRP"}
    for t in ("KRW-BTC", "KRW-ETH", "KRW-XRP"):
        assert stores[t].load().position is not None


def test_slot_cap_blocks_further_entries_in_same_tick(tmp_path, mocker):
    """max_concurrent=2일 때 앞 2개만 매수, 세번째는 HOLD."""
    bot, client, stores, _ = _bot(tmp_path, tickers=["KRW-BTC", "KRW-ETH", "KRW-XRP"],
                                  max_concurrent=2)
    mocker.patch("auto_coin.bot.fetch_daily",
                 return_value=_enriched(target=110.0, ma=100.0))
    mocker.patch.object(client, "get_current_price", return_value=120.0)
    recs = bot.tick()
    assert len(recs) == 2
    # 우선순위는 dict 삽입 순서(= tickers 순서)
    assert [r.market for r in recs] == ["KRW-BTC", "KRW-ETH"]
    assert stores["KRW-XRP"].load().position is None


def test_entry_size_uses_paper_initial_krw_for_every_slot(tmp_path, mocker):
    """각 종목 진입 크기는 `paper_initial_krw × max_position_ratio` 고정."""
    bot, client, stores, _ = _bot(tmp_path, tickers=["KRW-BTC", "KRW-ETH"],
                                  max_concurrent=3,
                                  paper_krw=1_000_000.0, max_pos_ratio=0.20)
    mocker.patch("auto_coin.bot.fetch_daily",
                 return_value=_enriched(target=110.0, ma=100.0))
    mocker.patch.object(client, "get_current_price", return_value=120.0)
    recs = bot.tick()
    for r in recs:
        assert r.krw_amount == pytest.approx(200_000.0)


def test_second_tick_respects_existing_positions_as_slot_count(tmp_path, mocker):
    """이미 2종목 보유 상태에서 max_concurrent=2라면 세번째 진입 차단."""
    bot, client, stores, s = _bot(tmp_path, tickers=["KRW-BTC", "KRW-ETH", "KRW-XRP"],
                                  max_concurrent=2)
    # BTC, ETH 미리 포지션 주입
    for t in ("KRW-BTC", "KRW-ETH"):
        state = stores[t].load()
        state.position = Position(ticker=t, volume=0.001, avg_entry_price=100.0,
                                  entry_uuid="seed", entry_at="2026-04-13T00:00:00+00:00")
        stores[t].save(state)
    mocker.patch("auto_coin.bot.fetch_daily",
                 return_value=_enriched(target=110.0, ma=100.0))
    mocker.patch.object(client, "get_current_price", return_value=120.0)
    recs = bot.tick()
    # 기존 보유 종목은 이미 포지션 있으니 BUY 차단, XRP는 슬롯 없음 → 0건
    assert recs == []
    assert stores["KRW-XRP"].load().position is None


def test_daily_reset_clears_all_ticker_pnl(tmp_path, mocker):
    bot, _, stores, _ = _bot(tmp_path, tickers=["KRW-BTC", "KRW-ETH"])
    for t, pnl in (("KRW-BTC", -0.02), ("KRW-ETH", 0.03)):
        st = stores[t].load()
        st.daily_pnl_ratio = pnl
        stores[t].save(st)
    bot.daily_reset()
    for t in ("KRW-BTC", "KRW-ETH"):
        assert stores[t].load().daily_pnl_ratio == 0.0


def test_force_exit_closes_all_holdings(tmp_path, mocker):
    bot, client, stores, _ = _bot(tmp_path, tickers=["KRW-BTC", "KRW-ETH", "KRW-XRP"])
    # BTC와 XRP만 보유, ETH는 미보유
    for t in ("KRW-BTC", "KRW-XRP"):
        st = stores[t].load()
        st.position = Position(ticker=t, volume=0.001, avg_entry_price=100.0,
                               entry_uuid="seed", entry_at="2026-04-13T00:00:00+00:00")
        stores[t].save(st)
    mocker.patch.object(client, "get_current_price", return_value=150.0)
    recs = bot.force_exit_if_holding()
    assert {r.market for r in recs} == {"KRW-BTC", "KRW-XRP"}
    for t in ("KRW-BTC", "KRW-XRP"):
        assert stores[t].load().position is None


def test_heartbeat_reports_portfolio_summary(tmp_path, mocker):
    bot, _, stores, _ = _bot(tmp_path, tickers=["KRW-BTC", "KRW-ETH"], max_concurrent=2)
    st = stores["KRW-BTC"].load()
    st.position = Position(ticker="KRW-BTC", volume=0.001, avg_entry_price=50_000_000.0,
                          entry_uuid="u", entry_at="2026-04-13T00:00:00+00:00")
    st.daily_pnl_ratio = 0.01
    stores["KRW-BTC"].save(st)
    send = mocker.patch.object(bot._notifier, "send", return_value=False)
    bot.heartbeat()
    msg = send.call_args.args[0]
    assert "positions 1/2" in msg
    assert "KRW-BTC" in msg
    assert "KRW-ETH" not in msg  # flat 종목은 생략


def test_daily_loss_limit_uses_portfolio_total(tmp_path, mocker):
    """개별 종목은 괜찮지만 합계 손실이 한도면 BUY 차단."""
    bot, client, stores, s = _bot(tmp_path, tickers=["KRW-BTC", "KRW-ETH", "KRW-XRP"],
                                  max_concurrent=3)
    # BTC -0.02, ETH -0.02 → 합계 -0.04 (한도 -0.03 초과)
    for t, pnl in (("KRW-BTC", -0.02), ("KRW-ETH", -0.02)):
        st = stores[t].load()
        st.daily_pnl_ratio = pnl
        stores[t].save(st)
    mocker.patch("auto_coin.bot.fetch_daily",
                 return_value=_enriched(target=110.0, ma=100.0))
    mocker.patch.object(client, "get_current_price", return_value=120.0)
    recs = bot.tick()
    # XRP는 미보유라 진입 시도하지만 daily_loss_limit에 걸림 → 0건
    assert recs == []
    assert stores["KRW-XRP"].load().position is None
