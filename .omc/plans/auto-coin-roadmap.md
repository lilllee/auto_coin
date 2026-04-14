# Auto Coin 실거래 준비 및 기능 확장 로드맵

> **생성일:** 2026-04-14
> **프로젝트:** auto_coin (업비트 KRW 마켓 자동매매 봇)
> **현재 상태:** V1 CLI + V2 Web 병합 완료, 287/287 pytest 통과, Day1 페이퍼 트레이딩 완료
> **목표:** 안전한 실거래(M8) 전환을 위한 버그 수정, 보안 강화, 운영 편의 기능 구축

---

## 컨텍스트

### 원래 요청
3명의 전문 분석 에이전트가 코드베이스를 심층 분석하여 28개 개선 항목을 도출. 이를 우선순위별 5개 Phase로 구조화하여 실거래 전환까지의 로드맵 수립.

### 분석 요약
- **버그 3건** (operator precedence, volume=0.0 ValueError, avg_entry_price=0 silent skip)
- **보안 4건** (CSRF, 세션 고정, TOTP 재확인, TOTP 복구)
- **거래 로직 4건** (쿨다운, PnL 표시, 체결 확인 폴링, current_price 가드)
- **UI/UX 7건** (수동 매도, 긴급 청산, 타임라인, 백테스트 UI, 성과 대시보드, 알림 설정, 감사 로그)
- **인프라 4건** (PWA, 다크 모드, 추가 전략, 동시 실행 방지)
- **기술 부채 6건** (deprecated API, 연산자 버그, 인스턴스 공유, 테스트 커버리지, pytest 경고)
- **문서 3건** (가이드 업데이트, CHANGELOG 정리, API 문서)

### 아키텍처 제약 (CLAUDE.md 기준 — 반드시 준수)
- `strategy/` — 순수 함수, I/O 금지
- `risk/manager.py` — Executor 앞단 게이트, 손절 최우선
- `exchange/upbit_client.py` — pyupbit 유일 import 지점
- `executor/store.py` — JSON 원자적 저장
- `web/` — V1 코드를 수정하지 않고 감싸는 구조

---

## 작업 목표

### 핵심 목표
안전하고 신뢰할 수 있는 실거래(M8) 전환을 위해 치명적 버그를 수정하고, 보안을 강화하며, 운영에 필요한 최소한의 UI를 구축한다.

### 산출물
1. 버그 0건의 거래 로직 (Phase 1)
2. 실거래 수준의 보안 체계 (Phase 2)
3. 운영 편의 UI (Phase 3)
4. 분석/확장 기능 (Phase 4)
5. 기술 부채 청산 및 문서 정비 (Phase 5)

### 완료 정의
- 모든 Phase의 태스크가 구현되고 테스트 통과
- pytest 전체 green (기존 287건 + 신규 테스트)
- ruff check clean
- 실거래 전환 체크리스트 전항목 충족

---

## 가드레일

### 반드시 지킬 것 (Must Have)
- 기존 287개 테스트 깨뜨리지 않기
- 모듈 경계 유지 (strategy에 I/O 넣지 않기, upbit_client 외 pyupbit import 금지)
- 모든 신규 기능에 테스트 동반
- 실거래 영향 변경은 페이퍼 모드 검증 후 진행
- 원자적 상태 저장 패턴 유지

### 절대 하지 말 것 (Must NOT Have)
- V1 코드 직접 수정 (web/에서 감싸는 패턴 유지)
- DB 이관 (JSON store 유지)
- 출금 권한이 있는 API 키 사용
- 테스트에서 사용자 HOME에 파일 남기기
- Kill-switch 우회 경로 생성

---

## 의존성 그래프

```
Phase 1 (버그 수정 + 실거래 전 필수)
├── T1: app.py 연산자 버그 ──────────────────────────┐
├── T2: order.py volume=0 ValueError ────────────────┤
├── T3: risk/manager.py avg_entry_price=0 가드 ──────┤
├── T4: current_price=0 가드 ────────────────────────┤
├── T5: 청산 후 재진입 쿨다운 ──────────┐             │
├── T6: 라이브 체결 확인 폴링 ──────────┤             │
│                                       ▼             ▼
│                              T7: daily_pnl 표시 개선
│
Phase 2 (보안 강화) — Phase 1 완료 후
├── T8: CSRF 토큰 검증 ─────────────────────────────┐
├── T9: 세션 고정 방지 ─────────────────────────────┤
│                                                    ▼
├── T10: 라이브 모드 전환 TOTP 재확인 ←── T9에 의존
├── T11: TOTP 복구 UI ←── T8, T9에 의존
│
Phase 3 (운영 편의 UI) — Phase 2 완료 후
├── T12: 수동 매도 버튼 ───┐
├── T13: 전체 긴급 청산 ───┤ (병렬 가능)
├── T14: 이벤트 타임라인 ──┘
├── T15: AuditLog 조회 UI
│
Phase 4 (분석/확장) — Phase 3 완료 후
├── T16: 백테스트 UI ──────┐
├── T17: 성과 대시보드 ────┤ (병렬 가능)
├── T18: 알림 커스터마이징 ┘
├── T19: 추가 전략 (MA, RSI, 볼린저)
├── T20: V1/V2 동시 실행 방지
│
Phase 5 (기술 부채 + 문서) — 독립 실행 가능
├── T21: datetime.utcnow() 교체 ──┐
├── T22: UpbitClient 공유 인스턴스 ┤ (병렬 가능)
├── T23: main.py 테스트 추가 ──────┤
├── T24: BotManager 동시성 테스트 ─┤
├── T25: pytest 경고 59건 정리 ────┘
├── T26: PWA (manifest + SW) ──────┐
├── T27: 다크 모드 ────────────────┘ (병렬 가능)
├── T28: 문서 정비 (USER_GUIDE, CHANGELOG, API docs)
```

