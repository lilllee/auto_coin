from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from auto_coin.runtime_guard import RuntimeGuardError
from auto_coin.web import db as web_db
from auto_coin.web.__main__ import main as web_main
from auto_coin.web.app import create_app


@pytest.fixture
def app_env(tmp_path, monkeypatch, mocker):
    """DB/마스터키를 tmp_path에 격리 + 네트워크 차단."""
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


def test_health_endpoint_running(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["running"] is True
        assert data["mode"] == "paper"
        assert "KRW-BTC" in data["tickers"]


def test_web_main_exits_when_cli_runtime_is_active(mocker):
    mocker.patch(
        "auto_coin.web.__main__.acquire_runtime_guard",
        side_effect=RuntimeGuardError("another auto_coin runtime is already active"),
    )
    run = mocker.patch("auto_coin.web.__main__.uvicorn.run")

    assert web_main([]) == 1
    run.assert_not_called()
