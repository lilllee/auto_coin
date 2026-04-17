"""FastAPI 인증 dependency.

- `require_auth(request)` : 세션에 user_id가 없으면 /login 리다이렉트
- `require_no_setup(request)` : 최초 설정 전이면 /setup, 이미 되어 있으면 /login (혹은 / 가드)
- `get_box(request)` / `get_manager(request)` : app.state 접근 헬퍼

/login, /setup, /health, /static은 public. middleware가 아니라 라우터 레벨 guard로 관리 →
테스트에서 개별 라우트를 더 쉽게 커버.
"""

from __future__ import annotations

import os

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from auto_coin.web import db as web_db
from auto_coin.web.bot_manager import BotManager
from auto_coin.web.crypto import SecretBox
from auto_coin.web.user_service import user_exists

AUTH_DISABLED = os.getenv("DISABLE_AUTH", "").lower() in ("1", "true", "yes")


def get_box(request: Request) -> SecretBox:
    return request.app.state.box


def get_manager(request: Request) -> BotManager:
    return request.app.state.bot_manager


def get_session_db() -> Session:
    with Session(web_db.engine()) as s:
        yield s


def require_auth(request: Request):
    """미인증 접근은 /login으로 리다이렉트. 의존성에서 raise해 라우터 본문은 실행되지 않음."""
    if AUTH_DISABLED:
        return 0  # 인증 비활성 — 더미 user_id
    if request.session.get("user_id") is None:
        raise _redirect("/login")
    return request.session["user_id"]


def _redirect(to: str) -> HTTPException:
    """FastAPI의 Depends는 Response를 직접 반환할 수 없으므로 예외로 리다이렉트."""
    # 미들웨어 없이 핸들러에서 처리하는 방식 대신, 명시적 예외 사용.
    exc = HTTPException(status_code=status.HTTP_303_SEE_OTHER)
    exc.headers = {"Location": to}
    return exc


def redirect_response(to: str, *, status_code: int = 303) -> RedirectResponse:
    return RedirectResponse(url=to, status_code=status_code)


def flash(request: Request, message: str, *, level: str = "ok") -> None:
    """다음 요청에 표시될 메시지 1건을 세션에 쌓는다.

    level: "ok" | "warn" | "error" (base.html이 색 구분에 사용 가능)
    """
    bucket = request.session.get("flash") or []
    bucket.append({"level": level, "text": message})
    request.session["flash"] = bucket


def needs_setup(db: Session = Depends(get_session_db)) -> bool:
    """User 테이블이 비어있거나 totp_confirmed=False면 setup 모드."""
    from auto_coin.web.user_service import get_user
    if not user_exists(db):
        return True
    u = get_user(db)
    return not u.totp_confirmed
