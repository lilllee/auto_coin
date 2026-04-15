# CHANGELOG

auto_coin의 버전/마일스톤별 주요 변경 이력.

형식: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) 참고.
날짜는 KST 기준, 커밋 SHA는 `main`/`v2` 브랜치 기준.

---

## [V3 — 전략 검토 고도화 + 투자 판단 보조] (2026-04-16)

### V3.1 — Review SELL 모드 (2026-04-15)

**추가**
- `review/simulator.py` — `include_strategy_sell` 파라미터: 전략 자체 SELL 로직을 review에서만 활성화
- `review.html` — 모드 선택 UI: "전략 신호만" / "전략 SELL 포함"
- entry-only 전략(volatility_breakout) 라벨 표시
- SELL 항상 활성 전략(sma200_ema_adx_composite) 라벨 표시

**테스트**: 533 passed

### V3.2 — Review 설명력 강화 (2026-04-15)

**추가**
- `review/reasons.py` — 전략별 reason formatter 모듈 분리
- 6개 전략 모두 상세 why-buy/hold/sell 이유 제공
- `mode_note()`, `mode_label()`, `summary_interpretation()` 헬퍼

**테스트**: 538 passed

### V3.3 — Operational Exit 모드 (2026-04-16)

**추가**
- review 전용 운영 청산 시뮬레이션: 손절(stop-loss) + 시간청산(time-exit for VB)
- `ReviewEvent.exit_type` — strategy vs operational 구분
- UI 3모드 선택: "전략 신호만" / "전략 SELL 포함" / "운영 청산 포함"
- 이벤트 테이블에 유형 컬럼 추가

**테스트**: 544 passed

### V3.4 — Signal Board (2026-04-16)

**추가**
- `/signal-board` 신규 페이지: 종목별 실시간 전략 상태 표시
- `web/services/signal_board.py` — 현재가 기반 전략 신호 계산 서비스
- 종목별 상태(매수 가능/대기/차단/보유 중) + 이유
- 레짐 인디케이터(risk-on/risk-off)
- 슬롯/kill-switch 요약

**테스트**: 549 passed

### V3.5 — Review/실운영 정합성 (2026-04-16)

**추가**
- review 페이지에 일봉 종가 기준 disclaimer 배너
- Signal Board에 장중 신호 힌트
- summary 해석 문구에 데이터 기준 접미사

### V3.6 — 전략 비교 보드 (2026-04-16)

**추가**
- `/compare` 신규 페이지: 전체 전략을 같은 기간/종목으로 비교
- 총 손익 기준 내림차순 정렬, 현재 전략 하이라이트
- BUY/SELL 횟수, 실현/미실현/총 손익 비교 테이블

### V3.7 — 리스크 대시보드 (2026-04-16)

**추가**
- `/risk` 신규 페이지: kill-switch, 슬롯, 손실 한도, 손절선, 운영 모드, 포지션 현황, 스케줄 정보 통합 뷰

### V3.8 — 문서화 (2026-04-16)

**변경**
- README.md 업데이트: V3 기능(전략검토/상태판/비교/리스크) 반영
- CHANGELOG.md 업데이트: V3.1~V3.8 이력 추가
- docs/v3/PLAN.md 체크박스 갱신

**테스트**: 553 passed · `ruff check` 통과

---

## [Unreleased — v2 branch]

### Phase 1 trade-safety fixes + Phase 2 security completion (2026-04-14)

**추가**
- `web/csrf.py` — 세션 기반 CSRF 토큰 생성/검증, form field + `X-CSRF-Token` 지원
- `templates/auth/recovery.html` + `/recovery` — 복구 코드 기반 TOTP 재설정 UI
- `runtime_guard.py` — V1 CLI / V2 web 동시 실행 방지 lock

**변경**
- `routers/auth.py` — 로그인/초기 설정 완료 시 세션 재생성, 복구 코드 플로우 추가
- `routers/settings.py` — `paper -> live` 전환 시 현재 TOTP 재확인 필수
- `models.py` / `db.py` — recovery code 저장 컬럼 + 경량 SQLite schema 보정
- 최신 운영 문서와 핸드오프 반영

**테스트**
- `pytest` 340 passed
- `ruff check src tests` 통과