---

## Phase 1: 버그 수정 + 실거래 전 필수

> **우선순위:** CRITICAL
> **예상 소요:** 3~4일
> **위험도:** 높음 — 거래 로직 핵심부를 수정하므로 회귀 테스트 필수

### T1: `_wants_html()` 연산자 우선순위 버그 수정

- **설명:** `app.py:121`에서 `not ... in ...` 패턴이 연산자 우선순위에 의해 의도와 다르게 동작. `not (... in ...)` 또는 `... not in ...`으로 명확히 수정.
- **수정 파일:** `src/auto_coin/web/app.py`
- **복잡도:** S
- **의존성:** 없음
- **테스트:**
  - 기존 웹 라우터 테스트 통과 확인
  - `_wants_html()` 단위 테스트 추가 (Accept 헤더 변형 테스트)
- **인수 조건:**
  - `ruff check` 경고 0건
  - HTML 요청과 JSON 요청이 올바르게 분기됨을 테스트로 증명

### T2: `order.py` 라이브 모드 volume=0.0 ValueError 수정

- **설명:** `order.py:134`에서 라이브 모드 체결 시 `volume=0.0`이 반환되면 `force_exit`에서 ValueError 발생. 체결량 검증 로직과 재시도/폴링 메커니즘 추가.
- **수정 파일:** `src/auto_coin/executor/order.py`
- **복잡도:** M
- **의존성:** 없음
- **테스트:**
  - volume=0.0 시나리오 단위 테스트
  - force_exit 호출 시 volume 검증 테스트
  - 재시도 로직 테스트 (mock으로 첫 시도 실패 → 재시도 성공)
- **인수 조건:**
  - volume=0.0일 때 ValueError 대신 적절한 예외 처리 또는 재시도
  - 텔레그램 알림 발송 (조용한 실패 방지)
  - 기존 페이퍼 모드 테스트 전체 통과

> **참고:** T2는 방어적 가드이며, T6(체결 확인 폴링)이 volume=0.0 문제의 근본 해결책. T2만으로는 라이브 모드의 volume 추적 문제가 완전히 해결되지 않음.

### T3: `risk/manager.py` avg_entry_price=0 가드 추가

- **설명:** `risk/manager.py:57`에서 `avg_entry_price=0`이면 손절 계산을 조용히 건너뜀. 이는 보유 중인 포지션의 손절이 실행되지 않는 치명적 결함.
- **수정 파일:** `src/auto_coin/risk/manager.py`
- **복잡도:** M
- **의존성:** 없음
- **테스트:**
  - avg_entry_price=0 시 경고 로그 + 알림 발송 테스트
  - avg_entry_price=0인 포지션에 대한 방어적 처리 테스트 (진입가 재조회 또는 보수적 손절)
- **인수 조건:**
  - avg_entry_price=0이면 손절을 건너뛰지 않고, 경고 알림 + 보수적 조치(시장가 청산 또는 진입가 재조회)
  - 로그에 WARNING 레벨 기록
  - 기존 RiskManager 테스트 전체 통과

### T4: current_price=0 가드 추가

- **설명:** API 일시 오류로 current_price=0이 반환될 경우, 잘못된 매매 시그널이 생성될 수 있음. Strategy와 RiskManager 양쪽에 가드 추가.
- **수정 파일:**
  - `src/auto_coin/strategy/volatility_breakout.py`
  - `src/auto_coin/risk/manager.py`
- **복잡도:** S
- **의존성:** 없음
- **테스트:**
  - current_price=0 또는 None 입력 시 시그널 생성 거부 테스트
  - RiskManager에서 current_price=0 시 주문 차단 테스트
- **인수 조건:**
  - current_price <= 0이면 HOLD 시그널 반환 (strategy)
  - current_price <= 0이면 Decision.reject 반환 (risk manager)
  - 로그에 WARNING 기록

> **구현 전 확인:** `RiskContext` 데이터클래스에 `current_price` 필드가 있는지 확인 필요. 없다면 `RiskContext`에 필드 추가 후 가드 구현하거나, strategy 레이어에서만 가드 적용.

### T5: 청산 후 재진입 쿨다운 메커니즘

- **설명:** Day1 페이퍼 리포트에서 08:55 강제청산 직후 즉시 재진입 발견. 실거래 시 매회 ~0.1% 수수료 낭비. 청산 후 일정 시간(설정 가능) 동안 해당 종목 재진입을 차단하는 쿨다운 메커니즘 필요.
- **수정 파일:**
  - `src/auto_coin/risk/manager.py` — 쿨다운 체크 로직 추가
  - `src/auto_coin/executor/order.py` — 청산 시 쿨다운 타임스탬프 기록
  - `src/auto_coin/executor/store.py` — 쿨다운 상태 저장
  - `src/auto_coin/config.py` — `cooldown_minutes` 설정 추가 (기본값: 30)
