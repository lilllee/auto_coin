"""AuditLog 기록 헬퍼.

설정 변경 시 before/after를 JSON으로 저장. 민감 필드(API 키·토큰)는 마스킹.
"""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, desc, select

from auto_coin.web.models import AuditLog

SENSITIVE_FIELDS = {
    "upbit_access_key", "upbit_secret_key", "telegram_bot_token",
    # SecretStr 객체를 그대로 넣지 못하니 평문 필드명도 함께
    "upbit_access_key_value", "upbit_secret_key_value", "telegram_bot_token_value",
}

ACTION_LABELS = {
    "auth.recovery.started": "복구 코드 확인",
    "auth.recovery.confirmed": "TOTP 재설정 완료",
    "auth.recovery.rejected": "복구 코드 거부",
    "control.kill_switch": "Kill-switch 변경",
    "control.restart": "봇 재시작",
    "control.start": "봇 시작",
    "control.stop": "봇 정지",
    "settings.api_keys": "API 키 저장",
    "settings.portfolio": "포트폴리오 저장",
    "settings.risk": "리스크 설정 저장",
    "settings.schedule": "스케줄 저장",
    "settings.schedule.live_totp_rejected": "라이브 전환 TOTP 거부",
    "settings.strategy": "전략 설정 저장",
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


def parse_audit_json(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return value if isinstance(value, dict) else {"value": value}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action.replace(".", " / "))


def summarize_payload(payload: dict[str, Any]) -> str:
    if not payload:
        return "상세 없음"
    parts: list[str] = []
    for key, value in payload.items():
        parts.append(f"{key}={value}")
        if len(parts) == 3:
            break
    return " · ".join(parts)


def list_entries(
    session: Session,
    *,
    limit: int = 50,
    action_prefix: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(AuditLog)
    if action_prefix:
        stmt = stmt.where(AuditLog.action.startswith(action_prefix))
    stmt = stmt.order_by(desc(AuditLog.at), desc(AuditLog.id)).limit(limit)

    entries: list[dict[str, Any]] = []
    for row in session.exec(stmt):
        before = parse_audit_json(row.before_json)
        after = parse_audit_json(row.after_json)
        entries.append({
            "id": row.id,
            "at": row.at,
            "action": row.action,
            "label": action_label(row.action),
            "actor": row.actor,
            "before": before,
            "after": after,
            "summary": summarize_payload(after or before),
        })
    return entries
