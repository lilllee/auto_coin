"""V2.3 settings 라우터 통합 테스트."""

from __future__ import annotations

import pyotp
import pytest
from csrf_helpers import csrf_data, csrf_headers
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from auto_coin.web import db as web_db
from auto_coin.web.app import create_app
from auto_coin.web.crypto import SecretBox
from auto_coin.web.models import AppSettings, AuditLog
from auto_coin.web.services import upbit_scan
from auto_coin.web.user_service import get_user


@pytest.fixture
def app_env(tmp_path, monkeypatch, mocker):
    web_db.reset_engine()
    upbit_scan.clear_cache()
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
    # upbit_scan은 각 테스트에서 개별 mock
    yield tmp_path
    web_db.reset_engine()
    upbit_scan.clear_cache()


def _login(client: TestClient) -> None:
    client.post("/setup", data={"password": "hunter22", "password_confirm": "hunter22"})
    with Session(web_db.engine()) as db:
        user = get_user(db)
        secret = SecretBox().decrypt(user.totp_secret_enc)
    client.post("/setup/totp", data={"code": pyotp.TOTP(secret).now()})


def _totp_code() -> str:
    with Session(web_db.engine()) as db:
        user = get_user(db)
        secret = SecretBox().decrypt(user.totp_secret_enc)
    return pyotp.TOTP(secret).now()


def _current_row():
    with Session(web_db.engine()) as db:
        return db.exec(select(AppSettings).where(AppSettings.id == 1)).first()


def _overwrite_api_key_row(*, access: str = "", secret: str = "",
                           telegram_token: str = "", telegram_chat_id: str = ""):
    box = SecretBox()
    with Session(web_db.engine()) as db:
        row = db.exec(select(AppSettings).where(AppSettings.id == 1)).first()
        row.upbit_access_key_enc = box.encrypt(access)
        row.upbit_secret_key_enc = box.encrypt(secret)
        row.telegram_bot_token_enc = box.encrypt(telegram_token)
        row.telegram_chat_id = telegram_chat_id
        db.add(row)
        db.commit()


def test_settings_index_renders(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/settings")
        assert r.status_code == 200
        for section in ("전략", "리스크", "포트폴리오", "API 키", "스케줄"):
            assert section in r.text


# ----- strategy --------


def test_strategy_get_renders_form(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/settings/strategy")
        assert r.status_code == 200
        assert 'name="strategy_name"' in r.text
        assert 'name="strategy_k"' in r.text


def test_strategy_post_updates_db_and_reloads(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        reload_spy = mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/settings/strategy",
                        data=csrf_data(client, {
                            "strategy_name": "volatility_breakout",
                            "strategy_k": "0.7",
                            "ma_filter_window": "10",
                            "watch_interval_minutes": "30",
                        }),
                        follow_redirects=False)
        assert r.status_code == 303
        reload_spy.assert_called_once()
    row = _current_row()
    assert row.strategy_k == 0.7
    assert row.ma_filter_window == 10
    assert row.watch_interval_minutes == 30
    assert row.strategy_name == "volatility_breakout"


def test_strategy_post_rejects_invalid(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        reload_spy = mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/settings/strategy",
                        data=csrf_data(client, {
                            "strategy_name": "volatility_breakout",
                            "strategy_k": "2.5",  # 1.0 초과
                            "ma_filter_window": "5",
                            "watch_interval_minutes": "15",
                        }))
        assert r.status_code == 400
        reload_spy.assert_not_called()
    row = _current_row()
    assert row.strategy_k == 0.5  # 기본값 유지


def test_strategy_post_unknown_strategy_rejected(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        reload_spy = mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/settings/strategy",
                        data=csrf_data(client, {
                            "strategy_name": "nonexistent",
                            "strategy_k": "0.5",
                            "ma_filter_window": "5",
                            "watch_interval_minutes": "15",
                        }))
        assert r.status_code == 400
        reload_spy.assert_not_called()


def test_strategy_post_saves_strategy_params_json(app_env, mocker):
    import json
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/settings/strategy",
                        data=csrf_data(client, {
                            "strategy_name": "volatility_breakout",
                            "strategy_k": "0.6",
                            "ma_filter_window": "7",
                            "watch_interval_minutes": "15",
                        }),
                        follow_redirects=False)
        assert r.status_code == 303
    row = _current_row()
    params = json.loads(row.strategy_params_json)
    assert params["k"] == 0.6
    assert params["ma_window"] == 7


def test_strategy_post_composite_params_saved(app_env, mocker):
    """sma200_ema_adx_composite 파라미터가 sp_* 폼에서 저장된다."""
    import json
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/settings/strategy",
                        data=csrf_data(client, {
                            "strategy_name": "sma200_ema_adx_composite",
                            "sp_sma_window": "100",
                            "sp_ema_fast_window": "20",
                            "sp_ema_slow_window": "60",
                            "sp_adx_window": "50",
                            "sp_adx_threshold": "12.5",
                            "watch_interval_minutes": "15",
                        }),
                        follow_redirects=False)
        assert r.status_code == 303
    row = _current_row()
    assert row.strategy_name == "sma200_ema_adx_composite"
    params = json.loads(row.strategy_params_json)
    assert params["sma_window"] == 100
    assert params["ema_fast_window"] == 20
    assert params["ema_slow_window"] == 60
    assert params["adx_window"] == 50
    assert params["adx_threshold"] == 12.5


