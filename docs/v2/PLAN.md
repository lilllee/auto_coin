# auto_coin V2 — 웹 운영 콘솔 구현 계획서

작성일: 2026-04-14 · 승인 후 `v2` 브랜치에서 구현 착수 예정.

---

## 0. 배경

V1까지 봇은 `.env` 편집 + `kill` + `nohup` 재시작으로 운영했다. 이 방식의 한계:

- 외출 중 전략/종목/리스크 파라미터 조정 불가
- 봇을 중단/재시작하려면 SSH/터미널 필요
- API 키·텔레그램 토큰은 파일 편집
- 리포트/차트/로그를 모바일에서 보기 불편

V2는 이 모든 운영 행위를 **모바일 웹 UI**로 옮긴다. 현재 돌고 있는 페이퍼 봇은 `main` 브랜치에서 계속 가동, V2는 `v2` 브랜치에서 병행 개발 후 머지.

---

## 1. 설계 결정 (2026-04-14 합의)

| 항목 | 결정 |
|---|---|
| **외부 접근** | Tailscale 기반 사설 VPN. 로컬 맥이 서버, Tailscale 네트워크 내부에서 폰으로 접근 |
| **인증** | 세션 쿠키(bcrypt 해시 패스워드) + **TOTP 2FA**. API 키 관리 페이지이므로 강제 |
| **브랜치** | `v2` 신규. `main`의 페이퍼 봇은 paper 운영 계속, V2.9 완료 시 merge |
| **프레임워크** | FastAPI + Jinja2 + HTMX + Tailwind (CDN). 빌드 단계 없음, 서버 렌더링 |
| **DB** | SQLite (SQLModel). 설정·세션·감사 로그 저장. 기존 `state/*.json`은 그대로 유지 |
| **API 키 암호화** | Fernet 대칭키. 마스터 키는 `~/.auto_coin_master.key` 파일 (600 권한) |
| **스케줄러** | APScheduler `BackgroundScheduler`로 전환. FastAPI startup에서 시작, 설정 변경 시 graceful 재구성 |
| **실행 단위** | 단일 프로세스에서 FastAPI + Scheduler + TradingBot 통합. `python -m auto_coin.web` 하나로 전부 시작 |

---

## 2. 아키텍처

```
┌─────────────────────────────────────────────────┐
│ macOS (launchd로 항상 실행)                       │
│                                                 │
│  uvicorn                                        │
│   └─ FastAPI app                                │
│       ├─ Routers (settings/dashboard/chart/..)  │
│       ├─ Auth middleware (session + TOTP)       │
│       └─ APScheduler BackgroundScheduler        │
│            ├─ tick (60s)                        │
│            ├─ watch (15m)                       │
│            ├─ force_exit (cron)                 │
│            ├─ daily_report (cron)               │
│            ├─ daily_reset (cron)                │
│            └─ heartbeat (6h)                    │
│                                                 │
│  SQLite (~/.auto_coin.db)   ← 설정/세션/감사    │
│  state/{TICKER}.json        ← 포지션 (기존 유지)  │
│  logs/*.log                 ← loguru (기존 유지)  │
│                                                 │
└─────────────────────────────────────────────────┘
       ▲
       │ Tailscale (100.x.y.z:8080)
       │
   [ iPhone Safari ]  ← 웹 UI (HTMX + Tailwind)
```

### 모듈 경계 (V1 불변 유지)

- `strategy/` · `risk/` · `backtest/` · `data/` · `exchange/` · `formatting.py` → **변경 없음**
- `bot.py::TradingBot` → 기본 인터페이스 유지, 생성자에 `settings_provider` 콜백 추가해 런타임 설정 갱신 반영 가능하게
- `config.py` → `.env` 로드에서 **SQLite 로드**로 기본값 전환, `.env`는 최초 부트스트랩 시드로만 사용
- `executor/store.py` → 그대로 (JSON 파일). DB로 이관 안 함 (재시작 복구 검증된 파일 기반 유지)
- `notifier/telegram.py` → 그대로
- 신규 `web/` 패키지 추가

