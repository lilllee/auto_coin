# 작업 핸드오프 문서

> **작성일:** 2026-04-15 (3차 업데이트)
> **전체 플랜:** `.omc/plans/auto-coin-roadmap.md`
> **현재 테스트:** 350 passed, 84 warnings

---

## 완료 상태 총괄

### Phase 1: 버그 수정 + 실거래 전 필수 — 완료

| # | 태스크 | 상태 |
|---|---|---|
| T1 | `_wants_html()` 연산자 우선순위 버그 | 완료 |
| T2 | 라이브 모드 volume=0.0 가드 | 완료 |
| T3 | `avg_entry_price=0` 가드 | 완료 |
| T4 | `current_price<=0` 가드 | 완료 |
| T5 | 청산 후 재진입 쿨다운 | 완료 |
| T6 | 라이브 체결 확인 폴링 | 완료 |
| T7 | daily PnL 표시 개선 | 완료 |

### Phase 2: 보안 강화 — 완료

| # | 태스크 | 상태 |
|---|---|---|
| T8 | CSRF 토큰 검증 | 완료 |
| T9 | 세션 고정 방지 | 완료 |
| T10 | paper→live 전환 시 TOTP 재확인 | 완료 |
| T11 | TOTP 복구 UI / 복구 코드 플로우 | 완료 |

### Phase 3: 운영 편의 UI — 진행중

| # | 태스크 | 상태 |
|---|---|---|
| T12 | 수동 매도 버튼 | **미착수** |
| T13 | 전체 긴급 청산 버튼 | **미착수** |
| T14 | 이벤트 타임라인 위젯 | **구현 완료, 미커밋** |
| T15 | AuditLog 조회 UI | **구현 완료, 미커밋** |

### Phase 3 이후 — 미착수

| # | 태스크 |
|---|---|
| T16 | 백테스트 UI |
| T17 | 성과 대시보드 |
| T18 | 알림 커스터마이징 |
| T19 | 추가 전략 (MA, RSI, 볼린저) |
| T20 | V1/V2 동시 실행 방지 (기본 lock 구현됨, 강화 미착수) |
| T21~T28 | 기술부채 + 문서 (Phase 5) |

---

## 미커밋 작업 상세 (T14 + T15)

**6파일 수정, 2파일 신규**, 350 passed, 테스트 green.

### T14: 이벤트 타임라인 — 구현 완료

대시보드에 최근 이벤트(주문 + 감사로그)를 시간순 통합 표시하는 위젯.

**변경 파일:**
- `src/auto_coin/web/audit.py` — `list_entries()`, `action_label()`, `parse_audit_json()`, `summarize_payload()` 추가
- `src/auto_coin/web/routers/dashboard.py` — `_build_timeline()`, `_parse_event_time()` 추가. `_collect_dashboard_context()`에서 timeline_events 조립
- `src/auto_coin/web/templates/partials/dashboard_body.html` — 타임라인 UI (order=emerald, audit=slate 배지 구분)
- `tests/test_web_dashboard.py` — `test_dashboard_timeline_includes_audit_and_order_events` 추가

**동작:** 최근 주문 + 감사로그 합쳐서 시간순 역순 8건 표시. 5초 자동 갱신.

### T15: AuditLog 조회 UI — 구현 완료

설정 메뉴에서 감사 로그를 필터링/검색할 수 있는 전용 페이지.

**변경 파일:**
- `src/auto_coin/web/routers/settings.py` — `GET /settings/audit` 엔드포인트 추가 (action_prefix 필터, limit)
- `src/auto_coin/web/templates/settings/audit.html` — 신규 (필터 폼 + 로그 목록 + before/after JSON 표시)
- `src/auto_coin/web/templates/settings/index.html` — "감사 로그" 링크 추가
- `tests/test_web_audit.py` — 신규 4건 (auth_required, empty_state, newest_first_mask, filter_by_prefix)

---

## 즉시 해야 할 작업

### Step 0: T14+T15 커밋

```bash
# 현재 상태 확인
python3 -m pytest --tb=short -q   # 350 passed 확인
python3 -m ruff check src tests   # clean 확인

# 커밋
git add src/auto_coin/web/audit.py \
        src/auto_coin/web/routers/dashboard.py \
        src/auto_coin/web/routers/settings.py \
        src/auto_coin/web/templates/partials/dashboard_body.html \
        src/auto_coin/web/templates/settings/index.html \
        src/auto_coin/web/templates/settings/audit.html \
        tests/test_web_dashboard.py \
        tests/test_web_audit.py

git commit -m "Add event timeline widget and audit log viewer (T14, T15)"
git push
```

### Step 1: T13 전체 긴급 청산 버튼

**왜 T12보다 먼저:** T13(전체 청산)이 T12(개별 매도)보다 안전상 더 급함. T12는 T13의 개별 매도 로직을 재활용.

