# 작업 핸드오프 문서

> **작성일:** 2026-04-14  
> **작업 범위:** Phase 1 (버그 수정 + 실거래 전 필수) + Phase 2 (보안 강화)  
> **전체 플랜:** `.omc/plans/auto-coin-roadmap.md`

---

## 완료 상태

### Phase 1: 버그 수정 + 실거래 전 필수

| # | 태스크 | 상태 |
|---|---|---|
| T1 | `_wants_html()` 연산자 우선순위 버그 | 완료 |
| T2 | 라이브 모드 volume=0.0 가드 | 완료 |
| T3 | `avg_entry_price=0` 가드 | 완료 |
| T4 | `current_price<=0` 가드 | 완료 |
| T5 | 청산 후 재진입 쿨다운 | 완료 |
| T6 | 라이브 체결 확인 폴링 | 완료 |
| T7 | daily PnL 표시 개선 | 완료 |

### Phase 2: 보안 강화

| # | 태스크 | 상태 |
|---|---|---|
| T8 | CSRF 토큰 검증 | 완료 |
| T9 | 세션 고정 방지 | 완료 |
| T10 | paper→live 전환 시 TOTP 재확인 | 완료 |
| T11 | TOTP 복구 UI / 복구 코드 플로우 | 완료 |

---

## 이번에 마무리된 내용

### T8 CSRF
- `src/auto_coin/web/csrf.py` 추가
- 세션 기반 CSRF 토큰 생성/검증
- form hidden field + `X-CSRF-Token` 헤더 둘 다 지원
- form body replay 처리로 FastAPI `Form(...)` 파싱 hang 문제 해결
- `base.html`에 meta token + HTMX 헤더 자동 첨부 유지

### T10 라이브 전환 TOTP 재확인
- `src/auto_coin/web/routers/settings.py`
- `paper -> live` 전환 시 현재 TOTP 6자리 필수
- 실패 시 설정 반영 거부 + audit log 기록
- `templates/settings/schedule.html`에 입력 필드 추가

### T11 TOTP 복구
- `src/auto_coin/web/models.py`에 `recovery_codes_enc` 추가
- `src/auto_coin/web/db.py`에 기존 SQLite row 대상 경량 schema 보정 추가
- `src/auto_coin/web/user_service.py`
  - 복구 코드 생성
  - 암복호화
  - 1회용 검증
  - TOTP secret 재발급
- `src/auto_coin/web/routers/auth.py`
  - `/recovery` GET/POST
  - 복구 코드 확인 → 새 TOTP 발급 → 새 TOTP 확인 → 새 복구 코드 표시
- `src/auto_coin/web/templates/auth/recovery.html` 추가

---

## 테스트 / 검증 결과

```bash
python3 -m pytest --tb=short -q
# 340 passed, 79 warnings

python3 -m ruff check src tests
# All checks passed

python3 -m compileall src tests
# success
```

추가로 영향 파일 diagnostics 0 errors, architect review APPROVED 확인.

---

## 주요 변경 파일

- `src/auto_coin/web/csrf.py`
- `src/auto_coin/web/app.py`
- `src/auto_coin/web/db.py`
- `src/auto_coin/web/models.py`
- `src/auto_coin/web/user_service.py`
- `src/auto_coin/web/routers/auth.py`
- `src/auto_coin/web/routers/settings.py`
- `src/auto_coin/web/templates/auth/login.html`
- `src/auto_coin/web/templates/auth/setup_password.html`
- `src/auto_coin/web/templates/auth/setup_totp.html`
- `src/auto_coin/web/templates/auth/recovery.html`
- `src/auto_coin/web/templates/settings/schedule.html`
- `tests/test_csrf.py`
- `tests/test_auth_flow.py`
- `tests/test_web_dashboard.py`
- `tests/test_web_settings.py`

---

## 남은 작업

다음 우선순위는 `.omc/plans/auto-coin-roadmap.md` 기준 **Phase 3**:

1. T12 수동 매도 버튼
2. T13 전체 긴급 청산
3. T14 이벤트 타임라인
4. T15 AuditLog 조회 UI

---

## 남은 리스크 / 참고

- 테스트는 모두 green이지만 `datetime.utcnow()` deprecation warning 79건은 남아 있음
- 런타임 로컬 상태는 `.omx/`로 ignore 처리됨
- `.omc/plans/auto-coin-roadmap.md`는 계획 문서로 유지, `.omc/sessions/*` 같은 로컬 세션 산출물은 커밋 대상에서 제외하는 편이 안전
