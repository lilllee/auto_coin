# REVIEW.md

## auto_coin 현재 상태 리뷰

작성일: 2026-04-14  
작성 목적: 인수인계 전에 저장소 기준으로 **무엇이 구현됐고**, **무엇이 아직 운영/후속 과제로 남아 있는지**를 빠르게 파악하기 위한 현황 정리.

---

## 1. 한줄 결론

이 프로젝트는 **"미완성 초안" 단계가 아니라, V1 CLI 자동매매 봇 + V2 웹 운영 콘솔까지 코드상 대부분 구현이 끝난 상태**입니다.  
지금 시점의 핵심은 새로 큰 기능을 처음부터 만드는 것보다,

1. **운영 전환/실사용 검증**,  
2. **남은 보안 보강**,  
3. **문서와 실제 운영 상태 동기화**

를 이어받아 진행하는 것입니다.

---

## 2. 이번 점검에서 직접 확인한 사실

### 저장소 / 브랜치
- 현재 브랜치: `main`
- `git status` 기준 작업트리 변경은 분석 시작 시점에 `.gitignore` 1건뿐이었음
  - 이는 개발자 지시대로 `.omx/`를 로컬 상태에서 제외하기 위한 변경
- 현재 로컬 git 이력은 매우 짧음
  - `c386ab7 init`
  - `98fdf52 first commit`

### 코드 규모
- `src/auto_coin/**/*.py` 기준 Python 파일 **48개**
- 그중 `src/auto_coin/web/**` 기준 웹 콘솔 관련 Python 파일 **24개**
- `tests/` 아래 테스트 파일 **27개**
- `src/auto_coin/web/templates/**` HTML 템플릿 **20개**

### 직접 실행한 검증
- `.venv/bin/pytest` → **287 passed, 59 warnings in 20.13s**
- `.venv/bin/ruff check src tests` → **All checks passed!**

즉, **현재 체크아웃된 코드 자체는 테스트/린트 기준으로 정상 상태**입니다.

---

## 3. 현재 프로젝트가 어디까지 왔는가

### 3-1. V1 (CLI 자동매매 봇)
문서와 코드 기준으로 아래는 구현 완료 상태입니다.

- Upbit 래퍼 (`exchange/upbit_client.py`)
- 일봉 데이터/지표 계산 (`data/candles.py`)
- 변동성 돌파 전략 (`strategy/volatility_breakout.py`)
- 리스크 게이트 (`risk/manager.py`)
- 주문 실행 / 상태 저장 (`executor/order.py`, `executor/store.py`)
- 백테스트 러너 (`backtest/runner.py`)
- 텔레그램 알림 및 CLI (`notifier/telegram.py`, `notifier/__main__.py`)
- 스케줄러 기반 봇 오케스트레이션 (`bot.py`, `main.py`)
- 멀티 종목 포트폴리오 운영
- 일일 리포트 생성 (`reporter.py`)

정리하면, **전략 실행 엔진 자체는 이미 동작 가능한 수준**이고, 문서상 흐름도 **백테스트 → 페이퍼 → 소액 실거래**로 분명하게 정리돼 있습니다.

### 3-2. V2 (웹 운영 콘솔)
`src/auto_coin/web/` 패키지가 실제로 존재하고, 테스트도 붙어 있어서 **계획만 있는 상태가 아니라 구현 완료된 상태**입니다.

구현 확인된 영역:
- FastAPI 앱/수명주기 관리 (`web/app.py`)
- SQLite/SQLModel 설정 저장 (`web/db.py`, `web/models.py`, `web/settings_service.py`)
- 암호화 저장 (`web/crypto.py`)
- 인증/세션/TOTP (`web/auth.py`, `web/user_service.py`, `web/routers/auth.py`)
- 봇 수명주기 제어 (`web/bot_manager.py`)
- 대시보드/제어 (`dashboard.py`, `control.py`)
- 설정 화면 (`settings.py`)
- 차트 (`charts.py`)
- 리포트 뷰어 (`reports.py`)
- 실시간 로그 SSE (`logs.py`, `services/log_stream.py`)
- 배포 문서/launchd/Tailscale 가이드 (`deploy/*`, `docs/v2/tailscale-setup.md`)

즉 현재 코드는 **"웹에서 설정 보고/수정하고, 봇 상태 보고, 리포트와 로그 보는 운영형 제품"**까지 이미 올라와 있습니다.

---

## 4. 문서 기준 마일스톤 상태 요약

### 이미 끝난 것으로 봐도 되는 것
- V1 M1 ~ M9a: 대부분 완료
- V2.0 ~ V2.9: 코드/문서 기준 완료 표시
- README / CHANGELOG / docs/v1 / docs/v2 문서 정리 완료
- `reports/2026-04-14-paper-day1.md` 운영 관찰 리포트 존재

### 아직 "운영 관점"으로 남아 있는 것
문서상 반복해서 **사용자 액션** 또는 **후속 과제**로 남겨둔 항목:

1. **실운영 검증 부족**
   - 페이퍼 1주+ 장기 운영 확인
   - 소액 실거래(M8)는 아직 미착수

2. **V2 실제 전환 작업**
   - `./deploy/install_launchd.sh` 실행
   - 재부팅 후 자동 기동 검증
   - Tailscale 폰 접속 확인
   - 기존 V1 상주 프로세스 정리

3. **보안 보강**
   - CSRF 토큰 검증 구현 완료
   - 로그인 후 세션 재생성 구현 완료
   - live 전환 시 TOTP 재확인 구현 완료
   - 복구 코드 기반 TOTP 재설정 UI 구현 완료

