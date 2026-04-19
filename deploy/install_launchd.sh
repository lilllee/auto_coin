#!/usr/bin/env bash
# auto_coin을 launchd에 등록 — macOS 재부팅 후 자동 기동.
#
# 사용법:
#   cd /path/to/auto_coin
#   ./deploy/install_launchd.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="auto_coin"
SRC="$PROJECT_DIR/deploy/$LABEL.plist"
DST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ ! -f "$SRC" ]]; then
  echo "❌ template not found: $SRC" >&2
  exit 1
fi

if [[ ! -d "$PROJECT_DIR/.venv" ]]; then
  echo "⚠️  .venv가 없습니다. 먼저 \`python3.11 -m venv .venv && .venv/bin/pip install -e .[dev]\` 실행"
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_DIR/logs"

# placeholder 치환 후 LaunchAgents에 복사
sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__HOME__|$HOME|g" \
    "$SRC" > "$DST"

# 기존 로드 해제 후 재로드
launchctl unload "$DST" >/dev/null 2>&1 || true
launchctl load "$DST"

echo "✅ loaded: $DST"
echo ""
echo "확인:"
echo "  launchctl list | grep auto_coin"
echo "  curl -s http://127.0.0.1:8080/health | python3 -m json.tool"
echo "  tail -f $PROJECT_DIR/logs/launchd.out.log"
echo ""
echo "정지:"
echo "  launchctl unload $DST"
