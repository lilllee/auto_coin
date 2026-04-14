"""V2.7 — 실시간 로그 SSE + ring buffer."""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient
from loguru import logger
from sqlmodel import Session

from auto_coin.web import db as web_db
from auto_coin.web.app import create_app
from auto_coin.web.crypto import SecretBox
from auto_coin.web.services import log_stream
from auto_coin.web.user_service import get_user


@pytest.fixture
def app_env(tmp_path, monkeypatch, mocker):
    web_db.reset_engine()
    log_stream.reset_for_test()
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
    log_stream.reset_for_test()


def _login(client: TestClient) -> None:
    client.post("/setup", data={"password": "hunter22", "password_confirm": "hunter22"})
    with Session(web_db.engine()) as db:
        user = get_user(db)
        secret = SecretBox().decrypt(user.totp_secret_enc)
    client.post("/setup/totp", data={"code": pyotp.TOTP(secret).now()})


# ----- log_stream unit ---------------------------------------------------


def test_inject_line_appears_in_buffer():
    log_stream.reset_for_test()
    log_stream.inject_line("INFO", "test", "hello")
    assert log_stream.current_buffer()[-1]["message"] == "hello"


def test_buffer_cap_at_500():
    log_stream.reset_for_test()
    for i in range(600):
        log_stream.inject_line("INFO", "t", f"msg-{i}")
    assert len(log_stream.current_buffer()) == 500
    assert log_stream.current_buffer()[0]["message"] == "msg-100"
    assert log_stream.current_buffer()[-1]["message"] == "msg-599"


def test_install_sink_routes_loguru_messages():
    log_stream.reset_for_test()
    sink_id = log_stream.install_sink(logger)
    try:
        logger.info("V2.7 sink test")
        assert any("V2.7 sink test" in line["message"]
                   for line in log_stream.current_buffer())
    finally:
        logger.remove(sink_id)


def test_format_sse_shape():
    line = {"ts": "2026-04-14T00:00:00+00:00", "level": "INFO",
            "name": "auto_coin.bot", "message": "tick ok"}
    out = log_stream.format_sse(line)
    assert out.startswith("data: ")
    assert out.endswith("\n\n")
    assert "tick ok" in out


# ----- HTTP --------------------------------------------------------------


def test_logs_page_renders(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/logs")
        assert r.status_code == 200
        assert "로그" in r.text
        assert "EventSource" in r.text  # SSE 클라이언트 코드 포함


def test_logs_page_shows_initial_buffer(app_env):
    # 기동 시 lifespan에서 sink 설치 + "starting" 로그가 들어가므로 버퍼에 최소 1건
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/logs")
        assert r.status_code == 200
        # 기동 로그가 포함되어야 함
        assert "starting" in r.text or "bootstrap" in r.text


def test_logs_recent_returns_json(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        log_stream.inject_line("WARNING", "auto_coin.bot", "test warn")
        r = client.get("/logs/recent?limit=5")
        assert r.status_code == 200
        data = r.json()
        assert any(line["message"] == "test warn" for line in data)


def test_logs_recent_clamps_limit(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/logs/recent?limit=99999")
        assert r.status_code == 200
        # BUFFER_SIZE로 clamp
        data = r.json()
        assert len(data) <= log_stream.BUFFER_SIZE


def test_logs_require_auth(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/logs", follow_redirects=False)
        assert r.status_code == 303
        r = client.get("/logs/recent", follow_redirects=False)
        assert r.status_code == 303


# NOTE: SSE stream HTTP test는 TestClient(sync) + 무한 loop 조합이 blocking 유발.
#       스트리밍 자체는 실 브라우저에서 수동 확인. 여기선 unsubscribe/format_sse 등
#       유닛 테스트로 로직을 커버하고, 엔드포인트는 /logs (HTML) · /logs/recent (JSON)
#       두 가지로 충분히 확인됨.


def test_subscribe_and_unsubscribe_tracks_count():
    log_stream.reset_for_test()
    q = log_stream.subscribe()
    assert q in log_stream._subscribers
    log_stream.unsubscribe(q)
    assert q not in log_stream._subscribers
    # 중복 unsubscribe는 raise하지 않음
    log_stream.unsubscribe(q)