def test_strategy_post_ad_turtle_params_saved(app_env, mocker):
    """ad_turtle 파라미터가 sp_* 폼에서 저장된다."""
    import json
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/settings/strategy",
                        data=csrf_data(client, {
                            "strategy_name": "ad_turtle",
                            "sp_entry_window": "30",
                            "sp_exit_window": "15",
                            "sp_allow_sell_signal": "on",
                            "watch_interval_minutes": "15",
                        }),
                        follow_redirects=False)
        assert r.status_code == 303
    row = _current_row()
    assert row.strategy_name == "ad_turtle"
    params = json.loads(row.strategy_params_json)
    assert params["entry_window"] == 30
    assert params["exit_window"] == 15
    assert params["allow_sell_signal"] is True


def test_strategy_post_checkbox_unchecked_saves_false(app_env, mocker):
    """체크박스 미선택 시 False로 저장된다."""
    import json
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/settings/strategy",
                        data=csrf_data(client, {
                            "strategy_name": "sma200_regime",
                            "sp_ma_window": "200",
                            "sp_buffer_pct": "0.01",
                            # sp_allow_sell_signal 미포함 = unchecked
                            "watch_interval_minutes": "15",
                        }),
                        follow_redirects=False)
        assert r.status_code == 303
    row = _current_row()
    params = json.loads(row.strategy_params_json)
    assert params["allow_sell_signal"] is False
    assert params["ma_window"] == 200
    assert params["buffer_pct"] == 0.01


def test_strategy_post_invalid_number_uses_default(app_env, mocker):
    """잘못된 숫자 입력 시 기본값으로 fallback된다."""
    import json
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/settings/strategy",
                        data=csrf_data(client, {
                            "strategy_name": "atr_channel_breakout",
                            "sp_atr_window": "not_a_number",
                            "sp_channel_multiplier": "abc",
                            "watch_interval_minutes": "15",
                        }),
                        follow_redirects=False)
        assert r.status_code == 303
    row = _current_row()
    params = json.loads(row.strategy_params_json)
    # 기본값으로 fallback
    assert params["atr_window"] == 14
    assert params["channel_multiplier"] == 1.0


def test_strategy_post_vb_with_sp_fields(app_env, mocker):
    """VB에서도 sp_* 필드가 동작한다 (실제 폼 동작 방식)."""
    import json
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/settings/strategy",
                        data=csrf_data(client, {
                            "strategy_name": "volatility_breakout",
                            "sp_k": "0.35",
                            "sp_ma_window": "12",
                            "sp_require_ma_filter": "on",
                            "strategy_k": "0.5",  # legacy — sp_ 값이 우선
                            "ma_filter_window": "5",
                            "watch_interval_minutes": "15",
                        }),
                        follow_redirects=False)
        assert r.status_code == 303
    row = _current_row()
    params = json.loads(row.strategy_params_json)
    assert params["k"] == 0.35
    assert params["ma_window"] == 12
    assert params["require_ma_filter"] is True