- **복잡도:** L
- **의존성:** T3 (RiskManager 가드와 충돌 방지를 위해 T3 먼저)
- **테스트:**
  - 청산 직후 재진입 시도 → 차단 확인
  - 쿨다운 만료 후 재진입 → 허용 확인
  - 일일 리셋(09:00) 시 쿨다운 초기화 확인
  - 강제청산과 수동청산 모두 쿨다운 적용 확인
- **인수 조건:**
  - 설정에서 `cooldown_minutes` 조정 가능
  - 쿨다운 중인 종목은 BUY 시그널이 와도 Decision.reject
  - 쿨다운 상태가 store에 원자적으로 저장/복구
  - 웹 UI에서 쿨다운 상태 표시 (종목 옆에 남은 시간)

### T6: 라이브 모드 체결 확인 폴링

- **설명:** 라이브 모드에서 주문 후 체결 여부를 확인하는 폴링 메커니즘이 없음. 미체결 주문이 방치될 수 있음. 주문 후 체결 상태를 확인하고, 미체결 시 취소 후 재주문 또는 알림 발송.
- **수정 파일:**
  - `src/auto_coin/executor/order.py` — 체결 확인 폴링 루프 추가
  - `src/auto_coin/exchange/upbit_client.py` — 주문 상태 조회 메서드 추가
- **복잡도:** L
- **의존성:** T2 (volume=0 버그 수정 먼저)
- **테스트:**
  - 즉시 체결 시나리오 (폴링 1회로 완료)
  - 부분 체결 시나리오
  - 미체결 후 타임아웃 → 취소 시나리오
  - 네트워크 오류 시 재시도 테스트
- **인수 조건:**
  - 주문 후 최대 N초(설정 가능) 동안 체결 확인 폴링
  - 미체결 시 주문 취소 + 텔레그램 알림
  - 부분 체결 시 나머지 취소 + 체결분만 포지션 기록
  - 폴링 간격과 타임아웃이 설정에서 조정 가능

### T7: `daily_pnl_ratio` 표시 개선

- **설명:** 현재 일일 PnL이 단순 합산만 표시. 투입 자본 대비 가중평균 PnL을 병행 표시하여 실제 수익률을 정확히 파악.
- **수정 파일:**
  - `src/auto_coin/web/routers/dashboard.py` — 가중평균 PnL 계산 로직
  - `templates/dashboard.html` — 표시 UI 수정
- **복잡도:** M
- **의존성:** T5 (쿨다운으로 인한 거래 패턴 변화 반영)
- **테스트:**
  - 가중평균 PnL 계산 단위 테스트
  - 대시보드 렌더링 테스트 (합산 + 가중평균 모두 표시)
- **인수 조건:**
  - 합산 PnL과 투입 자본 대비 가중평균 PnL 동시 표시
  - 포지션 없는 경우 0% 표시
  - 소수점 2자리까지 표시

### Phase 1 병렬 실행 그룹

```
그룹 A (독립, 동시 실행 가능):
  T1: _wants_html() 버그        ← S, 독립
  T2: volume=0 ValueError       ← M, 독립
  T3: avg_entry_price=0 가드    ← M, 독립
  T4: current_price=0 가드      ← S, 독립

그룹 B (그룹 A 완료 후):
  T5: 쿨다운 메커니즘           ← L, T3에 의존
  T6: 체결 확인 폴링            ← L, T2에 의존

그룹 C (그룹 B 완료 후):
  T7: daily_pnl 표시 개선       ← M, T5에 의존
```

### Phase 1 위험 평가

| 위험 | 영향 | 완화 방안 |
|------|------|-----------|
| RiskManager 수정으로 기존 손절 로직 회귀 | 높음 | T3 전후로 기존 테스트 전체 실행, 페이퍼 모드 24h 검증 |
| 쿨다운이 정상 매매를 과도하게 차단 | 중간 | 설정 가능한 파라미터로 구현, 페이퍼 모드에서 최적값 탐색 |
| 체결 폴링이 API rate limit 초과 | 중간 | 폴링 간격 최소 1초, 최대 시도 횟수 제한 |
| volume=0 재시도가 무한 루프 | 높음 | 최대 재시도 횟수 + 타임아웃 설정 |

---

## Phase 2: 보안 강화

> **우선순위:** HIGH
> **예상 소요:** 2~3일
> **위험도:** 중간 — 세션/인증 관련 변경이지만 거래 로직에는 영향 없음
> **선행 조건:** Phase 1 완료

### T8: CSRF 토큰 검증 도입

- **설명:** 현재 SameSite=lax 쿠키에만 의존. POST/PUT/DELETE 요청에 CSRF 토큰 검증 추가. Starlette의 CSRFMiddleware 또는 커스텀 미들웨어 사용.
- **수정 파일:**
  - `src/auto_coin/web/app.py` — CSRF 미들웨어 등록
  - `src/auto_coin/web/middleware.py` (신규) — CSRF 토큰 생성/검증
  - `templates/base.html` — meta 태그에 CSRF 토큰 삽입
  - `templates/` 내 모든 form — hidden input으로 CSRF 토큰 추가
  - `static/js/` — HTMX 요청에 CSRF 헤더 자동 첨부