4. **후순위 제품 기능 미구현**
   - 수동 매도 버튼
   - 최근 이벤트 타임라인
   - 백테스트 UI
   - 성과 대시보드
   - 알림 커스터마이징
   - PWA / 다크모드
   - AuditLog 조회 UI
   - 긴급 전량 청산 버튼

즉, **핵심 제품은 있음 / 운영 안정화와 운영 안전 가드 보강 과제가 남음** 상태입니다.

---

## 5. 인수인계 관점에서 특히 중요한 포인트

### A. 이 프로젝트는 이미 "운영 코드베이스"
테스트 287개가 모두 통과하고, 웹/CLI 양쪽 경로가 살아 있습니다.  
따라서 새 담당자는 "새로 설계"보다 **현재 구조를 이해하고, 운영 리스크를 낮추는 방향**으로 시작하는 것이 맞습니다.

### B. 문서의 목표와 현재 코드가 대체로 일치
README, CHANGELOG, `docs/v1/PLAN.md`, `docs/v2/PLAN.md`, 실제 코드 구조가 전반적으로 잘 맞습니다.  
즉, 문서 신뢰도는 높은 편입니다.

### C. 다만 git 히스토리는 문서보다 단순함
문서에는 `v2` 브랜치, PR #1, 세부 커밋 SHA들이 많이 적혀 있는데,  
**현재 로컬 저장소의 실제 git log는 2개 커밋만 보입니다.**

가능한 해석:
- squash / re-import / 이력 정리 후 현재 저장소만 남았을 수 있음
- 문서는 외부 원격/과거 이력을 기준으로 쓰였을 수 있음

즉, **코드 상태는 신뢰 가능하지만 git 고고학 정보는 현재 로컬 저장소만으로는 복원되지 않습니다.**

### D. 즉시 손볼 가치가 있는 기술 부채/운영 과제가 있음
pytest는 green이지만 경고가 있습니다.

- `src/auto_coin/web/bot_manager.py`에서 `datetime.utcnow()` 사용으로 DeprecationWarning 발생
- 테스트에서도 같은 패턴 일부 확인

치명적 문제는 아니지만, **다음 유지보수자가 가장 먼저 정리해도 되는 안전한 개선 포인트**입니다.
또한 문서상 불변인 **V1/V2 동시 실행 금지**는 코드 레벨 가드가 있으면 더 안전합니다.

---

## 6. 현재 기준 추천 우선순위

### 1순위 — 실제 운영 상태 확인
- 현재 실제로 어떤 프로세스가 돌고 있는지 확인
- V1 CLI 상주인지, V2 웹으로 이미 넘어갔는지 확인
- launchd 등록 여부 / Tailscale 연결 여부 확인
- `.env`, `~/.auto_coin.db`, `state/*.json`, 로그 파일 위치 점검

### 2순위 — 운영 안전성 보강
- V1/V2 동시 실행 방지
- exit 직후 재진입 쿨다운 같은 운영 규칙 개선의 지속 검증
  - `reports/2026-04-14-paper-day1.md`에서 이미 재진입 현상이 관찰됨
- 긴급 청산 / 수동 청산 같은 운영 제어 UI

### 3순위 — 운영 데이터 기반 개선
- paper 리포트 1일치 외에 며칠 더 누적 관찰
- AuditLog 조회 UI / 타임라인 UI 보강
- 성과 대시보드 정리

### 4순위 — 확장 기능
- 백테스트 UI
- 성과 대시보드
- 수동 청산 기능
- PWA/다크모드

---

## 7. 새 담당자가 이해해야 할 핵심 파일

### 꼭 먼저 읽을 문서
1. `README.md`
2. `CLAUDE.md`
3. `CHANGELOG.md`
4. `docs/v1/PLAN.md`
5. `docs/v2/PLAN.md`
6. `reports/2026-04-14-paper-day1.md`

### 코드 진입점
- V1 실행: `src/auto_coin/main.py`
- V1 오케스트레이션: `src/auto_coin/bot.py`
- V2 실행: `src/auto_coin/web/__main__.py`
- V2 앱 생성: `src/auto_coin/web/app.py`
- V2 봇 제어: `src/auto_coin/web/bot_manager.py`
- 설정 로드/저장: `src/auto_coin/config.py`, `src/auto_coin/web/settings_service.py`

---

## 8. 최종 판단

현재 `auto_coin`은:

- **코드 완성도:** 높음
- **테스트 신뢰도:** 높음 (`287 passed` 직접 확인)
- **문서 정리 상태:** 좋음
- **실운영 전환 상태:** 일부 사용자 액션 남음
- **보안/운영 보강 필요성:** 있음
- **인수인계 난이도:** 중간

따라서 이 프로젝트는 **"개발 초기"가 아니라 "이미 돌아갈 준비가 된 제품을 안정화/운영 전환하는 단계"**로 보는 것이 가장 정확합니다.

---

## 9. 이번 리뷰의 근거

직접 확인한 파일/명령:
- `README.md`
- `CHANGELOG.md`
- `CLAUDE.md`
- `docs/v1/PLAN.md`
- `docs/v2/PLAN.md`
- `deploy/README.md`
- `docs/v2/tailscale-setup.md`
- `reports/2026-04-14-paper-day1.md`
- `git status --short --branch`
- `git branch -vv`
- `git log --oneline --decorate -n 20`
- `.venv/bin/pytest`
- `.venv/bin/ruff check src tests`
