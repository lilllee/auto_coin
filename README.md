# auto_coin

> 업비트(Upbit) KRW 마켓 **자동매매 봇** + **모바일 웹 콘솔**.
> 변동성 돌파 · 추세추종 · 레짐 필터 등 **6종 전략**을 UI에서 선택, 포트폴리오 walk-forward 백테스트 인프라 포함.

FastAPI + HTMX + Tailwind로 만든 웹에서 전략·리스크·종목·API 키를 설정하고,
대시보드/차트/리포트/실시간 로그/KPI를 폰에서 확인한다.
macOS(launchd) / Docker / 직접 실행 3가지 배포 방식 지원, Tailscale로 외출 중 접근.

> ⚠️ **학습/실험용**. 본 프로젝트는 투자 권유가 아니며 **원금 손실 위험**이 있습니다.
> 현재 6종 전략은 **모두 walk-forward 검증 결과 실전 후보 탈락**(CSMOM 재설계 중). paper 모드 실험에 한정 권장.

---

## 목차

1. [한눈에 보기](#1-한눈에-보기)
2. [전략군](#2-전략군)
3. [빠른 시작](#3-빠른-시작)
4. [첫 접속 & TOTP 등록](#4-첫-접속--totp-등록)
5. [대시보드 · 봇 컨트롤](#5-대시보드--봇-컨트롤)
6. [설정 수정](#6-설정-수정)
7. [차트 · 리포트 · 실시간 로그](#7-차트--리포트--실시간-로그)
8. [분석 페이지들 (Review · Signal Board · Compare · Risk · KPI)](#8-분석-페이지들)
9. [백테스트 · Walk-Forward](#9-백테스트--walk-forward)
10. [외부(폰) 접속 — Tailscale](#10-외부폰-접속--tailscale)
11. [배포 — launchd / Docker](#11-배포--launchd--docker)
12. [파일 · 저장 경로](#12-파일--저장-경로)
13. [트러블슈팅](#13-트러블슈팅)
14. [V1 CLI](#14-v1-cli)
15. [개발자 참고](#15-개발자-참고)
16. [문서 인덱스](#16-문서-인덱스)

---

## 1. 한눈에 보기

```
[iPhone / 브라우저]  ←(Tailscale 선택)→  [서버(맥 launchd · Linux Docker · 직접 실행)]
                                                   ↓
                                           FastAPI + BackgroundScheduler
                                                   ↓
                                           TradingBot (paper/live)
                                                   ↓
                                          Upbit REST + WebSocket · Telegram Bot
```

- **단일 프로세스**: 웹 UI + BackgroundScheduler + TradingBot을 `python -m auto_coin.web` 하나로.
- **설정 변경은 UI → SQLite → `BotManager.reload()`** → 프로세스 재시작 없이 다음 tick부터 반영.
- **인증**: password + TOTP 2FA (`/setup` 최초 필수). 5회 실패 시 10분 lockout, 복구 코드 8개.
- **보안**: API 키 Fernet 암호화(`~/.auto_coin_master.key`, 0600), 세션 쿠키 7일.
- **실시간성**: 공개/개인 WebSocket 병행 — 공개 ticker로 현재가, 개인 myOrder로 체결 reconcile.
- **상태 지속**: 모든 운영 행위는 `AuditLog`에 before/after JSON (민감 필드 자동 마스킹).

하단 탭: **📊대시 · 📈차트 · 🔍검토 · 📡상태판 · 📊KPI · 📄리포트 · 📜로그 · ⚙️설정**.

---

## 2. 전략군

UI `/settings/strategy`에서 드롭다운으로 선택. 전략별 파라미터 폼은 동적으로 렌더됨.

| 이름 | 레이블 | 실행 모드 | 핵심 로직 |
|---|---|---|---|
| `volatility_breakout` | 변동성 돌파 (Larry Williams) | intraday | `target = 오늘 시가 + 전일 range × K`. 장중 돌파 시 진입. |
| `sma200_regime` | SMA200 추세 필터 | daily_confirm | 종가가 SMA(N) 위일 때만 BUY (옵션: 아래 이탈 시 SELL) |
| `atr_channel_breakout` | ATR 채널 돌파 | intraday | `upper = low + ATR × 배수` 상단 돌파 진입 |
| `ema_adx_atr_trend` | EMA+ADX 추세추종 | daily_confirm | EMA 골든크로스 + ADX > 임계값 |
| `ad_turtle` | AdTurtle (개선형 Turtle) | intraday | Donchian 상단 돌파 + 하단 이탈 청산 |
| `sma200_ema_adx_composite` | SMA200 필터 + EMA+ADX (권장) | daily_confirm | SMA200 risk-off면 전량 청산, 그 외 EMA+ADX 추세 진입 |

### 포트폴리오 전략 (연구 단계)

- `strategy/portfolio/csmom.py` — Cross-Sectional Momentum (rank + regime filter)
- `strategy/portfolio/baselines.py` — regime-only equal_weight / btc_only

현재 V1/V2 프로덕션에는 **종목별 전략**(위 표 6종)만 연결되어 있음. CSMOM 계열은
walk-forward 평가 결과 실전 후보 탈락 → v-next 재설계 중 (`docs/v4/PLAN_CSMOM.md`).

---

## 3. 빠른 시작

### 방법 A — Python 직접 실행 (가장 간단)

```bash
cd /path/to/auto_coin
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# (선택) .env 템플릿
cp .env.example .env && chmod 600 .env

# 기동
.venv/bin/python -m auto_coin.web --port 8080
# 브라우저: http://127.0.0.1:8080
```

### 방법 B — Docker Compose

```bash
docker compose up -d web
# 호스트 포트 3000 → 컨테이너 8080
# 상태/로그는 ./data 볼륨에 영속화
```

기본값은 **paper 모드**. 실거래는 `/settings/schedule`에서
`mode=live` + `live_trading` 체크 + `kill_switch OFF` **3중 조건** 충족 시에만 주문이 나갑니다.

외부 접근 → [§10 Tailscale](#10-외부폰-접속--tailscale).
상시 실행 → [§11 배포](#11-배포--launchd--docker).

---

## 4. 첫 접속 & TOTP 등록

### 4.1 `/setup`
1. 관리자 패스워드 8자 이상 (확인 포함)
2. **TOTP QR 표시** → Google Authenticator / 1Password / Authy / Bitwarden 중 하나로 스캔
3. 앱 6자리 코드 입력 → 확인
4. **복구 코드 8개 1회 표시** — 반드시 안전한 곳에 보관 (재발급 불가)
5. 자동 로그인 → `/` 대시보드

### 4.2 다음 방문 (`/login`)
- 패스워드 + 현재 TOTP 6자리
- 세션 쿠키 7일 유지
- **5회 실패 → 10분 lockout**

### 4.3 TOTP 기기 상실 시
`/login` 하단 **복구 코드로 재설정** 링크 → 복구 코드 1개 입력 → 새 QR/TOTP 등록 → 새 복구 코드 세트 발급. 1회용.

---

## 5. 대시보드 · 봇 컨트롤

경로: `/` (5초 polling partial refresh)

### 상단 뱃지 · 컨트롤
| 뱃지 | 의미 |
|---|---|
| 🟢 running / ⚪ stopped | BackgroundScheduler 활성 여부 |
| LIVE / paper | mode + live_trading + kill_switch 종합 |
| 🟡 kill-switch ON | 신규 진입 차단 중 (청산은 정상) |

버튼: **Kill-switch 토글 · 재시작(reload) · 봇 정지 · 봇 시작** (정지/Kill은 2단계 confirm).

### 본문
- 슬롯 사용량 `X/N`
- 오늘 PnL 합산
- 잔고 (live면 실제 Upbit KRW, paper면 가상 자본 + KRW 환산)
- 포지션 카드 — 종목별 수량·진입가·현재가·미실현 PnL
- 최근 주문 10건
- Upbit 보유자산 요약 (live 연결 시)

---

## 6. 설정 수정

경로: `/settings` (섹션 카드 5개). 저장 시
**pydantic 검증 → SQLite upsert → AuditLog → `BotManager.reload()` → flash → 303**. 재시작 불필요.

### 6.1 전략 (`/settings/strategy`)
- 전략 드롭다운에서 6종 중 선택
- 선택 즉시 **전략별 파라미터 폼**이 동적으로 표시 (K/MA/ATR/EMA/ADX/Donchian 등)
- `watch 주기 (분)` — 텔레그램 관측 메시지 간격

### 6.2 리스크 (`/settings/risk`)
- 1슬롯 투입 비율 / 동시 보유 상한 / 일일 손실 한도 / 개별 손절 / 최소 주문 / 페이퍼 가상 자본 / Kill-switch

### 6.3 포트폴리오 (`/settings/portfolio`)
- `TICKERS` — 나열 순서가 진입 우선순위
- `WATCH_TICKERS` — 관측 전용
- 업비트 상장 자동 검증 + 거래대금 상위 20 추천

### 6.4 API 키 (`/settings/api-keys`)
- 저장된 키는 `••••last4` 마스킹
- 빈 값 저장 = 기존 값 유지 (실수 보호)
- **Upbit 연결 테스트** / **Telegram 연결 테스트** HTMX 버튼

### 6.5 스케줄 / 모드 (`/settings/schedule`)
- mode drop-down (paper ↔ live) — live 전환 시 현재 TOTP 재확인 필수
- tick 주기 / heartbeat / 청산 시각 / 일일 리셋 시각

### 6.6 감사 로그 (`/settings/audit`)
모든 설정 변경 이력. API 키는 저장 시점에 마스킹된 채로 기록.

---

## 7. 차트 · 리포트 · 실시간 로그

- **`/charts`** — portfolio + watch 종목 드롭다운, 최근 60일 일봉 + MA + target + 진입가 라인. Chart.js.
- **`/reports`** — `reports/*.md` 자동 인덱싱, markdown2 렌더 (dark code block, 반응형 테이블).
- **`/logs`** — 최근 200줄 즉시 + SSE 스트림 실시간 추가. 레벨 필터(DEBUG↑/INFO↑/WARNING↑/ERROR↑), 자동 스크롤 토글.

---

## 8. 분석 페이지들

| 경로 | 내용 |
|---|---|
| `/review` | 신호 인터랙티브 리플레이. 3모드: **전략 신호만 / 전략 SELL 포함 / 운영 청산 포함**. 차트 + step slider + 상세 reason. |
| `/signal-board` | 현재가 기반 종목별 실시간 상태 (매수 가능/대기/차단/보유 중) + 레짐 인디케이터. |
| `/compare` | 모든 전략을 같은 기간/종목에서 일괄 비교. 총 손익 기준 정렬, 현재 전략 하이라이트. |
| `/risk` | Kill-switch · 슬롯 · 손실 한도 · 손절 · 모드 · 포지션 · 스케줄 통합 뷰. |
| `/kpi` | 2주 paper 검증용 KPI 요약. 7d / 14d / 30d / all 프리셋, 전략·종목·청산사유 분해 + 일별 차트. |

---

## 9. 백테스트 · Walk-Forward

CLI 도구. 모든 전략 및 포트폴리오 단위 평가 가능.

### 9.1 단일 종목 백테스트
```bash
python -m auto_coin.backtest.runner --ticker KRW-BTC --days 365 --k 0.5
python -m auto_coin.backtest.runner --ticker KRW-BTC --days 365 --sweep 0.3 0.7 0.1
```

### 9.2 단일 종목 Walk-Forward
```bash
python -m auto_coin.backtest.walk_forward --ticker KRW-BTC --strategy volatility_breakout
```

### 9.3 포트폴리오 백테스트 / Walk-Forward
```bash
python -m auto_coin.backtest.portfolio_runner ...
python -m auto_coin.backtest.portfolio_walk_forward ...
```

종목간 공통 자본 풀·슬롯 상한·레짐 필터·rebalance 주기를 반영한 **in-sample** 및
**walk-forward** 평가. CSMOM B-series 연구에서 stability/strategic-alpha/incremental-alpha
지표로 의사결정한 같은 인프라.

연구 스크립트: `scripts/csmom_b4_validation.py`, `csmom_b5_decomposition.py`, `csmom_b6_v3.py`.

---

## 10. 외부(폰) 접속 — Tailscale

자세한 내용: [docs/v2/tailscale-setup.md](docs/v2/tailscale-setup.md).

1. macOS/Linux 서버 + 폰에 Tailscale 설치 (동일 계정)
2. `auto_coin.web`을 `--host 0.0.0.0`으로 기동
3. 폰에서 `http://<서버이름>.<tailnet>.ts.net:8080` 접속
4. 로그인 + TOTP

### 보안 체크
- V2 자체 인증(`/setup` 완료)
- OS 방화벽 ON, Tailscale 인터페이스만 허용
- `0.0.0.0` 바인딩은 Tailscale + 방화벽 조합에서만 안전 (공인 IP 직노출 금지)

---

## 11. 배포 — launchd / Docker

### 11.1 macOS launchd (한 줄 설치)
```bash
./deploy/install_launchd.sh
```
- `~/Library/LaunchAgents/auto_coin.plist` 설치
- `RunAtLoad` + `KeepAlive` → 부팅 시 자동 기동 + 크래시 시 10초 후 재시작
- stdout/stderr → `logs/launchd.*.log`

관리:
```bash
launchctl list | grep auto_coin                        # PID
launchctl unload ~/Library/LaunchAgents/auto_coin.plist  # 정지
launchctl load   ~/Library/LaunchAgents/auto_coin.plist  # 재시작
launchctl kickstart -k gui/$(id -u)/auto_coin            # 재기동
```

자세히: [deploy/README.md](deploy/README.md).

### 11.2 Docker Compose (Linux/NAS 등)
```bash
docker compose up -d web            # V2 웹 (권장)
docker compose --profile cli up -d cli   # V1 CLI 모드로 돌릴 때
```

- 포트: 3000 → 8080 (컨테이너)
- 볼륨: `./data` → `/data` (state·logs·DB 전부 영속화)
- `.env`가 있으면 자동으로 주입, 없으면 UI `/setup`부터

### 11.3 동시 실행 방지
V1 CLI와 V2 웹은 `state/*.json`을 공유하므로 **runtime guard** 락이 걸려 있음. 하나만 기동 가능.

---

## 12. 파일 · 저장 경로

| 경로 | 내용 | 민감도 |
|---|---|---|
| `~/.auto_coin.db` | SQLite (설정/사용자/감사 로그/일별 스냅샷/체결 이력) | ⚠️ API 키 암호문 포함 |
| `~/.auto_coin_master.key` | Fernet 마스터 (DB 암호화) | 🚨 유출 금지, 0600 |
| `~/.auto_coin_session.key` | 세션 쿠키 서명 | ⚠️ 유출 시 세션 탈취 가능 |
| `state/{TICKER}.json` | 종목별 포지션/주문 기록 | V1/V2 공유, 재시작 자동 복구 |
| `logs/launchd.out.log` | launchd stdout (macOS) | — |
| `logs/auto_coin_YYYY-MM-DD.log` | loguru 회전 로그 (14일) | — |
| `reports/*.md` | 운영 분석 리포트 (웹 렌더) | — |
| `data/` (Docker) | 위 HOME 경로가 컨테이너에서 `/data`로 매핑 | — |

**백업 3종 세트**: DB + master key + session key. 하나만 잃어도 복원 불가.
**초기화**: 세 파일 제거 → 다시 `/setup`부터.

---

## 13. 트러블슈팅

### 웹이 뜨지 않음
```bash
lsof -i :8080                          # 포트 충돌?
tail -50 logs/launchd.err.log          # launchd 로그
.venv/bin/python -m auto_coin.web --port 8080  # foreground 직접 실행
```

### `/login`에서 "사용자가 존재하지 않습니다"
→ `/setup` 먼저. 캐시된 리다이렉트면 `/setup` 직접 입력.

### lockout
- 10분 대기 또는 `sqlite3 ~/.auto_coin.db "UPDATE user SET failed_attempts=0, locked_until=NULL;"`

### 설정 저장했는데 봇이 옛 값으로 동작
- `BotManager.reload()`는 자동이지만 진행 중인 tick은 끝까지 돎. 대시보드 **재시작(reload)** 수동 클릭.
- launchd: `launchctl kickstart -k gui/$(id -u)/auto_coin`

### `another auto_coin runtime is already active`
V1 CLI와 V2 웹 동시 실행 충돌. 한쪽을 종료:
```bash
pkill -f auto_coin.main
launchctl unload ~/Library/LaunchAgents/auto_coin.plist
```

### SSE 로그가 "재연결 중" 반복
- Tailscale DERP 릴레이 지연 가능. `/health` JSON이 정상 응답하는지 먼저 확인.
- 방화벽에서 Python 프로세스 허용.

### API 테스트는 되는데 tick에서 "order failed"
- Kill-switch OFF?
- 업비트 **출금 권한 꺼야 함**, **IP 화이트리스트**에 현재 IP 포함
- 잔고 < `min_order_krw` (5,000 KRW floor)

### "tick crashed" 반복
- `/logs`에서 traceback 확인
- 최근 설정을 되돌리거나 Kill-switch ON으로 우선 차단

---

## 14. V1 CLI

V2 머지 이후에도 V1 CLI 경로는 유지. `.env`와 `state/*.json` 공유.

```bash
python -m auto_coin.main            # 무한 스케줄링
python -m auto_coin.main --once     # 1 tick 디버그
python -m auto_coin.main --live     # 실거래 강제
```

자세한 CLI 운영법: [docs/v1/USER_GUIDE.md](docs/v1/USER_GUIDE.md).

---

## 15. 개발자 참고

### 모듈 구조
```
src/auto_coin/
├── config.py · logging_setup.py · formatting.py · runtime_guard.py
├── main.py                # V1 CLI 엔트리
├── bot.py                 # TradingBot (tick/watch/heartbeat/daily_reset/force_exit/report)
├── reporter.py            # 일일 리포트 생성
├── exchange/
│   ├── upbit_client.py    # pyupbit 래퍼 (유일한 import 지점)
│   ├── ws_client.py       # public WebSocket (ticker 실시간 현재가)
│   └── ws_private.py      # private WebSocket (myOrder 체결 reconcile)
├── data/
│   ├── candles.py         # 일봉 DataFrame + target/MA 컬럼
│   └── candle_cache.py    # 일봉 TTL 캐시
├── notifier/telegram.py   # Bot API · CLI (--check / --find-chat-id / --send)
├── strategy/
│   ├── base.py                      # Signal, MarketSnapshot, Strategy ABC
│   ├── __init__.py                  # REGISTRY + PARAMS + LABELS
│   ├── volatility_breakout.py
│   ├── sma200_regime.py
│   ├── atr_channel_breakout.py
│   ├── ema_adx_atr_trend.py
│   ├── ad_turtle.py
│   ├── sma200_ema_adx_composite.py
│   └── portfolio/
│       ├── csmom.py       # Cross-Sectional Momentum (연구)
│       └── baselines.py   # regime-only equal_weight / btc_only
├── review/                # 신호 리플레이 시뮬레이터 (reason formatter 포함)
├── backtest/
│   ├── runner.py                  # 단일 종목 백테스트 CLI
│   ├── walk_forward.py            # 단일 종목 walk-forward
│   ├── portfolio_runner.py        # 포트폴리오 백테스트
│   └── portfolio_walk_forward.py  # 포트폴리오 walk-forward
├── risk/manager.py        # Decision 게이트 (손절 최우선)
├── executor/
│   ├── order.py           # paper/live 주문, UUID 멱등
│   └── store.py           # JSON 원자적 상태 저장
└── web/                   # V2 웹 콘솔 (FastAPI + HTMX + Tailwind CDN)
    ├── app.py · __main__.py
    ├── crypto.py · session_secret.py · csrf.py · auth.py · audit.py
    ├── db.py · models.py
    ├── bot_manager.py · settings_service.py · user_service.py
    ├── routers/           # auth, dashboard, control, settings, charts,
    │                      # reports, logs, review, signal_board, compare,
    │                      # risk_dashboard, kpi
    ├── services/          # upbit_scan, credentials_check, log_stream,
    │                      # signal_board, kpi
    └── templates/         # base, dashboard, charts, logs, kpi, review,
                           # signal_board, compare, risk_dashboard,
                           # auth/*, settings/*, reports/*, partials/*
```

### 테스트 · 린트
```bash
pytest                  # 849 collected
ruff check src tests
```

### 실행 경로
| 진입점 | 용도 |
|---|---|
| `python -m auto_coin.web` | V2 웹 콘솔 (프로덕션) |
| `python -m auto_coin.main` | V1 CLI (legacy, state 공유) |
| `python -m auto_coin.backtest.runner` | 단일 종목 백테스트 |
| `python -m auto_coin.backtest.walk_forward` | 단일 종목 walk-forward |
| `python -m auto_coin.backtest.portfolio_runner` | 포트폴리오 백테스트 |
| `python -m auto_coin.backtest.portfolio_walk_forward` | 포트폴리오 walk-forward |
| `python -m auto_coin.notifier --check` | Telegram 토큰 검증 |

### 아키텍처 불변 (CLAUDE.md)
- `strategy/` — 순수 함수. I/O 금지. 백테스트 = 실거래 동일 코드.
- `risk/manager.py` — Executor 앞단 게이트. 손절 > BUY.
- `exchange/upbit_client.py` — `pyupbit` 유일 import 지점.
- `executor/store.py` — JSON 원자 저장. DB 이관 안 함.
- `web/` — V1 코드 수정 없이 감싸는 구조.

---

## 16. 문서 인덱스

```
.
├── README.md            # (이 문서)
├── CHANGELOG.md         # 버전/마일스톤별 구현 이력
├── CLAUDE.md            # Claude Code 작업 지침
├── Dockerfile · docker-compose.yml · .dockerignore
├── deploy/
│   ├── README.md                # launchd 설치/검증
│   ├── auto_coin.plist          # launchd 템플릿
│   └── install_launchd.sh       # 경로 치환 + load
├── docs/
│   ├── v1/{PLAN,USER_GUIDE}.md  # V1 CLI 설계·운영
│   ├── v2/{PLAN,tailscale-setup}.md  # V2 웹 설계·외부 접속
│   ├── v3/PLAN.md               # V3 분석 페이지 강화
│   ├── v4/PLAN_CSMOM.md         # V4 포트폴리오 전략 설계 (연구)
│   └── (전략 개발 가이드·WF 내용수정 이력 등)
├── scripts/             # CSMOM B-series walk-forward 연구 스크립트
└── reports/             # paper/live 운영 분석 리포트 (웹 렌더)
```

**변경 이력 한 줄 요약**은 [CHANGELOG.md](CHANGELOG.md).