- **복잡도:** L
- **의존성:** 없음
- **테스트:**
  - CSRF 토큰 없이 POST → 403 응답 테스트
  - 올바른 CSRF 토큰으로 POST → 200 응답 테스트
  - HTMX 요청에서 CSRF 토큰 자동 첨부 검증
  - SSE 엔드포인트는 CSRF 면제 확인
- **인수 조건:**
  - 모든 상태 변경 요청(POST/PUT/DELETE)에 CSRF 토큰 필수
  - 토큰 불일치 시 403 Forbidden + 로그
  - HTMX에서 투명하게 동작 (사용자 경험 변화 없음)

### T9: 세션 고정 방지

- **설명:** 로그인(TOTP 인증) 성공 시 기존 세션 ID를 폐기하고 새 세션을 발급하여 세션 고정 공격 방지.
- **수정 파일:**
  - `src/auto_coin/web/routers/auth.py` — 인증 성공 후 세션 재생성
  - `src/auto_coin/web/session.py` — 세션 재생성 유틸리티
- **복잡도:** M
- **의존성:** 없음
- **테스트:**
  - 로그인 전후 세션 ID 변경 확인
  - 이전 세션 ID로 접근 시 인증 실패 확인
  - 세션 데이터(사용자 정보) 유지 확인
- **인수 조건:**
  - TOTP 인증 성공 시 세션 ID 교체
  - 이전 세션 ID 즉시 무효화
  - 세션 내 사용자 데이터는 새 세션으로 이전

### T10: 라이브 모드 전환 시 TOTP 재확인

- **설명:** 페이퍼 → 라이브 모드 전환은 자산 손실 가능성이 있는 중대한 작업. 전환 시점에 TOTP 재인증을 요구.
- **수정 파일:**
  - `src/auto_coin/web/routers/settings.py` — 모드 전환 엔드포인트에 TOTP 검증 추가
  - `templates/settings.html` — 라이브 전환 시 TOTP 입력 모달
- **복잡도:** M
- **의존성:** T9 (세션 고정 방지 후 진행)
- **테스트:**
  - TOTP 없이 라이브 전환 시도 → 거부 테스트
  - 올바른 TOTP로 라이브 전환 → 성공 테스트
  - 틀린 TOTP로 라이브 전환 → 거부 + 감사 로그 테스트
- **인수 조건:**
  - 라이브 모드 전환 시 TOTP 6자리 입력 필수
  - 3회 실패 시 5분 잠금 + 텔레그램 알림
  - AuditLog에 전환 시도 기록

### T11: TOTP 복구 UI

- **설명:** TOTP 디바이스 분실 시 복구 경로 제공. 초기 설정 시 생성된 복구 코드를 사용하여 TOTP를 재설정.
- **수정 파일:**
  - `src/auto_coin/web/routers/auth.py` — 복구 코드 검증 + TOTP 재설정 엔드포인트
  - `templates/auth/recovery.html` (신규) — 복구 UI
  - `src/auto_coin/web/security.py` — 복구 코드 생성/저장 로직
- **복잡도:** L
- **의존성:** T8, T9 (CSRF + 세션 보안 기반 위에 구축)
- **테스트:**
  - 올바른 복구 코드로 TOTP 재설정 → 성공
  - 사용된 복구 코드 재사용 → 거부
  - 복구 코드 생성 시 암호화 저장 확인
- **인수 조건:**
  - TOTP 초기 설정 시 8개 복구 코드 생성
  - 복구 코드는 1회용 (사용 후 폐기)
  - 복구 성공 시 새 TOTP 시크릿 발급 + QR 표시
  - AuditLog에 복구 시도 기록

### Phase 2 병렬 실행 그룹

```
그룹 A (동시 실행 가능):
  T8: CSRF 토큰 검증         ← L, 독립
  T9: 세션 고정 방지          ← M, 독립

그룹 B (그룹 A 완료 후):
  T10: 라이브 전환 TOTP 재확인  ← M, T9에 의존
  T11: TOTP 복구 UI            ← L, T8+T9에 의존
```

### Phase 2 위험 평가

| 위험 | 영향 | 완화 방안 |
|------|------|-----------|
| CSRF 미들웨어가 HTMX 요청을 차단 | 중간 | HTMX의 hx-headers 설정으로 CSRF 토큰 자동 첨부 테스트 |
| 세션 재생성 시 기존 사용자 로그아웃 | 낮음 | 세션 데이터 마이그레이션 로직 구현 |
| 복구 코드 유출 | 높음 | Fernet 암호화 저장, 생성 시에만 평문 표시 |
| CSRF 미들웨어 순서가 SessionMiddleware와 충돌 | 중간 | Starlette 미들웨어 역순 처리 — CSRF를 SessionMiddleware보다 먼저 등록하여 세션 접근 보장 |

---

## Phase 3: 운영 편의 UI

> **우선순위:** MEDIUM
> **예상 소요:** 3~4일
> **위험도:** 낮음 — 표시/조작 UI이므로 거래 로직 회귀 위험 적음
> **선행 조건:** Phase 2 완료 (보안 기반 위에 구축)

### T12: 수동 매도 버튼 (종목별 긴급 청산)

- **설명:** 대시보드에서 보유 종목 옆에 "매도" 버튼 추가. 클릭 시 해당 종목을 시장가로 즉시 청산.
- **수정 파일:**
  - `src/auto_coin/web/routers/dashboard.py` — 수동 매도 API 엔드포인트
  - `templates/dashboard.html` — 매도 버튼 UI
  - `src/auto_coin/executor/order.py` — 수동 매도 메서드 (기존 force_exit 재활용)
