"""런타임 설정 서비스.

SQLite의 `AppSettings` row ↔ `auto_coin.config.Settings` 변환 레이어.

- `load_runtime_settings()` : DB에서 설정 읽어 기존 `Settings` 인스턴스로 조립
- `save_runtime_settings()` : `Settings` → DB 업서트
- `bootstrap_from_env()`    : 최초 기동 시 DB가 비어있으면 `.env`에서 한 번 시드

기존 `auto_coin.config.Settings`는 V1 CLI와 호환을 위해 그대로 둔다.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from pydantic import SecretStr
from sqlmodel import Session, select

from auto_coin.config import Mode, Settings
from auto_coin.web.crypto import SecretBox
from auto_coin.web.models import AppSettings, _now

# ----- DB ↔ Settings 변환 ---------------------------------------------------

_SCALAR_FIELDS = (
    "mode", "live_trading", "kill_switch",
    "ticker", "tickers", "max_concurrent_positions",
    "watch_tickers", "watch_interval_minutes",
    "strategy_k", "ma_filter_window",
    "max_position_ratio", "daily_loss_limit", "stop_loss_ratio",
    "min_order_krw", "api_max_retries",
    "paper_initial_krw", "check_interval_seconds", "heartbeat_interval_hours",
    "exit_hour_kst", "exit_minute_kst", "daily_reset_hour_kst",
    "state_dir", "log_level", "log_dir",
    "telegram_chat_id",
)


def row_to_settings(row: AppSettings, box: SecretBox) -> Settings:
    """`AppSettings` (DB) → `Settings` (pydantic)."""
    raw = {f: getattr(row, f) for f in _SCALAR_FIELDS}
    raw["mode"] = Mode(raw["mode"])
    raw["upbit_access_key"] = SecretStr(box.decrypt(row.upbit_access_key_enc))
    raw["upbit_secret_key"] = SecretStr(box.decrypt(row.upbit_secret_key_enc))
    raw["telegram_bot_token"] = SecretStr(box.decrypt(row.telegram_bot_token_enc))
    return Settings(_env_file=None, **raw)


def settings_to_row(settings: Settings, row: AppSettings, box: SecretBox) -> AppSettings:
    """`Settings` → `AppSettings` (row 수정). 암호화 필드는 인자의 평문에서 다시 암호화."""
    for f in _SCALAR_FIELDS:
        value = getattr(settings, f)
        if f == "mode":
            value = value.value  # StrEnum → str
        elif isinstance(value, Path):
            value = str(value)   # sqlite에 직접 바인딩 불가
        setattr(row, f, value)
    row.upbit_access_key_enc = box.encrypt(settings.upbit_access_key.get_secret_value())
    row.upbit_secret_key_enc = box.encrypt(settings.upbit_secret_key.get_secret_value())
    row.telegram_bot_token_enc = box.encrypt(settings.telegram_bot_token.get_secret_value())
    row.updated_at = _now()
    return row


# ----- high-level API ------------------------------------------------------


def get_or_create_row(session: Session) -> AppSettings:
    row = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()
    if row is None:
        row = AppSettings(id=1)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def load_runtime_settings(session: Session, box: SecretBox) -> Settings:
    row = get_or_create_row(session)
    return row_to_settings(row, box)


def save_runtime_settings(session: Session, box: SecretBox, settings: Settings) -> AppSettings:
    row = get_or_create_row(session)
    settings_to_row(settings, row, box)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ----- .env → DB 부트스트랩 -----------------------------------------------


def bootstrap_from_env(session: Session, box: SecretBox) -> tuple[AppSettings, bool]:
    """최초 기동: DB가 비어있고 `.env`가 있으면 한 번만 시드.

    반환: (row, seeded_from_env?)
    """
    existing = session.exec(select(AppSettings).where(AppSettings.id == 1)).first()
    if existing is not None:
        return existing, False
    # V1 Settings로 `.env` 파싱
    env_settings = Settings()  # env_file=".env" 기본
    row = AppSettings(id=1)
    settings_to_row(env_settings, row, box)
    session.add(row)
    session.commit()
    session.refresh(row)
    logger.info("seeded AppSettings row from .env (one-time migration)")
    return row, True
