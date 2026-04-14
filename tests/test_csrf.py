"""CSRF 미들웨어 검증 테스트."""

from __future__ import annotations

import pyotp
import pytest
from csrf_helpers import csrf_data, csrf_headers, extract_csrf_token
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
        "TICKER=KRW-BTC\nWATCH_INTERVAL_MINUTES=1440\n"
        "HEARTBEAT_INTERVAL_HOURS=0\nCHECK_INTERVAL_SECONDS=3600\n",
        encoding="utf-8",
    )
    mocker.patch("auto_coin.bot.fetch_daily", return_value=None)
    mocker.patch("auto_coin.exchange.upbit_client.pyupbit.get_current_price",
                 return_value=0.0)
    mocker.patch("auto_coin.notifier.telegram.requests.post")
    mocker.patch("auto_coin.web.routers.dashboard._safe_current_price",
                 return_value=None)
    yield tmp_path
    web_db.reset_engine()


def _login(client: TestClient) -> None:
    client.post("/setup", data={"password": "hunter22", "password_confirm": "hunter22"})
    with Session(web_db.engine()) as db:
        user = get_user(db)
        secret = SecretBox().decrypt(user.totp_secret_enc)
    client.post("/setup/totp", data={"code": pyotp.TOTP(secret).now()})


def test_post_without_csrf_token_returns_403(app_env, mocker):
    """인증된 사용자라도 CSRF 토큰 없이 POST하면 403."""
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/control/restart", follow_redirects=False)
        assert r.status_code == 403
        assert "CSRF" in r.json()["detail"]


def test_post_with_valid_csrf_token_succeeds(app_env, mocker):
    """올바른 CSRF 토큰을 포함하면 POST 성공."""
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/control/restart",
                        data=csrf_data(client),
                        follow_redirects=False)
        assert r.status_code == 303


def test_post_with_wrong_csrf_token_returns_403(app_env, mocker):
    """잘못된 CSRF 토큰으로 POST하면 403."""
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/control/restart",
                        data={"_csrf_token": "wrong-token"},
                        follow_redirects=False)
        assert r.status_code == 403


def test_get_request_not_affected(app_env):
    """GET 요청은 CSRF 검증을 거치지 않는다."""
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/")
        assert r.status_code == 200


def test_health_endpoint_exempt(app_env):
    """/health는 CSRF 면제."""
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200


def test_setup_endpoint_exempt(app_env):
    """/setup POST는 CSRF 면제 (초기 설정 흐름)."""
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/setup",
                        data={"password": "hunter22", "password_confirm": "hunter22"},
                        follow_redirects=False)
        # CSRF 없이도 성공 (303 또는 400, 403이 아님)
        assert r.status_code != 403


def test_login_endpoint_exempt(app_env):
    """/login POST는 CSRF 면제."""
    app = create_app()
    with TestClient(app) as client:
        # 먼저 유저 생성
        _login(client)
        # 로그아웃 (exempt path)
        client.post("/logout", data=csrf_data(client))
        # CSRF 토큰 없이 로그인 시도 — 403이 아닌 인증 실패 (401)
        r = client.post("/login",
                        data={"password": "wrong", "code": "000000"},
                        follow_redirects=False)
        assert r.status_code != 403


def test_htmx_header_csrf_works(app_env, mocker):
    """X-CSRF-Token 헤더로 CSRF 토큰 전달."""
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/control/restart",
                        headers=csrf_headers(client),
                        follow_redirects=False)
        assert r.status_code == 303


def test_csrf_meta_tag_present_in_html(app_env):
    """로그인 후 HTML에 CSRF meta 태그가 포함된다."""
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/")
        assert 'name="csrf-token"' in r.text
        token = extract_csrf_token(client)
        assert len(token) == 64  # secrets.token_hex(32) = 64 chars