### V2.8 — launchd 서비스 + Tailscale 가이드 (2026-04-14)

**추가**
- `deploy/com.sj9608.auto_coin.plist` — macOS launchd 템플릿 (`RunAtLoad`, `KeepAlive`, `ThrottleInterval=10`)
- `deploy/install_launchd.sh` — 프로젝트 경로 자동 치환 후 `~/Library/LaunchAgents/`에 로드
- `deploy/README.md` — 설치/검증/제거 명령, 3개 HOME 파일 백업 주의
- `docs/tailscale-setup.md` — Tailscale 설정 전체 흐름, `--host 0.0.0.0` 바인딩 + macOS 방화벽 + Tailscale ACL 3중 방어

**변경**
- 웹앱의 `--host 0.0.0.0` 지원 (launchd 설정이 기본 채용)

---

### V2.7 — 실시간 로그 SSE (2026-04-14)

**추가**
- `web/services/log_stream.py` — 500-line `deque` ring buffer + asyncio.Queue fan-out, loguru `install_sink()` 통해 record 수집
- `web/routers/logs.py` — GET `/logs` (페이지, 초기 200줄 embed) / GET `/logs/recent` (JSON, clamp limit) / GET `/logs/stream` (SSE)
- `templates/logs.html` — dark 터미널 스타일, 레벨 필터 (DEBUG/INFO/WARNING/ERROR), 자동 스크롤 토글, EventSource 재연결
- SSE 첫 chunk는 `: connected` 코멘트로 즉시 flush (프록시/TestClient 블로킹 우회)

**제거**
- `routers/placeholders.py`, `templates/placeholder.html` — 모든 섹션이 실제 구현됨

**테스트**: 10건 신규 (ring buffer cap · install_sink 통합 · format_sse · page render · recent JSON · clamp · auth · subscribe/unsubscribe).

---

### V2.6 — 리포트 뷰어 (2026-04-14)

**추가**
- `web/routers/reports.py` — GET `/reports` (파일 목록, 최신순, 첫 H1 title) / GET `/reports/{name}` (markdown2 렌더)
- 경로 traversal 방지: `/`·`\\`·`..`·`.prefix` 거부, `.md` 확장자 강제, `resolve()`로 경로 재검증
- `templates/reports/index.html` + `detail.html` — scoped `.markdown-body` CSS (dark code block, 반응형 테이블)

**테스트**: 8건 신규 (목록/정렬/타이틀/404/traversal/non-md/empty dir/auth).

---

### V2.5 — 차트 (Chart.js 일봉 라인) (2026-04-14)

**추가**
- `web/routers/charts.py` — GET `/charts` (드롭다운 + canvas), GET `/charts/data/{ticker}` (JSON: labels/close/target/ma + entry_price)
- `templates/charts.html` — Chart.js CDN, 종가 + MA(점선) + target(점선) + 보유 시 진입가 수평선
- UpbitError는 502로 응답, NaN은 JSON null (Chart.js가 gap으로 처리)

**테스트**: 7건 신규.

---

### V2.4 — 대시보드 + 봇 컨트롤 (2026-04-14)

**추가**
- `web/routers/dashboard.py` — GET `/` (전체 렌더), GET `/dashboard/partial` (5s polling 대상 본문)
- `web/routers/control.py` — POST `/control/kill-switch|start|stop|restart`, AuditLog 기록 + `BotManager.reload()` 연동, 정지는 `confirm=yes` 요구
- `templates/dashboard.html` — 상태 뱃지(running/paper·live/kill-switch) + 2열 컨트롤 그리드
- `templates/partials/dashboard_body.html` — 슬롯/PnL/잔고 요약, 포지션 카드, 최근 주문 10건, HTMX `hx-trigger="every 5s"`
- `templates/partials/_format.html` — `money()` / `sign_pct()` jinja macro (`auto_coin.formatting.format_price`와 동일 규칙)

**제거**
- 기존 V2.1 `/` home stub, `home.html`

**테스트**: 11건 신규 (render · positions+PnL · partial-only body · kill-switch toggle · restart · stop confirmation · start from stopped · auth · flash · LIVE badge).

---

### V2.3 — 설정 수정 UI · API 키 테스트 · 거래대금 추천 (2026-04-14)

