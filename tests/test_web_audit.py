from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from auto_coin.web import audit
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
        "TICKER=KRW-BTC\nWATCH_INTERVAL_MINUTES=1440\n"
        "HEARTBEAT_INTERVAL_HOURS=0\nCHECK_INTERVAL_SECONDS=3600\n",
        encoding="utf-8",
    )
    mocker.patch("auto_coin.bot.fetch_daily", return_value=None)
    mocker.patch("auto_coin.exchange.upbit_client.pyupbit.get_current_price", return_value=0.0)
    mocker.patch("auto_coin.notifier.telegram.requests.post")
    yield tmp_path
    web_db.reset_engine()


def _login(client: TestClient) -> None:
    client.post("/setup", data={"password": "hunter22", "password_confirm": "hunter22"})
    with Session(web_db.engine()) as db:
        user = get_user(db)
        secret = SecretBox().decrypt(user.totp_secret_enc)
    client.post("/setup/totp", data={"code": pyotp.TOTP(secret).now()})


def test_audit_page_requires_auth(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/settings/audit", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] in {"/setup", "/login"}


def test_audit_page_renders_empty_state(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/settings/audit")
        assert r.status_code == 200
        assert "표시할 감사 로그가 없습니다." in r.text


def test_audit_page_renders_newest_first_and_masks_values(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        with Session(web_db.engine()) as db:
            audit.record(
                db,
                "settings.api_keys",
                before={"upbit_access_key": "OLDSECRET9999"},
                after={"upbit_access_key": "SUPERSECRETKEY9999"},
            )
            audit.record(
                db,
                "control.restart",
                before={},
                after={"running": True},
            )

        r = client.get("/settings/audit")
        assert r.status_code == 200
        assert "봇 재시작" in r.text
        assert "API 키 저장" in r.text
        assert r.text.index("봇 재시작") < r.text.index("API 키 저장")
        assert "SUPERSECRETKEY9999" not in r.text
        assert "9999" in r.text


def test_audit_page_filters_by_action_prefix(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        with Session(web_db.engine()) as db:
            audit.record(db, "control.restart", before={}, after={})
            audit.record(db, "settings.strategy", before={"strategy_k": 0.5}, after={"strategy_k": 0.6})

        r = client.get("/settings/audit?action_prefix=control.")
        assert r.status_code == 200
        assert "봇 재시작" in r.text
        assert "전략 설정 저장" not in r.text
