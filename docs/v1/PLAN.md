# 업비트(Upbit) 자동매매 봇 구현 계획서

작성일: 2026-04-13
최종 수정: 2026-04-13 (마일스톤 재정리)

---

## 0. 요약

업비트 Open API + `pyupbit` 기반 KRW 마켓 자동매매 봇. MVP는 **변동성 돌파(Larry Williams)**, 이후 플러그인형 전략으로 확장. 검증 순서는 **백테스트 → 페이퍼 → 소액 실거래**.

---

## 1. 목표 / 비목표

**목표**
- 업비트 계좌에 안전하게 연결해 KRW 마켓 코인 매수/매도 자동화
- 단일 전략(변동성 돌파) MVP → 다중 전략 플러그인 구조 확장
- 백테스트 → 페이퍼 트레이딩 → 소액 실거래 3단계 검증

**비목표 (초기 범위 밖)**
- 파생/선물, 해외 거래소(Binance 등) 지원
- GUI 대시보드 (초기: CLI + 로그 + 텔레그램 알림)

---

## 2. 기술 스택

| 영역 | 선택 | 비고 |
|---|---|---|
| 언어 | Python 3.11+ | |
| 거래소 SDK | `pyupbit` | JWT 인증·시세·주문 래퍼 |
| 데이터 | `pandas`, `numpy` | 캔들/지표 |
| 스케줄링 | `APScheduler` | 주기 실행 |
| 설정 | `pydantic-settings` + `.env` | |
| 알림 | Telegram Bot API | |
| 로깅 | `loguru` | 회전 로그 |
| 테스트 | `pytest`, `pytest-mock` | |
| 배포 | Docker + systemd/tmux | 24시간 상주 |

---

## 3. 아키텍처

```
┌────────────────┐     ┌───────────────────┐
│  Scheduler     │────▶│  Strategy Engine  │
│ (APScheduler)  │     │  (plugin-based)   │
└────────────────┘     └─────────┬─────────┘
                                 │ signal(BUY/SELL/HOLD)
                                 ▼
┌─────────────────┐     ┌───────────────────┐     ┌──────────────┐
│ Market Data     │◀───▶│  Order Executor   │────▶│  Upbit API   │
│ (candles/ticker)│     │  (risk-checked)   │     │  (pyupbit)   │
└─────────────────┘     └─────────┬─────────┘     └──────────────┘
                                  ▼
                       ┌───────────────────┐
                       │ Logger / Telegram │
                       └───────────────────┘
```

**모듈 경계 (불변)**
- `strategy/`는 순수 함수 — 주문/네트워크/로깅을 직접 호출하지 않는다.
- `risk/`는 Executor **앞단 게이트** — 시그널이 여길 통과해야 주문 가능.
- `exchange/`만 `pyupbit`를 import — 다른 모듈은 래퍼만 사용.
- `backtest/`는 Executor 대체재로 같은 Strategy 객체를 실행.

### 디렉토리

```
auto_coin/
├── PLAN.md
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── src/auto_coin/
│   ├── __init__.py
│   ├── config.py
│   ├── exchange/upbit_client.py
│   ├── data/candles.py
│   ├── strategy/{base.py, volatility_breakout.py}
│   ├── risk/manager.py
│   ├── executor/order.py
│   ├── notifier/telegram.py
│   ├── backtest/runner.py
│   └── main.py
└── tests/
```

---

## 4. 핵심 규칙

### 4.1 업비트 인증
- JWT(HS256), 페이로드: `access_key`, `nonce(UUID)`, 주문 시 `query_hash` + `query_hash_alg="SHA512"`
- `secret_key`는 **Base64 디코드 없이 원문**을 서명 키로 사용
- API 키 권한: 출금 **반드시 비활성화**, IP 화이트리스트 필수
- 모든 주문에 **UUID 멱등 식별자** 부여

### 4.2 MVP 전략 — 변동성 돌파
- 09:00 KST 기준 일봉 경계
- `target_price = 오늘_시가 + (전일_고가 - 전일_저가) × K`, K 기본 0.5 (튜닝 0.3~0.7)
- 현재가가 `target_price` 돌파 시 시장가 매수 → 다음 09:00 직전 전량 청산
- 필터: **5일 이평 이상**일 때만 진입

### 4.3 리스크 관리 상수 (설정화)
| 항목 | 기본값 |
|---|---|
| 주문당 최대 투입 | 총 자산 20% |
| 일일 손실 한도 | -3% (도달 시 당일 중단) |
| 개별 손절 | 진입가 -2% |
| 업비트 최소 주문 | 5,000 KRW |
| API 재시도 | 3회 → 실패 시 알림 + 포지션 보존 |
| Kill-switch | `KILL_SWITCH=1` |