- **복잡도:** M
- **의존성:** T8 (CSRF 토큰으로 보호)
- **테스트:**
  - 매도 버튼 클릭 → 주문 실행 확인 (mock)
  - 보유하지 않은 종목 매도 시도 → 에러 처리
  - CSRF 토큰 검증 확인
  - AuditLog 기록 확인
- **인수 조건:**
  - 보유 종목 각각에 "매도" 버튼 표시
  - 클릭 시 확인 다이얼로그 (HTMX confirm)
  - 매도 완료 후 대시보드 자동 갱신
  - 텔레그램 알림 + AuditLog 기록

### T13: 전체 긴급 청산 버튼

- **설명:** 모든 보유 포지션을 한 번에 시장가 청산하는 "긴급 청산" 버튼. TOTP 재확인 필수.
- **수정 파일:**
  - `src/auto_coin/web/routers/dashboard.py` — 전체 청산 API
  - `templates/dashboard.html` — 긴급 청산 버튼 + TOTP 모달
  - `src/auto_coin/executor/order.py` — 전체 청산 메서드
- **복잡도:** M
- **의존성:** T10 (TOTP 재확인 메커니즘), T12 (개별 매도 메서드 재활용)
- **테스트:**
  - TOTP 없이 전체 청산 → 거부
  - TOTP 확인 후 전체 청산 → 모든 포지션 청산
  - 일부 종목 청산 실패 시 나머지 계속 진행
- **인수 조건:**
  - TOTP 6자리 입력 후에만 실행
  - Kill-switch 자동 활성화 (신규 진입 차단)
  - 각 종목 청산 결과 개별 표시
  - 텔레그램에 전체 청산 실행 알림

### T14: 이벤트 타임라인 위젯

- **설명:** 대시보드에 최근 이벤트(매수/매도/손절/에러/알림)를 시간순으로 표시하는 타임라인 위젯.
- **수정 파일:**
  - `src/auto_coin/web/routers/dashboard.py` — 이벤트 조회 API
  - `templates/components/timeline.html` (신규) — 타임라인 컴포넌트
  - `templates/dashboard.html` — 타임라인 위젯 삽입
- **복잡도:** M
- **의존성:** 없음 (기존 AuditLog/로그 데이터 활용)
- **테스트:**
  - 이벤트 목록 조회 API 테스트
  - 빈 이벤트 시 "이벤트 없음" 표시
  - 페이지네이션/무한 스크롤 동작 확인
- **인수 조건:**
  - 최근 50건 이벤트 시간순 표시
  - 이벤트 유형별 아이콘/색상 구분
  - 실시간 갱신 (SSE 또는 30초 폴링)
  - 이벤트 클릭 시 상세 정보 표시

### T15: AuditLog 조회 UI

- **설명:** 감사 로그를 웹 UI에서 검색/필터링할 수 있는 전용 페이지.
- **수정 파일:**
  - `src/auto_coin/web/routers/audit.py` (신규) — AuditLog 라우터
  - `templates/audit.html` (신규) — 감사 로그 페이지
  - `src/auto_coin/web/app.py` — 라우터 등록
- **복잡도:** M
- **의존성:** 없음
- **테스트:**
  - 로그 목록 조회 + 페이지네이션 테스트
  - 날짜/유형별 필터링 테스트
  - 검색 기능 테스트
- **인수 조건:**
  - 날짜 범위 + 이벤트 유형 필터
  - 텍스트 검색
  - CSV 내보내기 기능
  - 페이지당 50건, 페이지네이션

### Phase 3 병렬 실행 그룹

```
그룹 A (동시 실행 가능):
  T12: 수동 매도 버튼       ← M, T8 의존
  T14: 이벤트 타임라인       ← M, 독립
  T15: AuditLog 조회 UI     ← M, 독립

그룹 B (그룹 A 완료 후):
  T13: 전체 긴급 청산        ← M, T10+T12 의존
```

### Phase 3 위험 평가

| 위험 | 영향 | 완화 방안 |
|------|------|-----------|
| 수동 매도가 자동 매매와 충돌 | 중간 | 수동 매도 시 해당 종목 쿨다운 자동 적용 (T5 재활용) |
| 전체 청산 중 일부 종목 실패 | 중간 | 종목별 독립 실행 + 개별 결과 리포팅 |
| 타임라인 SSE가 대시보드 SSE와 충돌 | 낮음 | 기존 SSE 채널에 이벤트 타입 추가 |

---

## Phase 4: 분석/확장 기능

> **우선순위:** LOW
> **예상 소요:** 5~7일
> **위험도:** 낮음 — 신규 기능이므로 기존 코드 영향 최소
> **선행 조건:** Phase 3 완료 (권장, 필수 아님)

### T16: 백테스트 UI (웹 폼 → 결과 + 수익 곡선)