### 새 패키지 구조

```
src/auto_coin/web/
├── __init__.py
├── __main__.py           # python -m auto_coin.web → uvicorn 구동
├── app.py                # FastAPI 생성, lifespan으로 scheduler 관리
├── db.py                 # SQLModel 엔진, 세션
├── models.py             # Settings / User / Session / AuditLog
├── crypto.py             # Fernet 래퍼 (API 키 암호화)
├── auth.py               # password/TOTP/세션 미들웨어
├── bot_manager.py        # TradingBot 빌드/재구성, scheduler 제어
├── routers/
│   ├── auth.py           # /login, /logout, /setup (초기 TOTP 등록)
│   ├── dashboard.py      # /
│   ├── settings.py       # /settings/* (전략·리스크·API·알림·종목)
│   ├── charts.py         # /charts/:ticker
│   ├── reports.py        # /reports, /reports/:name
│   ├── logs.py           # /logs (SSE)
│   └── control.py        # /control/start|stop|restart|kill-switch
├── services/
│   ├── upbit_scan.py     # 거래대금 상위 조회, 상장 검증
│   └── log_stream.py     # loguru → SSE 브리지
├── templates/
│   ├── base.html         # 모바일 레이아웃, nav, 토스트
│   ├── auth/*.html
│   ├── dashboard.html
│   ├── settings/*.html
│   ├── charts.html
│   ├── reports/*.html
│   └── partials/*.html   # HTMX 부분 응답용
└── static/
    ├── app.css           # Tailwind CDN + 소량 커스텀
    └── app.js            # Chart.js 로드, HTMX 확장 훅
```

### 설정 저장 모델 (SQLModel)

```python
class Settings(SQLModel, table=True):
    id: int | None = None
    # 스칼라 전체를 한 row에 담는 형태 (싱글 user/config)
    mode, tickers(CSV), max_concurrent_positions, strategy_k,
    ma_filter_window, max_position_ratio, daily_loss_limit,
    stop_loss_ratio, min_order_krw, paper_initial_krw,
    check_interval_seconds, heartbeat_interval_hours, ...
    upbit_access_key_enc, upbit_secret_key_enc,
    telegram_bot_token_enc, telegram_chat_id,
    kill_switch, live_trading, updated_at

class User(SQLModel, table=True):
    id, username, password_hash, totp_secret_enc,
    created_at, last_login_at

class AuditLog(SQLModel, table=True):
    id, at, action, actor, before_json, after_json
```

### 스케줄러 재구성 흐름

1. 사용자가 `/settings/strategy` POST
2. 서버가 DB 업데이트 → `AuditLog` 기록
3. `BotManager.reload()` 호출:
   - 현재 tick 완료 대기 (lock)
   - scheduler 잡 제거 → 새 Settings로 TradingBot 재빌드 → 잡 재등록
4. 성공 토스트 + 현재 활성 설정 표시

---

## 3. 마일스톤

각 V2.x는 `v2` 브랜치의 독립 커밋 단위. pytest·ruff 통과 필수.

### V2.0 — 기반: FastAPI 프로세스 통합 + SQLite 이관 `[x]` (2026-04-14)
봇 로직 변경 최소, 실행 방식만 바꾼다.