---

## 5. 마일스톤

진행 상태: `[ ]` 미착수 · `[~]` 진행 중 · `[x]` 완료

### M1 — 프로젝트 스캐폴딩 `[x]`
저장소에 코드 골격 + 패키징 + 품질 도구 세팅. 실제 API 호출 없음.

- [x] `pyproject.toml` 작성 (Python 3.11+, 의존성, dev-deps, ruff/pytest 설정)
- [x] `.gitignore`, `.env.example` 작성
- [x] `src/auto_coin/` 패키지 골격 생성 (빈 모듈 + `__init__.py`)
- [x] `src/auto_coin/config.py` — `pydantic-settings`로 `.env` 로드
- [x] `tests/` 골격 + 샘플 테스트 5건 (기본값/env 오버라이드/kill-switch/검증)
- [x] `README.md` — 설치/실행 최소 안내
- [ ] `git init` + 첫 커밋 (사용자 요청 시)

**완료 기준**: `pip install -e ".[dev]"` → `pytest` 통과 (5/5), `python -m auto_coin.main` 로그 출력, `ruff check` 통과. ✅

### M2 — 거래소 래퍼 + 데이터 레이어 `[x]`
`pyupbit` 의존성을 모듈 경계 안으로 캡슐화.

- [x] `exchange/upbit_client.py` — `UpbitClient` 클래스 (잔고/현재가/시장가 매수·매도)
- [x] 재시도(exponential backoff) + 레이트리밋 throttle (~10 req/s)
- [x] `data/candles.py` — 일봉 DataFrame 변환, `target`/`range`/`maN` 컬럼 추가
- [x] 단위 테스트 — `pytest-mock`으로 `pyupbit`/`requests` 모킹 (네트워크 0회)
- [x] `notifier/telegram.py` — 토큰 없을 때 no-op, 네트워크 실패 swallow

**완료 기준**: `pytest` 26/26 통과, `ruff check` 통과, 네트워크 호출 0회. ✅

### M3 — 전략 인터페이스 + 변동성 돌파 `[x]`
순수 함수 전략 구현.

- [x] `strategy/base.py` — `Signal`(BUY/SELL/HOLD), `MarketSnapshot`, `Strategy` ABC
- [x] `strategy/volatility_breakout.py` — K·이평 필터 파라미터화, 보유 중 진입 차단
- [x] 단위 테스트 — 돌파/미돌파/이평 하회/보유/NaN/순수성 11건

**완료 기준**: `pytest` 37/37 통과, 전략 호출이 입력 DataFrame을 변형하지 않음, 네트워크·시간 의존 0. ✅

### M4 — 백테스트 러너 `[x]`
같은 Strategy 객체로 과거 데이터 시뮬레이션.

- [x] `backtest/runner.py` — 일봉 DataFrame 주입 → 수익률/MDD/승률/거래수 계산
- [x] 수수료(업비트 0.05% 기본) + 슬리피지 파라미터화
- [x] CLI: `python -m auto_coin.backtest.runner --ticker KRW-BTC --k 0.5 --days 365`
- [x] K값 스윕: `--sweep START STOP STEP`
- [x] 단위 테스트 12건 (진입/청산/수수료/슬리피지/MDD/MA 필터/CLI)

**완료 기준**: `pytest` 49/49 통과, 실제 BTC 1년 백테스트 K 스윕 결과표 출력. ✅
참고 결과(2026-04-13 BTC 365일): K=0.4 cum +9.60%, K=0.5 cum -2.59%

### M5 — 리스크 매니저 + 주문 실행기 `[x]`
실거래의 "안전판" 레이어.

- [x] `risk/manager.py` — `Decision`/`Action`/`RiskContext` + kill-switch/일일손실/손절/최소주문 게이트
- [x] `executor/order.py` — `Decision` 받아 paper/live 분기, UUID 멱등키, store 기록
- [x] `executor/store.py` — JSON 원자적 저장(임시파일+os.replace), `Position`/`OrderRecord` 복원
- [x] 페이퍼 모드 디폴트, live는 `OrderExecutor(..., live=True)` 명시 + 인증 클라이언트 강제
- [x] 단위·통합 테스트 27건 (RiskManager 12 + Store 5 + Executor 10)

**완료 기준**: `pytest` 76/76 통과, 모킹된 거래소로 BUY→SELL 1사이클 페이퍼 성공, 손익 누적 정확. ✅

