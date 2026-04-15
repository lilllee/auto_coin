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


def test_compare_page_renders(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/compare")
        assert r.status_code == 200
        assert "전략 비교" in r.text
        assert 'id="compare-form"' in r.text


def test_compare_requires_auth(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/compare", follow_redirects=False)
        assert r.status_code == 303


def test_compare_data_requires_auth(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/compare/data?ticker=KRW-BTC&start_date=2026-04-01&end_date=2026-04-05", follow_redirects=False)
        assert r.status_code == 303


def test_compare_data_rejects_invalid_ticker(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/compare/data?ticker=KRW-FAKE&start_date=2026-04-01&end_date=2026-04-05")
        assert r.status_code == 400