- [x] `v2` 브랜치 생성 (커밋 `76fb114`)
- [x] 의존성 추가: `fastapi`, `uvicorn[standard]`, `jinja2`, `sqlmodel`, `cryptography`, `bcrypt`(직접), `pyotp`, `qrcode[pil]`, `itsdangerous`, `markdown2`, `python-multipart`, `httpx`
- [x] `web/db.py` + `models.py` — SQLite 스키마 (AppSettings / User / AuditLog)
- [x] `web/crypto.py` — Fernet 래퍼, 마스터 키 자동 생성(`~/.auto_coin_master.key`, 0600)
- [x] **부트스트랩 마이그레이션**: 최초 기동 시 `.env` → SQLite Settings row 1건 복사
- [x] `web/settings_service.py`: DB 우선, 빈 DB면 `.env`에서 시드
- [x] `bot_manager.py` — `build()` / `reload()` / `start()` / `stop()` + `threading.Lock`
- [x] `web/__main__.py`로 uvicorn 기동 + `BackgroundScheduler` lifespan hook
- [x] 기존 `BlockingScheduler` 경로 유지 (V1 CLI `python -m auto_coin.main` 그대로 작동)

**완료 기준**: `python -m auto_coin.web --port 18081`로 기동, `/health`가 실제 포트폴리오 반환. pytest 193/193. ✅

---

### V2.1 — 인증 / 세션 / TOTP `[x]` (2026-04-14)

- [x] 최초 접속 시 **`/setup` 강제**: 패스워드 설정 → TOTP QR 발급 → 6자리 확인 → 자동 로그인
- [x] `/login` · `/logout` · `/setup` · `/setup/totp` 라우터
- [x] Starlette `SessionMiddleware` (파일 기반 `~/.auto_coin_session.key`, 600)
- [x] `require_auth` dependency — 미인증 요청 `/login` 리다이렉트
- [x] 세션 TTL 7일, SameSite=lax
- [x] 실패 카운터 5회 → 10분 lockout, 성공 시 리셋
- [x] bcrypt 직접 사용 (passlib 제거 — bcrypt 5.x 호환 이슈)
- [x] TOTP secret은 Fernet 암호화로 DB 저장
- [x] 테스트 28건 (user_service 20 + auth_flow 8)

**완료 기준**: 브라우저에서 `/` 접근 → `/setup` 자동 리다이렉트 → password → QR 스캔 → 코드 확인 → 로그인 상태로 `/` 접근. 로그아웃 후 재로그인은 password + TOTP 필요. ✅

---

### V2.2 — UI 스캐폴딩 (HTMX + Tailwind) `[x]` (2026-04-14)

- [x] `base.html`: 모바일 viewport, **하단 고정 탭 네비게이션**(대시/차트/리포트/로그/설정), 토스트 영역, safe-area-inset 반영
- [x] Tailwind CDN + HTMX CDN 로드
- [x] active 탭 하이라이트 (request.url.path 기반)
- [x] 로그아웃은 상단 헤더에
- [x] `error.html` (404/기타 HTTPException) — HTML/JSON 협상
- [x] 공용 `placeholder.html` + `/settings`·`/charts`·`/reports`·`/logs` 라우터 (각각 V2.3/V2.5/V2.6/V2.7 마일스톤 표기)
- [x] 테스트 13건: 모든 placeholder 경로, 미인증 리다이렉트, 탭 표시/숨김, active 표시, 404 HTML/JSON 분기

**완료 기준**: 로그인 후 5개 탭 이동 자유, 미인증 요청은 `/setup` 또는 `/login`으로 차단, 없는 경로는 404 에러 카드. ✅

---

### V2.3 — 설정 수정 UI `[x]` (2026-04-14)
핵심 가치가 몰려 있는 마일스톤.

- [x] `/settings` 허브 + `/settings/strategy`·`/settings/risk`·`/settings/portfolio`·`/settings/api-keys`·`/settings/schedule` 5개 섹션
- [x] API 키 섹션은 masked 표시(`••••last4`), 공란 입력 시 기존 값 유지
- [x] HTMX `/settings/api-keys/test-upbit` · `/test-telegram` 버튼 — Upbit `get_balance` / Telegram `getMe` + 테스트 메시지
- [x] 전 폼 pydantic 재검증 (ValidationError → 400 + 폼 재렌더 + 에러 문구)
- [x] 저장 → `BotManager.reload()` → flash 메시지 → 303 리다이렉트
- [x] 포트폴리오 페이지에 **거래대금 상위 20 추천** (보유/관측 종목 자동 제외) + 상장 검증 (오타 거부)
- [x] `AuditLog` 기록 (민감 필드 자동 마스킹)
- [x] `web/services/upbit_scan.py` (60s TTL 캐시), `web/services/credentials_check.py`, `web/audit.py`, `auth.flash()`
- [x] 테스트 30건 신규 (services 14 + settings 16)

