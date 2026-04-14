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
    # reports 디렉토리 준비
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "2026-04-14-paper-day1.md").write_text(
        "# 페이퍼 Day 1\n\n- 총 수익 +7%\n\n## 타임라인\n\n| 시각 | 이벤트 |\n|---|---|\n| 09:00 | 리셋 |\n",
        encoding="utf-8",
    )
    (reports / "2026-04-15-paper-day2.md").write_text(
        "# Day 2\n\n추가 관찰\n",
        encoding="utf-8",
    )
    yield tmp_path
    web_db.reset_engine()


def _login(client: TestClient) -> None:
    client.post("/setup", data={"password": "hunter22", "password_confirm": "hunter22"})
    with Session(web_db.engine()) as db:
        user = get_user(db)
        secret = SecretBox().decrypt(user.totp_secret_enc)
    client.post("/setup/totp", data={"code": pyotp.TOTP(secret).now()})


def test_reports_index_lists_files(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/reports")
        assert r.status_code == 200
        assert "2026-04-14-paper-day1.md" in r.text
        assert "2026-04-15-paper-day2.md" in r.text
        # 정렬: 최신이 먼저
        i15 = r.text.index("2026-04-15")
        i14 = r.text.index("2026-04-14")
        assert i15 < i14


def test_reports_index_shows_first_heading_as_title(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/reports")
        assert "페이퍼 Day 1" in r.text
        assert "Day 2" in r.text


def test_reports_detail_renders_markdown_to_html(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/reports/2026-04-14-paper-day1.md")
        assert r.status_code == 200
        assert "<h1>페이퍼 Day 1</h1>" in r.text
        # 테이블 렌더링
        assert "<table>" in r.text
        assert "<th>시각</th>" in r.text


def test_reports_detail_404_for_missing_file(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/reports/nope.md")
        assert r.status_code == 404


def test_reports_detail_rejects_traversal(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        # TestClient가 path normalize하므로 직접 URL로 시도해도 서버 도달 전 정리됨 —
        # 문자열 기반 공격은 이름 검증에서 잡힌다
        r = client.get("/reports/..%2F..%2Fetc%2Fpasswd.md")
        assert r.status_code in (400, 404)


def test_reports_detail_rejects_non_md_extension(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/reports/hidden.txt")
        assert r.status_code == 400


def test_reports_index_empty_directory(tmp_path, monkeypatch, mocker):
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
    try:
        app = create_app()
        with TestClient(app) as client:
            _login(client)
            r = client.get("/reports")
            assert r.status_code == 200
            assert "아직 리포트가 없습니다" in r.text
    finally:
        web_db.reset_engine()


def test_reports_require_auth(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/reports", follow_redirects=False)
        assert r.status_code == 303
        r = client.get("/reports/2026-04-14-paper-day1.md", follow_redirects=False)
        assert r.status_code == 303