# ----- risk --------


def test_risk_post_applies(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/settings/risk",
                        data=csrf_data(client, {"max_position_ratio": "0.15",
                              "daily_loss_limit": "-0.05",
                              "stop_loss_ratio": "-0.03",
                              "min_order_krw": "10000",
                              "max_concurrent_positions": "5",
                              "paper_initial_krw": "2000000",
                              "kill_switch": "on"}),
                        follow_redirects=False)
        assert r.status_code == 303
    row = _current_row()
    assert row.max_position_ratio == 0.15
    assert row.kill_switch is True
    assert row.paper_initial_krw == 2_000_000.0
    assert row.max_concurrent_positions == 5


def test_risk_post_rejects_bad_min_order(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.post("/settings/risk",
                        data=csrf_data(client, {"max_position_ratio": "0.2",
                              "daily_loss_limit": "-0.03",
                              "stop_loss_ratio": "-0.02",
                              "min_order_krw": "1000",    # < 5000
                              "max_concurrent_positions": "3",
                              "paper_initial_krw": "1000000"}))
        assert r.status_code == 400


# ----- portfolio --------


def test_portfolio_post_validates_listing(app_env, mocker):
    mocker.patch("auto_coin.web.services.upbit_scan.pyupbit.get_tickers",
                 return_value=["KRW-BTC", "KRW-ETH"])
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/settings/portfolio",
                        data=csrf_data(client, {"tickers": "KRW-BTC,KRW-FAKE", "watch_tickers": ""}))
        assert r.status_code == 400
        assert "KRW-FAKE" in r.text


def test_portfolio_post_saves_when_all_listed(app_env, mocker):
    mocker.patch("auto_coin.web.services.upbit_scan.pyupbit.get_tickers",
                 return_value=["KRW-BTC", "KRW-ETH", "KRW-XRP"])
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/settings/portfolio",
                        data=csrf_data(client, {"tickers": "krw-btc, KRW-ETH",
                              "watch_tickers": "KRW-XRP"}),
                        follow_redirects=False)
        assert r.status_code == 303
    row = _current_row()
    assert row.tickers == "KRW-BTC,KRW-ETH"
    assert row.watch_tickers == "KRW-XRP"


def test_portfolio_get_includes_top_suggestions(app_env, mocker):
    mocker.patch("auto_coin.web.services.upbit_scan.pyupbit.get_tickers",
                 return_value=["KRW-BTC", "KRW-ETH", "KRW-DOGE"])
    mock_resp = mocker.Mock()
    mock_resp.json.return_value = [
        {"market": "KRW-BTC", "trade_price": 100_000_000, "acc_trade_price_24h": 1e11,
         "signed_change_rate": 0.01},
        {"market": "KRW-ETH", "trade_price": 3_000_000, "acc_trade_price_24h": 5e10,
         "signed_change_rate": -0.02},
        {"market": "KRW-DOGE", "trade_price": 140, "acc_trade_price_24h": 2e10,
         "signed_change_rate": 0.05},
    ]
    mock_resp.raise_for_status = mocker.Mock()
    mocker.patch("auto_coin.web.services.upbit_scan.requests.get", return_value=mock_resp)

    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/settings/portfolio")
        assert r.status_code == 200
        # 현재 포트폴리오는 KRW-BTC 하나 → DOGE가 추천에 보여야 함
        assert "KRW-DOGE" in r.text


# ----- api keys --------