**완료 기준**: 폰에서 K 0.5 → 0.6 변경 → 저장 → `BotManager.reload()` 트리거 → 다음 tick이 새 K로 돈다. ✅

---

### V2.4 — 대시보드 (현황 + 봇 컨트롤) `[x]` (2026-04-14)
요청하신 핵심 기능 #1, #2가 여기.

- [x] 포지션 카드 그리드 (종목별: 수량 · 진입가 · 현재가 · 미실현 PnL)
- [x] 슬롯 상태 `X/N 사용 중`
- [x] 포트폴리오 일일 PnL (종목별 합산 표시; 평균은 후속 개선)
- [x] 업비트 KRW 잔고 (live) / 페이퍼 가상 자본 표시
- [x] 최근 BUY/SELL 10건 (원래 5건에서 늘림 — 모바일 스크롤 허용)
- [x] **Kill-switch 토글** (기능 #1) — 2단계 confirm + 상태 배지
- [x] **봇 start/stop/restart 버튼** (기능 #2)
  - start: `BotManager.start()`
  - stop: `BotManager.stop()`, `confirm=yes` 요구, 기존 포지션 유지
  - restart: `BotManager.reload()` — 설정 재로드 + scheduler 재등록
- [x] 5초 polling: `/dashboard/partial` + `hx-trigger="every 5s"`
- [x] 테스트 11건 (render · positions · partial · kill-switch toggle · restart · stop confirm · start · auth · flash · LIVE badge)

**완료 기준**: TestClient + 실 기동 smoke 모두 통과. Kill-switch 토글로 다음 tick BUY 차단 가능. ✅

---

### V2.5 — 차트 (ticker 변동 추이) `[x]` (2026-04-14)

- [x] `/charts` — portfolio + watch 병합 셀렉터 (드롭다운)
- [x] **Chart.js** 4.4.4 (lightweight-charts는 무거워 drop) — 최근 60일 일봉 라인 + target 점선
- [x] 현재 보유 중이면 진입가 수평선 (녹색)
- [x] N일 이평 보조선 (회색 점선, MA 창은 Settings의 `ma_filter_window`)
- [x] 모바일 반응형 (`responsive: true`, `maxTicksLimit` 8로 x축 정리)
- [x] 터치 시 툴팁 — 각 데이터셋 값 + ko-KR 로케일 포맷
- [x] `/charts/data/{ticker}` JSON API, UpbitError → 502, NaN → JSON null
- [x] 테스트 7건 (페이지 렌더 · 셀렉터 · JSON 형태 · 보유 시 entry_price · 502 · auth · NaN 처리)

**완료 기준**: 로그인 후 `/charts`에서 종목 전환 시 JSON fetch + Chart.js 렌더 1초 이내. ✅

---

### V2.6 — 리포트 뷰어 `[x]` (2026-04-14)

- [x] `/reports` — `reports/*.md` 목록 (날짜 내림차순, 첫 H1을 타이틀로, 파일 크기 + mtime 표시)
- [x] `/reports/{name}` — markdown2 렌더 (tables / fenced-code / strike / task_list / break-on-newline)
- [x] scoped `.markdown-body` CSS — dark code block, 반응형 테이블(가로 스크롤), 모바일 여백
- [x] **경로 traversal 방어**: `.md` 확장자 강제, `/` · `\\` · 시작점(`.`) · `..` 거부, `resolve()` 경계 재검증
- [x] 테스트 8건 (목록/정렬/첫 H1 title/404/URL-인코딩 traversal/non-md 거부/빈 디렉토리/auth)

**완료 기준**: `reports/2026-04-14-paper-day1.md`가 모바일에서 표·코드블록 포함 정상 렌더. ✅

---

### V2.7 — 실시간 로그 (기능 #6) `[x]` (2026-04-14)

- [x] loguru 커스텀 sink → in-memory ring buffer (`deque(maxlen=500)`)
- [x] `/logs/stream` SSE 엔드포인트 — 첫 chunk에 `: connected` flush + 초기 50줄 replay + 15s keep-alive
- [x] `/logs` 페이지 — 레벨 필터 (DEBUG↑/INFO↑/WARNING↑/ERROR↑), 자동 스크롤 토글, 연결 상태 표시
- [x] `/logs/recent` JSON — 초기 렌더/수동 새로고침 용도 (limit clamp)
- [x] dark 터미널 스타일, 모바일에서도 1000줄까지 유지 후 FIFO 트림
- [x] EventSource 재연결 로직 (브라우저 기본)
- [x] 테스트 10건 (ring buffer cap · sink 통합 · format_sse · page · recent JSON · clamp · auth · subscribe/unsubscribe)

**완료 기준**: `/logs` 열어둔 상태에서 서버 로그가 SSE로 실시간 반영, 페이지 새로고침 시 최근 200줄 재현. ✅
(SSE 전체 body 반복 구독 테스트는 TestClient sync 제약으로 수동 E2E 검증.)

---

### V2.8 — Tailscale 배포 + launchd `[x]` (2026-04-14)

- [x] `deploy/com.sj9608.auto_coin.plist` — launchd 템플릿 (RunAtLoad + KeepAlive + ThrottleInterval=10)
- [x] `deploy/install_launchd.sh` — 경로 치환 + 로드 자동화
- [x] `deploy/README.md` — 설치/검증/제거 명령, HOME 파일 3종 백업 주의
- [x] `docs/tailscale-setup.md` — 맥 OS / iPhone 앱 설치, MagicDNS, ACL, 보안 체크 3종, 트러블슈팅
- [x] 내부 URL 예시 포함 (`http://macbook-pro.tail-abcd1234.ts.net:8080`)
- [x] launchd 로그 경로: `logs/launchd.out.log` · `logs/launchd.err.log`
- [ ] 재부팅 후 자동 기동 **실환경 검증** — 사용자 액션 (launchd 등록 실행 + 맥 재부팅 1회)

**완료 기준(코드/문서)**: plist 템플릿 + 설치 스크립트 + Tailscale 가이드 모두 작성. ✅
**완료 기준(운영)**: 사용자가 `./deploy/install_launchd.sh` 실행 → 재부팅 테스트 → 폰 접속 확인.

---

### V2.9 — 문서 + v1 마이그레이션 + main 머지 `[x]` (2026-04-14)

- [x] 웹 운영 매뉴얼 — 최상위 **`README.md`에 통합** (V1 CLI 운영은 `docs/v1/USER_GUIDE.md`로 보존)
- [x] `README.md` — V2 기준 통합, 테스트 287/287 표기, 문서 인덱스 갱신
- [x] `CHANGELOG.md` — V1 M1~M9a + V2.0~V2.8 전체 이력 + 누적 테스트 카운트 표
- [x] `docs/v2/PLAN.md` (구 `PLAN_V2.md`) — 각 마일스톤 `[x]` + 완료 일자
- [x] `.env` → SQLite 자동 마이그레이션 동작 확인 (V2.0 부트스트랩 테스트 + 실 기동 smoke)
- [x] `main` PR 생성 — [#1](https://github.com/sj9608/auto_coin/pull/1)
- [x] `main` 머지 (2026-04-14 merge commit `ed30556`)
- [x] 문서 재편: `docs/v1/` · `docs/v2/` · 최상위는 README 통합본
- [ ] launchd 등록 + V1 페이퍼 봇 정지 → V2 전환 — **사용자 액션**

**완료 기준(코드)**: PR #1 생성, 모든 문서 반영, pytest 287/287. ✅
**완료 기준(운영)**: 사용자가 PR 머지 → launchd로 V2 기동 → 기존 페이퍼 봇 정리.

---

## 4. 보안 · 운영 체크리스트 (V2)

- [x] API 키는 **Fernet 암호화** 후 DB 저장, 마스터 키 파일 `600` (V2.0)
- [x] API 키 화면 표시는 masked (`SecretBox.mask`로 `••••last4`) (V2.3)
- [x] 모든 state 변경 행위는 `AuditLog`에 before/after 기록 (V2.3)
  - 민감 필드(API 키·Telegram 토큰) 자동 마스킹 저장
- [x] 로그인 실패 rate limit (5회 → 10분 lockout, 성공 시 리셋) (V2.1)
- [~] Tailscale 외부 접근 제한 — `--host 0.0.0.0`이지만 Tailscale + macOS 방화벽 조합으로 방어 (V2.8)
  - 더 엄격히 가두려면 launchd plist의 `--host`를 Tailscale IP로 고정 가능 (docs 참고)
- [x] `--live` 활성화 UI 가드 — mode=live + live_trading + Kill-switch OFF 3중 조건 (V2.3)
  - paper→live 전환 시 추가 TOTP 재확인 구현 완료
- [x] CSRF 토큰 검증 — 세션 기반 토큰 + form field + `X-CSRF-Token` 헤더
- [x] 세션 고정 공격 방지 — 로그인/초기 설정 완료 후 세션 재생성
- [x] 복구 코드 기반 TOTP 재설정 UI

---

## 5. 테스트 전략

- 기존 pytest suite 그대로 유지 (172/172 → V2 작업 후에도 동등하게)
- 신규 `tests/test_web_*` 추가: 라우터 단위 테스트 (httpx TestClient)
- 인증/설정 변경 플로우 통합 테스트
- BotManager.reload() 동시성 테스트 (tick 중간에 reload 호출)

---

## 6. TODO (후순위 — V2.x 이후 또는 별도 라인)

사용자가 저순위로 빼기로 한 기능들. `v2.x`에서 필요 시 마일스톤으로 승격:

- [ ] **#4 수동 매도 버튼** — 보유 포지션별 긴급 청산
- [ ] **#5 최근 이벤트 타임라인** — 대시보드에 BUY/SELL/에러/heartbeat 연대기 위젯
- [ ] **#9 백테스트 UI** — ticker/k/기간 폼 → 결과 표 + 자본 곡선 차트
- [ ] **#10 성과 대시보드** — 일별 PnL 막대, 승률/MDD 추이
- [ ] **#11 알림 커스터마이징** — 텔레그램 이벤트 on/off 체크박스
- [ ] **#12 PWA** — manifest.json + service worker, 폰 홈화면 앱 설치
- [ ] **#13 다크 모드** — Tailwind dark: 변형 + 시스템 프리퍼런스 자동 감지
- [ ] **#14 설정 변경 이력 UI** — AuditLog는 V2.3부터 기록만 하고, 조회 UI는 추후
- [ ] **#15 긴급 전량 청산 버튼** — 모든 보유 포지션 시장가 매도, 2단계 TOTP 확인
- [x] **#16 CSRF 토큰 + 세션 재생성** — 완료
- [x] **#17 live 전환 TOTP 재확인** — mode=live 전환 POST 시 6자리 재입력 요구
- [x] **#18 복구 코드 기반 TOTP 재설정**
- [ ] **#19 V1/V2 동시 실행 방지** — 런타임 lock으로 CLI/web 상호 배타 실행

---

## 7. 예상 타임라인

순차 진행 가정 (승인 후):

| 마일스톤 | 예상 소요 |
|---|---|
| V2.0 | 1~2일 (DB·scheduler 재구조화가 가장 큼) |
| V2.1 | 0.5일 |
| V2.2 | 0.5일 |
| V2.3 | 1.5~2일 (폼 많음) |
| V2.4 | 1일 |
| V2.5 | 0.5~1일 |
| V2.6 | 0.3일 |
| V2.7 | 0.5일 |
| V2.8 | 0.5일 |
| V2.9 | 0.3일 |
| **합계** | **약 6~8일** |

페이퍼 봇은 `main`에서 그대로 돌리므로, V2 개발은 데이터 손실 위험 없이 병행 가능.

---

## 8. 열려 있는 결정 — 진행 중 해소 결과

| 주제 | 최종 결정 |
|---|---|
| TOTP 백업 코드 | **미발급** — 복구는 DB 직접 조작(`DELETE FROM user`) + 3개 HOME 파일 삭제로 초기화 (`README.md` §3.3) |
| 설정 변경 직후 다음 tick | 강제 트리거 안 함 — **자연 스케줄 대기**. `/dashboard`의 "재시작" 버튼으로 즉시 반영 원할 때만 수동 reload |
| 차트 라이브러리 | **Chart.js 4.4.4** 채택 (lightweight-charts는 캔들 차트 기능 당장 불필요, ~40KB 경량) |
| 로그 보관 기간 | 파일 회전은 V1의 `loguru` 유지 (14일). V2 웹은 in-memory ring(500줄) + `/logs/stream` SSE. DB 이관은 후속 |
| 봇 재시작 실패 알림 | 텔레그램 (`🔥 tick crashed`) + 웹 UI flash 메시지 양쪽 모두 |

---

## 9. 승인 / 진행 요약

2026-04-14 승인 받음 → V2.0부터 V2.9까지 순차 구현 완료.

- [x] 마일스톤 순서 그대로 진행 (V2.0 → V2.9)
- [x] V2 본편은 제안 그대로, 기능 #2/#3/#1/#8/#6 우선 포함 (V2.3/V2.4/V2.7)
- [x] TODO 항목(#4/#5/#9–#15)은 후순위 보존. V2.8 이후 #16/#17(보안 강화) 추가
- [x] `v2` 브랜치 생성 (커밋 `76fb114`) → v2 푸시 → PR #1
- [x] `main` 브랜치의 V1 페이퍼 봇은 병행 운영 (공존 검증 완료)

### 최종 머지 대기 (사용자 액션)

1. **PR #1 리뷰 & 머지** — https://github.com/sj9608/auto_coin/pull/1
2. **launchd 등록** — `./deploy/install_launchd.sh`
3. **V1 페이퍼 봇 정지** — `kill $(cat .bot.pid)` (선택)
4. **Tailscale 설정** — docs/tailscale-setup.md 참고 (선택, 외부 접근 시)

---

## 10. 완료 메트릭

| 항목 | 수치 |
|---|---|
| 마일스톤 | **V2.0 ~ V2.9 모두 완료** (10개) |
| 테스트 | **287/287 통과** (V1 172 + V2 +115) |
| 커밋 (v2 브랜치) | V2.0 `76fb114` · V2.1 `8b85df9` · V2.2 `8592ec5` · V2.3 `dafbac2` · V2.4 `7432106` · V2.5 `117776c` · V2.6 `50b5ddf` · V2.7 `7988e65` · V2.8 `58e7029` · V2.9 `edce429` |
| 신규 모듈 | `web/` 패키지 (app/db/crypto/bot_manager/audit/auth/user_service/session_secret/settings_service + 7 routers + 3 services + 템플릿) |
| 신규 문서 | README.md(통합) · CHANGELOG.md · docs/v2/tailscale-setup.md · deploy/README.md |

자세한 변경 이력은 [CHANGELOG.md](CHANGELOG.md).
