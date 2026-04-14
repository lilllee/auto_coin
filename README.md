# auto_coin

> 업비트(Upbit) KRW 마켓 **변동성 돌파 자동매매 봇** + **모바일 웹 콘솔**.

FastAPI + HTMX + Tailwind로 만든 웹에서 전략·리스크·종목·API 키를
설정하고, 대시보드/차트/리포트/실시간 로그를 폰에서 확인한다.
Tailscale로 외출 중 접근, launchd로 맥 재부팅 후 자동 기동.

> ⚠️ **학습/실험용**. 본 프로젝트는 투자 권유가 아니며 **원금 손실 위험**이 있습니다.
> 자세한 내용은 [docs/v1/PLAN.md §8](docs/v1/PLAN.md) 참고.

---

## 목차

1. [한눈에 보기](#1-한눈에-보기)
2. [빠른 시작](#2-빠른-시작)
3. [첫 접속 & TOTP 등록](#3-첫-접속--totp-등록)
4. [대시보드 · 봇 컨트롤](#4-대시보드--봇-컨트롤)
5. [설정 수정](#5-설정-수정)
6. [차트 보기](#6-차트-보기)
7. [리포트 · 실시간 로그](#7-리포트--실시간-로그)
8. [외부(폰) 접속 — Tailscale](#8-외부폰-접속--tailscale)
9. [상시 실행 — launchd](#9-상시-실행--launchd)
10. [파일 · 저장 경로](#10-파일--저장-경로)
11. [트러블슈팅](#11-트러블슈팅)
12. [V1 CLI도 여전히 동작](#12-v1-cli도-여전히-동작)
13. [개발자 참고](#13-개발자-참고)
14. [문서 인덱스](#14-문서-인덱스)

---

## 1. 한눈에 보기

```
[iPhone / 맥 브라우저]  ←(Tailscale)→  [맥, launchd로 24/7 실행]
                                            ↓
                                    FastAPI + BackgroundScheduler
                                            ↓
                                    TradingBot (paper/live)
                                            ↓
                                   Upbit API · Telegram Bot
```

- **단일 프로세스**: 웹 UI + BackgroundScheduler + TradingBot을 `python -m auto_coin.web` 하나로 돌림.
- **설정 변경은 UI → SQLite → `BotManager.reload()`** → 프로세스 재시작 없이 다음 tick부터 반영.
- **인증**: password + TOTP 2FA (`/setup` 최초 필수).
- **보안**: API 키 Fernet 암호화(`~/.auto_coin_master.key`, 0600), 세션 쿠키 7일, 5회 실패 시 10분 lockout.

하단 탭: **📊대시 · 📈차트 · 📄리포트 · 📜로그 · ⚙️설정**.

---

## 2. 빠른 시작

```bash
# 1) 의존성
cd /path/to/auto_coin
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 2) (선택) V1 .env가 있으면 최초 기동 시 자동 마이그레이션 대상
cp .env.example .env && chmod 600 .env

# 3) 기동
.venv/bin/python -m auto_coin.web --port 8080
# 브라우저: http://127.0.0.1:8080
```

**기본값은 paper 모드**. 실거래는 `/settings/schedule`에서 mode=live + live_trading +
Kill-switch OFF 3중 조건 충족 시에만 주문이 나갑니다.

재부팅 후 자동 기동 → [§9 launchd](#9-상시-실행--launchd).
외출 중 폰 접속 → [§8 Tailscale](#8-외부폰-접속--tailscale).

---

## 3. 첫 접속 & TOTP 등록

### 3.1 `/setup` 화면
1. 관리자 패스워드 8자 이상 입력 (확인 포함)
2. **TOTP QR 코드 표시** → 인증 앱으로 스캔
   - Google Authenticator / 1Password / Authy / Bitwarden 모두 호환
3. 앱이 표시하는 **6자리 코드**를 폼에 입력 → "확인 및 완료"
4. 자동으로 로그인된 상태로 `/` 대시보드 이동

### 3.2 다음 방문 (`/login`)
- 패스워드 + 현재 TOTP 6자리
- 세션 쿠키 7일 유지
- **5회 실패 → 10분 lockout** (올바른 값도 거부)

### 3.3 TOTP 기기를 잃었을 때
V2.x 현재 셀프 리커버리 UI는 없습니다. 임시 조치:
```bash
# HOME의 3개 파일을 전부 삭제하면 완전 초기화 (설정도 날아감)
rm ~/.auto_coin.db ~/.auto_coin_master.key ~/.auto_coin_session.key
```
또는 SQLite를 직접 열어 `user` 테이블만 비우면 TOTP만 재설정 가능:
```bash
sqlite3 ~/.auto_coin.db "DELETE FROM user;"
```

---

## 4. 대시보드 · 봇 컨트롤

경로: `/`

### 상단 — 상태 & 컨트롤
| 뱃지 | 의미 |
|---|---|
| 🟢 running / ⚪ stopped | BackgroundScheduler 활성 여부 |
| LIVE / paper | mode + live_trading + kill_switch 종합 |
| 🟡 kill-switch ON | 신규 진입 차단 중 (청산은 정상) |

버튼 4개:
- **Kill-switch 켜기/해제** — 즉시 반영, 2단계 confirm
- **재시작 (reload)** — `BotManager.reload()`. 설정 변경 직후 즉시 반영용
- **봇 정지** — scheduler shutdown (포지션은 유지, 2단계 confirm)
- **봇 시작** — 정지 상태에서만

### 본문 (5초 polling 자동 갱신)
- 슬롯 사용량 `X/N`
- 오늘 PnL 합산
- 잔고 (live 모드면 실제 Upbit KRW, paper는 가상 자본)
- 포지션 카드 — 종목별 수량 · 진입가 · 현재가 · 미실현 PnL
- 최근 주문 10건

---

## 5. 설정 수정

경로: `/settings` (섹션 카드 5개)

모든 폼은 저장 시 **pydantic 재검증 → SQLite 업서트 → AuditLog → `BotManager.reload()` → flash 메시지 → 303 리다이렉트**. 프로세스 재시작 필요 없음.

### 5.1 전략 (`/settings/strategy`)
- `K` (0.1 – 1.0): 변동성 돌파 계수
- `MA 필터 창` (일): 5일 이평 이상일 때만 진입
- `watch 주기 (분)`: 텔레그램 관측 메시지 간격

### 5.2 리스크 (`/settings/risk`)
- `1슬롯 투입 비율` — `max_position_ratio × paper_initial_krw`가 1회 매수액
- `동시 보유 상한`
- `일일 손실 한도` (음수, 포트폴리오 합산)
- `개별 손절선` (음수, 종목별 진입가 기준)
- `최소 주문 (KRW)` — 업비트 5,000 KRW floor
- `페이퍼 가상 자본`
- `Kill-switch` 체크박스 (대시보드 토글과 동일)

### 5.3 포트폴리오 (`/settings/portfolio`)
- `TICKERS` (콤마) — 매매 대상, **나열 순서가 진입 우선순위**
- `WATCH_TICKERS` (콤마) — 관측 전용
- **업비트 상장 자동 검증** — 오타/미상장 티커 제출 시 400 + 안내
- **거래대금 상위 20 추천** — 페이지 하단에 현재 보유/관측 제외 표시

### 5.4 API 키 (`/settings/api-keys`)
- 저장된 키는 `••••last4` 마스킹
- **빈 값으로 저장 = 기존 값 유지** (실수로 지워지지 않게)
- `Upbit 연결 테스트` — `get_balance` 호출, 성공 시 잔고 표시
- `Telegram 연결 테스트` — `getMe` + 테스트 메시지 1건 전송

### 5.5 스케줄 / 모드 (`/settings/schedule`)
- `mode` drop-down: **paper ↔ live**
- `live_trading` 체크박스 (mode=live + 이 스위치 + kill_switch OFF 모두 true일 때만 실주문)
- tick 주기 / heartbeat 주기 / 청산 시각 / 일일 리셋 시각

### 5.6 변경 이력 (AuditLog)
`auditlog` 테이블에 모든 설정 변경의 before/after JSON이 쌓입니다. API 키는 자동 마스킹 저장. 전용 UI는 후속:
```bash
sqlite3 ~/.auto_coin.db \
  "SELECT at, action, after_json FROM auditlog ORDER BY id DESC LIMIT 10;"
```

---

## 6. 차트 보기

경로: `/charts`

- 드롭다운에서 **portfolio + watch** 전체 종목 중 하나 선택
- 최근 60일 일봉 라인 차트:
  - 🔵 **종가**
  - ◻️ **MA(N)** — 회색 점선
  - 🟠 **target** — 돌파 기준선 (주황 점선)
  - 🟢 **진입가** — 보유 중일 때만 수평 실선

터치로 툴팁 확인.

---

## 7. 리포트 · 실시간 로그

### 7.1 리포트 — `/reports`
- `reports/*.md` 자동 인식 → 최신순 목록
- 클릭 시 markdown2 렌더 (테이블 · 코드블록 · 인라인 서식 지원)
- 모바일 가독성 최적화 (dark code block, 가로 스크롤 테이블)

수동으로 파일을 넣고 싶으면:
```bash
cp my-analysis.md reports/2026-04-14-manual.md
# 바로 /reports 에서 보임
```

### 7.2 실시간 로그 — `/logs`
- 최근 200줄 즉시 렌더 + **SSE 스트림**으로 새 로그 실시간 추가
- 레벨 필터: DEBUG↑ / INFO↑ / WARNING↑ / ERROR↑
- 자동 스크롤 토글
- 상단 우측에 **연결됨/재연결 중** 상태 표시

---

## 8. 외부(폰) 접속 — Tailscale

자세한 내용: [docs/v2/tailscale-setup.md](docs/v2/tailscale-setup.md).

### 요약
1. macOS + iPhone에 Tailscale 설치 (동일 계정)
2. `auto_coin.web`을 `--host 0.0.0.0`으로 기동 (launchd 기본 설정)
3. 폰에서 `http://<MAC-HOSTNAME>.<TAILNET>.ts.net:8080` 접속
4. 로그인 → TOTP

### 보안 필수 체크 3종
- [x] V2 자체 인증 (`/setup` 완료)
- [x] macOS 방화벽 ON (System Settings → Network → Firewall)
- [x] `0.0.0.0` 바인딩은 Tailscale + 방화벽 조합에서만 안전

---

## 9. 상시 실행 — launchd

```bash
./deploy/install_launchd.sh
```

이 한 줄로:
- `~/Library/LaunchAgents/com.sj9608.auto_coin.plist` 설치
- `RunAtLoad` + `KeepAlive` → 부팅 시 자동 기동 + 프로세스 크래시 시 10초 후 재시작
- stdout/stderr → `logs/launchd.*.log`

### 관리
```bash
launchctl list | grep auto_coin             # PID 확인
launchctl unload ~/Library/LaunchAgents/com.sj9608.auto_coin.plist   # 정지
launchctl load   ~/Library/LaunchAgents/com.sj9608.auto_coin.plist   # 재시작
```

자세한 내용은 [deploy/README.md](deploy/README.md).

---

## 10. 파일 · 저장 경로

| 경로 | 내용 | 민감도 |
|---|---|---|
| `~/.auto_coin.db` | SQLite — 설정/사용자/감사 로그 | ⚠️ API 키 암호문 포함 |
| `~/.auto_coin_master.key` | Fernet 마스터 (DB 암호화 키) | 🚨 절대 유출 금지, 0600 |
| `~/.auto_coin_session.key` | 세션 쿠키 서명 | ⚠️ 유출 시 세션 탈취 가능 |
| `state/{TICKER}.json` | 종목별 포지션/주문 기록 | V1/V2 공유, 재시작 시 복구 |
| `logs/launchd.out.log` | launchd stdout | — |
| `logs/auto_coin_YYYY-MM-DD.log` | loguru 회전 로그 (14일) | — |
| `reports/*.md` | 수동 또는 자동 생성 분석 리포트 | — |

**백업 3종 세트**: DB + master key + session key를 함께 옮기지 않으면 복원 불가.
**초기화**: 세 파일을 전부 지우면 다시 `/setup`부터 시작.

---

## 11. 트러블슈팅

### 웹이 뜨지 않음
```bash
# 1) 포트 충돌?
lsof -i :8080
# 2) launchd 로그
tail -50 logs/launchd.err.log
# 3) 수동으로 포어그라운드 실행 → 에러 즉시 확인
.venv/bin/python -m auto_coin.web --port 8080
```

### `/login`에서 "사용자가 존재하지 않습니다"
→ `/setup` 먼저. 브라우저가 캐시된 리다이렉트로 걸리면 `http://.../setup`을 직접 입력.

### lockout에 걸림
- 10분 대기가 가장 쉬움
- 조급하면 `sqlite3 ~/.auto_coin.db "UPDATE user SET failed_attempts=0, locked_until=NULL;"`

### 설정 저장했는데 봇이 계속 옛 값으로 동작
- `BotManager.reload()`는 저장과 동시에 자동 호출. 진행 중이던 tick은 끝까지 돈 다음 반영.
- 대시보드에서 **재시작(reload)** 수동 클릭
- 그래도 안 되면 launchd 재시작:
  ```bash
  launchctl kickstart -k gui/$(id -u)/com.sj9608.auto_coin
  ```

### SSE 로그가 계속 "재연결 중"
- Tailscale DERP 릴레이 경로가 느릴 수 있음
- 맥 방화벽에서 Python 프로세스 허용 확인
- 새로고침 후 `/health` JSON이 반환되는지 먼저 확인

### API 키 연결 테스트는 되는데 실제 tick에 "order failed"
- Kill-switch=ON? (OFF로)
- 업비트 **출금 권한 꺼야 함**, **IP 화이트리스트**에 맥의 현재 IP 포함
- 잔고 < `min_order_krw`

### 🔥 "tick crashed" 알림이 반복
- `/logs`에서 구체적 traceback 확인
- 마지막으로 바꾼 설정을 되돌리거나, Kill-switch ON으로 우선 차단

---

## 12. V1 CLI도 여전히 동작

`v2` 머지 이후에도 V1 CLI 경로는 그대로 유지됩니다. `.env`와 `state/*.json`을 공유합니다.

```bash
python -m auto_coin.main            # 무한 스케줄링
python -m auto_coin.main --once     # 1 tick 디버그
python -m auto_coin.main --live     # 실거래 강제 (주의)
```

자세한 CLI 운영법은 **[docs/v1/USER_GUIDE.md](docs/v1/USER_GUIDE.md)**.

**주의**: V1 CLI와 V2 웹을 **동시에 실행하지 마세요** — 같은 `state/*.json`을 경쟁해 주문이 중복될 수 있습니다.

---

## 13. 개발자 참고

### 모듈 구조
```
src/auto_coin/
├── config.py              # pydantic-settings
├── logging_setup.py       # loguru 회전 로그
├── formatting.py          # 가격 포매터 (저가 종목 소수점)
├── main.py                # V1 CLI 엔트리 (APScheduler BlockingScheduler)
├── bot.py                 # TradingBot (tick/watch/heartbeat/daily_reset/force_exit/report)
├── reporter.py            # 일일 리포트 생성
├── exchange/upbit_client.py    # pyupbit 래퍼
├── data/candles.py             # 일봉 DataFrame + target/MA 컬럼
├── notifier/
│   ├── telegram.py             # Bot API 호출
│   └── __main__.py             # CLI: --check / --find-chat-id / --send
├── strategy/
│   ├── base.py                 # Signal, MarketSnapshot, Strategy ABC
│   └── volatility_breakout.py  # Larry Williams 변동성 돌파
├── backtest/runner.py          # 백테스트 CLI (수수료/슬리피지/K 스윕)
├── risk/manager.py             # Decision 게이트
├── executor/
│   ├── order.py                # paper/live 주문, UUID 멱등
│   └── store.py                # JSON 원자적 상태 저장
└── web/                        # V2 웹 콘솔 (FastAPI + HTMX + Tailwind CDN)
    ├── app.py  __main__.py     # uvicorn 런처 + lifespan
    ├── crypto.py               # Fernet 래퍼
    ├── db.py  models.py        # SQLModel 엔진/테이블
    ├── bot_manager.py          # BackgroundScheduler + TradingBot 수명
    ├── settings_service.py     # DB ↔ Settings + .env 부트스트랩
    ├── user_service.py         # bcrypt + pyotp + lockout
    ├── session_secret.py  auth.py  audit.py
    ├── routers/ (auth, dashboard, control, settings, charts, reports, logs)
    ├── services/ (upbit_scan, credentials_check, log_stream)
    └── templates/ (base, dashboard, charts, logs, auth/*, settings/*, reports/*, partials/*)
```

### 테스트 · 린트
```bash
pytest                      # 287/287
ruff check src tests
```

### 백테스트
```bash
python -m auto_coin.backtest.runner --ticker KRW-BTC --days 365 --k 0.5
python -m auto_coin.backtest.runner --ticker KRW-BTC --days 365 --sweep 0.3 0.7 0.1
```

### 실행 경로 정리
| 진입점 | 용도 |
|---|---|
| `python -m auto_coin.web` | V2 웹 콘솔 (프로덕션) |
| `python -m auto_coin.main` | V1 CLI (legacy, state 공유) |
| `python -m auto_coin.backtest.runner` | 오프라인 백테스트 |
| `python -m auto_coin.notifier --check` | Telegram 토큰 검증 |

---

## 14. 문서 인덱스

```
.
├── README.md            # (이 문서) V2 기준 통합 사용자 가이드
├── CHANGELOG.md         # 버전/마일스톤별 구현 이력
├── CLAUDE.md            # Claude Code 작업 지침
├── deploy/
│   ├── README.md                    # launchd 설치/검증
│   ├── com.sj9608.auto_coin.plist   # launchd 템플릿
│   └── install_launchd.sh           # 경로 치환 + load
├── docs/
│   ├── v1/
│   │   ├── PLAN.md          # V1 아키텍처·마일스톤 (M1~M9a, formatter)
│   │   └── USER_GUIDE.md    # V1 CLI 운영 매뉴얼
│   └── v2/
│       ├── PLAN.md          # V2 설계서·마일스톤 (V2.0~V2.9)
│       └── tailscale-setup.md   # 외부 접속 상세
└── reports/             # paper/live 운영 분석 리포트
```

**변경 이력 한 줄 요약**은 [CHANGELOG.md](CHANGELOG.md)에 있습니다.
