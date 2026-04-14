"""대시보드 홈 (/).

페이지 구조:
- 상단: 상태 배지(running/paper·live/kill-switch) + 컨트롤 버튼 (restart/stop/start)
- 본문 (partial, 5s polling):
    - 슬롯 사용 / 일일 PnL / 잔고
    - 포지션 카드 그리드 (종목별 unrealized PnL)
    - 최근 주문 10건
    - Kill-switch 토글

`/dashboard/partial`은 본문만 반환 — HTMX `hx-get` + `hx-trigger="every 5s"`로 부분 갱신.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger
from sqlmodel import Session

from auto_coin.exchange.upbit_client import UpbitClient, UpbitError
from auto_coin.executor.store import OrderStore
from auto_coin.web.auth import get_box, get_manager, get_session_db, require_auth
from auto_coin.web.bot_manager import BotManager
from auto_coin.web.crypto import SecretBox
from auto_coin.web.settings_service import load_runtime_settings

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _collect_dashboard_context(
    db: Session, box: SecretBox, manager: BotManager,
) -> dict[str, Any]:
    """대시보드/partial 양쪽에서 쓰는 컨텍스트 조립."""
    settings = load_runtime_settings(db, box)
    tickers = settings.portfolio_ticker_list
    state_dir = Path(settings.state_dir)

    # ticker별 position / orders 수집
    positions = []
    all_orders = []
    slot_used = 0
    total_daily_pnl = 0.0
    for t in tickers:
        safe = t.replace("/", "_")
        store = OrderStore(state_dir / f"{safe}.json")
        state = store.load()
        total_daily_pnl += state.daily_pnl_ratio
        for order in state.orders:
            all_orders.append({
                "market": order.market,
                "side": order.side,
                "price": order.price,
                "krw_amount": order.krw_amount,
                "volume": order.volume,
                "placed_at": order.placed_at,
                "status": order.status,
            })
        if state.position is None:
            positions.append({
                "ticker": t, "has_position": False,
                "volume": 0, "entry_price": None,
                "current_price": None, "pnl_ratio": None,
            })
            continue
        slot_used += 1
        pos = state.position
        # 현재가 조회 (실패해도 대시보드는 렌더)
        current_price = _safe_current_price(settings, t)
        pnl = None
        if current_price is not None and pos.avg_entry_price > 0:
            pnl = (current_price - pos.avg_entry_price) / pos.avg_entry_price
        positions.append({
            "ticker": t, "has_position": True,
            "volume": pos.volume, "entry_price": pos.avg_entry_price,
            "current_price": current_price, "pnl_ratio": pnl,
            "entry_at": pos.entry_at,
        })

    # KRW 잔고 — live + 인증이면 실제, 아니면 paper 자본
    krw_balance = _safe_krw_balance(settings)

    # 최근 주문 (전 종목 통합, 최신순 10건)
    all_orders.sort(key=lambda o: o["placed_at"], reverse=True)
    recent_orders = all_orders[:10]

    return {
        "settings": settings,
        "running": manager.running,
        "started_at": manager.started_at,
        "tickers": tickers,
        "positions": positions,
        "slot_used": slot_used,
        "slot_max": settings.max_concurrent_positions,
        "recent_orders": recent_orders,
        "krw_balance": krw_balance,
        "total_daily_pnl": total_daily_pnl,
        "avg_daily_pnl": total_daily_pnl / max(slot_used, 1) if slot_used else 0.0,
    }


def _safe_current_price(settings, ticker: str) -> float | None:
    try:
        client = UpbitClient(
            access_key=settings.upbit_access_key.get_secret_value(),
            secret_key=settings.upbit_secret_key.get_secret_value(),
            max_retries=1, backoff_base=0.0,
        )
        return float(client.get_current_price(ticker))
    except UpbitError as exc:
        logger.warning("dashboard price fetch failed for {}: {}", ticker, exc)
        return None
    except Exception as exc:  # pragma: no cover - 방어적
        logger.warning("dashboard price fetch error for {}: {}", ticker, exc)
        return None


def _safe_krw_balance(settings) -> float | None:
    """live 모드면 실제 잔고, 아니면 paper_initial_krw (표시용)."""
    access = settings.upbit_access_key.get_secret_value()
    secret = settings.upbit_secret_key.get_secret_value()
    if settings.is_live and access and secret:
        try:
            client = UpbitClient(
                access_key=access, secret_key=secret,
                max_retries=1, backoff_base=0.0,
            )
            return float(client.get_krw_balance())
        except Exception as exc:
            logger.warning("dashboard balance fetch failed: {}", exc)
            return None
    return float(settings.paper_initial_krw)


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    manager: BotManager = Depends(get_manager),
    _uid=Depends(require_auth),
):
    ctx = _collect_dashboard_context(db, box, manager)
    return templates.TemplateResponse(
        request=request, name="dashboard.html", context=ctx,
    )


@router.get("/dashboard/partial", response_class=HTMLResponse)
def dashboard_partial(
    request: Request,
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    manager: BotManager = Depends(get_manager),
    _uid=Depends(require_auth),
):
    ctx = _collect_dashboard_context(db, box, manager)
    return templates.TemplateResponse(
        request=request, name="partials/dashboard_body.html", context=ctx,
    )
