from enum import StrEnum
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Mode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    upbit_access_key: SecretStr = SecretStr("")
    upbit_secret_key: SecretStr = SecretStr("")

    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""

    mode: Mode = Mode.PAPER
    live_trading: bool = False
    kill_switch: bool = False

    ticker: str = "KRW-BTC"
    # 멀티 종목 매매 대상. 콤마 구분. 비어 있으면 ticker 하나만 매매.
    tickers: str = ""
    max_concurrent_positions: int = Field(3, ge=1, le=20)
    # 관측 전용(주문 없음) 티커 목록. 콤마 구분. 비어 있으면 메인 티커 1개만 관측.
    watch_tickers: str = ""
    watch_interval_minutes: int = Field(15, ge=1, le=1440)

    strategy_name: str = Field(default="volatility_breakout")
    strategy_params_json: str = ""  # JSON string for strategy-specific params

    strategy_k: float = Field(0.5, ge=0.1, le=1.0)
    ma_filter_window: int = Field(5, ge=1)

    max_position_ratio: float = Field(0.20, gt=0, le=1)
    daily_loss_limit: float = Field(-0.03, lt=0)
    stop_loss_ratio: float = Field(-0.02, lt=0)
    min_order_krw: int = Field(5000, ge=5000)
    cooldown_minutes: int = Field(30, ge=0, le=1440)  # 0 = 비활성
    fill_poll_interval_seconds: float = Field(1.0, ge=0.5, le=10.0)
    fill_poll_timeout_seconds: float = Field(10.0, ge=1.0, le=60.0)
    api_max_retries: int = Field(3, ge=0)

    paper_initial_krw: float = Field(1_000_000.0, gt=0)
    check_interval_seconds: int = Field(60, ge=5)
    heartbeat_interval_hours: int = Field(6, ge=0, le=24)  # 0 = 비활성
    exit_hour_kst: int = Field(8, ge=0, le=23)   # 다음날 09:00 직전 청산 (8시 55분)
    exit_minute_kst: int = Field(55, ge=0, le=59)
    daily_reset_hour_kst: int = Field(9, ge=0, le=23)

    state_dir: Path = Path("state")

    log_level: str = "INFO"
    log_dir: Path = Path("logs")

    @property
    def is_live(self) -> bool:
        return self.mode is Mode.LIVE and self.live_trading and not self.kill_switch

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token.get_secret_value()) and bool(self.telegram_chat_id)

    @property
    def portfolio_ticker_list(self) -> list[str]:
        """매매 대상 티커 목록. `tickers`(콤마) 우선, 비어있으면 `ticker` 하나로 폴백.

        진입 우선순위는 이 리스트의 순서대로다 — 앞 종목이 먼저 슬롯을 차지한다.
        """
        raw = [t.strip().upper() for t in self.tickers.split(",") if t.strip()]
        merged: list[str] = []
        for t in raw:
            if t and t not in merged:
                merged.append(t)
        if not merged and self.ticker:
            merged = [self.ticker.upper()]
        return merged

    @property
    def watch_ticker_list(self) -> list[str]:
        """매매 대상(portfolio) + watch_tickers(관측 전용) 중복 제거 목록."""
        raw = [t.strip().upper() for t in self.watch_tickers.split(",") if t.strip()]
        merged: list[str] = []
        for t in [*self.portfolio_ticker_list, *raw]:
            if t and t not in merged:
                merged.append(t)
        return merged


def load_settings() -> Settings:
    return Settings()
