"""/settings/* — 전략 / 리스크 / 포트폴리오 / API 키 / 스케줄 수정.

각 POST는:
  1. 현재 DB 설정 로드
  2. 입력값으로 `Settings` 재생성 (pydantic 검증)
  3. 실패 시 400 + 폼 재렌더 + 에러 메시지
  4. 성공 시 DB 저장 → `AuditLog` 기록 → `BotManager.reload()` → flash → 303 자기 자신으로
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import SecretStr, ValidationError
from sqlmodel import Session

from auto_coin.config import Mode, Settings
from auto_coin.web import audit
from auto_coin.web.auth import flash, get_box, get_manager, get_session_db, require_auth
from auto_coin.web.bot_manager import BotManager
from auto_coin.web.crypto import SecretBox
from auto_coin.web.services import upbit_scan
from auto_coin.web.services.credentials_check import (
    check_telegram,
    check_upbit,
    fetch_upbit_holdings,
)
from auto_coin.web.settings_service import load_runtime_settings, save_runtime_settings
from auto_coin.web.user_service import get_user, verify_totp

router = APIRouter(prefix="/settings")
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _validate_settings(candidate: dict) -> tuple[Settings | None, str | None]:
    """dict → Settings 인스턴스 (검증 포함)."""
    try:
        return Settings(_env_file=None, **candidate), None
    except ValidationError as e:
        errs = e.errors()
        msgs = []
        for er in errs:
            loc = ".".join(str(x) for x in er["loc"]) if er["loc"] else "?"
            msgs.append(f"{loc}: {er['msg']}")
        return None, " / ".join(msgs)


def _effective_api_settings(current: Settings) -> Settings:
    """API 키 조회/테스트용 유효 설정.

    우선순위:
    1. DB에 저장된 현재 런타임 값
    2. DB 값이 비어 있으면 `.env` 값 폴백
    """
    env_settings = Settings()
    candidate = current.model_dump()
    if not current.upbit_access_key.get_secret_value():
        candidate["upbit_access_key"] = env_settings.upbit_access_key
    if not current.upbit_secret_key.get_secret_value():
        candidate["upbit_secret_key"] = env_settings.upbit_secret_key
    if not current.telegram_bot_token.get_secret_value():
        candidate["telegram_bot_token"] = env_settings.telegram_bot_token
    if not current.telegram_chat_id:
        candidate["telegram_chat_id"] = env_settings.telegram_chat_id
    return Settings(_env_file=None, **candidate)


def _summary_for_audit(s: Settings) -> dict:
    """AuditLog에 넣을 flat dict (SecretStr은 자동 마스킹)."""
    d = s.model_dump()
    return d


def _apply(db: Session, box: SecretBox, manager: BotManager, old: Settings, new: Settings,
           action: str) -> None:
    save_runtime_settings(db, box, new)
    audit.record(db, action,
                 before=_summary_for_audit(old),
                 after=_summary_for_audit(new))
    manager.reload()


# ----- index --------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def index(request: Request,
          db: Session = Depends(get_session_db),
          box: SecretBox = Depends(get_box),
          _uid=Depends(require_auth)):
    s = load_runtime_settings(db, box)
    return templates.TemplateResponse(
        request=request, name="settings/index.html",
        context={"s": s},
    )


# ----- strategy -----------------------------------------------------------


@router.get("/strategy", response_class=HTMLResponse)
def strategy_get(request: Request,
                 db: Session = Depends(get_session_db),
                 box: SecretBox = Depends(get_box),
                 _uid=Depends(require_auth)):
    s = load_runtime_settings(db, box)
    return templates.TemplateResponse(
        request=request, name="settings/strategy.html",
        context={"s": s, "error": None},
    )


@router.post("/strategy", response_class=HTMLResponse)
def strategy_post(
    request: Request,
    strategy_k: float = Form(...),
    ma_filter_window: int = Form(...),
    watch_interval_minutes: int = Form(...),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    manager: BotManager = Depends(get_manager),
    _uid=Depends(require_auth),
):
    current = load_runtime_settings(db, box)
    candidate = current.model_dump()
    candidate.update({
        "strategy_k": strategy_k,
        "ma_filter_window": ma_filter_window,
        "watch_interval_minutes": watch_interval_minutes,
    })
    new, err = _validate_settings(candidate)
    if new is None:
        return templates.TemplateResponse(
            request=request, name="settings/strategy.html",
            context={"s": current, "error": err},
            status_code=400,
        )
    _apply(db, box, manager, current, new, "settings.strategy")
    flash(request, f"전략 설정 저장: K={new.strategy_k}, MA={new.ma_filter_window}")
    return RedirectResponse("/settings/strategy", status_code=303)


# ----- risk ---------------------------------------------------------------


@router.get("/risk", response_class=HTMLResponse)
def risk_get(request: Request,
             db: Session = Depends(get_session_db),
             box: SecretBox = Depends(get_box),
             _uid=Depends(require_auth)):
    s = load_runtime_settings(db, box)
    return templates.TemplateResponse(
        request=request, name="settings/risk.html",
        context={"s": s, "error": None},
    )


@router.post("/risk", response_class=HTMLResponse)
def risk_post(
    request: Request,
    max_position_ratio: float = Form(...),
    daily_loss_limit: float = Form(...),
    stop_loss_ratio: float = Form(...),
    min_order_krw: int = Form(...),
    max_concurrent_positions: int = Form(...),
    paper_initial_krw: float = Form(...),
    kill_switch: str = Form(default=""),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    manager: BotManager = Depends(get_manager),
    _uid=Depends(require_auth),
):
    current = load_runtime_settings(db, box)
    candidate = current.model_dump()
    candidate.update({
        "max_position_ratio": max_position_ratio,
        "daily_loss_limit": daily_loss_limit,
        "stop_loss_ratio": stop_loss_ratio,
        "min_order_krw": min_order_krw,
        "max_concurrent_positions": max_concurrent_positions,
        "paper_initial_krw": paper_initial_krw,
        "kill_switch": kill_switch == "on",
    })
    new, err = _validate_settings(candidate)
    if new is None:
        return templates.TemplateResponse(
            request=request, name="settings/risk.html",
            context={"s": current, "error": err},
            status_code=400,
        )
    _apply(db, box, manager, current, new, "settings.risk")
    flash(request, "리스크 설정 저장됨")
    return RedirectResponse("/settings/risk", status_code=303)


# ----- portfolio ----------------------------------------------------------


@router.get("/portfolio", response_class=HTMLResponse)
def portfolio_get(request: Request,
                  db: Session = Depends(get_session_db),
                  box: SecretBox = Depends(get_box),
                  _uid=Depends(require_auth)):
    s = load_runtime_settings(db, box)
    try:
        suggestions = upbit_scan.top_by_volume(
            n=20, exclude=set(s.portfolio_ticker_list) | set(s.watch_ticker_list),
        )
    except Exception as exc:
        # 업비트 API 장애여도 폼은 떠야 함
        suggestions = []
        fetch_error = str(exc)
    else:
        fetch_error = None
    return templates.TemplateResponse(
        request=request, name="settings/portfolio.html",
        context={"s": s, "error": None, "suggestions": suggestions,
                 "fetch_error": fetch_error},
    )


@router.post("/portfolio", response_class=HTMLResponse)
def portfolio_post(
    request: Request,
    tickers: str = Form(""),
    watch_tickers: str = Form(""),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    manager: BotManager = Depends(get_manager),
    _uid=Depends(require_auth),
):
    raw_tickers = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    raw_watches = [t.strip().upper() for t in watch_tickers.split(",") if t.strip()]

    try:
        listed = set(upbit_scan.list_krw_tickers())
    except Exception as exc:
        current = load_runtime_settings(db, box)
        return templates.TemplateResponse(
            request=request, name="settings/portfolio.html",
            context={"s": current, "error": f"업비트 마켓 조회 실패: {exc}",
                     "suggestions": [], "fetch_error": None},
            status_code=502,
        )

    unknown = [t for t in (raw_tickers + raw_watches) if t not in listed]
    if unknown:
        current = load_runtime_settings(db, box)
        return templates.TemplateResponse(
            request=request, name="settings/portfolio.html",
            context={"s": current,
                     "error": f"업비트 KRW 마켓에 없는 티커: {', '.join(unknown)}",
                     "suggestions": [], "fetch_error": None},
            status_code=400,
        )

    current = load_runtime_settings(db, box)
    candidate = current.model_dump()
    candidate.update({
        "tickers": ",".join(raw_tickers),
        "watch_tickers": ",".join(raw_watches),
        "ticker": "" if raw_tickers else current.ticker,  # TICKERS가 있으면 TICKER는 clear
    })
    new, err = _validate_settings(candidate)
    if new is None or not new.portfolio_ticker_list:
        current_s = load_runtime_settings(db, box)
        return templates.TemplateResponse(
            request=request, name="settings/portfolio.html",
            context={"s": current_s,
                     "error": err or "매매 대상이 비어 있습니다 (최소 1종목)",
                     "suggestions": [], "fetch_error": None},
            status_code=400,
        )
    _apply(db, box, manager, current, new, "settings.portfolio")
    flash(request,
          f"포트폴리오 저장: {', '.join(new.portfolio_ticker_list)} (동시보유 {new.max_concurrent_positions})")
    return RedirectResponse("/settings/portfolio", status_code=303)


# ----- api keys -----------------------------------------------------------


@router.get("/api-keys", response_class=HTMLResponse)
def api_keys_get(request: Request,
                 db: Session = Depends(get_session_db),
                 box: SecretBox = Depends(get_box),
                 _uid=Depends(require_auth)):
    s = _effective_api_settings(load_runtime_settings(db, box))
    return templates.TemplateResponse(
        request=request, name="settings/api_keys.html",
        context={
            "s": s, "error": None,
            "upbit_access_mask": SecretBox.mask(s.upbit_access_key.get_secret_value()),
            "upbit_secret_mask": SecretBox.mask(s.upbit_secret_key.get_secret_value()),
            "telegram_mask": SecretBox.mask(s.telegram_bot_token.get_secret_value()),
        },
    )


@router.post("/api-keys", response_class=HTMLResponse)
def api_keys_post(
    request: Request,
    upbit_access_key: str = Form(default=""),
    upbit_secret_key: str = Form(default=""),
    telegram_bot_token: str = Form(default=""),
    telegram_chat_id: str = Form(default=""),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    manager: BotManager = Depends(get_manager),
    _uid=Depends(require_auth),
):
    current = load_runtime_settings(db, box)
    # 빈 입력 = 기존 값 유지
    new_access = upbit_access_key.strip() or current.upbit_access_key.get_secret_value()
    new_secret = upbit_secret_key.strip() or current.upbit_secret_key.get_secret_value()
    new_tg_token = telegram_bot_token.strip() or current.telegram_bot_token.get_secret_value()
    new_tg_chat = telegram_chat_id.strip() if telegram_chat_id.strip() else current.telegram_chat_id

    candidate = current.model_dump()
    candidate.update({
        "upbit_access_key": SecretStr(new_access),
        "upbit_secret_key": SecretStr(new_secret),
        "telegram_bot_token": SecretStr(new_tg_token),
        "telegram_chat_id": new_tg_chat,
    })
    new, err = _validate_settings(candidate)
    if new is None:
        return templates.TemplateResponse(
            request=request, name="settings/api_keys.html",
            context={"s": current, "error": err,
                     "upbit_access_mask": SecretBox.mask(current.upbit_access_key.get_secret_value()),
                     "upbit_secret_mask": SecretBox.mask(current.upbit_secret_key.get_secret_value()),
                     "telegram_mask": SecretBox.mask(current.telegram_bot_token.get_secret_value())},
            status_code=400,
        )
    _apply(db, box, manager, current, new, "settings.api_keys")
    flash(request, "API 키 저장됨")
    return RedirectResponse("/settings/api-keys", status_code=303)


@router.post("/api-keys/test-upbit", response_class=HTMLResponse)
def api_keys_test_upbit(
    request: Request,
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    _uid=Depends(require_auth),
):
    s = _effective_api_settings(load_runtime_settings(db, box))
    result = check_upbit(
        s.upbit_access_key.get_secret_value(),
        s.upbit_secret_key.get_secret_value(),
    )
    return templates.TemplateResponse(
        request=request, name="partials/check_result.html",
        context={"ok": result.ok, "detail": result.detail},
    )


@router.post("/api-keys/upbit-holdings", response_class=HTMLResponse)
def api_keys_upbit_holdings(
    request: Request,
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    _uid=Depends(require_auth),
):
    s = _effective_api_settings(load_runtime_settings(db, box))
    result = fetch_upbit_holdings(
        s.upbit_access_key.get_secret_value(),
        s.upbit_secret_key.get_secret_value(),
    )
    return templates.TemplateResponse(
        request=request, name="partials/upbit_holdings.html",
        context={"ok": result.ok, "detail": result.detail, "holdings": result.holdings},
    )


@router.post("/api-keys/test-telegram", response_class=HTMLResponse)
def api_keys_test_telegram(
    request: Request,
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    _uid=Depends(require_auth),
):
    s = _effective_api_settings(load_runtime_settings(db, box))
    result = check_telegram(
        s.telegram_bot_token.get_secret_value(),
        s.telegram_chat_id,
        send_probe=True,
    )
    return templates.TemplateResponse(
        request=request, name="partials/check_result.html",
        context={"ok": result.ok, "detail": result.detail},
    )


# ----- schedule -----------------------------------------------------------


@router.get("/schedule", response_class=HTMLResponse)
def schedule_get(request: Request,
                 db: Session = Depends(get_session_db),
                 box: SecretBox = Depends(get_box),
                 _uid=Depends(require_auth)):
    s = load_runtime_settings(db, box)
    return templates.TemplateResponse(
        request=request, name="settings/schedule.html",
        context={"s": s, "error": None},
    )


@router.post("/schedule", response_class=HTMLResponse)
def schedule_post(
    request: Request,
    check_interval_seconds: int = Form(...),
    heartbeat_interval_hours: int = Form(...),
    exit_hour_kst: int = Form(...),
    exit_minute_kst: int = Form(...),
    daily_reset_hour_kst: int = Form(...),
    mode: str = Form(...),
    live_trading: str = Form(default=""),
    totp_code: str = Form(default=""),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    manager: BotManager = Depends(get_manager),
    _uid=Depends(require_auth),
):
    current = load_runtime_settings(db, box)
    candidate = current.model_dump()
    candidate.update({
        "check_interval_seconds": check_interval_seconds,
        "heartbeat_interval_hours": heartbeat_interval_hours,
        "exit_hour_kst": exit_hour_kst,
        "exit_minute_kst": exit_minute_kst,
        "daily_reset_hour_kst": daily_reset_hour_kst,
        "mode": Mode(mode),
        "live_trading": live_trading == "on",
    })
    new, err = _validate_settings(candidate)
    if new is None:
        return templates.TemplateResponse(
            request=request, name="settings/schedule.html",
            context={"s": current, "error": err},
            status_code=400,
        )

    if current.mode != Mode.LIVE and new.mode == Mode.LIVE:
        user = get_user(db)
        secret = box.decrypt(user.totp_secret_enc) if user is not None else ""
        if not verify_totp(secret, totp_code):
            audit.record(
                db,
                "settings.schedule.live_totp_rejected",
                before=_summary_for_audit(current),
                after={"requested_mode": new.mode.value, "reason": "bad_totp"},
            )
            return templates.TemplateResponse(
                request=request,
                name="settings/schedule.html",
                context={"s": current, "error": "실거래 전환에는 현재 TOTP 6자리 인증이 필요합니다."},
                status_code=400,
            )

    _apply(db, box, manager, current, new, "settings.schedule")
    flash(request, f"스케줄 저장됨 — mode={new.mode.value}, live={new.is_live}")
    return RedirectResponse("/settings/schedule", status_code=303)