- **설명:** 웹 UI에서 백테스트 파라미터를 입력하고 결과를 시각화. 기존 `backtest/runner.py`를 웹에서 호출.
- **수정 파일:**
  - `src/auto_coin/web/routers/backtest.py` (신규) — 백테스트 라우터
  - `templates/backtest.html` (신규) — 백테스트 폼 + 결과 페이지
  - `templates/components/equity_curve.html` (신규) — 수익 곡선 차트 (Chart.js)
  - `src/auto_coin/web/app.py` — 라우터 등록
  - `src/auto_coin/backtest/runner.py` — 웹 호출용 인터페이스 추가 (CLI 외)
- **복잡도:** XL
- **의존성:** 없음 (독립 기능)
- **테스트:**
  - 백테스트 실행 API 테스트 (짧은 기간)
  - 파라미터 유효성 검증 테스트
  - 결과 JSON 포맷 테스트
  - 동시 백테스트 실행 방지 테스트
- **인수 조건:**
  - 종목, 기간, K값, sweep 범위 입력 폼
  - 백그라운드 실행 + 진행 상태 표시
  - 결과: 수익률, MDD, 승률, 거래 횟수
  - 수익 곡선 차트 (Chart.js)
  - 결과 저장 + 이력 조회

### T17: 성과 대시보드 (일별 PnL, 승률/MDD 추이)

- **설명:** 일별 PnL, 누적 수익률, 승률, MDD 추이를 차트로 시각화하는 전용 성과 페이지.
- **수정 파일:**
  - `src/auto_coin/web/routers/performance.py` (신규) — 성과 라우터
  - `templates/performance.html` (신규) — 성과 대시보드
  - `src/auto_coin/analytics/` (신규 패키지) — 성과 집계 로직
- **복잡도:** XL
- **의존성:** 없음 (기존 리포트 데이터 활용)
- **테스트:**
  - 성과 집계 로직 단위 테스트
  - 데이터 없을 때 빈 차트 표시
  - 날짜 범위 필터 테스트
- **인수 조건:**
  - 일별 PnL 막대 차트
  - 누적 수익률 라인 차트
  - 승률/MDD 추이 차트
  - 기간 필터 (7일/30일/전체)

### T18: 알림 커스터마이징 (이벤트별 on/off)

- **설명:** 텔레그램 알림을 이벤트 유형별로 on/off 설정. 현재는 모든 이벤트가 발송됨.
- **수정 파일:**
  - `src/auto_coin/web/routers/settings.py` — 알림 설정 UI
  - `src/auto_coin/notifier/telegram.py` — 이벤트 유형별 필터링
  - `src/auto_coin/config.py` — 알림 설정 추가
  - `templates/settings.html` — 알림 설정 폼
- **복잡도:** M
- **의존성:** 없음
- **테스트:**
  - 알림 on/off 설정 저장/로드 테스트
  - off된 이벤트 알림 미발송 확인
  - 기본값: 모든 이벤트 on
- **인수 조건:**
  - 이벤트 유형: 매수, 매도, 손절, 에러, 하트비트, 일일 리포트
  - 각각 독립적으로 on/off
  - 설정 DB 저장 + 재시작 시 유지

### T19: 추가 전략 (MA 크로스, RSI, 볼린저)

- **설명:** 변동성 돌파 외에 추가 전략 구현. Strategy 인터페이스를 따르는 새 전략 클래스.
- **수정 파일:**
  - `src/auto_coin/strategy/ma_crossover.py` (신규)
  - `src/auto_coin/strategy/rsi.py` (신규)
  - `src/auto_coin/strategy/bollinger.py` (신규)
  - `src/auto_coin/strategy/__init__.py` — 전략 레지스트리
  - `src/auto_coin/web/routers/settings.py` — 전략 선택 UI
- **복잡도:** XL
- **의존성:** 없음 (Strategy 인터페이스 준수)
- **테스트:**
  - 각 전략 단위 테스트 (순수 함수 검증)
  - 백테스트 러너와 통합 테스트
  - 동일 입력 = 동일 출력 보장
- **인수 조건:**
  - strategy/ 내 순수 함수로 구현 (I/O 금지)
  - 기존 Strategy 인터페이스 (`generate_signal()`) 준수
  - 각 전략별 백테스트 결과 제공
  - 웹 UI에서 전략 선택 가능

### T20: V1/V2 동시 실행 방지 메커니즘

- **설명:** V1 CLI와 V2 웹 콘솔이 동시 실행되면 상태 파일 충돌. Lock 파일 기반 동시 실행 방지.
- **수정 파일:**
  - `src/auto_coin/utils/lock.py` (신규) — 프로세스 lock 유틸리티
  - `src/auto_coin/main.py` — 시작 시 lock 획득
  - `src/auto_coin/web/app.py` — 시작 시 lock 획득
- **복잡도:** M
- **의존성:** 없음
- **테스트:**
  - 첫 번째 인스턴스 lock 획득 → 성공
  - 두 번째 인스턴스 lock 획득 → 실패 + 에러 메시지
  - 비정상 종료 후 stale lock 정리
- **인수 조건:**
  - PID 기반 lock 파일 (`state/auto_coin.lock`)
  - 이미 실행 중이면 명확한 에러 메시지 + 종료
  - stale lock (프로세스 죽었지만 파일 남음) 자동 감지/정리

### Phase 4 병렬 실행 그룹

```
그룹 A (모두 동시 실행 가능):
  T16: 백테스트 UI           ← XL, 독립
  T17: 성과 대시보드          ← XL, 독립
  T18: 알림 커스터마이징      ← M, 독립
  T19: 추가 전략             ← XL, 독립
  T20: V1/V2 동시 실행 방지   ← M, 독립
```

