from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from auto_coin.exchange.upbit_client import UpbitError
from auto_coin.review.simulator import ReviewValidationError
from auto_coin.web import db as web_db
from auto_coin.web.app import create_app
from auto_coin.web.crypto import SecretBox
from auto_coin.web.user_service import get_user


class _FakeReviewResult:
    def to_dict(self):
        return {
            "ticker": "KRW-BTC",
            "strategy": {"name": "volatility_breakout", "params": {"k": 0.5}},
            "range": {"start_date": "2026-04-01", "end_date": "2026-04-03", "days": 3},
            "summary": {"buy_count": 1, "sell_count": 0, "event_count": 1},
            "rows": [{"date": "2026-04-01", "signal": "hold"}],
            "events": [{"date": "2026-04-02", "signal": "buy"}],
        }


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


def test_review_page_renders(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/review")
        assert r.status_code == 200
        assert "전략 검토" in r.text
        assert "KRW-BTC" in r.text
        assert "KRW-ETH" in r.text
        assert 'id="review-form"' in r.text
        assert 'id="review-run-button"' in r.text
        assert 'id="review-chart-container"' in r.text
        assert 'id="review-summary"' in r.text
        assert 'id="review-events"' in r.text
        assert 'id="review-error"' in r.text
        assert "Chart.js" in r.text or "review-chart" in r.text


def test_review_data_requires_auth(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.get(
            "/review/data/KRW-BTC?start_date=2026-04-01&end_date=2026-04-03",
            follow_redirects=False,
        )
        assert r.status_code == 303


def test_review_data_returns_json(app_env, mocker):
    run = mocker.patch("auto_coin.web.routers.review.run_review_simulation", return_value=_FakeReviewResult())
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get(
            "/review/data/KRW-BTC?start_date=2026-04-01&end_date=2026-04-03",
            headers={"accept": "application/json"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "KRW-BTC"
        assert data["summary"]["buy_count"] == 1
        assert data["rows"][0]["signal"] == "hold"
        run.assert_called_once()


def test_review_data_rejects_invalid_ticker(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get(
            "/review/data/KRW-FAKE?start_date=2026-04-01&end_date=2026-04-03",
            headers={"accept": "application/json"},
        )
        assert r.status_code == 400
        assert "unsupported ticker" in r.text


def test_review_data_rejects_invalid_range(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get(
            "/review/data/KRW-BTC?start_date=2026-04-05&end_date=2026-04-01",
            headers={"accept": "application/json"},
        )
        assert r.status_code == 400
        assert "end_date must be >=" in r.text


def test_review_data_rejects_range_over_90_days(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get(
            "/review/data/KRW-BTC?start_date=2026-01-01&end_date=2026-04-15",
            headers={"accept": "application/json"},
        )
        assert r.status_code == 400
        assert "review range must be <= 90 days" in r.text


def test_review_data_maps_no_data_to_404(app_env, mocker):
    mocker.patch(
        "auto_coin.web.routers.review.run_review_simulation",
        side_effect=ReviewValidationError("no candles available for selected range"),
    )
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get(
            "/review/data/KRW-BTC?start_date=2026-04-01&end_date=2026-04-03",
            headers={"accept": "application/json"},
        )
        assert r.status_code == 404


def test_review_data_maps_upbit_error_to_502(app_env, mocker):
    mocker.patch(
        "auto_coin.web.routers.review.run_review_simulation",
        side_effect=UpbitError("timeout"),
    )
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get(
            "/review/data/KRW-BTC?start_date=2026-04-01&end_date=2026-04-03",
            headers={"accept": "application/json"},
        )
        assert r.status_code == 502
        assert "업비트 시세 조회 실패" in r.text


def test_review_data_maps_internal_error_to_500(app_env, mocker):
    mocker.patch(
        "auto_coin.web.routers.review.run_review_simulation",
        side_effect=RuntimeError("boom"),
    )
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get(
            "/review/data/KRW-BTC?start_date=2026-04-01&end_date=2026-04-03",
            headers={"accept": "application/json"},
        )
        assert r.status_code == 500
        assert "review simulation failed" in r.text