**추가**
- `/settings` 허브 + 5개 섹션 폼: **전략 / 리스크 / 포트폴리오 / API 키 / 스케줄·모드**
- 저장 시 pydantic 재검증 → DB 업서트 → `AuditLog` 기록 → `BotManager.reload()` → flash 메시지 → 303 리다이렉트
- 포트폴리오 폼에 **업비트 KRW 마켓 거래대금 상위 20 추천** (현재 보유/관측 종목 자동 제외)
- 종목 입력 시 **업비트 상장 검증** — 미상장 티커 거부 (오타 방지)
- API 키 섹션에 **HTMX 기반 "연결 테스트" 버튼** — Upbit `get_balance` / Telegram `getMe` + 테스트 메시지
- API 키 UI 마스킹 (`••••last4`), 빈 입력 시 기존 값 유지
- `web/services/upbit_scan.py` — 60s TTL 캐시로 KRW 마켓 목록 / 거래대금 상위 조회
- `web/services/credentials_check.py` — `check_upbit` / `check_telegram` 서비스
- `web/audit.py` — `AuditLog` 기록 헬퍼 (민감 필드 자동 마스킹)
- `web/auth.py::flash()` — 세션 기반 플래시 메시지

**변경**
- `placeholders.py`에서 `/settings` 제거 (실제 라우터로 대체)
- `base.html` flash 영역이 `{level, text}` dict 구조로 확장 (ok/warn/error 색상 분기)

**테스트**: 30건 신규 (services 14 + settings 16). 전체 **263/263**.

---

### V2.2 — UI 스캐폴딩: 하단 탭 / 404 / placeholder 라우터 (2026-04-14)

**추가**
- `base.html` 모바일 하단 고정 탭 네비(📊대시/📈차트/📄리포트/📜로그/⚙️설정), iOS safe-area 반영, active 탭 하이라이트
- `templates/placeholder.html` — 마일스톤 표기 있는 "예정" 카드
- `templates/error.html` — 404/HTTPException 공용 에러 카드
- `routers/placeholders.py` — `/charts`·`/reports`·`/logs`·`/settings` 임시 페이지
- HTTPException 핸들러 content-negotiation: `text/html` → 에러 페이지, `application/json` → JSON

**테스트**: 13건 신규.

---

### V2.1 — 인증 (password + TOTP + 세션 + lockout) (2026-04-14)

**추가**
- `/setup` 최초 가드: 패스워드 설정 → TOTP QR 발급 → 6자리 확인 → 자동 로그인
- `/login` · `/logout` 라우터
- Starlette `SessionMiddleware` — 파일 기반 비밀키(`~/.auto_coin_session.key`, 0600), 7일 TTL, `SameSite=lax`
- `require_auth` dependency — 미인증 요청 `/login`으로 303 리다이렉트
- 실패 카운터: 5회 실패 시 10분 lockout, 성공 시 리셋
- bcrypt 직접 사용 (passlib 1.7.4가 bcrypt 5.x의 `__about__` 제거와 충돌)
- TOTP secret은 Fernet 암호화로 DB에 저장

**테스트**: 28건 신규 (user_service 20 + auth_flow 8).

---

### V2.0 — 웹 기반: FastAPI + SQLite + BotManager (2026-04-14)

**추가**
- `src/auto_coin/web/` 패키지 신설 — FastAPI + BackgroundScheduler 단일 프로세스
- `web/crypto.py::SecretBox` — Fernet 대칭키 래퍼, 마스터키 `~/.auto_coin_master.key` (0600 자동 생성)
- `web/models.py` — SQLModel 테이블: `AppSettings` (단일 row), `User`, `AuditLog`
- `web/db.py` — SQLite 엔진, `check_same_thread=False`로 스케줄러 워커와 요청 스레드 공유
- `web/settings_service.py` — DB ↔ `Settings` 변환, **최초 1회 `.env` → DB 시드**
- `web/bot_manager.py` — `BackgroundScheduler` + `TradingBot` 수명 관리, `reload()` 시 lock으로 동시성 보호
- `web/app.py` — FastAPI 앱 팩토리 + lifespan, `/health` 엔드포인트
- `web/__main__.py` — uvicorn 런처 (기본 127.0.0.1)
- 의존성: fastapi / uvicorn / sqlmodel / cryptography / bcrypt / pyotp / qrcode / httpx / jinja2 / markdown2