### Phase 4 위험 평가

| 위험 | 영향 | 완화 방안 |
|------|------|-----------|
| 백테스트가 서버 리소스 과다 사용 | 중간 | 동시 실행 1건 제한, 타임아웃 설정 |
| 새 전략이 Strategy 인터페이스와 불일치 | 낮음 | 인터페이스 ABC 클래스로 강제 |
| Lock 파일이 NFS/Tailscale 환경에서 오동작 | 낮음 | fcntl.flock() 대신 PID 파일 + 프로세스 존재 확인 |

---

## Phase 5: 기술 부채 + 문서

> **우선순위:** LOW
> **예상 소요:** 3~4일
> **위험도:** 매우 낮음 — 대부분 리팩토링과 문서 작업
> **선행 조건:** 없음 (독립 실행 가능, Phase 1~4와 병렬 가능)

### T21: `datetime.utcnow()` → `datetime.now(UTC)` 교체

- **설명:** Python 3.12에서 deprecated된 `datetime.utcnow()` 호출을 `datetime.now(timezone.utc)`로 교체.
- **수정 파일:** `datetime.utcnow()` 사용하는 모든 파일 (전체 검색 필요)
- **복잡도:** S
- **의존성:** 없음
- **테스트:** 기존 테스트 전체 통과 확인 (동작 변화 없어야 함)
- **인수 조건:**
  - `datetime.utcnow()` 호출 0건
  - `ruff check` 관련 경고 0건
  - 기존 테스트 전체 통과

### T22: 대시보드 UpbitClient 공유 인스턴스

- **설명:** 대시보드 요청마다 UpbitClient를 재생성하는 비효율. 앱 레벨 공유 인스턴스로 변경.
- **수정 파일:**
  - `src/auto_coin/web/routers/dashboard.py` — 공유 인스턴스 사용
  - `src/auto_coin/web/dependencies.py` (신규 또는 기존) — FastAPI Depends로 공유 인스턴스 주입
- **복잡도:** M
- **의존성:** 없음
- **테스트:**
  - 동일 요청에서 같은 인스턴스 사용 확인
  - 인증 정보 변경 시 인스턴스 갱신 확인
- **인수 조건:**
  - 요청당 UpbitClient 생성 횟수: 0 (앱 시작 시 1회)
  - 인증 정보 변경 시 인스턴스 재생성
  - 기존 동작과 동일

### T23: `main.py` 테스트 추가

- **설명:** V1 진입점 `main.py`의 테스트 커버리지가 0건. 주요 경로 테스트 추가.
- **수정 파일:**
  - `tests/test_main.py` (신규) — main.py 테스트
- **복잡도:** M
- **의존성:** 없음
- **테스트:**
  - `--once` 모드 실행 테스트
  - `--live` 플래그 파싱 테스트
  - 스케줄러 초기화 테스트
  - 잘못된 인자 에러 처리 테스트
- **인수 조건:**
  - main.py 주요 함수 커버리지 80% 이상
  - 실제 API 호출 없이 mock으로 검증

### T24: BotManager 동시성 테스트

- **설명:** BotManager의 lock-protected reload와 동시 접근 시나리오 테스트 추가.
- **수정 파일:**
  - `tests/test_bot_manager_concurrency.py` (신규)
- **복잡도:** M
- **의존성:** 없음
- **테스트:**
  - 동시 reload 호출 시 데이터 정합성 테스트
  - reload 중 상태 조회 시 일관성 테스트
  - 다중 스레드에서 BotManager 접근 테스트
- **인수 조건:**
  - 동시성 관련 테스트 5건 이상
  - threading/asyncio 기반 동시 접근 시나리오 커버

### T25: pytest 경고 59건 정리

- **설명:** 현재 pytest 실행 시 59건의 경고 발생. deprecation warning과 설정 경고 정리.
- **수정 파일:** 경고 원인에 따라 다수 파일 (pytest 실행하여 확인 필요)
- **복잡도:** M
- **의존성:** T21 (datetime 교체로 일부 경고 해소)
- **테스트:** `pytest -W error` 실행 시 경고 0건
- **인수 조건:**
  - pytest 경고 0건 (또는 외부 라이브러리 발 경고만 남김)
  - `pyproject.toml`에서 필터링할 경고 명시

### T26: PWA (manifest + service worker)

- **설명:** Progressive Web App 지원 추가. 모바일에서 홈 화면에 추가하여 앱처럼 사용.
- **수정 파일:**
  - `src/auto_coin/web/static/manifest.json` (신규)
  - `src/auto_coin/web/static/sw.js` (신규)
  - `src/auto_coin/web/static/icons/` (신규) — 앱 아이콘
  - `templates/base.html` — manifest 링크 + SW 등록
- **복잡도:** M
- **의존성:** 없음
- **테스트:**
  - manifest.json 응답 테스트
  - service worker 등록 스크립트 존재 확인
- **인수 조건:**
  - 모바일 크롬에서 "홈 화면에 추가" 가능
  - 오프라인 시 캐시된 페이지 표시
  - 앱 아이콘 + 스플래시 스크린

### T27: 다크 모드

