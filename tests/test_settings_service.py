from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

from auto_coin.config import Mode
from auto_coin.web.crypto import SecretBox
from auto_coin.web.settings_service import (
    get_or_create_row,
    load_runtime_settings,
    row_to_settings,
    save_runtime_settings,
    settings_to_row,
)


@pytest.fixture
def box(tmp_path):
    return SecretBox(key_path=tmp_path / "m.key")


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_get_or_create_creates_row_once(db_session):
    row1 = get_or_create_row(db_session)
    row2 = get_or_create_row(db_session)
    assert row1.id == 1
    assert row2.id == 1


def test_load_returns_defaults_on_empty_db(db_session, box):
    s = load_runtime_settings(db_session, box)
    assert s.mode is Mode.PAPER
    assert s.ticker == "KRW-BTC"
    assert s.max_concurrent_positions == 3
    assert s.upbit_access_key.get_secret_value() == ""


def test_save_then_load_roundtrip(db_session, box):
    s = load_runtime_settings(db_session, box)
    # Settings는 frozen이 아니므로 model_copy로 업데이트
    updated = s.model_copy(update={
        "strategy_k": 0.6,
        "tickers": "KRW-BTC,KRW-ETH,KRW-SOL",
        "max_concurrent_positions": 2,
    })
    save_runtime_settings(db_session, box, updated)
    reloaded = load_runtime_settings(db_session, box)
    assert reloaded.strategy_k == 0.6
    assert reloaded.tickers == "KRW-BTC,KRW-ETH,KRW-SOL"
    assert reloaded.max_concurrent_positions == 2
    assert reloaded.portfolio_ticker_list == ["KRW-BTC", "KRW-ETH", "KRW-SOL"]


def test_api_keys_encrypted_at_rest(db_session, box):
    from pydantic import SecretStr
    s = load_runtime_settings(db_session, box)
    updated = s.model_copy(update={
        "upbit_access_key": SecretStr("AKEY123"),
        "upbit_secret_key": SecretStr("SKEY456"),
        "telegram_bot_token": SecretStr("TTOKEN789"),
    })
    save_runtime_settings(db_session, box, updated)
    # raw row를 읽어 암호문인지 확인
    row = get_or_create_row(db_session)
    assert row.upbit_access_key_enc != "AKEY123"
    assert "AKEY123" not in row.upbit_access_key_enc
    # 복호화 정상
    reloaded = load_runtime_settings(db_session, box)
    assert reloaded.upbit_access_key.get_secret_value() == "AKEY123"
    assert reloaded.upbit_secret_key.get_secret_value() == "SKEY456"
    assert reloaded.telegram_bot_token.get_secret_value() == "TTOKEN789"


def test_settings_to_row_updates_timestamp(db_session, box):
    from datetime import datetime, timedelta
    row = get_or_create_row(db_session)
    old_ts = row.updated_at
    s = load_runtime_settings(db_session, box)
    settings_to_row(s, row, box)
    assert row.updated_at >= old_ts
    # naive UTC로 저장됨 (tzinfo 없음)
    assert row.updated_at.tzinfo is None
    # 현재 시각 기준 1초 이내
    assert row.updated_at <= datetime.utcnow() + timedelta(seconds=1)


def test_row_to_settings_preserves_mode_enum(db_session, box):
    row = get_or_create_row(db_session)
    row.mode = "live"
    db_session.add(row)
    db_session.commit()
    s = row_to_settings(row, box)
    assert s.mode is Mode.LIVE


def test_bootstrap_from_env_seeds_when_db_empty(tmp_path, monkeypatch, box):
    """DB가 비어있으면 .env → row 시드, 두 번째 호출은 no-op."""
    from auto_coin.web.settings_service import bootstrap_from_env
    # 테스트 디렉토리에 가짜 .env 생성 후 cwd 변경
    env_file = tmp_path / ".env"
    env_file.write_text("TICKER=KRW-TEST\nSTRATEGY_K=0.42\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    engine = create_engine(f"sqlite:///{tmp_path / 'boot.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        row, seeded = bootstrap_from_env(s, box)
        assert seeded is True
        assert row.ticker == "KRW-TEST"
        assert row.strategy_k == 0.42
        # 두 번째 호출은 기존 row 그대로
        row2, seeded2 = bootstrap_from_env(s, box)
        assert seeded2 is False
        assert row2.id == row.id