**테스트**: 30건 신규 (crypto 9 + settings_service 7 + bot_manager 4 + health 1 등).

---

## [main — V1 완료]

### formatter — 저가 종목 가격 포매팅 (2026-04-14)

**추가**
- `auto_coin/formatting.py::format_price` — 값 크기에 따라 소수점 자릿수 자동 (100 이상 정수 / 10–100 .1f / 1–10 .2f / 0.01–1 .4f / 0.0001–0.01 .6f / 이하 .8f)
- `bot.watch` / `bot.heartbeat` / BUY·SELL 알림 / `force_exit` / `executor.order` 로그 / `reporter` 포지션 표기에 전면 적용
- DRIFT(87.6)·ATH(9.47)처럼 저가 종목의 소수점 변화 가시화

**테스트**: 26건 신규.

---

### M9a — 멀티 종목 포트폴리오 (2026-04-13)

**추가**
- `TICKERS` (콤마 구분, 진입 우선순위) + `MAX_CONCURRENT_POSITIONS` 설정
- `config.Settings.portfolio_ticker_list` — `TICKERS` 우선, 비어있으면 `TICKER` 폴백
- `RiskContext`에 `portfolio_open_positions` / `portfolio_max_positions` 추가
- BUY 시 동시 보유 상한 가드, 손절은 슬롯과 무관하게 최우선
- `TradingBot` 생성자가 `stores`/`executors` dict로 변경 — 종목별 독립 `OrderStore` / `OrderExecutor`
- `tick`이 TICKERS 순회하며 슬롯 카운트 실시간 갱신 (앞 종목이 진입하면 뒤 종목은 슬롯 없어 HOLD)
- `force_exit` / `daily_reset` / `heartbeat` / `daily_report` 전부 포트폴리오 순회로 재구성
- `state/{TICKER}.json` 종목별 파일 분리 (재시작 시 자동 복구)

**설계 결정** (Day 1 합의)
- 자본 배분: **균등** (`paper_initial_krw × max_position_ratio` 고정)
- 시그널 충돌 해소: 정적 우선순위 (`TICKERS` 나열 순서)
- 일일 손실 한도: 모든 종목 `daily_pnl_ratio` **합산** 기준

**테스트**: 22건 신규 (config 7 + risk 4 + portfolio integration 8 + 기존 호환 수정).

---

### M7b — 텔레그램 모니터링 강화 (2026-04-13)

**추가**
- `TelegramNotifier.check()` — `getMe`로 토큰 유효성 확인 + `BotInfo` 반환
- `TelegramNotifier.find_chat_ids()` — `getUpdates`에서 1:1/채널/그룹 chat_id 추출
- Markdown `parse_mode=None` 기본 (400 노이즈 제거)
- `python -m auto_coin.notifier` CLI — `--check` / `--find-chat-id` / `--send TEXT`
- `HEARTBEAT_INTERVAL_HOURS` + 스케줄러 IntervalTrigger heartbeat 잡 (기본 6시간)
- `TradingBot.tick`을 `_tick_impl` 래핑 → 예상 외 예외도 🔥 크래시 알림 보장

**테스트**: 17건 신규.

---

### M7 — 페이퍼 운영 인프라: 일일 리포트 (2026-04-13)

**추가**
- `reporter.py::build_daily_report` — 매수/매도 페어링으로 사이클 손익, 승률, best/worst 계산
- `TradingBot.daily_report()` — 08:58 KST cron에 자동 발송
- 메시지 포맷: 포트폴리오 합계 + 종목별 리포트

**테스트**: 8건 신규.

---

### M6 — 스케줄러 + 엔트리포인트 통합 (2026-04-13)

**추가**
- `TradingBot` — `tick` / `daily_reset` / `force_exit_if_holding` 오케스트레이션
- `main.py` — `BlockingScheduler`(Asia/Seoul): 60s tick, 08:55 청산, 08:58 리포트, 09:00 리셋, 6h heartbeat, 15m watch
- `--once` 디버그 실행, `--live` 실거래 강제 플래그
- SIGINT/SIGTERM → graceful shutdown + 텔레그램 종료 알림