- **설명:** 시스템 설정 또는 수동 토글로 다크 모드 전환.
- **수정 파일:**
  - `src/auto_coin/web/static/css/dark.css` (신규) — 다크 모드 스타일
  - `templates/base.html` — 다크 모드 토글 + prefers-color-scheme
  - `src/auto_coin/web/static/js/theme.js` (신규) — 테마 전환 로직
- **복잡도:** M
- **의존성:** 없음
- **테스트:**
  - 테마 전환 localStorage 저장 확인
  - prefers-color-scheme 자동 감지 확인
- **인수 조건:**
  - 수동 토글 + 시스템 설정 자동 감지
  - 선택한 테마 localStorage에 저장
  - 모든 페이지에서 다크 모드 정상 렌더링

### T28: 문서 정비

- **설명:** USER_GUIDE.md 하드코딩 경로 업데이트, CHANGELOG [Unreleased] 정리, REST API 문서 작성.
- **수정 파일:**
  - `docs/USER_GUIDE.md` — 경로 업데이트
  - `CHANGELOG.md` — [Unreleased] 정리
  - `docs/v2/API.md` (신규) — REST API 엔드포인트 문서
- **복잡도:** M
- **의존성:** Phase 3 완료 후 (API 확정 이후 문서화)
- **테스트:** N/A (문서)
- **인수 조건:**
  - 하드코딩 경로 0건
  - CHANGELOG 최신 상태 반영
  - 모든 REST 엔드포인트 문서화 (경로, 메서드, 파라미터, 응답)

### Phase 5 병렬 실행 그룹

```
그룹 A (모두 동시 실행 가능):
  T21: datetime.utcnow() 교체    ← S, 독립
  T22: UpbitClient 공유 인스턴스  ← M, 독립
  T23: main.py 테스트 추가       ← M, 독립
  T24: BotManager 동시성 테스트  ← M, 독립
  T26: PWA                       ← M, 독립
  T27: 다크 모드                  ← M, 독립

그룹 B (그룹 A 완료 후):
  T25: pytest 경고 정리           ← M, T21 의존

그룹 C (Phase 3 완료 후):
  T28: 문서 정비                  ← M, Phase 3 의존
```

### Phase 5 위험 평가

| 위험 | 영향 | 완화 방안 |
|------|------|-----------|
| datetime 교체로 시간 비교 로직 변경 | 낮음 | aware/naive datetime 혼용 체크 |
| UpbitClient 공유 인스턴스 thread-safety | 중간 | pyupbit의 thread-safety 확인 후 lock 추가 |
| pytest 경고 정리 시 테스트 동작 변경 | 낮음 | 한 건씩 수정하며 테스트 통과 확인 |

---

## 커밋 전략

### Phase별 커밋 단위

| Phase | 커밋 전략 |
|-------|-----------|
| Phase 1 | 태스크별 개별 커밋 (버그 수정은 추적 용이하도록) |
| Phase 2 | T8+T9 묶어서 1커밋, T10 1커밋, T11 1커밋 |
| Phase 3 | 태스크별 개별 커밋 |
| Phase 4 | 기능별 개별 커밋 (각각 독립 PR 가능) |
| Phase 5 | 관련 항목 묶어서 (T21+T25, T26+T27 등) |

### 브랜치 전략

```
main
├── fix/phase1-critical-bugs      ← Phase 1 (머지 후 Phase 2 시작)
├── feat/phase2-security          ← Phase 2
├── feat/phase3-operational-ui    ← Phase 3
├── feat/backtest-ui              ← T16
├── feat/performance-dashboard    ← T17
├── feat/additional-strategies    ← T19
├── chore/tech-debt               ← Phase 5
└── docs/documentation-update     ← T28
```

---

## 성공 기준

### Phase 1 완료 기준 (실거래 전환 게이트)
- [ ] 3건 버그 모두 수정 + 테스트 통과
- [ ] 쿨다운 메커니즘 페이퍼 모드 24h 검증 완료
- [ ] 체결 확인 폴링 페이퍼 모드 검증 완료
- [ ] 기존 287건 + 신규 테스트 전체 green
- [ ] ruff check clean

### Phase 2 완료 기준 (보안 게이트)
- [ ] CSRF 토큰 검증 활성화
- [ ] 세션 고정 방지 적용
- [ ] 라이브 전환 TOTP 재확인 동작
- [ ] 침투 테스트 기본 항목 통과

### 최종 완료 기준
- [ ] Phase 1~5 전체 태스크 구현
- [ ] pytest 전체 green (287 + 신규)
- [ ] ruff check clean
- [ ] 실거래 7일 무사고 운영

---

## 전체 일정 요약

| Phase | 예상 소요 | 누적 | 실거래 전 필수 |
|-------|-----------|------|---------------|
| Phase 1: 버그 수정 + 실거래 전 필수 | 3~4일 | 3~4일 | **YES** |
| Phase 2: 보안 강화 | 2~3일 | 5~7일 | **YES** |
| Phase 3: 운영 편의 UI | 3~4일 | 8~11일 | 권장 |
| Phase 4: 분석/확장 기능 | 5~7일 | 13~18일 | 아니오 |
| Phase 5: 기술 부채 + 문서 | 3~4일 | (병렬) | 아니오 |

> **실거래 전환 최소 경로:** Phase 1 + Phase 2 = 약 5~7일
> **Phase 5는 다른 Phase와 병렬 실행 가능**하므로 전체 일정에 추가되지 않음
