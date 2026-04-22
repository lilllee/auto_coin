"""트레이딩 봇 오케스트레이터.

단일 종목일 때도 동작하도록 설계되었지만, 내부 구조는 **멀티 종목 포트폴리오**를
기본 전제로 한다. `TradingBot`은 ticker별 `OrderStore`/`OrderExecutor` dict를 보유한다.

스케줄러가 주기적으로 `tick()`/`daily_reset()`/`force_exit_if_holding()`/
`heartbeat()`/`watch()`/`daily_report()`를 호출한다.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time

from loguru import logger

from auto_coin.config import Settings
from auto_coin.data.candle_cache import DailyCandleCache
from auto_coin.data.candles import (  # noqa: F401 — fetch_daily used by test mocks
    fetch_daily,
    recommended_history_days,
)
from auto_coin.exchange.upbit_client import AssetBalance, UpbitClient, UpbitError
from auto_coin.exchange.ws_client import UpbitWebSocket
from auto_coin.exchange.ws_private import UpbitPrivateWebSocket
from auto_coin.executor.order import OrderExecutor
from auto_coin.executor.store import OrderRecord, OrderStore, Position, State, now_iso, today_utc
from auto_coin.formatting import format_price
from auto_coin.notifier.telegram import TelegramNotifier
from auto_coin.reporter import build_daily_report
from auto_coin.risk.manager import Action, Decision, RiskContext, RiskManager
from auto_coin.strategy import STRATEGY_ENTRY_CONFIRMATION, STRATEGY_EXECUTION_MODE
from auto_coin.strategy.base import MarketSnapshot, Signal, Strategy


class TradingBot:
    def __init__(
        self,
        *,
        settings: Settings,
        client: UpbitClient,
        strategy: Strategy,
        risk_manager: RiskManager,
        stores: dict[str, OrderStore],
        executors: dict[str, OrderExecutor],
        notifier: TelegramNotifier,
        ws_client: UpbitWebSocket | None = None,
        ws_private: UpbitPrivateWebSocket | None = None,
        snapshot_writer=None,
        trade_log_query=None,
    ) -> None:
        self._s = settings
        self._client = client
        self._strategy = strategy
        self._risk = risk_manager
        self._stores = stores
        self._executors = executors
        self._notifier = notifier
        self._ws = ws_client
        self._ws_private = ws_private
        self._snapshot_writer = snapshot_writer
        self._trade_log_query = trade_log_query
        self._tickers = list(stores.keys())  # 진입 우선순위는 dict 삽입 순서
        self._strategy_name = strategy.name
        self._strategy_params: dict = {}
        if settings.strategy_params_json:
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                self._strategy_params = json.loads(settings.strategy_params_json)
        self._candle_cache = DailyCandleCache()
        self._pending_buys: dict[str, int] = {}  # ticker → 연속 BUY 신호 횟수
        self._entry_confirmation_ticks = STRATEGY_ENTRY_CONFIRMATION.get(
            strategy.name, 0
        )
        self._execution_mode = STRATEGY_EXECUTION_MODE.get(strategy.name, "intraday")
        self._entry_evaluated: dict[str, str] = {}  # ticker → trading_day (평가 완료 표시)
        self._stop_loss_counts: dict[str, int] = {}  # ticker → 당일 손절 횟수

        # WS 이벤트 드리븐 긴급 손절
        self._position_cache: dict[str, tuple[float, float]] = {}  # ticker → (avg_entry, volume)
        self._exit_in_flight: dict[str, bool] = {}
        self._exit_cooldown: dict[str, float] = {}  # ticker → cooldown 해제 시각
        self._exit_lock = threading.Lock()

        # 초기 포지션 ��시 구축
        for _t, _store in self._stores.items():
            _state = _store.load()
            if _state.position and _state.position.volume > 0:
                self._position_cache[_t] = (
                    _state.position.avg_entry_price,
                    _state.position.volume,
                )

        # WS 가격 콜백 등록 — 긴급 손절 판단
        if self._ws:
            self._ws.set_price_callback(self._on_ws_price)

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

        # 현재가 일괄 조회 (WebSocket 우선, REST fallback)
        try:
            price_map = self._get_prices(self._tickers)
        except UpbitError as exc:
            logger.error("batch price fetch failed: {}", exc)
            self._notifier.send(f"⚠️ batch price fetch failed: {exc}")
            return results

        for ticker in self._tickers:
            # WS 긴급 exit 진행 중이면 해당 종목 건너뜀
            with self._exit_lock:
                if self._exit_in_flight.get(ticker):
                    logger.debug("tick {}: skip — ws emergency exit in progress", ticker)
                    continue

            store = self._stores[ticker]
            executor = self._executors[ticker]

            # 현재가 누락 시 skip
            price = price_map.get(ticker)
            if price is None or price <= 0:
                logger.warning("no price for {} — skipping", ticker)
                continue

            try:
                extra_count = self._extra_candle_count()
                df = self._candle_cache.get(
                    self._client,
                    ticker,
                    count=max(
                        self._s.ma_filter_window + 50,
                        60,
                        extra_count,
                    ),
                    ma_window=self._s.ma_filter_window,
                    k=self._s.strategy_k,
                    strategy_name=self._strategy_name,
                    strategy_params=self._strategy_params,
                )
            except UpbitError as exc:
                logger.error("candle fetch failed for {}: {}", ticker, exc)
                self._notifier.send(f"⚠️ {ticker} candle fetch failed: {exc}")
                continue

            state = store.load()
            coin_balance = state.position.volume if state.position else 0.0
            avg_entry = state.position.avg_entry_price if state.position else None
            krw_balance = self._krw_slot_budget(executor.live)

            # 포지션 캐시 갱신 (WS 긴급 손절 판단용)
            if state.position and coin_balance > 0:
                self._position_cache[ticker] = (
                    state.position.avg_entry_price,
                    state.position.volume,
                )
            else:
                self._position_cache.pop(ticker, None)

            # daily_confirm 모드: 미보유 시 거래일당 1회만 BUY 평가
            _daily_confirm_pending = False
            if self._execution_mode == "daily_confirm" and coin_balance <= 0:
                trading_day = self._current_trading_day()
                if self._entry_evaluated.get(ticker) == trading_day:
                    # 이미 오늘 평가 완료 — BUY skip, 손절/SELL 대상 아님(미보유)
                    continue
                _daily_confirm_pending = True
                logger.info("tick {}: daily_confirm entry evaluation (once per day)", ticker)

            snap = MarketSnapshot(df=df, current_price=price, has_position=coin_balance > 0)
            signal = self._strategy.generate_signal(snap)

            # 진입 확인 메커니즘 (BUY만, SELL/HOLD/손절 무관)
            if signal is Signal.BUY and self._entry_confirmation_ticks > 0:
                self._pending_buys[ticker] = self._pending_buys.get(ticker, 0) + 1
                pending = self._pending_buys[ticker]
                required = self._entry_confirmation_ticks
                if pending < required:
                    logger.info(
                        "tick {}: BUY pending ({}/{}) — waiting for confirmation",
                        ticker, pending, required,
                    )
                    continue
                logger.info(
                    "tick {}: BUY confirmed ({}/{}) — proceeding",
                    ticker, pending, required,
                )
                self._pending_buys[ticker] = 0
            elif signal is not Signal.BUY:
                if self._pending_buys.get(ticker, 0) > 0:
                    logger.debug("tick {}: pending BUY reset (signal={})", ticker, signal.value)
                self._pending_buys[ticker] = 0
                # daily_confirm이고 BUY가 아님 → 오늘 평가 완료 (조건 미충족)
                if _daily_confirm_pending:
                    self._entry_evaluated[ticker] = self._current_trading_day()
                    logger.info("tick {}: daily_confirm evaluated — no entry today", ticker)

            ctx = RiskContext(
                krw_balance=krw_balance,
                coin_balance=coin_balance,
                current_price=price,
                avg_entry_price=avg_entry,
                daily_pnl_ratio=total_daily_pnl,
                portfolio_open_positions=open_positions,
                portfolio_max_positions=self._s.max_concurrent_positions,
                cooldown_active=self._is_cooldown_active(state),
                stop_loss_count_today=self._stop_loss_counts.get(ticker, 0),
            )
            decision = self._risk.evaluate(signal, ctx)
            logger.debug("tick {}: signal={} decision={} reason={}",
                         ticker, signal.value, decision.action.value, decision.reason)

            # daily_confirm 표시 (BUY 평가 완료 — HOLD/SELL 포함)
            if _daily_confirm_pending:
                self._entry_evaluated[ticker] = self._current_trading_day()

            if decision.action is Action.HOLD:
                continue

            effective_decision = self._prepare_live_sell_decision(
                ticker,
                decision,
                source="tick",
            )
            if effective_decision is None:
                continue

            try:
                record = executor.execute(effective_decision, current_price=price)
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

            # 손절 카운트
            if record.side == "sell" and effective_decision.reason_code == "stop_loss":
                self._stop_loss_counts[ticker] = self._stop_loss_counts.get(ticker, 0) + 1
                sl_count = self._stop_loss_counts[ticker]
                logger.warning(
                    "tick {}: stop-loss count {}/{}",
                    ticker, sl_count, self._s.max_daily_stop_losses,
                )
                if sl_count >= self._s.max_daily_stop_losses:
                    self._notifier.send(
                        f"🔒 {ticker} locked for today: {sl_count} stop-losses"
                    )

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
        self._save_daily_snapshot()
        self._candle_cache.invalidate()
        self._pending_buys.clear()
        self._entry_evaluated.clear()
        self._stop_loss_counts.clear()
        prev_total = self._total_daily_pnl_ratio()
        for store in self._stores.values():
            state = store.load()
            state.daily_pnl_ratio = 0.0
            state.daily_pnl_date = today_utc()
            state.last_exit_at = ""
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

        try:
            price_map = self._get_prices(tickers)
        except UpbitError as exc:
            logger.error("watch batch price failed: {}", exc)
            return

        lines: list[str] = []
        for ticker in tickers:
            price = price_map.get(ticker)
            if price is None:
                lines.append(f"• {ticker}: 현재가 조회 실패")
                continue
            try:
                extra_count = self._extra_candle_count()
                df = self._candle_cache.get(
                    self._client,
                    ticker,
                    count=max(
                        self._s.ma_filter_window + 50,
                        60,
                        extra_count,
                    ),
                    ma_window=self._s.ma_filter_window,
                    k=self._s.strategy_k,
                    strategy_name=self._strategy_name,
                    strategy_params=self._strategy_params,
                )
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
        # 보유 중인 종목 목록
        holding_tickers = [
            t for t in self._tickers
            if self._stores[t].load().position is not None
        ]
        if not holding_tickers:
            return results

        try:
            price_map = self._get_prices(holding_tickers)
        except UpbitError as exc:
            logger.error("force_exit batch price failed: {}", exc)
            return results

        for ticker in holding_tickers:
            # WS emergency exit 진행 중이면 중복 SELL 방지
            with self._exit_lock:
                if self._exit_in_flight.get(ticker):
                    logger.warning(
                        "force_exit skipped for {}: exit already in flight", ticker
                    )
                    continue

            store = self._stores[ticker]
            executor = self._executors[ticker]
            state = store.load()
            if state.position is None:
                continue

            price = price_map.get(ticker)
            if price is None or price <= 0:
                logger.error("force_exit: no price for {} — skipping", ticker)
                continue

            decision = Decision(
                action=Action.SELL,
                reason="exit window (next-day open)",
                volume=state.position.volume,
                reason_code="time_exit",
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

    def _get_prices(self, tickers: list[str]) -> dict[str, float]:
        """WebSocket 가격 우선, REST fallback."""
        if self._ws and self._ws.is_connected():
            ws_prices = self._ws.get_prices()
            # stale 종목 확인
            stale = set(self._ws.stale_tickers(max_age_seconds=60.0))
            available = {t: ws_prices[t] for t in tickers if t in ws_prices and t not in stale}
            if len(available) == len(tickers):
                return available
            # 부분만 있으면 누락분을 REST로 보충
            missing = [t for t in tickers if t not in available]
            if missing:
                try:
                    rest = self._client.get_current_prices(missing)
                    available.update(rest)
                except Exception:  # noqa: BLE001
                    pass  # 가능한 만큼 반환
            return available
        # WebSocket 없음 — 기존 REST 경로
        return self._client.get_current_prices(tickers)

    def _save_daily_snapshot(self) -> None:
        """Persist daily performance snapshot before reset."""
        if self._snapshot_writer is None:
            return
        try:
            from datetime import date as date_cls
            from datetime import timedelta, timezone

            kst = timezone(timedelta(hours=9))
            # Use the first store's daily_pnl_date as the trading day
            sample_state = next(iter(self._stores.values())).load()
            if sample_state.daily_pnl_date:
                snap_date = date_cls.fromisoformat(sample_state.daily_pnl_date)
            else:
                from datetime import datetime as _dt

                snap_date = (_dt.now(kst) - timedelta(days=1)).date()

            total_pnl = self._total_daily_pnl_ratio()
            open_pos = sum(1 for s in self._stores.values() if s.load().position is not None)

            # Count today's closed trades from TradeLog if available
            closed_count = 0
            win_count = 0
            loss_count = 0
            realized_krw = 0.0
            tradelog_pnl_ratio = None
            if self._trade_log_query:
                try:
                    stats = self._trade_log_query(snap_date)
                    closed_count = stats.get("closed_count", 0)
                    win_count = stats.get("win_count", 0)
                    loss_count = stats.get("loss_count", 0)
                    realized_krw = stats.get("realized_pnl_krw", 0.0)
                    tradelog_pnl_ratio = stats.get("total_pnl_ratio")
                except Exception:
                    logger.warning("trade log query for snapshot failed", exc_info=True)

            # live 모드: state 기반 daily_pnl_ratio는 항상 0이므로
            # TradeLog 기반 pnl_ratio 합을 사용한다.
            is_live = self._s.mode.value == "live" if hasattr(self._s.mode, "value") else str(self._s.mode) == "live"
            if is_live and tradelog_pnl_ratio is not None:
                total_pnl = tradelog_pnl_ratio

            self._snapshot_writer({
                "snapshot_date": snap_date,
                "mode": self._s.mode.value if hasattr(self._s.mode, "value") else str(self._s.mode),
                "strategy_name": self._strategy_name,
                "total_pnl_ratio": total_pnl,
                "open_positions": open_pos,
                "closed_trades_count": closed_count,
                "win_count": win_count,
                "loss_count": loss_count,
                "realized_pnl_krw": realized_krw,
            })
        except Exception:
            logger.warning("daily snapshot save failed", exc_info=True)

    def _current_trading_day(self) -> str:
        """KST 09:00 기준 거래일 키 반환."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        if now.hour < 9:
            now = now - timedelta(days=1)
        return now.strftime("%Y-%m-%d")

    def _extra_candle_count(self) -> int:
        """전략별 필요 캔들 수 계산."""
        return recommended_history_days(
            self._strategy_name,
            self._strategy_params,
            ma_window=self._s.ma_filter_window,
        )

    def _count_open_positions(self) -> int:
        return sum(1 for s in self._stores.values() if s.load().position is not None)

    def _total_daily_pnl_ratio(self) -> float:
        return sum(s.load().daily_pnl_ratio for s in self._stores.values())

    def _is_cooldown_active(self, state: State) -> bool:
        """최근 청산 이후 쿨다운 기간이 남아 있는지 확인."""
        if self._s.cooldown_minutes <= 0:
            return False
        if not state.last_exit_at:
            return False
        from datetime import UTC, datetime, timedelta
        try:
            exit_time = datetime.fromisoformat(state.last_exit_at)
            if exit_time.tzinfo is None:
                exit_time = exit_time.replace(tzinfo=UTC)
            cooldown_end = exit_time + timedelta(minutes=self._s.cooldown_minutes)
            return datetime.now(UTC) < cooldown_end
        except (ValueError, TypeError):
            return False

    # ----- WS event-driven emergency exit -----

    def _on_ws_price(self, code: str, price: float, ts: int) -> None:
        """WS 가격 이벤트 콜백 — 긴급 손절 판단. WS 스레드에서 호출된다."""
        try:
            self._check_emergency_exit(code, price)
        except Exception:
            logger.opt(exception=True).warning("ws emergency check failed for {}", code)

    def _check_emergency_exit(self, ticker: str, price: float) -> None:
        """포지션 캐시 기반으로 긴급 손절 조건을 확인한다."""
        # 1. 포지션 캐시 확인 (file I/O 없음)
        cached = self._position_cache.get(ticker)
        if not cached:
            return
        avg_entry, _ = cached
        if avg_entry <= 0:
            return

        # 2. 이미 exit 진행 중이거나 cooldown 중인지
        with self._exit_lock:
            if self._exit_in_flight.get(ticker):
                return
            cooldown_until = self._exit_cooldown.get(ticker, 0)
            if time.time() < cooldown_until:
                return

        # 3. stop-loss 조건 확인
        pnl_ratio = (price - avg_entry) / avg_entry
        if pnl_ratio >= self._s.stop_loss_ratio:
            return

        # 4. 긴급 SELL 트리거
        self._trigger_emergency_sell(
            ticker=ticker,
            price=price,
            reason_code="ws_stop_loss",
            reason=f"WS stop-loss ({pnl_ratio:.2%} <= {self._s.stop_loss_ratio:.2%})",
        )

    def _get_exchange_asset_balance(self, ticker: str) -> AssetBalance | None:
        """실거래 SELL 직전에 거래소 기준 잔고를 조회한다."""
        executor = self._executors[ticker]
        if not executor.live or not self._client.authenticated:
            return None
        holdings = self._client.get_holdings(include_zero=True, include_krw=False)
        for holding in holdings:
            if holding.market == ticker:
                return holding
        return None

    def _sync_local_position_from_exchange(
        self,
        ticker: str,
        asset: AssetBalance | None,
        *,
        reason: str,
    ) -> None:
        """거래소 잔고 기준으로 로컬 포지션 상태를 보정한다."""
        store = self._stores[ticker]
        epsilon = 1e-12

        def _update(state: State) -> State:
            position = state.position
            if position is None:
                return state

            total_volume = asset.total_volume if asset else 0.0
            if total_volume <= epsilon:
                state.position = None
                state.last_exit_at = now_iso()
                return state

            avg_entry_price = (
                asset.avg_buy_price
                if asset is not None and asset.avg_buy_price > 0
                else position.avg_entry_price
            )
            volume_close = abs(position.volume - total_volume) <= max(1e-12, position.volume * 1e-6)
            price_close = (
                abs(position.avg_entry_price - avg_entry_price)
                <= max(1e-9, position.avg_entry_price * 1e-6)
            )
            if volume_close and price_close:
                return state

            state.position = Position(
                ticker=position.ticker,
                volume=total_volume,
                avg_entry_price=avg_entry_price,
                entry_uuid=position.entry_uuid,
                entry_at=position.entry_at,
            )
            return state

        new_state = store.atomic_update(_update)
        if new_state.position is None:
            self._position_cache.pop(ticker, None)
            logger.warning(
                "position reconciled [{}]: local position cleared after {} (exchange balance empty)",
                ticker,
                reason,
            )
            return

        self._position_cache[ticker] = (
            new_state.position.avg_entry_price,
            new_state.position.volume,
        )
        logger.warning(
            "position reconciled [{}]: volume={:.8f} avg_entry={} after {}",
            ticker,
            new_state.position.volume,
            format_price(new_state.position.avg_entry_price),
            reason,
        )

    def _prepare_live_sell_decision(
        self,
        ticker: str,
        decision: Decision,
        *,
        source: str,
    ) -> Decision | None:
        """실거래 SELL 전에 거래소 가용 수량 기준으로 의사결정을 보정한다."""
        if decision.action is not Action.SELL:
            return decision
        executor = self._executors[ticker]
        if not executor.live or not self._client.authenticated:
            return decision

        try:
            asset = self._get_exchange_asset_balance(ticker)
        except UpbitError as exc:
            logger.warning("sell preflight holdings fetch failed for {} ({}): {}", ticker, source, exc)
            return decision

        if asset is None or asset.total_volume <= 1e-12:
            self._sync_local_position_from_exchange(
                ticker,
                asset,
                reason=f"{source} sell preflight",
            )
            return None

        available_volume = asset.balance
        if available_volume <= 1e-12 and asset.locked > 1e-12:
            logger.warning(
                "sell skipped for {} ({}): exchange available balance empty, locked={:.8f}",
                ticker,
                source,
                asset.locked,
            )
            return None

        desired_volume = decision.volume or 0.0
        if desired_volume > 0 and available_volume + 1e-12 < desired_volume:
            self._sync_local_position_from_exchange(
                ticker,
                asset,
                reason=f"{source} sell volume adjustment",
            )
            logger.warning(
                "sell volume adjusted for {} ({}): local={:.8f} -> exchange_available={:.8f}",
                ticker,
                source,
                desired_volume,
                available_volume,
            )
            return Decision(
                action=decision.action,
                reason=decision.reason,
                volume=available_volume,
                krw_amount=decision.krw_amount,
                reason_code=decision.reason_code,
            )

        return decision

    def _trigger_emergency_sell(
        self,
        ticker: str,
        price: float,
        reason_code: str,
        reason: str,
    ) -> None:
        """긴급 SELL을 트리거한다. 중복 방지 + 별도 스레드에서 실행."""
        with self._exit_lock:
            if self._exit_in_flight.get(ticker):
                return
            self._exit_in_flight[ticker] = True

        # store에서 포지션 재확인 (캐시 stale 방지)
        state = self._stores[ticker].load()
        if state.position is None or state.position.volume <= 0:
            self._position_cache.pop(ticker, None)
            with self._exit_lock:
                self._exit_in_flight[ticker] = False
            return

        volume = state.position.volume

        logger.warning(
            "🚨 EMERGENCY SELL [{}] price={} volume={} {}",
            ticker, format_price(price), volume, reason,
        )

        try:
            threading.Thread(
                target=self._execute_emergency_sell,
                args=(ticker, price, volume, reason_code, reason),
                daemon=True,
                name=f"ws-exit-{ticker}",
            ).start()
        except Exception:
            logger.exception("failed to spawn emergency sell thread for {}", ticker)
            with self._exit_lock:
                self._exit_in_flight[ticker] = False

    def _execute_emergency_sell(
        self,
        ticker: str,
        price: float,
        volume: float,
        reason_code: str,
        reason: str,
    ) -> None:
        """별도 스레드에서 긴급 SELL을 실행한다."""
        try:
            executor = self._executors[ticker]
            decision = Decision(
                action=Action.SELL,
                reason=reason,
                volume=volume,
                reason_code=reason_code,
            )
            effective_decision = self._prepare_live_sell_decision(
                ticker,
                decision,
                source="emergency",
            )
            if effective_decision is None:
                return
            record = executor.execute(effective_decision, current_price=price)
            if record:
                self._position_cache.pop(ticker, None)
                self._stop_loss_counts[ticker] = (
                    self._stop_loss_counts.get(ticker, 0) + 1
                )
                sl_count = self._stop_loss_counts[ticker]
                self._notifier.send(
                    f"🚨 EMERGENCY {record.side.upper()} {record.market} "
                    f"@ {format_price(price)} — {reason}"
                )
                if sl_count >= self._s.max_daily_stop_losses:
                    self._notifier.send(
                        f"🔒 {ticker} locked for today: {sl_count} stop-losses"
                    )
                logger.info(
                    "emergency sell complete [{}] side={} price={}",
                    ticker, record.side, format_price(price),
                )
        except UpbitError as exc:
            logger.error("emergency sell failed for {}: {}", ticker, exc)
            self._notifier.send(f"❌ {ticker} emergency sell failed: {exc}")
            with self._exit_lock:
                self._exit_cooldown[ticker] = time.time() + 30.0  # 30s cooldown
        except Exception:
            logger.exception("emergency sell crashed for {}", ticker)
            self._notifier.send(f"❌ {ticker} emergency sell crashed (see logs)")
            with self._exit_lock:
                self._exit_cooldown[ticker] = time.time() + 30.0
        finally:
            with self._exit_lock:
                self._exit_in_flight[ticker] = False

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
