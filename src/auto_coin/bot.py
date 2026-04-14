"""트레이딩 봇 오케스트레이터.

단일 종목일 때도 동작하도록 설계되었지만, 내부 구조는 **멀티 종목 포트폴리오**를
기본 전제로 한다. `TradingBot`은 ticker별 `OrderStore`/`OrderExecutor` dict를 보유한다.

스케줄러가 주기적으로 `tick()`/`daily_reset()`/`force_exit_if_holding()`/
`heartbeat()`/`watch()`/`daily_report()`를 호출한다.
"""

from __future__ import annotations

from loguru import logger

from auto_coin.config import Settings
from auto_coin.data.candles import fetch_daily
from auto_coin.exchange.upbit_client import UpbitClient, UpbitError
from auto_coin.executor.order import OrderExecutor
from auto_coin.executor.store import OrderRecord, OrderStore, today_utc
from auto_coin.formatting import format_price
from auto_coin.notifier.telegram import TelegramNotifier
from auto_coin.reporter import build_daily_report
from auto_coin.risk.manager import Action, Decision, RiskContext, RiskManager
from auto_coin.strategy.base import MarketSnapshot
from auto_coin.strategy.volatility_breakout import VolatilityBreakout


class TradingBot:
    def __init__(
        self,
        *,
        settings: Settings,
        client: UpbitClient,
        strategy: VolatilityBreakout,
        risk_manager: RiskManager,
        stores: dict[str, OrderStore],
        executors: dict[str, OrderExecutor],
        notifier: TelegramNotifier,
    ) -> None:
        self._s = settings
        self._client = client
        self._strategy = strategy
        self._risk = risk_manager
        self._stores = stores
        self._executors = executors
        self._notifier = notifier
        self._tickers = list(stores.keys())  # 진입 우선순위는 dict 삽입 순서

    # ----- main loop steps -----

    def tick(self) -> list[OrderRecord]:
        """1회 사이클. 스케줄러가 `check_interval_seconds`마다 호출.

        모든 예외를 삼켜 다음 tick이 계속 돌게 한다. 예상 외 예외는 텔레그램으로 강제 알림.
        반환: 이번 tick에서 체결된 주문 목록 (대부분의 tick은 빈 리스트).
        """
        try:
            return self._tick_impl()
        except Exception as exc:  # pragma: no cover - 안전망
            logger.exception("tick crashed unexpectedly")
            self._notifier.send(f"🔥 tick crashed: {type(exc).__name__}: {exc}")
            return []

    def _tick_impl(self) -> list[OrderRecord]:
        results: list[OrderRecord] = []
        # 포트폴리오 스냅샷 (1 tick 안에서는 고정)
        open_positions = self._count_open_positions()
        total_daily_pnl = self._total_daily_pnl_ratio()

        for ticker in self._tickers:
            store = self._stores[ticker]
            executor = self._executors[ticker]
            try:
                df = fetch_daily(
                    self._client,
                    ticker,
                    count=max(self._s.ma_filter_window + 50, 60),
                    ma_window=self._s.ma_filter_window,
                    k=self._s.strategy_k,
                )
                price = self._client.get_current_price(ticker)
            except UpbitError as exc:
                logger.error("market data fetch failed for {}: {}", ticker, exc)
                self._notifier.send(f"⚠️ {ticker} market data fetch failed: {exc}")
                continue

            state = store.load()
            coin_balance = state.position.volume if state.position else 0.0
            avg_entry = state.position.avg_entry_price if state.position else None
            krw_balance = self._krw_slot_budget(executor.live)

            snap = MarketSnapshot(df=df, current_price=price, has_position=coin_balance > 0)
            signal = self._strategy.generate_signal(snap)

            ctx = RiskContext(
                krw_balance=krw_balance,
                coin_balance=coin_balance,
                current_price=price,
                avg_entry_price=avg_entry,
                daily_pnl_ratio=total_daily_pnl,
                portfolio_open_positions=open_positions,
                portfolio_max_positions=self._s.max_concurrent_positions,
            )
            decision = self._risk.evaluate(signal, ctx)
            logger.debug("tick {}: signal={} decision={} reason={}",
                         ticker, signal.value, decision.action.value, decision.reason)

            if decision.action is Action.HOLD:
                continue

            try:
                record = executor.execute(decision, current_price=price)
            except UpbitError as exc:
                logger.error("order failed for {}: {}", ticker, exc)
                self._notifier.send(f"❌ {ticker} order failed: {exc}")
                continue

            if record is None:
                continue

            # 포트폴리오 슬롯 카운트 업데이트 — 다음 종목 판단에 반영
            if record.side == "buy":
                open_positions += 1
            elif record.side == "sell":
                open_positions = max(0, open_positions - 1)

            side_emoji = "🟢" if record.side == "buy" else "🔴"
            self._notifier.send(
                f"{side_emoji} {record.side.upper()} {record.market} "
                f"@ {format_price(price)} (mode={'live' if executor.live else 'paper'}) "
                f"— {decision.reason}"
            )
            results.append(record)

        return results

    def daily_reset(self) -> None:
        """KST 09:00 — 모든 종목의 일일 손익 누적 초기화."""
        prev_total = self._total_daily_pnl_ratio()
        for store in self._stores.values():
            state = store.load()
            state.daily_pnl_ratio = 0.0
            state.daily_pnl_date = today_utc()
            store.save(state)
        logger.info("daily reset — previous day portfolio pnl was {:+.2%}", prev_total)
        self._notifier.send(f"📊 daily reset — yesterday portfolio pnl: {prev_total*100:+.2f}%")

    def heartbeat(self) -> None:
        """주기 heartbeat — 봇이 살아있음을 알린다."""
        open_positions = self._count_open_positions()
        total_pnl = self._total_daily_pnl_ratio()
        mode = "live" if any(e.live for e in self._executors.values()) else "paper"
        lines = [
            f"💓 heartbeat · mode={mode} · "
            f"positions {open_positions}/{self._s.max_concurrent_positions} · "
            f"daily_pnl={total_pnl*100:+.2f}%"
        ]
        for ticker in self._tickers:
            state = self._stores[ticker].load()
            pos = state.position
            if pos is None:
                continue
            lines.append(
                f"  · {ticker} vol={pos.volume:.8f} entry={format_price(pos.avg_entry_price)}"
            )
        msg = "\n".join(lines)
        logger.info(msg)
        self._notifier.send(msg)

    def watch(self) -> None:
        """관측 전용 — watch_ticker_list의 각 티커에 대해 현재가/target/MA 상태를
        계산해 텔레그램에 요약 1건으로 전송. 주문은 하지 않는다.
        """
        tickers = self._s.watch_ticker_list
        if not tickers:
            return
        lines: list[str] = []
        for ticker in tickers:
            try:
                df = fetch_daily(
                    self._client,
                    ticker,
                    count=max(self._s.ma_filter_window + 50, 60),
                    ma_window=self._s.ma_filter_window,
                    k=self._s.strategy_k,
                )
                price = self._client.get_current_price(ticker)
            except UpbitError as exc:
                lines.append(f"• {ticker}: fetch 실패 ({exc})")
                continue

            last = df.iloc[-1]
            target = last.get("target")
            ma_col = f"ma{self._s.ma_filter_window}"
            ma = last.get(ma_col) if ma_col in df.columns else None

            try:
                target_f = float(target) if target == target else None  # NaN 체크
            except (TypeError, ValueError):
                target_f = None
            try:
                ma_f = float(ma) if ma is not None and ma == ma else None
            except (TypeError, ValueError):
                ma_f = None

            if target_f is None:
                lines.append(f"• {ticker} {format_price(price)} (target N/A)")
                continue

            gap = (price - target_f) / target_f * 100
            mark = "🚀" if price >= target_f else "·"
            ma_mark = ""
            if ma_f is not None:
                ma_mark = " ↑MA" if price > ma_f else " ↓MA"
            lines.append(
                f"{mark} {ticker} {format_price(price)} / target {format_price(target_f)} "
                f"({gap:+.2f}%){ma_mark}"
            )

        msg = "👀 watch\n" + "\n".join(lines)
        logger.info("watch:\n{}", msg)
        self._notifier.send(msg)

    def daily_report(self) -> str:
        """지난 24시간 요약 — 포트폴리오 합계 + 종목별 개별 리포트."""
        lines: list[str] = []
        combined_orders = []
        for ticker in self._tickers:
            state = self._stores[ticker].load()
            combined_orders.extend(state.orders)
        # 합계 리포트 1건
        total_daily_pnl = self._total_daily_pnl_ratio()
        merged_state_like = self._stores[self._tickers[0]].load() if self._tickers else None
        if merged_state_like is not None:
            merged_state_like.orders = combined_orders
            merged_state_like.daily_pnl_ratio = total_daily_pnl
            lines.append("📊 Portfolio (last 24h)")
            lines.append(build_daily_report(merged_state_like, hours=24))
        # 종목별 개별 리포트
        for ticker in self._tickers:
            state = self._stores[ticker].load()
            if not state.orders and state.position is None:
                continue
            lines.append(f"\n── {ticker} ──")
            lines.append(build_daily_report(state, hours=24))

        text = "\n".join(lines) if lines else "📊 Daily report: no activity"
        logger.info("daily report:\n{}", text)
        self._notifier.send(text)
        return text

    def force_exit_if_holding(self) -> list[OrderRecord]:
        """KST 08:55 — 보유 중인 모든 종목을 일괄 청산."""
        results: list[OrderRecord] = []
        for ticker in self._tickers:
            store = self._stores[ticker]
            executor = self._executors[ticker]
            state = store.load()
            if state.position is None:
                continue
            try:
                price = self._client.get_current_price(ticker)
            except UpbitError as exc:
                logger.error("force_exit price fetch failed for {}: {}", ticker, exc)
                continue

            decision = Decision(
                action=Action.SELL,
                reason="exit window (next-day open)",
                volume=state.position.volume,
            )
            try:
                record = executor.execute(decision, current_price=price)
            except UpbitError as exc:
                logger.error("force_exit order failed for {}: {}", ticker, exc)
                self._notifier.send(f"❌ {ticker} force_exit failed: {exc}")
                continue
            if record is not None:
                self._notifier.send(
                    f"⏰ exit window SELL {record.market} @ {format_price(price)} "
                    f"(mode={'live' if executor.live else 'paper'})"
                )
                results.append(record)
        return results

    # ----- helpers -----

    def _count_open_positions(self) -> int:
        return sum(1 for s in self._stores.values() if s.load().position is not None)

    def _total_daily_pnl_ratio(self) -> float:
        return sum(s.load().daily_pnl_ratio for s in self._stores.values())

    def _krw_slot_budget(self, is_live: bool) -> float:
        """한 종목 진입 시 "사용 가능한 KRW 잔고"로 리포트할 값.

        진입 크기는 `max_position_ratio × krw_balance`로 계산되므로, 이 함수가 돌려주는
        KRW가 실질적인 "1슬롯 예산"이다.

        - **live 모드**: 실제 거래소 잔고를 그대로 사용 (업비트가 이중 진입 방지)
        - **paper 모드**: `paper_initial_krw`를 그대로 반환.
          진입 크기가 `paper_initial_krw × max_position_ratio`로 고정되므로, 종목을
          몇 개 보유했든 새 진입은 항상 **초기 자본 기준의 균등 슬롯**을 쓴다.
        """
        if self._client.authenticated and is_live:
            try:
                return self._client.get_krw_balance()
            except UpbitError as exc:
                logger.warning("krw balance fetch failed, falling back to paper: {}", exc)
        return float(self._s.paper_initial_krw)
