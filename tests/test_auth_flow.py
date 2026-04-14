"""end-to-end auth flow via FastAPI TestClient.

셋업 → TOTP 확인 → 보호된 홈 렌더 → 로그아웃 → 로그인 재진입.
"""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from auto_coin.web import db as web_db
from auto_coin.web.app import create_app
from auto_coin.web.session_secret import default_session_secret_path
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
    yield tmp_path
    web_db.reset_engine()


def _totp_code(db):
    """현재 TOTP 코드 계산을 위해 User의 암호화된 secret을 복호화."""
    from auto_coin.web.crypto import SecretBox
    # box는 app.state에서 가져와야 정확 — 테스트 헬퍼는 session_secret와 동일 HOME 하에 SecretBox()를 쓰면 같은 키
    user = get_user(db)
    box = SecretBox()
    secret = box.decrypt(user.totp_secret_enc)
    return pyotp.TOTP(secret).now(), secret


def test_initial_redirect_to_setup(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/setup"


def test_health_is_public(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["running"] is True


def test_full_setup_then_login(app_env):
    app = create_app()
    with TestClient(app) as client:
        # 1) setup_password 페이지
        r = client.get("/setup")
        assert r.status_code == 200
        assert "초기 설정" in r.text

        # 2) password 제출
        r = client.post("/setup",
                        data={"password": "hunter22", "password_confirm": "hunter22"},
                        follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/setup/totp"

        # 3) QR 페이지
        r = client.get("/setup/totp")
        assert r.status_code == 200
        assert "TOTP 등록" in r.text
        assert "data:image/png;base64" in r.text

        # 4) 잘못된 코드 거부
        r = client.post("/setup/totp", data={"code": "000000"}, follow_redirects=False)
        assert r.status_code == 400

        # 5) 올바른 코드 입력 → /로 리다이렉트 + 로그인 상태
        with Session(web_db.engine()) as db:
            code, _secret = _totp_code(db)
        r = client.post("/setup/totp", data={"code": code}, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/"

        # 6) /에 접근 가능 (세션 쿠키) — 대시보드가 렌더됨
        r = client.get("/")
        assert r.status_code == 200
        assert "대시보드" in r.text


def test_login_after_setup_then_logout(app_env):
    app = create_app()
    with TestClient(app) as client:
        # setup 한 번 해두기
        client.post("/setup", data={"password": "hunter22", "password_confirm": "hunter22"})
        with Session(web_db.engine()) as db:
            code, secret = _totp_code(db)
        client.post("/setup/totp", data={"code": code})
        # 로그아웃
        r = client.post("/logout", follow_redirects=False)
        assert r.status_code == 303
        # 홈 접근 → /login 리다이렉트
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"
        # 잘못된 패스워드
        r = client.post("/login",
                        data={"password": "WRONG", "code": pyotp.TOTP(secret).now()})
        assert r.status_code == 401
        # 올바른 로그인
        r = client.post("/login",
                        data={"password": "hunter22", "code": pyotp.TOTP(secret).now()},
                        follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/"


def test_setup_rejects_short_password(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/setup",
                        data={"password": "short", "password_confirm": "short"})
        assert r.status_code == 400


def test_setup_rejects_mismatched_password(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/setup",
                        data={"password": "hunter22", "password_confirm": "different"})
        assert r.status_code == 400


def test_session_persists_across_requests(app_env):
    app = create_app()
    with TestClient(app) as client:
        client.post("/setup", data={"password": "hunter22", "password_confirm": "hunter22"})
        with Session(web_db.engine()) as db:
            code, _ = _totp_code(db)
        client.post("/setup/totp", data={"code": code})
        # 여러 번 /로 접근해도 모두 200
        for _ in range(3):
            assert client.get("/").status_code == 200


def test_session_secret_file_created_with_600(app_env):
    create_app()
    path = default_session_secret_path()
    assert path.exists()
    import os
    import stat
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
