"""/setup · /login · /logout.

Setup 흐름:
    GET  /setup         → password form (이미 User 있으면 /setup/totp 또는 /login)
    POST /setup         → password 저장 + TOTP secret 발급 → /setup/totp
    GET  /setup/totp    → QR + 코드 입력 폼
    POST /setup/totp    → 코드 확인 → totp_confirmed=True → 자동 로그인 → /
    GET  /login         → 로그인 폼
    POST /login         → 성공 시 세션 설정 → /
    POST /logout        → 세션 클리어 → /login
"""

from __future__ import annotations

import base64
import io
from datetime import UTC, datetime
from pathlib import Path

import qrcode
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from auto_coin.web import audit
from auto_coin.web.auth import get_box, get_session_db
from auto_coin.web.crypto import SecretBox
from auto_coin.web.user_service import (
    LoginFailure,
    LoginSuccess,
    RecoveryFailure,
    RecoverySuccess,
    attempt_login,
    confirm_totp,
    create_user,
    decrypt_recovery_codes,
    ensure_recovery_codes,
    get_user,
    reset_totp_with_recovery_code,
    totp_provisioning_uri,
    user_exists,
)

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _qr_png_base64(uri: str) -> str:
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _render_recovery(
    request: Request,
    *,
    error: str | None = None,
    secret: str | None = None,
    recovery_codes: tuple[str, ...] | list[str] | None = None,
    needs_totp_confirmation: bool = False,
    preview_only: bool = False,
    status_code: int = 200,
):
    qr_png_b64 = None
    if secret:
        qr_png_b64 = _qr_png_base64(totp_provisioning_uri(secret, username="admin"))
    return templates.TemplateResponse(
        request=request,
        name="auth/recovery.html",
        context={
            "error": error,
            "secret": secret,
            "qr_png_b64": qr_png_b64,
            "recovery_codes": list(recovery_codes or []),
            "needs_totp_confirmation": needs_totp_confirmation,
            "preview_only": preview_only,
        },
        status_code=status_code,
    )


def _recovery_material(user, box: SecretBox) -> tuple[str, tuple[str, ...]]:
    return box.decrypt(user.totp_secret_enc), decrypt_recovery_codes(box, user.recovery_codes_enc)


# ----- setup ---------------------------------------------------------------


@router.get("/setup", response_class=HTMLResponse)
def setup_get(request: Request, db: Session = Depends(get_session_db)):
    if user_exists(db):
        user = get_user(db)
        if not user.totp_confirmed:
            return RedirectResponse("/setup/totp", status_code=303)
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request=request, name="auth/setup_password.html", context={"error": None})


@router.post("/setup", response_class=HTMLResponse)
def setup_post(
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
):
    if user_exists(db):
        return RedirectResponse("/login", status_code=303)
    if len(password) < 8:
        return templates.TemplateResponse(
            request=request, name="auth/setup_password.html",
            context={"error": "패스워드는 8자 이상이어야 합니다."},
            status_code=400,
        )
    if password != password_confirm:
        return templates.TemplateResponse(
            request=request, name="auth/setup_password.html",
            context={"error": "패스워드 확인이 일치하지 않습니다."},
            status_code=400,
        )
    _user, secret = create_user(db, box, password=password)
    # 세션에 임시 마커 — /setup/totp 보호
    request.session["setup_user_id"] = _user.id
    return RedirectResponse("/setup/totp", status_code=303)


@router.get("/setup/totp", response_class=HTMLResponse)
def setup_totp_get(request: Request,
                   db: Session = Depends(get_session_db),
                   box: SecretBox = Depends(get_box)):
    user = get_user(db)
    if user is None:
        return RedirectResponse("/setup", status_code=303)
    if user.totp_confirmed:
        return RedirectResponse("/login", status_code=303)
    secret = box.decrypt(user.totp_secret_enc)
    uri = totp_provisioning_uri(secret, username=user.username)
    return templates.TemplateResponse(
        request=request, name="auth/setup_totp.html",
        context={"qr_png_b64": _qr_png_base64(uri), "secret": secret, "error": None},
    )


@router.post("/setup/totp", response_class=HTMLResponse)
def setup_totp_post(
    request: Request,
    code: str = Form(...),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
):
    user = get_user(db)
    if user is None:
        return RedirectResponse("/setup", status_code=303)
    if user.totp_confirmed:
        return RedirectResponse("/login", status_code=303)
    if not confirm_totp(db, box, user=user, code=code):
        secret = box.decrypt(user.totp_secret_enc)
        uri = totp_provisioning_uri(secret, username=user.username)
        return templates.TemplateResponse(
            request=request, name="auth/setup_totp.html",
            context={"qr_png_b64": _qr_png_base64(uri), "secret": secret,
                     "error": "6자리 코드가 올바르지 않습니다. 시계 동기화 확인 후 다시 시도하세요."},
            status_code=400,
        )
    recovery_codes = ensure_recovery_codes(db, box, user=user)
    # 자동 로그인 — 세션 고정 공격 방지: 세션 재생성
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["recovery_codes_preview"] = list(recovery_codes)
    return RedirectResponse("/", status_code=303)