**구현 내용:**
- 대시보드에 "긴급 청산" 버튼 추가 (빨간색, 눈에 띄게)
- 클릭 시 TOTP 6자리 입력 모달 표시
- TOTP 확인 후 모든 보유 포지션 시장가 매도
- Kill-switch 자동 활성화 (신규 진입 차단)
- 각 종목별 청산 결과 개별 리포팅
- 일부 실패해도 나머지 계속 진행

**수정 파일:**
- `src/auto_coin/web/routers/control.py` — `POST /control/emergency-liquidate` 엔드포인트
  - TOTP 검증 (user_service의 verify_totp 사용)
  - 모든 ticker의 OrderStore 순회 → position 있으면 매도 Decision 생성 → executor.execute()
  - Kill-switch 자동 ON
  - AuditLog 기록
  - 텔레그램 알림
- `src/auto_coin/web/templates/dashboard.html` — 긴급 청산 버튼 + TOTP 입력 모달 (HTMX)
- `tests/test_web_dashboard.py` 또는 `tests/test_control.py` — 테스트:
  - `test_emergency_liquidate_requires_totp` — TOTP 없이 → 거부
  - `test_emergency_liquidate_sells_all_positions` — 정상 청산
  - `test_emergency_liquidate_activates_kill_switch` — kill-switch ON 확인
  - `test_emergency_liquidate_partial_failure` — 일부 실패 시 나머지 계속

**참고 코드:** `bot.py:force_exit_if_holding()` (line 251-283) — 동일한 패턴으로 모든 ticker 순회하며 청산. 이 로직을 재활용하되, TOTP 검증 + kill-switch 활성화를 추가.

**CSRF 주의:** 모든 POST는 CSRF 토큰 필요. `csrf_helpers.py`의 `csrf_data()` 사용 (테스트), 템플릿에서는 base.html의 HTMX 자동 첨부 활용.

### Step 2: T12 수동 매도 버튼

**구현 내용:**
- 대시보드 포지션 카드 각각에 "매도" 버튼 추가
- 클릭 시 확인 다이얼로그 (HTMX `hx-confirm`)
- 해당 종목만 시장가 청산
- AuditLog + flash + 텔레그램 알림

**수정 파일:**
- `src/auto_coin/web/routers/control.py` — `POST /control/sell/{ticker}` 엔드포인트
  - ticker의 OrderStore에서 position 확인
  - position 없으면 에러
  - 매도 Decision 생성 → executor.execute()
  - 쿨다운 자동 적용 (T5 메커니즘 재활용)
  - AuditLog 기록
- `src/auto_coin/web/templates/partials/dashboard_body.html` — 포지션 카드에 매도 버튼
- `tests/test_web_dashboard.py` — 테스트:
  - `test_manual_sell_single_ticker` — 단일 종목 청산
  - `test_manual_sell_no_position` — 미보유 종목 매도 시도 → 에러
  - `test_manual_sell_requires_auth` — 미인증 차단

**BotManager lock 주의:** 수동 매도 시 BotManager의 lock을 획득해야 tick()과 충돌 방지. `manager._lock` 사용 또는 manager를 통해 실행.

### Step 3: 문서 업데이트 + 커밋

- `docs/HANDOFF.md` 갱신 (T12~T15 완료 표기)
- `CHANGELOG.md` 갱신 (Phase 3 마일스톤)
- `README.md`에 긴급 청산/수동 매도/감사 로그 UI 반영

---

## Phase 4 이후 (참고)

전체 플랜은 `.omc/plans/auto-coin-roadmap.md` 참조:

| # | 태스크 | 복잡도 | 독립성 |
|---|---|---|---|
| T16 | 백테스트 UI | XL | 독립 |
| T17 | 성과 대시보드 | XL | 독립 |
| T18 | 알림 커스터마이징 | M | 독립 |
| T19 | 추가 전략 (MA, RSI, 볼린저) | XL | 독립 |
| T20 | V1/V2 동시 실행 방지 강화 | M | 독립 |

Phase 4는 모두 독립 → 병렬 실행 가능.

---

## 아키텍처 제약 (반드시 준수)

1. **`strategy/`** — 순수 함수. I/O/네트워크/로깅 직접 호출 금지
2. **`risk/manager.py`** — I/O 금지. 모든 상태는 `RiskContext`로 주입
3. **`exchange/upbit_client.py`** — pyupbit 유일 import 지점
4. **`executor/store.py`** — JSON 원자적 저장 (tmpfile + os.replace)
5. **`web/`** — V1 코드를 수정하지 않고 감싸는 구조

## 테스트 관례

- V2 테스트에서 `monkeypatch.setenv("HOME", str(tmp_path))` 필수
- CSRF: `from csrf_helpers import csrf_data` → `csrf_data(client)` 또는 `csrf_data(client, {"key": "val"})`
- `TemplateResponse`는 starlette 1.0 시그니처: `TemplateResponse(request=request, name=..., context=...)`

## 실행 명령

```bash
python3 -m pytest --tb=short -q        # 테스트
python3 -m ruff check src tests        # 린트
python3 -m auto_coin.web --port 8080   # V2 웹 서버
```
