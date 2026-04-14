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

from auto_coin.web.auth import get_box, get_session_db
from auto_coin.web.crypto import SecretBox
from auto_coin.web.user_service import (
    LoginFailure,
    LoginSuccess,
    attempt_login,
    confirm_totp,
    create_user,
    get_user,
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
    # 자동 로그인 — 세션에 user_id 설정
    request.session["user_id"] = user.id
    request.session.pop("setup_user_id", None)
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
        request.session["user_id"] = result.user_id
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
