from __future__ import annotations

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session

from auto_coin.web import db as web_db
from auto_coin.web.bot_manager import BotManager
from auto_coin.web.crypto import SecretBox
from auto_coin.web.settings_service import (
    bootstrap_from_env,
    load_runtime_settings,
    save_runtime_settings,
)


@pytest.fixture
def box(tmp_path):
    return SecretBox(key_path=tmp_path / "m.key")


@pytest.fixture
def db(tmp_path, monkeypatch, mocker):
    """테스트용 DB 초기화 + pyupbit/Telegram 네트워크 차단."""
    web_db.reset_engine()
    web_db.init_engine(db_path=tmp_path / "t.db")
    # 부트스트랩에 쓸 가짜 .env (watch/heartbeat을 테스트에서 비활성)
    env = tmp_path / ".env"
    env.write_text(
        "TICKER=KRW-BTC\nTICKERS=\nSTRATEGY_K=0.5\n"
        "WATCH_INTERVAL_MINUTES=1440\nHEARTBEAT_INTERVAL_HOURS=0\n"
        "CHECK_INTERVAL_SECONDS=3600\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    # scheduler 워커가 혹시 tick을 찍으면 네트워크/텔레그램 전부 차단
    mocker.patch("auto_coin.bot.fetch_daily", return_value=None)
    mocker.patch("auto_coin.exchange.upbit_client.pyupbit.get_current_price",
                 return_value=0.0)
    mocker.patch("auto_coin.notifier.telegram.requests.post")
    yield
    web_db.reset_engine()


def test_bot_manager_builds_without_error(db, box):
    with Session(web_db.engine()) as s:
        bootstrap_from_env(s, box)
    mgr = BotManager(box)
    mgr._build_bot()
    assert mgr.bot is not None
    assert mgr.settings is not None
    assert mgr.settings.portfolio_ticker_list == ["KRW-BTC"]


def test_start_and_stop(db, box):
    with Session(web_db.engine()) as s:
        bootstrap_from_env(s, box)
    mgr = BotManager(box)
    # notifier.send를 막아 네트워크 호출 방지
    mgr.start()
    assert mgr.running is True
    assert mgr.started_at is not None
    mgr.stop(notify=False)
    assert mgr.running is False


def test_reload_updates_settings(db, box):
    with Session(web_db.engine()) as s:
        bootstrap_from_env(s, box)
    mgr = BotManager(box)
    mgr.start()
    # 설정 변경 후 reload
    with Session(web_db.engine()) as s:
        from auto_coin.web.settings_service import load_runtime_settings
        current = load_runtime_settings(s, box)
        updated = current.model_copy(update={
            "strategy_k": 0.7,
            "tickers": "KRW-BTC,KRW-ETH",
        })
        save_runtime_settings(s, box, updated)
    mgr.reload()
    assert mgr.settings.strategy_k == 0.7
    assert mgr.settings.portfolio_ticker_list == ["KRW-BTC", "KRW-ETH"]
    assert mgr.running is True
    mgr.stop(notify=False)


def test_reload_when_stopped_stays_stopped(db, box):
    with Session(web_db.engine()) as s:
        bootstrap_from_env(s, box)
    mgr = BotManager(box)
    mgr.reload()
    # 한 번도 start 안 했으면 reload 후에도 멈춰있음
    assert mgr.running is False


def test_register_jobs_disables_force_exit_for_composite(db, box):
    with Session(web_db.engine()) as s:
        bootstrap_from_env(s, box)
        current = load_runtime_settings(s, box)
        updated = current.model_copy(update={"strategy_name": "sma200_ema_adx_composite"})
        save_runtime_settings(s, box, updated)

    mgr = BotManager(box)
    mgr._build_bot()
    mgr._scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    mgr._register_jobs()

    assert mgr._scheduler.get_job("force_exit") is None
    assert mgr._scheduler.get_job("daily_report") is not None


def test_register_jobs_keeps_force_exit_for_volatility_breakout(db, box):
    with Session(web_db.engine()) as s:
        bootstrap_from_env(s, box)

    mgr = BotManager(box)
    mgr._build_bot()
    mgr._scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    mgr._register_jobs()

    assert mgr._scheduler.get_job("force_exit") is not None
