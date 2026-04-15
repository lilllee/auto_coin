"""TradingBot + APScheduler 수명 관리.

FastAPI lifespan에서 `start()`, 종료 시 `stop()`.
설정 변경 시 `reload()`로 새 `Settings`를 읽어 bot을 재구성하고 스케줄 잡을 재등록.

tick이 도는 동안 reload가 호출되어도 안전하도록 `threading.Lock`으로 가드.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from sqlmodel import Session

from auto_coin import __version__
from auto_coin.bot import TradingBot
from auto_coin.config import Settings
from auto_coin.exchange.upbit_client import UpbitClient
from auto_coin.executor.order import OrderExecutor
from auto_coin.executor.store import OrderStore
from auto_coin.notifier.telegram import TelegramNotifier
from auto_coin.risk.manager import RiskManager
from auto_coin.strategy import create_strategy
from auto_coin.web import db as web_db
from auto_coin.web.crypto import SecretBox
from auto_coin.web.settings_service import load_runtime_settings


class BotManager:
    """TradingBot + BackgroundScheduler 단일 인스턴스."""

    def __init__(self, box: SecretBox, timezone: str = "Asia/Seoul") -> None:
        self._box = box
        self._tz = timezone
        self._lock = threading.Lock()
        self._scheduler: BackgroundScheduler | None = None
        self._bot: TradingBot | None = None
        self._settings: Settings | None = None
        self._started_at: datetime | None = None

    # ----- public API --------------------------------------------------

    @property
    def running(self) -> bool:
        return self._scheduler is not None and self._scheduler.running

    @property
    def settings(self) -> Settings | None:
        return self._settings

    @property
    def bot(self) -> TradingBot | None:
        return self._bot

    @property
    def started_at(self) -> datetime | None:
        return self._started_at

    def start(self) -> None:
        with self._lock:
            if self.running:
                logger.warning("BotManager.start called but already running")
                return
            self._build_bot()
            self._scheduler = BackgroundScheduler(timezone=self._tz)
            self._register_jobs()
            self._scheduler.start()
            self._started_at = datetime.utcnow()
            logger.info("BotManager started (v{})", __version__)
            if self._bot is not None:
                self._bot._notifier.send(
                    f"🚀 auto_coin v{__version__} started "
                    f"(mode={self._settings.mode.value}, live={self._settings.is_live}, "
                    f"tickers={','.join(self._settings.portfolio_ticker_list)})"
                )

    def stop(self, *, notify: bool = True) -> None:
        with self._lock:
            if self._scheduler is not None and self._scheduler.running:
                self._scheduler.shutdown(wait=False)
            self._scheduler = None
            if notify and self._bot is not None:
                self._bot._notifier.send("🛑 auto_coin stopped")
            self._bot = None
            self._started_at = None
            logger.info("BotManager stopped")

    def reload(self) -> None:
        """설정 변경 반영: 현재 scheduler 종료 → 새 설정으로 bot 재빌드 → 재등록."""
        with self._lock:
            was_running = self._scheduler is not None and self._scheduler.running
            if was_running:
                self._scheduler.shutdown(wait=False)
            self._build_bot()
            self._scheduler = BackgroundScheduler(timezone=self._tz)
            self._register_jobs()
            if was_running:
                self._scheduler.start()
                self._started_at = datetime.utcnow()
            logger.info("BotManager reloaded (running={})", was_running)
            if was_running and self._bot is not None:
                self._bot._notifier.send(
                    f"🔄 auto_coin reloaded "
                    f"(tickers={','.join(self._settings.portfolio_ticker_list)}, "
                    f"k={self._settings.strategy_k})"
                )

    # ----- internals ---------------------------------------------------

    def _build_bot(self) -> None:
        """현재 DB 설정을 기반으로 TradingBot 인스턴스를 새로 조립."""
        with Session(web_db.engine()) as s:
            settings = load_runtime_settings(s, self._box)
        self._settings = settings

        client = UpbitClient(
            access_key=settings.upbit_access_key.get_secret_value(),
            secret_key=settings.upbit_secret_key.get_secret_value(),
            max_retries=settings.api_max_retries,
        )
        tickers = settings.portfolio_ticker_list
        state_dir = Path(settings.state_dir)
        stores: dict[str, OrderStore] = {}
        executors: dict[str, OrderExecutor] = {}
        for t in tickers:
            safe = t.replace("/", "_")
            stores[t] = OrderStore(state_dir / f"{safe}.json")
            executors[t] = OrderExecutor(
                client, stores[t], t, live=settings.is_live,
                fill_poll_interval=settings.fill_poll_interval_seconds,
                fill_poll_timeout=settings.fill_poll_timeout_seconds,
            )

        notifier = TelegramNotifier(
            bot_token=settings.telegram_bot_token.get_secret_value(),
            chat_id=settings.telegram_chat_id,
        )
        import json as _json
        strategy_params: dict = {}
        if settings.strategy_params_json:
            strategy_params = _json.loads(settings.strategy_params_json)
        # Backward compat: if no params_json, use legacy fields for VB
        if not strategy_params and settings.strategy_name == "volatility_breakout":
            strategy_params = {"k": settings.strategy_k, "ma_window": settings.ma_filter_window}
        self._bot = TradingBot(
            settings=settings, client=client,
            strategy=create_strategy(settings.strategy_name, strategy_params),
            risk_manager=RiskManager(settings),
            stores=stores, executors=executors,
            notifier=notifier,
        )

    def _register_jobs(self) -> None:
        assert self._scheduler is not None and self._bot is not None and self._settings is not None
        s = self._settings
        sch = self._scheduler
        bot = self._bot

        sch.add_job(bot.tick, IntervalTrigger(seconds=s.check_interval_seconds),
                    id="tick", max_instances=1, coalesce=True)
        sch.add_job(bot.daily_reset,
                    CronTrigger(hour=s.daily_reset_hour_kst, minute=0, second=0, timezone=self._tz),
                    id="daily_reset")
        if s.time_exit_enabled:
            sch.add_job(bot.force_exit_if_holding,
                        CronTrigger(hour=s.exit_hour_kst, minute=s.exit_minute_kst, second=0,
                                    timezone=self._tz),
                        id="force_exit")
        sch.add_job(bot.daily_report,
                    CronTrigger(hour=s.exit_hour_kst, minute=58, second=0, timezone=self._tz),
                    id="daily_report")
        if s.watch_interval_minutes > 0 and s.watch_ticker_list:
            sch.add_job(bot.watch, IntervalTrigger(minutes=s.watch_interval_minutes),
                        id="watch", max_instances=1, coalesce=True,
                        next_run_time=datetime.now())
        if s.heartbeat_interval_hours > 0:
            sch.add_job(bot.heartbeat,
                        IntervalTrigger(hours=s.heartbeat_interval_hours),
                        id="heartbeat")
