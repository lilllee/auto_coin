"""엔트리포인트.

설정 → 부품 조립 → APScheduler 시작 → SIGINT/SIGTERM에 우아하게 종료.
페이퍼 모드가 디폴트. 실거래는 `--live` 또는 `LIVE_TRADING=1`로만 활성화된다.
"""

from __future__ import annotations

import argparse
import signal
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from auto_coin import __version__
from auto_coin.bot import TradingBot
from auto_coin.config import Mode, Settings, load_settings
from auto_coin.exchange.upbit_client import UpbitClient
from auto_coin.executor.order import OrderExecutor
from auto_coin.executor.store import OrderStore
from auto_coin.logging_setup import setup_logging
from auto_coin.notifier.telegram import TelegramNotifier
from auto_coin.risk.manager import RiskManager
from auto_coin.strategy.volatility_breakout import VolatilityBreakout


def build_bot(settings: Settings) -> tuple[TradingBot, TelegramNotifier]:
    client = UpbitClient(
        access_key=settings.upbit_access_key.get_secret_value(),
        secret_key=settings.upbit_secret_key.get_secret_value(),
        max_retries=settings.api_max_retries,
    )
    tickers = settings.portfolio_ticker_list
    if not tickers:
        raise ValueError(
            "no trading targets — set TICKER or TICKERS in .env"
        )
    stores: dict[str, OrderStore] = {}
    executors: dict[str, OrderExecutor] = {}
    for t in tickers:
        safe = t.replace("/", "_")
        stores[t] = OrderStore(settings.state_dir / f"{safe}.json")
        executors[t] = OrderExecutor(client, stores[t], t, live=settings.is_live)

    strategy = VolatilityBreakout(k=settings.strategy_k, ma_window=settings.ma_filter_window)
    risk_manager = RiskManager(settings)
    notifier = TelegramNotifier(
        bot_token=settings.telegram_bot_token.get_secret_value(),
        chat_id=settings.telegram_chat_id,
    )
    bot = TradingBot(
        settings=settings,
        client=client,
        strategy=strategy,
        risk_manager=risk_manager,
        stores=stores,
        executors=executors,
        notifier=notifier,
    )
    return bot, notifier


def run_scheduler(bot: TradingBot, settings: Settings, notifier: TelegramNotifier) -> int:
    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        bot.tick,
        IntervalTrigger(seconds=settings.check_interval_seconds),
        id="tick",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        bot.daily_reset,
        CronTrigger(hour=settings.daily_reset_hour_kst, minute=0, second=0,
                    timezone="Asia/Seoul"),
        id="daily_reset",
    )
    scheduler.add_job(
        bot.force_exit_if_holding,
        CronTrigger(hour=settings.exit_hour_kst, minute=settings.exit_minute_kst, second=0,
                    timezone="Asia/Seoul"),
        id="force_exit",
    )
    # 일일 리셋 직전 리포트 (force_exit 08:55 이후, daily_reset 09:00 이전)
    scheduler.add_job(
        bot.daily_report,
        CronTrigger(hour=settings.exit_hour_kst, minute=58, second=0,
                    timezone="Asia/Seoul"),
        id="daily_report",
    )
    # watch — 관측 대상 티커들에 대해 주기적으로 신호 상태를 텔레그램 전송
    if settings.watch_interval_minutes > 0 and settings.watch_ticker_list:
        scheduler.add_job(
            bot.watch,
            IntervalTrigger(minutes=settings.watch_interval_minutes),
            id="watch",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(),
        )

    # heartbeat — 봇이 살아있음을 주기적으로 알림
    if settings.heartbeat_interval_hours > 0:
        scheduler.add_job(
            bot.heartbeat,
            IntervalTrigger(hours=settings.heartbeat_interval_hours),
            id="heartbeat",
        )

    def shutdown(signum, _frame):
        logger.info("received signal {} — shutting down", signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    tickers = settings.portfolio_ticker_list
    notifier.send(
        f"🚀 auto_coin v{__version__} started (mode={settings.mode.value}, "
        f"live={settings.is_live}, tickers={','.join(tickers)}, "
        f"max_concurrent={settings.max_concurrent_positions}, k={settings.strategy_k})"
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        notifier.send("🛑 auto_coin stopped")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="auto-coin")
    p.add_argument("--once", action="store_true", help="단일 tick 실행 후 종료 (디버그)")
    p.add_argument("--live", action="store_true",
                   help="실거래 모드 강제 활성화 (LIVE_TRADING=1과 동치, kill_switch가 우선)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = load_settings()
    if args.live:
        settings = settings.model_copy(update={"mode": Mode.LIVE, "live_trading": True})

    setup_logging(level=settings.log_level, log_dir=settings.log_dir)
    logger.info(
        "auto_coin v{} starting (mode={}, live={}, kill_switch={}, tickers={}, max_concurrent={})",
        __version__, settings.mode.value, settings.is_live, settings.kill_switch,
        ",".join(settings.portfolio_ticker_list), settings.max_concurrent_positions,
    )

    if settings.is_live:
        logger.warning("⚠️  LIVE TRADING MODE — orders will hit the real exchange")

    bot, notifier = build_bot(settings)

    if args.once:
        logger.info("--once: running single tick and exiting")
        bot.tick()
        return 0

    return run_scheduler(bot, settings, notifier)


if __name__ == "__main__":
    sys.exit(main())
