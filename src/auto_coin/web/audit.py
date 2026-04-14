"""AuditLog 기록 헬퍼.

설정 변경 시 before/after를 JSON으로 저장. 민감 필드(API 키·토큰)는 마스킹.
"""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session

from auto_coin.web.models import AuditLog

SENSITIVE_FIELDS = {
    "upbit_access_key", "upbit_secret_key", "telegram_bot_token",
    # SecretStr 객체를 그대로 넣지 못하니 평문 필드명도 함께
    "upbit_access_key_value", "upbit_secret_key_value", "telegram_bot_token_value",
}


def mask_for_audit(data: dict[str, Any]) -> dict[str, Any]:
    """민감 필드는 '•••last4' 형태로 마스킹. Path 등 JSON 직렬화 불가 타입은 str()."""
    out: dict[str, Any] = {}
    for k, v in data.items():
        if k in SENSITIVE_FIELDS and v:
            s = str(v)
            out[k] = ("•" * max(len(s) - 4, 0) + s[-4:]) if len(s) > 4 else ("•" * len(s))
        elif hasattr(v, "get_secret_value"):
            raw = v.get_secret_value()
            if not raw:
                out[k] = ""
            elif len(raw) > 4:
                out[k] = "•" * (len(raw) - 4) + raw[-4:]
            else:
                out[k] = "•" * len(raw)
        else:
            try:
                json.dumps(v)
                out[k] = v
            except TypeError:
                out[k] = str(v)
    return out


def record(session: Session, action: str, *,
           before: dict[str, Any], after: dict[str, Any], actor: str = "admin") -> None:
    """설정 변경 이력 1건 기록."""
    log = AuditLog(
        action=action,
        actor=actor,
        before_json=json.dumps(mask_for_audit(before), ensure_ascii=False, sort_keys=True),
        after_json=json.dumps(mask_for_audit(after), ensure_ascii=False, sort_keys=True),
    )
    session.add(log)
    session.commit()
