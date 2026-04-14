"""봇 프로세스 컨트롤 — start / stop / restart / kill-switch toggle.

모두 POST. 대시보드에서 버튼 클릭 시 호출. 2단계 확인은 폼의 `confirm` 히든
필드로 처리 (자바스크립트 confirm prompt). 결과는 flash 후 /로 303.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from auto_coin.web import audit
from auto_coin.web.auth import flash, get_box, get_manager, get_session_db, require_auth
from auto_coin.web.bot_manager import BotManager
from auto_coin.web.crypto import SecretBox
from auto_coin.web.settings_service import load_runtime_settings, save_runtime_settings

router = APIRouter(prefix="/control")


@router.post("/kill-switch")
def toggle_kill_switch(
    request: Request,
    confirm: str = Form(default=""),
    db: Session = Depends(get_session_db),
    box: SecretBox = Depends(get_box),
    manager: BotManager = Depends(get_manager),
    _uid=Depends(require_auth),
):
    current = load_runtime_settings(db, box)
    new = current.model_copy(update={"kill_switch": not current.kill_switch})
    save_runtime_settings(db, box, new)
    audit.record(
        db, "control.kill_switch",
        before={"kill_switch": current.kill_switch},
        after={"kill_switch": new.kill_switch},
    )
    manager.reload()
    state = "켜짐" if new.kill_switch else "해제"
    flash(request, f"Kill-switch {state}", level="warn" if new.kill_switch else "ok")
    return RedirectResponse("/", status_code=303)


@router.post("/start")
def start_bot(
    request: Request,
    manager: BotManager = Depends(get_manager),
    db: Session = Depends(get_session_db),
    _uid=Depends(require_auth),
):
    if manager.running:
        flash(request, "이미 실행 중입니다", level="warn")
    else:
        audit.record(db, "control.start", before={"running": False}, after={"running": True})
        manager.start()
        flash(request, "봇 시작됨")
    return RedirectResponse("/", status_code=303)


@router.post("/stop")
def stop_bot(
    request: Request,
    confirm: str = Form(default=""),
    manager: BotManager = Depends(get_manager),
    db: Session = Depends(get_session_db),
    _uid=Depends(require_auth),
):
    if confirm != "yes":
        flash(request, "정지 확인이 필요합니다", level="error")
        return RedirectResponse("/", status_code=303)
    if not manager.running:
        flash(request, "이미 정지 상태입니다", level="warn")
    else:
        audit.record(db, "control.stop", before={"running": True}, after={"running": False})
        manager.stop()
        flash(request, "봇 정지됨 (포지션은 그대로 유지)")
    return RedirectResponse("/", status_code=303)


@router.post("/restart")
def restart_bot(
    request: Request,
    manager: BotManager = Depends(get_manager),
    db: Session = Depends(get_session_db),
    _uid=Depends(require_auth),
):
    audit.record(db, "control.restart", before={}, after={})
    manager.reload()
    flash(request, "봇 재시작 완료 — 새 설정이 적용됩니다")
    return RedirectResponse("/", status_code=303)
