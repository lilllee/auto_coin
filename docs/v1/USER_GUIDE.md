# auto_coin — 운영 가이드

일상 운영에 필요한 명령어·설정만 모은 문서입니다.
설계 배경은 [PLAN.md](PLAN.md), 개요는 최상위 [README.md](../../README.md)를 보세요.

> **V1(CLI) vs V2(웹)**: 본 가이드는 **V1 CLI** 기준입니다. V2 웹 콘솔 전체 운영법은
> 최상위 [README.md](../../README.md)에 통합되어 있습니다. V2 설계 세부는
> [docs/v2/PLAN.md](../v2/PLAN.md) 참고.

---

## 목차

1. [최초 설치](#1-최초-설치-1회만)
2. [.env 구성](#2-env-구성)
3. [봇 실행 · 종료 · 재시작](#3-봇-실행--종료--재시작)
4. [종목 변경하기](#4-종목-변경하기)
5. [투자 금액 조정](#5-투자-금액-조정)
6. [리스크 파라미터 튜닝](#6-리스크-파라미터-튜닝)
7. [텔레그램 알림 설정](#7-텔레그램-알림-설정)
8. [백테스트 돌리기](#8-백테스트-돌리기)
9. [로그 · 상태 파일 위치](#9-로그--상태-파일-위치)
10. [자주 쓰는 확인 명령](#10-자주-쓰는-확인-명령)
11. [트러블슈팅](#11-트러블슈팅)

---

## 1. 최초 설치 (1회만)

```bash
cd /Users/seungjun/IdeaProjects/auto_coin
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
chmod 600 .env            # 키 파일 권한 제한
```

이후에는 `.venv`를 유지하면 되고, 코드만 `git pull`하면 됩니다.

---

## 2. .env 구성

`.env`는 git에 올라가지 않습니다 (`.gitignore`). 반드시 `chmod 600 .env`로 본인만 읽게 두세요.

```bash
# ── 업비트 API ────────────────────────────────────
# 출금 권한 반드시 비활성, IP 화이트리스트 권장
UPBIT_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
UPBIT_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── 텔레그램 ──────────────────────────────────────
TELEGRAM_BOT_TOKEN=123456:AAA...
TELEGRAM_CHAT_ID=1234567890

# ── 실행 모드 ────────────────────────────────────
MODE=paper        # paper | live
LIVE_TRADING=0    # 실거래 강제 활성화 (1로 바꿔야만 실거래)
KILL_SWITCH=0     # 1이면 신규 진입 전면 차단 (기존 포지션 청산은 허용)

# ── 매매 대상 ────────────────────────────────────
TICKER=                                                   # (비우면 TICKERS 사용)
TICKERS=KRW-DRIFT,KRW-ETH,KRW-XRP,KRW-SOL,KRW-DOGE        # 나열 순서가 진입 우선순위
MAX_CONCURRENT_POSITIONS=3                                # 동시 보유 상한
WATCH_TICKERS=                                            # 매매는 않고 관측만 할 종목
WATCH_INTERVAL_MINUTES=15

# ── 전략 ────────────────────────────────────────
STRATEGY_K=0.5            # 변동성 돌파 K (0.3~0.7 튜닝)
MA_FILTER_WINDOW=5        # 5일 이평 필터

# ── 리스크 ──────────────────────────────────────
MAX_POSITION_RATIO=0.20   # 1슬롯 크기 = 이 비율 × 자본
DAILY_LOSS_LIMIT=-0.03    # 포트폴리오 일일 손실 한도
STOP_LOSS_RATIO=-0.02     # 개별 종목 손절선
MIN_ORDER_KRW=5000        # 업비트 최소 주문
API_MAX_RETRIES=3

# ── 스케줄 · 페이퍼 가상 자본 ────────────────────
PAPER_INITIAL_KRW=1000000
CHECK_INTERVAL_SECONDS=60
HEARTBEAT_INTERVAL_HOURS=6
EXIT_HOUR_KST=8
EXIT_MINUTE_KST=55
DAILY_RESET_HOUR_KST=9

# ── 저장/로그 ──────────────────────────────────
STATE_DIR=state
LOG_LEVEL=INFO            # DEBUG로 올리면 tick마다 로그
LOG_DIR=logs
```

**변경 후에는 반드시 봇을 재시작해야 반영됩니다.** 봇은 시작 시에만 `.env`를 읽습니다.

---

## 3. 봇 실행 · 종료 · 재시작

### 실행 (백그라운드, 터미널/세션 끊어져도 유지)

```bash
cd /Users/seungjun/IdeaProjects/auto_coin
nohup .venv/bin/python -m auto_coin.main > logs/bot.out.log 2>&1 < /dev/null & disown
echo $! > .bot.pid
```

시작 직후 텔레그램으로 🚀 시작 알림이 오면 성공입니다.

### 종료 (graceful — 🛑 종료 알림 + state 저장)

```bash
kill $(cat .bot.pid)
```

PID 파일이 없다면:
```bash
pkill -f auto_coin.main
```

### 재시작

```bash
kill $(cat .bot.pid)       # 1) 종료
# (1~2초 대기 후)
nohup .venv/bin/python -m auto_coin.main > logs/bot.out.log 2>&1 < /dev/null & disown
echo $! > .bot.pid
```

### 단일 tick 디버그 (스케줄러 없이 1번만 실행 후 종료)

```bash
.venv/bin/python -m auto_coin.main --once
```

### 실거래 강제 (위험)

```bash
.venv/bin/python -m auto_coin.main --live
```

`KILL_SWITCH=0`, 업비트 키 유효, **출금 권한 꺼짐** 확인 후에만 사용. `--live` 없이는 절대 실거래 안 합니다.

---

## 4. 종목 변경하기

### 종목 추가 · 제거 · 우선순위 변경

`.env`의 `TICKERS`를 편집합니다. **순서가 곧 진입 우선순위**입니다:

```bash
# 예: DOGE 뒤에 PEPE 추가 (업비트 상장 확인 먼저)
TICKERS=KRW-DRIFT,KRW-ETH,KRW-XRP,KRW-SOL,KRW-DOGE,KRW-PEPE

# 예: DRIFT를 맨 뒤로
TICKERS=KRW-ETH,KRW-XRP,KRW-SOL,KRW-DOGE,KRW-DRIFT

# 예: 단일 종목만
TICKER=KRW-BTC
TICKERS=
```

편집 후 [봇 재시작](#3-봇-실행--종료--재시작).

### 종목이 업비트 KRW 마켓에 있는지 먼저 확인

```bash
.venv/bin/python -c "
import pyupbit
t = 'KRW-PEPE'
print(t, '✅ listed' if t in pyupbit.get_tickers(fiat='KRW') else '❌ NOT listed')
"
```

### 매매는 안 하고 관찰만 하고 싶을 때

`WATCH_TICKERS`에 콤마로 넣으면 주문은 나가지 않고 watch 메시지에만 포함됩니다:

```bash
TICKERS=KRW-BTC
WATCH_TICKERS=KRW-ETH,KRW-XRP,KRW-SOL
```

---

## 5. 투자 금액 조정

### 페이퍼 모드 (가상 자본 조정)

```bash
PAPER_INITIAL_KRW=1000000     # 가상 자본 (기본 100만원)
MAX_POSITION_RATIO=0.20       # 한 종목당 투입 비율 (기본 20%)
```

**1슬롯 투입 = `PAPER_INITIAL_KRW × MAX_POSITION_RATIO`** (= 기본 200,000 KRW)

| 자본 | 비율 | 1슬롯 | 동시 3종목일 때 총 투입 |
|---:|---:|---:|---:|
| 1,000,000 | 0.20 | 200,000 | 600,000 |
| 500,000 | 0.20 | 100,000 | 300,000 |
| 1,000,000 | 0.10 | 100,000 | 300,000 |
| 2,000,000 | 0.15 | 300,000 | 900,000 |

### 실거래 모드

실거래는 `.env`의 `PAPER_INITIAL_KRW`를 무시하고 **실제 업비트 KRW 잔고**를 기준으로 계산합니다. 1슬롯 투입은 그대로 `MAX_POSITION_RATIO × 현재 잔고`.

**⚠️ 업비트 최소 주문**은 `MIN_ORDER_KRW=5000`. 1슬롯이 5,000 KRW 미만이면 BUY 자동 차단.

### 동시 보유 종목 수 조정

```bash
MAX_CONCURRENT_POSITIONS=3   # 최대 3종목 (5종목 중 3)
```

5종목 후보 중 몇 개까지 동시에 들고 갈지 결정합니다. 슬롯이 가득 차면 뒤 종목은 자동 HOLD.

---

## 6. 리스크 파라미터 튜닝

```bash
DAILY_LOSS_LIMIT=-0.03        # 포트폴리오 전체 일일 손실 한도 (종목별 합산)
STOP_LOSS_RATIO=-0.02         # 개별 종목 손절선 (진입가 기준)
MIN_ORDER_KRW=5000            # 업비트 최소 주문 금액
KILL_SWITCH=0                 # 1로 바꾸면 신규 진입 즉시 전면 차단
```

### 한도 발동 예시
- 3종목이 각각 -1%씩 하락 → 합산 -3% → `DAILY_LOSS_LIMIT` 도달 → **당일 신규 BUY 전면 차단**
- ETH가 진입가 대비 -2% 도달 → **ETH만 즉시 시장가 청산** (다른 종목은 영향 없음)
- `KILL_SWITCH=1`로 설정 → 신규 BUY 차단 (기존 포지션 청산은 정상 동작)

### 긴급 정지

```bash
# 1) Kill-switch만 켜기 (기존 포지션 유지, 신규 진입만 차단)
#    .env의 KILL_SWITCH=1 로 바꾸고 재시작

# 2) 봇 완전 정지 (포지션은 state/에 그대로 남음)
kill $(cat .bot.pid)
```

---

## 7. 텔레그램 알림 설정

### 처음 세팅

1. `@BotFather`와 대화 → `/newbot` → 이름·username 입력 → 토큰 받기
2. `.env`에 `TELEGRAM_BOT_TOKEN=...` 입력
3. 토큰 유효성 확인:
   ```bash
   .venv/bin/python -m auto_coin.notifier --check
   ```
4. 만든 봇과 1:1 대화창을 열고 아무 메시지(`/start` 등) 전송
5. chat_id 확인:
   ```bash
   .venv/bin/python -m auto_coin.notifier --find-chat-id
   ```
6. 출력된 `chat_id`를 `.env`의 `TELEGRAM_CHAT_ID`에 복사
7. 테스트 메시지:
   ```bash
   .venv/bin/python -m auto_coin.notifier --send "hello"
   ```

### 수신하는 알림 종류

| 이벤트 | 주기 / 트리거 |
|---|---|
| 🚀 시작 | 봇 기동 시 |
| 🛑 종료 | SIGTERM/SIGINT 수신 시 |
| 👀 watch | `WATCH_INTERVAL_MINUTES`마다 (기본 15분) |
| 🟢 BUY / 🔴 SELL | 체결 시 |
| ⏰ exit window SELL | 매일 08:55 KST |
| 📊 daily report | 매일 08:58 KST |
| 📊 daily reset | 매일 09:00 KST |
| 💓 heartbeat | `HEARTBEAT_INTERVAL_HOURS`마다 (기본 6시간) |
| ⚠️ market data fetch failed | 시세 조회 실패 시 |
| ❌ order failed | 주문 실패 시 |
| 🔥 tick crashed | 예상 못한 예외 발생 시 |

알림 주기를 줄이고 싶으면 `HEARTBEAT_INTERVAL_HOURS=0`으로 heartbeat 비활성, `WATCH_INTERVAL_MINUTES`를 60분 이상으로.

---

## 8. 백테스트 돌리기

```bash
# 단일 K값 — 최근 1년 BTC 일봉
.venv/bin/python -m auto_coin.backtest.runner --ticker KRW-BTC --days 365 --k 0.5

# K값 스윕 (0.3 ~ 0.7, 0.1 간격)
.venv/bin/python -m auto_coin.backtest.runner --ticker KRW-BTC --days 365 --sweep 0.3 0.7 0.1

# MA 필터 끄기
.venv/bin/python -m auto_coin.backtest.runner --ticker KRW-DOGE --days 365 --no-ma-filter

# 수수료/슬리피지 가정 변경
.venv/bin/python -m auto_coin.backtest.runner --ticker KRW-ETH --fee 0.0005 --slippage 0.001
```

백테스트는 봇과 독립 실행이며 `.env`를 읽지 않습니다. 모든 파라미터를 CLI로 전달.

---

## 9. 로그 · 상태 파일 위치

```
logs/
├── bot.out.log                   # nohup 표준 출력 (실시간 디버그용)
├── auto_coin_2026-04-14.log      # loguru 회전 로그 (일별)
state/
├── KRW-DRIFT.json
├── KRW-ETH.json
├── KRW-XRP.json
├── KRW-SOL.json
└── KRW-DOGE.json                 # 종목별 독립 포지션/주문 기록
reports/
└── 2026-04-14-paper-day1.md      # 수동 작성한 분석 리포트
.bot.pid                          # 현재 실행 중인 봇 PID (가장 최근 nohup으로 띄운 것)
.env                              # 설정 (git에 안 올라감, 600 권한)
```

- `state/{TICKER}.json`은 재시작 시 자동 복구됨. 삭제하지 마세요.
- `logs/auto_coin_*.log`는 14일 보관 후 자동 삭제.
- `state/` 디렉토리는 봇이 처음 주문을 실행할 때 자동 생성됨.

---

## 10. 자주 쓰는 확인 명령

```bash
# 봇이 살아있는가
pgrep -lf auto_coin.main

# 실시간 로그 (종료: Ctrl+C)
tail -f logs/bot.out.log

# 최근 매매 이벤트만 보기 (watch 제외)
grep -E "BUY|SELL|exit window|daily reset|heartbeat|crashed" logs/bot.out.log | tail -30

# 현재 포지션 한 눈에
for f in state/*.json; do
  echo "=== $f ==="
  .venv/bin/python -c "
import json, sys
s = json.load(open('$f'))
p = s.get('position')
if p: print(f\"  {p['ticker']} vol={p['volume']:.6f} entry={p['avg_entry_price']}\")
else: print('  flat')
print(f\"  orders: {len(s['orders'])}  daily_pnl: {s['daily_pnl_ratio']*100:+.2f}%\")
"
done

# 업비트 잔고 (인증 필요)
.venv/bin/python -c "
from auto_coin.config import load_settings
from auto_coin.exchange.upbit_client import UpbitClient
s = load_settings()
c = UpbitClient(s.upbit_access_key.get_secret_value(), s.upbit_secret_key.get_secret_value())
print(f'KRW: {c.get_krw_balance():,.0f}')
"

# 거래대금 상위 15종 (추천 종목 찾기)
.venv/bin/python -c "
import requests
r = requests.get('https://api.upbit.com/v1/market/all').json()
krw = [m['market'] for m in r if m['market'].startswith('KRW-')]
tickers = []
for i in range(0, len(krw), 100):
    tickers.extend(requests.get('https://api.upbit.com/v1/ticker', params={'markets': ','.join(krw[i:i+100])}).json())
tickers.sort(key=lambda x: x['acc_trade_price_24h'], reverse=True)
for t in tickers[:15]:
    print(f\"{t['market']:<14} price={t['trade_price']:>12,.6g} vol24h={t['acc_trade_price_24h']/1e9:>6.1f}B\")
"
```

---

## 11. 트러블슈팅

### 봇이 죽었다
```bash
pgrep -lf auto_coin.main    # 안 나오면 죽은 것
tail -50 logs/bot.out.log   # 마지막 로그에서 원인 확인
```
예외 종류와 함께 🔥 `tick crashed` 메시지가 텔레그램에 갔어야 합니다.

### 텔레그램 알림이 안 옴
```bash
.venv/bin/python -m auto_coin.notifier --check            # 토큰 유효성
.venv/bin/python -m auto_coin.notifier --send "ping"      # 직접 전송 테스트
```
- 토큰/chat_id가 `.env`에 제대로 들어갔는지
- 봇이 block당하지 않았는지 (텔레그램에서 봇 차단 해제)

### 업비트 API 호출이 계속 실패
- IP 화이트리스트 확인 (발급 시 설정한 IP와 현재 IP 일치 여부)
- 키 권한 (조회/주문 체크, 출금은 꺼짐이 맞는지)
- 키 재발급이 필요할 수도

### 종목 변경했는데 적용이 안 된 것 같다
```bash
# 봇이 옛 설정으로 돌고 있음 — 재시작 필수
kill $(cat .bot.pid) && sleep 2 && \
  nohup .venv/bin/python -m auto_coin.main > logs/bot.out.log 2>&1 < /dev/null & disown
echo $! > .bot.pid
```
시작 로그/텔레그램 알림의 `tickers=...` 부분에서 새 종목 리스트가 보이는지 확인.

### 페이퍼 모드인데 실제로 매수된 것 같다
절대 아닙니다. paper 모드는 `orders[*].status == "paper"`로 기록되고 업비트 API는 건드리지 않습니다. `state/*.json`의 status 필드로 확인.

### 일일 손실 한도 해석이 이상하다
`DAILY_LOSS_LIMIT=-0.03`은 **"각 종목 daily_pnl_ratio의 합산"** 기준입니다. 종목이 3개면 실질 차단선은 포트폴리오 평균 -1% 정도에 해당합니다. 리포트에서 "포트폴리오 가중 평균"과 "단순 합산" 두 값을 함께 확인하세요 — 자세한 내용은 [reports/2026-04-14-paper-day1.md](reports/2026-04-14-paper-day1.md).

---

## V2 웹 콘솔 미리보기

`v2` 브랜치에서 개발 중. 완성되면 `main`으로 머지 예정.

### 현재 가능한 것 (V2.0 ~ V2.3)

```bash
git checkout v2
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m auto_coin.web --port 8080
# 브라우저에서 http://127.0.0.1:8080
```

- `.env`에 설정이 있으면 최초 기동 시 **SQLite로 1회 자동 마이그레이션** (`~/.auto_coin.db`)
- `/setup`에서 관리자 **패스워드 + TOTP** 등록 (Google Authenticator 등으로 QR 스캔)
- 이후 `/login`으로 들어오면 세션 7일 유지, 5회 실패 시 10분 lockout
- 로그인 후 하단 5탭: 📊대시(placeholder) / 📈차트(V2.5) / 📄리포트(V2.6) / 📜로그(V2.7) / ⚙️설정

### /settings에서 할 수 있는 것 (V2.3 기준)

| 섹션 | 내용 |
|---|---|
| **전략** | K (0.1–1.0), MA 필터 창, watch 주기 |
| **리스크** | 슬롯 비율, 동시 보유 상한, 일일 손실/손절, 최소 주문, 페이퍼 가상 자본, **Kill-switch 토글** |
| **포트폴리오** | TICKERS · WATCH_TICKERS 편집, **거래대금 상위 20 추천**, 업비트 상장 자동 검증 |
| **API 키** | Upbit / Telegram. masked 표시, 빈 입력 = 기존 값 유지, **HTMX 연결 테스트 버튼** |
| **스케줄·모드** | tick/heartbeat/청산/리셋 시각, **paper ↔ live 전환** |

저장 버튼을 누르면:
1. pydantic 재검증 (실패 시 400 + 필드 에러 표시)
2. SQLite 업서트 + `AuditLog` 기록 (API 키는 마스킹)
3. **`BotManager.reload()` 자동 호출** → 프로세스 재시작 없이 다음 tick부터 새 설정 적용
4. 초록 flash 메시지로 결과 확인

### 아직 미구현 (V2.4 이후)

- 대시보드 (현재 포지션/PnL 카드, Kill-switch 토글, **봇 start/stop/restart 버튼**)
- 차트 · 리포트 뷰어 · 실시간 로그
- Tailscale 외부 접근 가이드 · launchd 자동 시작

상세 로드맵은 [docs/v2/PLAN.md](../v2/PLAN.md), 실제 사용법은 최상위 [README.md](../../README.md) 참고.

### V2 관련 파일 위치

| 경로 | 용도 |
|---|---|
| `~/.auto_coin.db` | SQLite (설정/사용자/감사 로그) |
| `~/.auto_coin_master.key` | API 키 Fernet 암호화 마스터 키 (600) |
| `~/.auto_coin_session.key` | 세션 쿠키 서명 비밀키 (600) |

세 파일 모두 삭제하면 **초기화** 됩니다 (사용자/TOTP 재등록 필요).

---

## 참고 문서

- [../../README.md](../../README.md) — V2 기준 통합 사용자 가이드 (프로젝트 진입점)
- [./PLAN.md](PLAN.md) — V1 아키텍처 · 마일스톤 · 리스크 규칙
- [../v2/PLAN.md](../v2/PLAN.md) — V2 웹 콘솔 설계서
- [../../CHANGELOG.md](../../CHANGELOG.md) — 전체 변경 이력
- [../../CLAUDE.md](../../CLAUDE.md) — Claude Code 작업 지침
- [../../reports/](../../reports/) — 운영 리포트