**테스트**: 10건 신규.

---

### M5 — 리스크 매니저 + 주문 실행기 + 상태 영속화 (2026-04-13)

**추가**
- `RiskManager.evaluate(signal, ctx)` → `Decision`
- 손절 최우선 (BUY 시그널 덮어씀), kill-switch는 신규 진입만 차단, 일일 손실 한도 가드, 최소 주문 / 이중 진입 방지
- `OrderExecutor` — paper/live 분기, 클라이언트 UUID 멱등성, live는 인증 클라이언트 강제
- `OrderStore` — JSON 원자적 저장 (임시파일 + `os.replace`), 재시작 자동 복구
- paper 모드 즉시 체결 시뮬레이션 + `daily_pnl_ratio` 누적

**테스트**: 27건 신규 (RiskManager 12 + Store 5 + Executor 10).

---

### M4 — 백테스트 러너 + K 스윕 CLI (2026-04-13)

**추가**
- `backtest/runner.py::backtest` — 순수 함수, 수수료·슬리피지 파라미터화
- 진입가 = target × (1+slippage), 청산가 = 다음 시가 × (1−slippage)
- `Trade` / `BacktestResult` dataclass, MDD/승률/누적 수익률
- CLI: `--ticker / --days / --k / --sweep START STOP STEP / --fee / --slippage / --no-ma-filter`

**실측 검증**: BTC 365일 K=0.4 cum +9.60%, K=0.5 −2.59%

**테스트**: 12건 신규.

---

### M3 — 전략 인터페이스 + 변동성 돌파 (2026-04-13)

**추가**
- `strategy/base.py` — `Signal`(BUY/SELL/HOLD), `MarketSnapshot`, `Strategy` ABC (순수 함수)
- `strategy/volatility_breakout.py` — Larry Williams 변동성 돌파 + 5일 이평 필터
- BUY 조건: `current_price >= target` AND `current_price > maN`
- 청산은 외부(스케줄러), 손절은 RiskManager 책임

**테스트**: 11건 신규.

---

### M2 — 거래소 래퍼 + 데이터 레이어 + Telegram (2026-04-13)

**추가**
- `exchange/upbit_client.py` — `pyupbit` 래퍼, 재시도(exponential backoff), ~10 req/s throttle, dict-error 정규화, `OrderResult` dataclass
- `data/candles.py::enrich_daily` — 일봉 DataFrame에 `range`/`target`/`maN` 컬럼 추가 (전일 데이터만 사용 → 백테스트 미래 누수 방지)
- `notifier/telegram.py` — 토큰/chat_id 없으면 no-op, 네트워크 실패 swallow
- **다른 모듈은 `pyupbit` 직접 import 금지** (모듈 경계 규칙)

**테스트**: 21건 신규.

---

### M1 — 프로젝트 스캐폴딩 (2026-04-13)

**추가**
- `pyproject.toml` (Python 3.11+, 의존성, ruff/pytest 설정)
- `src/auto_coin/` 패키지 구조 (config / logging_setup / main / 빈 서브모듈)
- `config.py` — `pydantic-settings` 기반 `.env` 로드, 검증
- `.env.example`, `.gitignore`, README, CLAUDE.md
- pytest 5건 (defaults / env 오버라이드 / kill-switch / 검증 거부)

---

## 초기 설계 (2026-04-13)

- `PLAN.md` — 업비트 자동매매 봇 V1 설계서 (아키텍처 / 마일스톤 M1~M9 / 리스크 규칙 / 업비트 인증 / 구현 단계)
- 커밋 `27d249d` 초기 커밋

---

## 테스트 진행 경과

| 시점 | 누적 테스트 |
|---|---:|
| M1 | 5 |
| M2 | 26 |
| M3 | 37 |
| M4 | 49 |
| M5 | 76 |
| M6 | 86 |
| M7 | 94 |
| M7b | 111 |
| M9a | 146 |
| formatter | 172 |
| V2.0 | 193 |
| V2.1 | 221 |
| V2.2 | 234 |
| V2.3 | 263 |
| V2.4 | 274 |
| V2.5 | 278 |
| V2.6 | 284 |
| V2.7 | 287 |
| **V2.8** | **287** (deploy scripts, no new tests) |
