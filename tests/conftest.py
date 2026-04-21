"""공용 테스트 헬퍼 — conftest.py.

CSRF 헬퍼 함수는 csrf_helpers 모듈에서 제공.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def enable_auth_for_existing_tests(monkeypatch):
    """기존 테스트 기본값은 보호 모드 유지.

    운영 기본 동작은 무인증 진입으로 바뀌었지만, 기존 인증/세션 회귀 테스트는
    별도 수정 없이 계속 같은 전제에서 동작하도록 기본적으로 ENABLE_AUTH=1을 준다.
    개별 테스트는 필요하면 override 가능하다.
    """
    monkeypatch.setenv("ENABLE_AUTH", "1")