# ----- login / logout -----------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request, db: Session = Depends(get_session_db)):
    if not user_exists(db):
        return RedirectResponse("/setup", status_code=303)
    user = get_user(db)
    if not user.totp_confirmed:
        return RedirectResponse("/setup/totp", status_code=303)
    return templates.TemplateResponse(
        request=request, name="auth/login.html",
        context={"error": None, "locked_seconds": None},
    )


@router.post("/login", response_class=HTMLResponse)
def login_post(
    request: Request,
    password: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
):
    result = attempt_login(db, box, password=password, totp_code=code)
    if isinstance(result, LoginSuccess):
        # 세션 고정 공격 방지: 인증 성공 시 세션 재생성
        old_data = dict(request.session)
        request.session.clear()
        request.session["user_id"] = result.user_id
        if "flash" in old_data:
            request.session["flash"] = old_data["flash"]
        return RedirectResponse("/", status_code=303)

    assert isinstance(result, LoginFailure)
    if result.reason == "locked" and result.locked_until is not None:
        remaining = int((result.locked_until - datetime.now(UTC).replace(tzinfo=None)).total_seconds())
        remaining = max(remaining, 1)
        return templates.TemplateResponse(
            request=request, name="auth/login.html",
            context={"error": None, "locked_seconds": remaining},
            status_code=429,
        )
    error_msg = {
        "no_user": "사용자가 존재하지 않습니다.",
        "bad_password": "패스워드 또는 TOTP가 올바르지 않습니다.",
        "bad_totp": "패스워드 또는 TOTP가 올바르지 않습니다.",
        "not_confirmed": "TOTP 등록이 완료되지 않았습니다.",
    }.get(result.reason, "로그인 실패")
    return templates.TemplateResponse(
        request=request, name="auth/login.html",
        context={"error": error_msg, "locked_seconds": None},
        status_code=401,
    )


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/recovery", response_class=HTMLResponse)
def recovery_get(
    request: Request,
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
):
    preview_codes = request.session.pop("recovery_codes_preview", None)
    if preview_codes:
        return _render_recovery(
            request,
            recovery_codes=preview_codes,
            preview_only=True,
        )

    if request.session.get("recovery_user_id") is not None:
        user = get_user(db)
        if user is None:
            request.session.clear()
            return RedirectResponse("/login", status_code=303)
        secret, codes = _recovery_material(user, box)
        return _render_recovery(
            request,
            secret=secret,
            recovery_codes=codes,
            needs_totp_confirmation=True,
        )

    return _render_recovery(request)


@router.post("/recovery", response_class=HTMLResponse)
def recovery_post(
    request: Request,
    recovery_code: str = Form(default=""),
    totp_code: str = Form(default=""),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
):
    if request.session.get("recovery_user_id") is not None:
        user = get_user(db)
        if user is None:
            request.session.clear()
            return RedirectResponse("/login", status_code=303)
        if not confirm_totp(db, box, user=user, code=totp_code):
            secret, codes = _recovery_material(user, box)
            return _render_recovery(
                request,
                error="새 TOTP 6자리 코드가 올바르지 않습니다.",
                secret=secret,
                recovery_codes=codes,
                needs_totp_confirmation=True,
                status_code=400,
            )

        _, codes = _recovery_material(user, box)
        request.session.clear()
        request.session["user_id"] = user.id
        request.session["recovery_codes_preview"] = list(codes)
        audit.record(
            db,
            "auth.recovery.confirmed",
            before={"stage": "recovery_pending"},
            after={"stage": "totp_reset_complete"},
        )
        return RedirectResponse("/recovery", status_code=303)

    result = reset_totp_with_recovery_code(db, box, code=recovery_code)
    if isinstance(result, RecoveryFailure):
        audit.record(
            db,
            "auth.recovery.rejected",
            before={"stage": "recovery_requested"},
            after={"reason": result.reason},
        )
        return _render_recovery(
            request,
            error="복구 코드가 올바르지 않습니다.",
            status_code=400,
        )

    assert isinstance(result, RecoverySuccess)
    request.session.clear()
    request.session["recovery_user_id"] = result.user_id
    audit.record(
        db,
        "auth.recovery.started",
        before={"stage": "recovery_requested"},
        after={"stage": "totp_reset_pending"},
    )
    return _render_recovery(
        request,
        secret=result.secret,
        recovery_codes=result.recovery_codes,
        needs_totp_confirmation=True,
    )
