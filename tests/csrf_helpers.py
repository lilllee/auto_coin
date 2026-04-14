"""CSRF 토큰 추출 헬퍼 — 테스트 전용."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient


def extract_csrf_token(client: TestClient, url: str = "/") -> str:
    """GET 응답의 <meta name="csrf-token"> 에서 토큰 추출."""
    r = client.get(url)
    m = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', r.text)
    assert m, f"CSRF meta tag not found in response from {url}"
    return m.group(1)


def csrf_data(client: TestClient, data: dict | None = None, url: str = "/") -> dict:
    """POST용 form data에 _csrf_token을 자동 추가."""
    token = extract_csrf_token(client, url)
    result = dict(data) if data else {}
    result["_csrf_token"] = token
    return result


def csrf_headers(client: TestClient, url: str = "/") -> dict[str, str]:
    """HTMX 스타일 X-CSRF-Token 헤더 반환."""
    return {"X-CSRF-Token": extract_csrf_token(client, url)}
