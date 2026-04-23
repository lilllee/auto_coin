# auto_coin minute30 + 멀티타임프레임 확장 작업 기록

## 작업 시작 시각
2026-04-23

## 완료된 작업

### P1-1: candles 계층 - minute30 지원

**변경 파일**: `src/auto_coin/data/candles.py`

1. **interval alias 정규화** (line 11-24)
   - `_CANDLE_INTERVAL_ALIASES` 에 `minute30`, `30m`, `30min` 추가
   - `_CANDLE_INTERVAL_SECONDS` 에 `minute30: 1800` 추가

2. **history_days_to_candles** docstring 업데이트
   - minute30: N일 -> N*48 candles 설명 추가

3. **project_higher_timeframe_features** docstring 일반화
   - daily→minute60, daily→minute30, 1H→30m 모두 지원 가능하도록 문서화

4. **project_features** 함수 추가 (새 헬퍼)
   - 멀티 타임프레임 일반화 projection helper
   - source_interval vs target_interval 비교 후 ffill/bfill 선택
   - daily→1H, daily→30m, 1H→30m 모두 처리 가능

5. **enrich_regime_reclaim_30m** 함수 추가 (새 enrich 함수)
   - daily regime_df → 30m 인덱스 투영
   - hourly_setup_df → 30m 인덱스 투영
   - 30m trigger features (dip, RSI, reclaim EMA, reversion SMA, ATR)
   - 사용 패턴 주석 포함 (next-turn 전략 구현자용)

6. **enrich_for_strategy** dispatcher 업데이트
   - `regime_reclaim_30m` 전략명 추가
   - `hourly_setup_df` 파라미터 추가

7. **recommended_history_days** 업데이트
   - `regime_reclaim_30m` 케이스 추가

8. **fetch_candles** 업데이트
   - `regime_reclaim_30m` 전략 시 daily + 1H + 30m 자동 fetch
   - 기존 regime 전략(rcdb, rcdb_v2, regime_reclaim_1h) 경로 변경 없음

---

### P1-2: backtest 계층 - minute30 지원

**변경 파일**: `src/auto_coin/backtest/runner.py`

1. **CLI help text 업데이트** (line 560-561)
   - `"day | minute60 | minute30 (aliases: 1h, 60m, hourly, 30m, 30min)"`

**구조적 호환성**:
- `backtest()` 함수는 이미 `normalize_candle_interval(interval)` + `candle_bar_seconds(interval)` 사용
- `bar_seconds`, `hold_bars` 메타데이터가 모든 interval에서 자연스럽게 동작
- time_exit 등이 "bar 기준"으로 안전하게 해석됨
- **추가 코드 변경 불필요** (기존 구조가 이미 interval-aware 함)

---

### P1-3: walk_forward 계층 - minute30 지원

**변경 파일**: `src/auto_coin/backtest/walk_forward.py`

1. **CLI help text 업데이트** (line 468-469)
   - `"day | minute60 | minute30 (aliases: 1h, 60m, hourly, 30m, 30min)"`

2. **_enrich 함수 업데이트**
   - `hourly_setup_df` 파라미터 추가
   - `enrich_for_strategy` 에 전달

3. **walk_forward 함수 시그니처 업데이트**
   - `hourly_setup_df: pd.DataFrame | None = None` 파라미터 추가

4. **walk_forward CLI 업데이트**
   - `regime_reclaim_30m` 전략 시 daily + 1H 자동 fetch
   - `hourly_setup_df` 를 walk_forward 에 전달

**구조적 호환성**:
- `history_days_to_candles()` 가 이미 interval-aware
- window candle count 계산이 minute30 에서도 자연스럽게 동작
- regime_df 전달 경로 유지

---

### P1-4: 멀티타임프레임 projection 정리

**변경 파일**: `src/auto_coin/data/candles.py`

**project_features 함수** (새로 추가)
```python
def project_features(
    source_df,
    target_index,
    *,
    source_interval,
    target_interval,
    columns=None,
) -> pd.DataFrame:
```

지원 패턴:
- source > target: ffill (daily→1H, daily→30m, 1H→30m)
- source == target: 단순 reindex
- source < target: bfill (30m→1H, 드묾)

**enrich_regime_reclaim_30m 함수** (새로 추가)
- daily regime → 30m 투영
- 1H setup → 30m 투영
- 30m trigger features 자체 계산
- 사용 패턴 주석 포함

---

## 아직 안 한 작업

### 1. 테스트 추가 (중요)
다음 테스트들을 추가해야 함:

**tests/test_candles.py**:
- `test_normalize_candle_interval_minute30` - minute30, 30m, 30min alias
- `test_candle_bar_seconds_minute30` - 1800 반환
- `test_history_days_to_candles_minute30` - 10일 = 480 candles
- `test_fetch_candles_supports_minute30_interval` - mocking으로 fetch
- `test_project_features_daily_to_30m` - daily → 30m projection
- `test_project_features_1h_to_30m` - 1H → 30m projection
- `test_enrich_regime_reclaim_30m_basic` - 기본 enrich
- `test_enrich_regime_reclaim_30m_with_daily_regime` - daily regime_df 포함
- `test_enrich_regime_reclaim_30m_with_hourly_setup` - 1H setup_df 포함
- `test_enrich_for_strategy_regime_reclaim_30m` - dispatcher 라우팅
- `test_recommended_history_days_regime_reclaim_30m` - 권장 히스토리

**tests/test_backtest.py**:
- `test_backtest_supports_minute30_interval` - minute30 backtest crash-free

**tests/test_walk_forward.py**:
- `test_walk_forward_supports_minute30_interval` - minute30 WF
- `test_walk_forward_regime_reclaim_30m` - multi-TF WF

### 2. 전체 테스트 실행
```bash
pytest tests/ -v
ruff check src auto_coin tests
```

### 3. 기존 경로 회귀 확인
- day 경로: 기존 테스트 모두 통과해야 함
- minute60 경로: 기존 테스트 모두 통과해야 함
- regime_reclaim_1h: 기존 테스트 모두 통과해야 함

---

## 구조 요약: day / minute60 / minute30 공존

```
normalize_candle_interval()
  ├── "day", "daily", "1d", "d"         → "day"        (86400s)
  ├── "minute60", "60m", "1h", "hour"   → "minute60"   (3600s)
  └── "minute30", "30m", "30min"        → "minute30"   (1800s)

history_days_to_candles(days, interval)
  ├── day:        days * 1
  ├── minute60:   days * 24
  └── minute30:   days * 48

project_higher_timeframe_features(higher_df, lower_index)
  → ffill 로 상위 feature 를 하위 인덱스에 투영

project_features(source_df, target_index, source_interval, target_interval)
  → ffill/bfill 선택적 멀티-TF projection
```

---

## 다음 턴에 할 일 (P2)

1. 테스트 추가 및 전체 테스트 통과 확인
2. `regime_reclaim_30m` 전략 구현 (strategy/)
   - Daily regime ON 확인
   - 1H pullback/oversold setup 확인
   - 30m reclaim trigger 확인 시 BUY
   - Exit: 30m reversion / trailing / regime_off / time_exit
3. walk_forward 로 전략 검증

---

## 작업 중 참고사항

- SSE 타임아웃으로 인해 긴 파일 읽기가 어려움
- `candles.py` 는 총 1090 라인 정도로 커짐
- 기존 day/minute60 경로는 절대 변경하지 않음
- `regime_reclaim_30m` 은 새로운 전략명으로 기존 코드와 분리