### M6 — 스케줄러 + 엔트리포인트 통합 `[x]`
- [x] `bot.py` — `TradingBot` 오케스트레이터: tick / daily_reset / force_exit_if_holding
- [x] `main.py` — 부품 조립, `BlockingScheduler`(KST), `--once` 디버그 옵션, `--live` 강제 플래그
- [x] APScheduler 잡: tick(IntervalTrigger), daily_reset(09:00 KST cron), force_exit(08:55 KST cron)
- [x] SIGINT/SIGTERM 핸들러로 우아한 종료, store는 매 tick마다 영속화되어 재시작 복구 자동
- [x] 텔레그램: 시작/종료/매수/매도/일일리셋/에러 알림. 토큰 없으면 no-op
- [x] 단위 테스트 10건 (TradingBot tick/daily_reset/force_exit + paper 잔고 분기 + 손절 우선)

**완료 기준**: `pytest` 86/86 통과, `python -m auto_coin.main --once` 실제 BTC 시세로 1 tick 무오류 실행. ✅

### M7 — 페이퍼 트레이딩 운영 인프라 `[~]`
- [x] `reporter.py` — 24시간 주문/사이클/승률/PnL/포지션 리포트 생성
- [x] `TradingBot.daily_report()` + 스케줄러 08:58 KST cron 등록
- [x] 체결 시뮬레이션: paper 모드가 현재가 즉시 체결 + `daily_pnl_ratio` 누적 (M5에서 완료)
- [ ] **운영**: 페이퍼 모드로 1주+ 상주하며 로그/알림/슬리피지 관찰 (사용자 태스크)

**완료 기준(코드)**: `pytest` 94/94 통과. 리포트가 오래된(>24h) 주문을 스킵하고, 매수/매도 페어링으로 승률을 정확히 산출. ✅
**완료 기준(운영)**: 1주+ 무중단 실행, 일일 리포트 정상 수신.

### M7b — 텔레그램 모니터링 강화 `[x]` (최우선 완료)
봇이 조용히 죽는 일이 없도록 알림 커버리지를 올린다.

- [x] `TelegramNotifier.check()` — `getMe`로 토큰 유효성 확인, `BotInfo` 반환
- [x] `TelegramNotifier.find_chat_ids()` — `getUpdates`에서 1:1/채널/그룹 chat_id 추출
- [x] Markdown parse_mode 기본 적용, 400 응답 시 plain 자동 폴백
- [x] `python -m auto_coin.notifier` CLI: `--check` / `--find-chat-id` / `--send TEXT`
- [x] `HEARTBEAT_INTERVAL_HOURS` + 스케줄러 IntervalTrigger heartbeat 잡
- [x] `TradingBot.tick`을 `_tick_impl` 래핑 — 예상 외 예외도 텔레그램 크래시 알림
- [x] README 봇 설정 가이드 (@BotFather → 토큰 → chat_id 찾기)

**완료 기준**: `pytest` 111/111 통과, `auto_coin.notifier --check`로 토큰 검증 가능, 크래시/heartbeat 테스트 포함. ✅

### M8 — 소액 실거래 (1주+) `[ ]`
- [ ] 10~30만 원으로 실전
- [ ] 체결 지연·슬리피지·API 에러 실측
- [ ] Kill-switch 동작 확인

### M9 — 확장 (선택) `[ ]`
- [ ] 전략 추가: MA 크로스, RSI, 볼린저밴드
- [ ] 간이 웹 대시보드 (FastAPI + Chart.js)

### M9a — 멀티 종목 포트폴리오 `[x]`
변동성 돌파 전략을 **여러 KRW 종목**에 동시 적용한다. 기존 단일 ticker 파이프라인을
ticker 순회로 리팩토링하되, 하위 호환(`TICKER` 단일 사용) 유지.

#### 설계 결정 (2026-04-13 합의)
- **자본 배분**: 균등 (`paper_initial_krw / MAX_CONCURRENT_POSITIONS`)
- **동시 보유 상한**: `MAX_CONCURRENT_POSITIONS` (기본 3)
- **진입 크기**: `MAX_POSITION_RATIO × paper_initial_krw` **고정** (= 초기 자본 기준)
  - live 모드는 같은 로직을 실제 KRW 잔고에 적용 (변경 없음)
- **시그널 우선순위**: `TICKERS` 콤마 순서. 앞 종목부터 진입 → 슬롯 소진되면 뒤 HOLD.
- **리스크**:
  - 종목별: 손절(-2%), 이중 진입 금지, 최소 주문(5,000 KRW) ← 기존 동일
  - 포트폴리오: 일일 손실(-3%) = **모든 종목 daily_pnl 합산**, kill-switch, 동시 보유 상한