def test_api_keys_get_shows_mask(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        # 저장된 키가 있는 상황을 만든 뒤
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        client.post("/settings/api-keys",
                    data=csrf_data(client, {"upbit_access_key": "ACCESSKEY123456",
                          "upbit_secret_key": "SECRETKEY123456",
                          "telegram_bot_token": "BOTTOKEN123456",
                          "telegram_chat_id": "9999"}))
        r = client.get("/settings/api-keys")
        assert r.status_code == 200
        # 마지막 4자리만 노출
        assert "3456" in r.text
        # 평문 키가 페이지에 그대로 있으면 안 됨
        assert "ACCESSKEY123456" not in r.text


def test_api_keys_post_empty_preserves_existing(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        # 먼저 저장
        client.post("/settings/api-keys",
                    data=csrf_data(client, {"upbit_access_key": "AK1", "upbit_secret_key": "SK1",
                          "telegram_bot_token": "", "telegram_chat_id": ""}))
        # 빈 값으로 두 번째 POST → 기존 유지
        client.post("/settings/api-keys",
                    data=csrf_data(client, {"upbit_access_key": "", "upbit_secret_key": "",
                          "telegram_bot_token": "", "telegram_chat_id": ""}))
    # 복호화하여 확인
    from auto_coin.web.settings_service import load_runtime_settings
    with Session(web_db.engine()) as db:
        s = load_runtime_settings(db, SecretBox())
    assert s.upbit_access_key.get_secret_value() == "AK1"
    assert s.upbit_secret_key.get_secret_value() == "SK1"


def test_api_keys_test_upbit_success(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        client.post("/settings/api-keys",
                    data=csrf_data(client, {"upbit_access_key": "AK", "upbit_secret_key": "SK",
                          "telegram_bot_token": "", "telegram_chat_id": ""}))
        mocker.patch("auto_coin.web.services.credentials_check.UpbitClient.get_krw_balance",
                     return_value=1000.0)
        r = client.post("/settings/api-keys/test-upbit", headers=csrf_headers(client))
        assert r.status_code == 200
        assert "✅" in r.text
        assert "1,000" in r.text


def test_api_keys_upbit_holdings_renders_saved_assets(app_env, mocker):
    from auto_coin.web.services.credentials_check import HoldingRow

    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        client.post("/settings/api-keys",
                    data=csrf_data(client, {"upbit_access_key": "AK", "upbit_secret_key": "SK",
                          "telegram_bot_token": "", "telegram_chat_id": ""}))
        mocker.patch(
            "auto_coin.web.routers.settings.fetch_upbit_holdings",
            return_value=__import__("auto_coin.web.services.credentials_check",
                                    fromlist=["HoldingsResult"]).HoldingsResult(
                ok=True,
                detail="보유 코인 2개",
                holdings=(
                    HoldingRow("KRW-BTC", "0.01", "-", "100,000,000", "1,000,000"),
                    HoldingRow("KRW-ETH", "1.25", "0.2", "3,500,000", "4,375,000"),
                ),
            ),
        )
        r = client.post("/settings/api-keys/upbit-holdings", headers=csrf_headers(client))
        assert r.status_code == 200
        assert "KRW-BTC" in r.text
        assert "KRW-ETH" in r.text
        assert "1,000,000" in r.text
        assert "보유 코인 2개" in r.text


def test_api_keys_upbit_holding_falls_back_to_env_when_db_blank(app_env, mocker):
    app_env.joinpath(".env").write_text(
        "TICKER=KRW-BTC\nWATCH_INTERVAL_MINUTES=1440\n"
        "HEARTBEAT_INTERVAL_HOURS=0\nCHECK_INTERVAL_SECONDS=3600\n"
        "UPBIT_ACCESS_KEY=ENV_AK\nUPBIT_SECRET_KEY=ENV_SK\n",
        encoding="utf-8",
    )
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        _overwrite_api_key_row(access="", secret="")
        fetch = mocker.patch(
            "auto_coin.web.routers.settings.fetch_upbit_holdings",
            return_value=__import__("auto_coin.web.services.credentials_check",
                                    fromlist=["HoldingsResult"]).HoldingsResult(
                ok=True, detail="보유 코인 0개", holdings=()
            ),
        )
        r = client.post("/settings/api-keys/upbit-holdings", headers=csrf_headers(client))
        assert r.status_code == 200
        fetch.assert_called_once_with("ENV_AK", "ENV_SK")


def test_api_keys_test_telegram_failure(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        client.post("/settings/api-keys",
                    data=csrf_data(client, {"upbit_access_key": "", "upbit_secret_key": "",
                          "telegram_bot_token": "", "telegram_chat_id": ""}))
        r = client.post("/settings/api-keys/test-telegram", headers=csrf_headers(client))
        assert r.status_code == 200
        assert "❌" in r.text


# ----- schedule --------


def test_schedule_post_applies(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post("/settings/schedule",
                        data=csrf_data(client, {"check_interval_seconds": "120",
                              "heartbeat_interval_hours": "12",
                              "exit_hour_kst": "8",
                              "exit_minute_kst": "55",
                              "daily_reset_hour_kst": "9",
                              "mode": "paper"}),
                        follow_redirects=False)
        assert r.status_code == 303
    row = _current_row()
    assert row.check_interval_seconds == 120
    assert row.heartbeat_interval_hours == 12
    assert row.live_trading is False


def test_schedule_live_mode_requires_totp(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        reload_spy = mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post(
            "/settings/schedule",
            data=csrf_data(
                client,
                {
                    "check_interval_seconds": "60",
                    "heartbeat_interval_hours": "0",
                    "exit_hour_kst": "8",
                    "exit_minute_kst": "55",
                    "daily_reset_hour_kst": "9",
                    "mode": "live",
                    "live_trading": "on",
                    "totp_code": "",
                },
            ),
        )
        assert r.status_code == 400
        assert "TOTP" in r.text
        reload_spy.assert_not_called()
    row = _current_row()
    assert row.mode == "paper"


def test_schedule_live_mode_rejects_wrong_totp_and_records_audit(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        reload_spy = mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post(
            "/settings/schedule",
            data=csrf_data(
                client,
                {
                    "check_interval_seconds": "60",
                    "heartbeat_interval_hours": "0",
                    "exit_hour_kst": "8",
                    "exit_minute_kst": "55",
                    "daily_reset_hour_kst": "9",
                    "mode": "live",
                    "live_trading": "on",
                    "totp_code": "000000",
                },
            ),
        )
        assert r.status_code == 400
        reload_spy.assert_not_called()
    with Session(web_db.engine()) as db:
        audit_logs = db.exec(select(AuditLog).where(AuditLog.action == "settings.schedule.live_totp_rejected")).all()
    assert audit_logs


def test_schedule_live_mode_accepts_valid_totp(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        reload_spy = mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        r = client.post(
            "/settings/schedule",
            data=csrf_data(
                client,
                {
                    "check_interval_seconds": "60",
                    "heartbeat_interval_hours": "0",
                    "exit_hour_kst": "8",
                    "exit_minute_kst": "55",
                    "daily_reset_hour_kst": "9",
                    "mode": "live",
                    "live_trading": "on",
                    "totp_code": _totp_code(),
                },
            ),
            follow_redirects=False,
        )
        assert r.status_code == 303
        reload_spy.assert_called_once()
    row = _current_row()
    assert row.mode == "live"
    assert row.live_trading is True


# ----- audit log --------


def test_settings_change_records_audit_log(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        client.post("/settings/strategy",
                    data=csrf_data(client, {
                        "strategy_name": "volatility_breakout",
                        "strategy_k": "0.6",
                        "ma_filter_window": "5",
                        "watch_interval_minutes": "15",
                    }))
    with Session(web_db.engine()) as db:
        logs = db.exec(select(AuditLog)).all()
    assert len(logs) >= 1
    assert any(log.action == "settings.strategy" for log in logs)


def test_audit_log_masks_api_keys(app_env, mocker):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        mocker.patch("auto_coin.web.bot_manager.BotManager.reload")
        client.post("/settings/api-keys",
                    data=csrf_data(client, {"upbit_access_key": "SUPERSECRETKEY999",
                          "upbit_secret_key": "SK", "telegram_bot_token": "",
                          "telegram_chat_id": ""}))
    with Session(web_db.engine()) as db:
        logs = db.exec(select(AuditLog).where(AuditLog.action == "settings.api_keys")).all()
    assert logs
    for log in logs:
        assert "SUPERSECRETKEY999" not in log.after_json
        assert "SUPERSECRETKEY999" not in log.before_json
