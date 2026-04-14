"""CSRF 토큰 검증 미들웨어.

모든 POST/PUT/DELETE 요청에 대해 세션의 CSRF 토큰과 요청의 토큰을 비교한다.
토큰은 form hidden input (``_csrf_token``) 또는 헤더 (``X-CSRF-Token``)로 전달된다.

주의:
- form body를 읽으면 downstream의 ``Form(...)`` 파싱이 다시 body를 읽어야 하므로
  body를 버퍼링하고 재생(replay)해야 한다.
- SessionMiddleware 바깥쪽에서 세션을 붙여주므로, 이 미들웨어는 session이 들어있는
  scope를 그대로 사용한다.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

if TYPE_CHECKING:
    pass

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_EXEMPT_PATHS = frozenset({"/health", "/login", "/logout"})
_EXEMPT_PREFIXES = ("/setup", "/static", "/favicon")


def _is_exempt(path: str) -> bool:
    return path in _EXEMPT_PATHS or path.startswith(_EXEMPT_PREFIXES)


def ensure_csrf_token(request: Request) -> str:
    """세션에 CSRF 토큰이 없으면 생성. 있으면 반환."""
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        request.session["csrf_token"] = token
    return token


def _replay_receive(body: bytes) -> Receive:
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


class CSRFMiddleware:
    """Pure ASGI middleware — BaseHTTPMiddleware의 scope 문제를 회피."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)

        # 세션에 토큰 보장 (모든 요청)
        ensure_csrf_token(request)

        # safe method / 면제 경로는 통과
        if request.method in _SAFE_METHODS or _is_exempt(request.url.path):
            await self.app(scope, receive, send)
            return

        session_token = request.session.get("csrf_token")
        if not session_token:
            response = JSONResponse(
                {"detail": "CSRF token missing from session"}, status_code=403,
            )
            await response(scope, receive, send)
            return

        # 1) 헤더에서 확인 (HTMX용)
        request_token = request.headers.get("X-CSRF-Token")

        downstream_receive = receive

        # 2) 폼 데이터에서 확인
        if not request_token:
            content_type = request.headers.get("content-type", "")
            if "form" in content_type:
                body = await request.body()
                downstream_receive = _replay_receive(body)
                form = await Request(scope, receive=_replay_receive(body)).form()
                request_token = form.get("_csrf_token")

        if not request_token or not secrets.compare_digest(request_token, session_token):
            response = JSONResponse(
                {"detail": "CSRF token invalid"}, status_code=403,
            )
            await response(scope, downstream_receive, send)
            return

        await self.app(scope, downstream_receive, send)
