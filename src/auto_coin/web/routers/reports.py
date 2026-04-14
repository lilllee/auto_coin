"""/reports — `reports/*.md` 마크다운 뷰어.

GET /reports          → 목록 (날짜 내림차순)
GET /reports/{name}   → 단일 파일 마크다운 렌더

보안:
- 경로 traversal 방지: `/` · `..` · 절대경로 거부. 파일명은 `.md` 확장자 강제
- `reports/` 디렉토리 밖은 절대 읽지 않음 (resolve()로 재확인)
- 읽기 전용 — 작성/삭제는 제공하지 않음
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import markdown2
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from auto_coin.web.auth import require_auth

router = APIRouter(prefix="/reports")
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _reports_dir() -> Path:
    # 프로젝트 루트 기준. uvicorn 실행 cwd = 프로젝트 루트 가정.
    return Path.cwd() / "reports"


def _is_safe_name(name: str) -> bool:
    if not name or not name.endswith(".md"):
        return False
    return not ("/" in name or "\\" in name or name.startswith(".") or ".." in name)


@router.get("", response_class=HTMLResponse)
def reports_index(request: Request, _uid=Depends(require_auth)):
    reports_dir = _reports_dir()
    items = []
    if reports_dir.exists() and reports_dir.is_dir():
        for p in sorted(reports_dir.glob("*.md"), reverse=True):
            stat = p.stat()
            items.append({
                "name": p.name,
                "size_kb": max(1, round(stat.st_size / 1024)),
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                # 첫 줄 (H1) → 프리뷰 제목
                "title": _first_heading(p) or p.stem,
            })
    return templates.TemplateResponse(
        request=request, name="reports/index.html",
        context={"items": items, "reports_dir": str(reports_dir)},
    )


@router.get("/{name}", response_class=HTMLResponse)
def report_detail(name: str, request: Request, _uid=Depends(require_auth)):
    if not _is_safe_name(name):
        raise HTTPException(status_code=400, detail="잘못된 파일명")
    reports_dir = _reports_dir().resolve()
    path = (reports_dir / name).resolve()
    try:
        path.relative_to(reports_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="경로가 허용 범위를 벗어납니다") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"{name} 파일이 없습니다")
    source = path.read_text(encoding="utf-8")
    html = markdown2.markdown(
        source,
        extras=["tables", "fenced-code-blocks", "strike", "task_list", "code-friendly", "break-on-newline"],
    )
    title = _first_heading_from_text(source) or path.stem
    return templates.TemplateResponse(
        request=request, name="reports/detail.html",
        context={"name": name, "title": title, "html": html},
    )


def _first_heading(path: Path) -> str | None:
    try:
        return _first_heading_from_text(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return None


def _first_heading_from_text(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return None
