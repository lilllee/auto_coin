"""V2.4 — 대시보드 + 컨트롤 라우터."""

from __future__ import annotations

import pyotp
import pytest
from csrf_helpers import csrf_data
from fastapi.testclient import TestClient
from sqlmodel import Session

from auto_coin.executor.store import OrderRecord, OrderStore, Position
from auto_coin.web import audit
from auto_coin.web import db as web_db
from auto_coin.web.app import create_app
from auto_coin.web.crypto import SecretBox
from auto_coin.web.settings_service import load_runtime_settings
from auto_coin.web.user_service import get_user


@pytest.fixture
def app_env(tmp_path, monkeypatch, mocker):
    web_db.reset_engine()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "TICKER=\nTICKERS=KRW-BTC,KRW-ETH\nMAX_CONCURRENT_POSITIONS=2\n"
        "WATCH_INTERVAL_MINUTES=1440\nHEARTBEAT_INTERVAL_HOURS=0\n"
        "CHECK_INTERVAL_SECONDS=3600\nSTATE_DIR=state\n",
        encoding="utf-8",
    )
    mocker.patch("auto_coin.bot.fetch_daily", return_value=None)
    mocker.patch("auto_coin.exchange.upbit_client.pyupbit.get_current_price",
                 return_value=0.0)
    mocker.patch("auto_coin.notifier.telegram.requests.post")
    # dashboard 자체가 current price를 조회할 때 사용하는 경로도 mock
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


def _current_totp_code() -> str:
    with Session(web_db.engine()) as db:
        user = get_user(db)
        secret = SecretBox().decrypt(user.totp_secret_enc)
    return pyotp.TOTP(secret).now()


def _seed_position(tmp_path, ticker: str, *, entry: float = 100.0, volume: float = 0.5):
    store = OrderStore(tmp_path / "state" / f"{ticker}.json")
    state = store.load()
    state.position = Position(
        ticker=ticker, volume=volume, avg_entry_price=entry,
        entry_uuid="u1", entry_at="2026-04-14T00:00:00",
    )
    state.orders.append(OrderRecord(
        uuid="u1", side="buy", market=ticker, krw_amount=50.0,
        volume=volume, price=entry, placed_at="2026-04-14T00:00:00",
        status="paper",
    ))
    store.save(state)


