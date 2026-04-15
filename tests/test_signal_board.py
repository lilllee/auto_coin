from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from auto_coin.web import db as web_db
from auto_coin.web.app import create_app
from auto_coin.web.crypto import SecretBox
from auto_coin.web.user_service import get_user


@pytest.fixture
def app_env(tmp_path, monkeypatch, mocker):
    web_db.reset_engine()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "TICKER=\nTICKERS=KRW-BTC,KRW-ETH\nMAX_CONCURRENT_POSITIONS=2\n"
        "WATCH_INTERVAL_MINUTES=1440\nHEARTBEAT_INTERVAL_HOURS=0\n"
        "CHECK_INTERVAL_SECONDS=3600\nSTATE_DIR=state\nMA_FILTER_WINDOW=5\n",
        encoding="utf-8",
    )
    mocker.patch("auto_coin.bot.fetch_daily", return_value=None)
    mocker.patch("auto_coin.exchange.upbit_client.pyupbit.get_current_price", return_value=0.0)
    mocker.patch("auto_coin.notifier.telegram.requests.post")
    mocker.patch("auto_coin.web.routers.dashboard._safe_current_price", return_value=None)
    yield tmp_path
    web_db.reset_engine()


def _login(client: TestClient) -> None:
    client.post("/setup", data={"password": "hunter22", "password_confirm": "hunter22"})
    with Session(web_db.engine()) as db:
        user = get_user(db)
        secret = SecretBox().decrypt(user.totp_secret_enc)
    client.post("/setup/totp", data={"code": pyotp.TOTP(secret).now()})


def test_signal_board_page_renders(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/signal-board")
        assert r.status_code == 200
        assert "전략 상태판" in r.text
        assert 'id="signal-refresh"' in r.text
        assert 'id="signal-tickers"' in r.text
        assert 'id="signal-regime"' in r.text


def test_signal_board_requires_auth(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/signal-board", follow_redirects=False)
        assert r.status_code == 303


def test_signal_board_data_requires_auth(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/signal-board/data", follow_redirects=False)
        assert r.status_code == 303


def test_signal_board_data_returns_json(app_env, mocker):
    from auto_coin.web.services.signal_board import SignalBoardResult, TickerSignalState

    fake_result = SignalBoardResult(
        strategy_name="volatility_breakout",
        strategy_label="변동성 돌파",
        regime="unknown",
        regime_reason="레짐 판단 불가",
        tickers=[
            TickerSignalState(
                ticker="KRW-BTC",
                signal="hold",
                reason="price<target",
                status="waiting",
                status_label="대기",
                has_position=False,
                current_price=50000000.0,
            ),
        ],
        slot_used=0,
        slot_max=2,
        kill_switch=False,
    )
    mocker.patch(
        "auto_coin.web.routers.signal_board.compute_signal_board",
        return_value=fake_result,
    )
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/signal-board/data", headers={"accept": "application/json"})
        assert r.status_code == 200
        data = r.json()
        assert data["strategy_name"] == "volatility_breakout"
        assert len(data["tickers"]) == 1
        assert data["tickers"][0]["ticker"] == "KRW-BTC"
        assert data["tickers"][0]["status"] == "waiting"
        assert data["slot_max"] == 2
        assert data["kill_switch"] is False


def test_signal_board_nav_tab_exists(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/signal-board")
        assert r.status_code == 200
        assert "상태판" in r.text