- **청산(08:55)**: 보유 중인 **모든** 종목 일괄 매도
- **일일 리셋(09:00)**: 모든 종목 store의 `daily_pnl_ratio = 0`
- **일일 리포트(08:58)**: 종목별 cycle 집계 + 포트폴리오 합계

#### 상태 저장
- `state/{ticker}.json` 구조 그대로 유지 (ticker별 독립 `OrderStore`).
- 포트폴리오 공용 상태는 별도 파일 불필요 — 모든 store의 `daily_pnl_ratio`를 합산해 산출.

#### 하위 마일스톤
- **M9a.1** — Settings: `TICKERS` 콤마 필드, `MAX_CONCURRENT_POSITIONS`, `portfolio_ticker_list` 프로퍼티 (비어있으면 `TICKER` 하나로 폴백). 테스트 포함.
- **M9a.2** — `RiskManager`: `portfolio_open_positions` / `portfolio_max_positions` / `portfolio_daily_pnl` 필드를 `RiskContext`에 추가, BUY 시 동시 보유 상한 체크, 일일 손실 기준을 포트폴리오 합계로.
- **M9a.3** — `TradingBot`: ticker별 `OrderStore`/`OrderExecutor` dict 보관, `_tick_impl`에서 TICKERS 순회, 진입 슬롯 카운팅으로 뒤 종목 차단. 진입 크기는 `paper_initial_krw × max_position_ratio` 고정.
- **M9a.4** — `force_exit_if_holding`·`daily_reset`·`heartbeat`·`daily_report`를 포트폴리오 전체 순회로 재구성. watch는 그대로(이미 다중 ticker).
- **M9a.5** — `main.py` 배선 수정, README 업데이트, 전체 테스트·커밋·푸시.

**완료 기준**: `TICKERS=KRW-BTC,KRW-ETH,KRW-XRP` 설정 시 3종목 독립 포지션 관리,
동시 보유 ≤ `MAX_CONCURRENT_POSITIONS`, 테스트 전체 통과.

### 부록 — 저가 종목 가격 포매팅 `[x]`
PEPE/DRIFT처럼 단위가 작은 종목을 `:.0f`로 찍으면 소수점 변화를 못 본다.
- [x] `auto_coin/formatting.py::format_price(value)` — 크기에 따라 소수점 자릿수 자동 선택
- [x] `bot.watch/heartbeat/tick` 알림, `executor.order` 로그, `reporter` 포지션 표기 전면 적용
- [x] 테스트 26건 (범위 매트릭스 + 방어적 None/NaN/inf 처리)

### 부록 — USER_GUIDE.md 작성 `[x]`
일상 운영(종목 변경, 투자 금액 조정, 실행/종료/재시작, 텔레그램, 백테스트, 트러블슈팅)을
한 곳에 정리한 매뉴얼 추가. README는 개요/빠른시작 중심으로 축약.

---

## 6. 보안 · 운영 체크리스트

- [ ] API Secret은 `.env`에만 저장, 커밋 금지
- [ ] 출금 권한 비활성 API 키만 사용
- [ ] IP 화이트리스트 설정
- [ ] 모든 주문에 UUID 멱등키
- [ ] 예외 발생 시 텔레그램 즉시 알림
- [ ] 일일 손익/체결 리포트 자동 발송
- [ ] 서버 재시작 시 미체결 주문 복구 로직
- [ ] 실거래 기본값 금지, 명시적 플래그로만 활성화

---

## 7. 참고 자료

- [Upbit Open API — 인증](https://global-docs.upbit.com/reference/auth)
- [sharebook-kr/pyupbit](https://github.com/sharebook-kr/pyupbit)
- [파이썬 비트코인 자동매매 (위키독스)](https://wikidocs.net/book/1665)
- [youtube-jocoding/pyupbit-autotrade](https://github.com/youtube-jocoding/pyupbit-autotrade)
- [hyeon9698/upbit_bot — 변동성 돌파 예제](https://github.com/hyeon9698/upbit_bot)
- [암호화폐 자동매매를 위한 파이썬과 CCXT](https://wikidocs.net/179292)

---

## 8. 면책

암호화폐 자동매매는 **원금 손실 위험**이 크다. 본 계획서는 학습/실험용이며 투자 권유가 아니다. 반드시 백테스트 → 페이퍼 → 소액 순서로 검증하고, 잃어도 되는 금액만 사용한다.