def test_dashboard_renders_when_logged_in(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/")
        assert r.status_code == 200
        assert "대시보드" in r.text
        assert "KRW-BTC" in r.text
        assert "KRW-ETH" in r.text
        # 상태 뱃지
        assert "paper" in r.text
        # 컨트롤 버튼
        assert "Kill-switch" in r.text
        assert "재시작" in r.text
        assert "이벤트 타임라인" in r.text


def test_dashboard_shows_positions_and_pnl(app_env):
    _seed_position(app_env, "KRW-BTC", entry=100.0)
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/")
        assert "KRW-BTC" in r.text
        assert "1/2" in r.text  # 슬롯 사용 카운트
        # 최근 주문 BUY 기록 확인
        assert "BUY" in r.text


def test_dashboard_context_contains_avg_and_total_pnl(app_env, mocker):
    """_collect_dashboard_context must expose both total_daily_pnl and avg_daily_pnl."""
    from auto_coin.web.crypto import SecretBox
    from auto_coin.web.routers.dashboard import _collect_dashboard_context

    # seed two positions so slot_used = 2
    _seed_position(app_env, "KRW-BTC", entry=100.0)
    _seed_position(app_env, "KRW-ETH", entry=200.0)

    # manually set daily_pnl_ratio on each state file
    from auto_coin.executor.store import OrderStore
    for ticker, pnl in [("KRW-BTC", 0.02), ("KRW-ETH", 0.02)]:
        safe = ticker.replace("/", "_")
        store = OrderStore(app_env / "state" / f"{safe}.json")
        state = store.load()
        state.daily_pnl_ratio = pnl
        store.save(state)

    app = create_app()
    with TestClient(app) as client:
        _login(client)
        with Session(web_db.engine()) as db:
            box = SecretBox()
            manager = app.state.bot_manager  # type: ignore[attr-defined]
            ctx = _collect_dashboard_context(db, box, manager)

    assert "total_daily_pnl" in ctx
    assert "avg_daily_pnl" in ctx
    # total = 0.02 + 0.02 = 0.04; avg = 0.04 / 2 = 0.02
    assert abs(ctx["total_daily_pnl"] - 0.04) < 1e-9
    assert abs(ctx["avg_daily_pnl"] - 0.02) < 1e-9


def test_dashboard_partial_returns_body_only(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/dashboard/partial")
        assert r.status_code == 200
        # partial이므로 base.html의 헤더(탭)는 없어야 한다
        assert "<html" not in r.text
        assert "슬롯 사용" in r.text


def test_kill_switch_toggle_persists(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        # 처음엔 OFF
        with Session(web_db.engine()) as db:
            s = load_runtime_settings(db, SecretBox())
            assert s.kill_switch is False
        r = client.post("/control/kill-switch", data=csrf_data(client), follow_redirects=False)
        assert r.status_code == 303
        with Session(web_db.engine()) as db:
            s = load_runtime_settings(db, SecretBox())
            assert s.kill_switch is True
        # 다시 토글 → OFF
        client.post("/control/kill-switch", data=csrf_data(client))
        with Session(web_db.engine()) as db:
            s = load_runtime_settings(db, SecretBox())
            assert s.kill_switch is False


def test_restart_calls_reload(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        reload_spy = mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/control/restart", data=csrf_data(client), follow_redirects=False)
        assert r.status_code == 303
        reload_spy.assert_called_once()


def test_stop_requires_confirmation(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        stop_spy = mocker.patch("auto_coin.web.bot_manager.BotManager.stop")
        r = client.post("/control/stop", data=csrf_data(client, {"confirm": ""}), follow_redirects=False)
        assert r.status_code == 303
        stop_spy.assert_not_called()


def test_stop_with_confirmation_stops(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        stop_spy = mocker.patch("auto_coin.web.bot_manager.BotManager.stop")
        # running 상태로 만들기 위해 default는 start되어 있음
        r = client.post("/control/stop", data=csrf_data(client, {"confirm": "yes"}), follow_redirects=False)
        assert r.status_code == 303
        stop_spy.assert_called_once()


def test_start_when_stopped(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        # 먼저 stop
        mocker.patch("auto_coin.web.bot_manager.BotManager.stop")
        client.post("/control/stop", data=csrf_data(client, {"confirm": "yes"}))
        # running=False 상태 simulate
        mocker.patch("auto_coin.web.bot_manager.BotManager.running",
                     new_callable=mocker.PropertyMock, return_value=False)
        start_spy = mocker.patch("auto_coin.web.bot_manager.BotManager.start")
        r = client.post("/control/start", data=csrf_data(client), follow_redirects=False)
        assert r.status_code == 303
        start_spy.assert_called_once()


def test_control_requires_auth(app_env):
    app = create_app()
    with TestClient(app) as client:
        # 미인증 POST는 현재 설치 상태에 따라 setup 또는 login으로 보낸다.
        r = client.post("/control/kill-switch", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] in {"/setup", "/login"}


def test_kill_switch_flash_shows_on_next_load(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        client.post("/control/kill-switch", data=csrf_data(client), follow_redirects=False)
        # 다음 GET 시 flash 메시지 렌더
        r = client.get("/")
        assert "Kill-switch 켜짐" in r.text


def test_dashboard_includes_live_badge_when_is_live(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        # settings 수정 → live
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        client.post("/settings/schedule",
                    data=csrf_data(client, {
                        "check_interval_seconds": "60",
                        "heartbeat_interval_hours": "0",
                        "exit_hour_kst": "8", "exit_minute_kst": "55",
                        "daily_reset_hour_kst": "9",
                        "mode": "live", "live_trading": "on",
                        "totp_code": _current_totp_code()}))
        r = client.get("/")
        assert "LIVE" in r.text


def test_dashboard_timeline_includes_audit_and_order_events(app_env):
    _seed_position(app_env, "KRW-BTC", entry=100.0)
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        with Session(web_db.engine()) as db:
            audit.record(
                db,
                "settings.strategy",
                before={"strategy_k": 0.5},
                after={"strategy_k": 0.6},
            )
        r = client.get("/dashboard/partial")
        assert r.status_code == 200
        assert "이벤트 타임라인" in r.text
        assert "BUY KRW-BTC" in r.text
        assert "전략 설정 저장" in r.text


# ---- risk_dashboard 라우터 등록 ----


def test_risk_dashboard_returns_200(app_env):
    """GET /risk 가 404가 아닌 200을 반환해야 한다."""
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/risk")
        assert r.status_code == 200


def test_risk_dashboard_requires_auth(app_env):
    """비인증 상태에서 /risk 접근 시 인증 페이지로 리다이렉트."""
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/risk", follow_redirects=False)
        assert r.status_code == 303
        loc = r.headers.get("location", "")
        assert "/login" in loc or "/setup" in loc
