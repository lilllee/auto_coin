"""SQLModel 테이블 정의.

핵심:
- `AppSettings`: 런타임 설정 단일 row. `auto_coin.config.Settings`와 필드 대응.
- `User`: 단일 사용자 (username="admin" 고정 권장). password + TOTP.
- `AuditLog`: 설정 변경 이력.

암호화가 필요한 필드는 `_enc` suffix로 저장 (빈 문자열 = 평문 빈 값).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    """SQLite는 tz 정보를 벗기므로 naive UTC로 통일해 저장한다."""
    return datetime.now(UTC).replace(tzinfo=None)


class AppSettings(SQLModel, table=True):
    """단일 row (id=1)에 모든 런타임 설정 저장."""

    id: int | None = Field(default=None, primary_key=True)

    # 실행 모드
    mode: str = Field(default="paper")             # paper | live
    live_trading: bool = False
    kill_switch: bool = False

    # 포트폴리오
    ticker: str = Field(default="KRW-BTC")
    tickers: str = Field(default="")               # 콤마 구분
    max_concurrent_positions: int = 3
    watch_tickers: str = Field(default="")
    watch_interval_minutes: int = 15

    # 전략
    strategy_name: str = Field(default="volatility_breakout")
    strategy_params_json: str = Field(default="")  # JSON for strategy-specific params
    strategy_k: float = 0.5
    ma_filter_window: int = 5

    # 리스크
    max_position_ratio: float = 0.20
    daily_loss_limit: float = -0.03
    stop_loss_ratio: float = -0.02
    min_order_krw: int = 5000
    api_max_retries: int = 3

    # 스케줄
    paper_initial_krw: float = 1_000_000.0
    check_interval_seconds: int = 60
    heartbeat_interval_hours: int = 6
    exit_hour_kst: int = 8
    exit_minute_kst: int = 55
    daily_reset_hour_kst: int = 9

    # 로그 / 저장
    state_dir: str = "state"
    log_level: str = "INFO"
    log_dir: str = "logs"

    # 암호화 필드
    upbit_access_key_enc: str = ""
    upbit_secret_key_enc: str = ""
    telegram_bot_token_enc: str = ""
    telegram_chat_id: str = ""

    updated_at: datetime = Field(default_factory=_now)


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(default="admin", unique=True, index=True)
    password_hash: str
    totp_secret_enc: str                # Fernet-encrypted base32 seed
    recovery_codes_enc: str = ""        # Fernet-encrypted JSON array of one-time recovery codes
    totp_confirmed: bool = False        # setup flow에서 6자리 확인 전엔 False
    failed_attempts: int = 0
    locked_until: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
    last_login_at: datetime | None = None


class AuditLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=_now, index=True)
    action: str                         # "settings.update" / "auth.login" / ...
    actor: str = "admin"
    before_json: str = ""
    after_json: str = ""


def default_db_path() -> Path:
    """lazy 평가 — HOME 변경(테스트)을 반영하기 위해 매 호출 시 재계산."""
    return Path.home() / ".auto_coin.db"
