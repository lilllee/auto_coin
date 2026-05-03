from enum import StrEnum
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

UPBIT_FEE_RATE: float = 0.0005  # Upbit 0.05% per trade (buy + sell)


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
    max_daily_stop_losses: int = Field(2, ge=1)  # 당일 종목별 최대 손절 횟수 (초과 시 신규 진입 차단)
    fill_poll_interval_seconds: float = Field(1.0, ge=0.5, le=10.0)
    fill_poll_timeout_seconds: float = Field(10.0, ge=1.0, le=60.0)
    api_max_retries: int = Field(3, ge=0)

    paper_initial_krw: float = Field(1_000_000.0, gt=0)
    # 30s가 현실적 floor: 5s는 종목 polling/fill polling 누적시 max_instances skip 유발.
    check_interval_seconds: int = Field(30, ge=30)
    heartbeat_interval_hours: int = Field(6, ge=0, le=24)  # 0 = 비활성
    use_websocket: bool = Field(default=False, description="WebSocket 실시간 가격 피드 사용")
    exit_hour_kst: int = Field(8, ge=0, le=23)   # 다음날 09:00 직전 청산 (8시 55분)
    exit_minute_kst: int = Field(55, ge=0, le=59)
    daily_reset_hour_kst: int = Field(9, ge=0, le=23)

    state_dir: Path = Path("state")

    log_level: str = "INFO"
    log_dir: Path = Path("logs")

    # --- V4 portfolio-aware infra (B2 skeleton) ---
    # CSMOM / RCDB 등 multi-asset 전략이 사용할 sizing · 그룹 태그 입력창.
    # 아직 DB AppSettings 에 매핑되지 않음 (legacy 단일자산 경로에서는 None/default 유지).
    active_strategy_group: str = Field(
        default="legacy_single_ticker",
        description="실행 중인 전략군 태그. DailySnapshot.active_strategy_group 에 기록.",
    )
    risk_budget_krw: float | None = Field(
        default=None,
        description="volatility-scaled sizing 시 포지션당 위험 예산 (KRW). None 이면 비활성.",
    )
    atr_window_for_sizing: int = Field(
        default=20, ge=1, le=200,
        description="vol-scaled sizing 용 ATR 기간 (CSMOM 등 multi-asset 전략).",
    )
    portfolio_rebal_days: int = Field(
        default=7, ge=1, le=90,
        description="portfolio 리밸런싱 주기 (일). legacy 경로에서는 사용 안 함.",
    )

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

    @property
    def time_exit_enabled(self) -> bool:
        """전략별 시간 청산 사용 여부.

        합성 전략(`sma200_ema_adx_composite`)은 추세를 길게 가져가는 설계라
        전역 08:55 강제 청산을 비활성화한다. 기존 변동성 돌파 계열 전략은
        현재 동작을 유지한다.
        """
        return self.strategy_name not in {"sma200_ema_adx_composite", "vwap_ema_pullback"}


def load_settings() -> Settings:
    return Settings()
