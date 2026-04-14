from __future__ import annotations

import numpy as np
import pandas as pd
import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from auto_coin.web import db as web_db
from auto_coin.web.app import create_app
from auto_coin.web.crypto import SecretBox
from auto_coin.web.user_service import get_user


def _enriched_df(n: int = 20, ma_window: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2026-03-01", periods=n, freq="D")
    df = pd.DataFrame({
        "open":   np.linspace(100, 120, n),
        "high":   np.linspace(110, 130, n),
        "low":    np.linspace(90, 110, n),
        "close":  np.linspace(105, 125, n),
        "volume": np.ones(n),
        "range":  np.full(n, 20.0),
        "target": np.linspace(115, 135, n),
        f"ma{ma_window}": np.linspace(100, 120, n),
    }, index=idx)
    return df


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
    # bot의 watch 등이 네트워크 치지 않도록
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


def test_charts_page_renders_with_selector(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/charts")
        assert r.status_code == 200
        assert "차트" in r.text
        assert "KRW-BTC" in r.text
        assert "KRW-ETH" in r.text


def test_charts_page_ticker_query_selects(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/charts?ticker=KRW-ETH")
        assert r.status_code == 200
        # 선택된 ticker는 JS에 embed
        assert '"KRW-ETH"' in r.text


def test_charts_data_returns_json(app_env, mocker):
    mocker.patch("auto_coin.web.routers.charts.fetch_daily",
                 return_value=_enriched_df(n=15, ma_window=5))
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/charts/data/KRW-BTC?days=10")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "KRW-BTC"
        assert data["ma_window"] == 5
        assert len(data["labels"]) == 10
        assert len(data["close"]) == 10
        assert len(data["target"]) == 10
        assert len(data["ma"]) == 10


def test_charts_data_includes_position_entry_when_holding(app_env, mocker):
    from auto_coin.executor.store import OrderStore, Position
    mocker.patch("auto_coin.web.routers.charts.fetch_daily",
                 return_value=_enriched_df(n=15, ma_window=5))
    # 포지션 시드
    state_dir = app_env / "state"
    store = OrderStore(state_dir / "KRW-BTC.json")
    state = store.load()
    state.position = Position(
        ticker="KRW-BTC", volume=0.5, avg_entry_price=110.0,
        entry_uuid="u", entry_at="2026-03-10T00:00:00",
    )
    store.save(state)
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/charts/data/KRW-BTC")
        data = r.json()
        assert data["has_position"] is True
        assert data["entry_price"] == 110.0


def test_charts_data_propagates_upbit_error(app_env, mocker):
    from auto_coin.exchange.upbit_client import UpbitError
    mocker.patch("auto_coin.web.routers.charts.fetch_daily",
                 side_effect=UpbitError("timeout"))
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/charts/data/KRW-BTC")
        assert r.status_code == 502
        assert "timeout" in r.text


def test_charts_require_auth(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/charts", follow_redirects=False)
        assert r.status_code == 303


def test_charts_data_nan_values_become_none(app_env, mocker):
    df = _enriched_df(n=10, ma_window=5)
    df.iloc[0, df.columns.get_loc("ma5")] = np.nan
    mocker.patch("auto_coin.web.routers.charts.fetch_daily", return_value=df)
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/charts/data/KRW-BTC?days=10")
        assert r.status_code == 200
        data = r.json()
        # NaN은 JSON null로 변환
        assert data["ma"][0] is None
