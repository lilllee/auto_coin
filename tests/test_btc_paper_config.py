"""BTC-only paper config validation.

PRD: ``.omx/plans/prd-vwap-ema-pullback-btc-paper-2026-05-04.md``
Test spec: ``.omx/plans/test-spec-vwap-ema-pullback-btc-paper-2026-05-04.md`` §3 / §6.
Runbook: ``docs/v2/vwap-ema-pullback-btc-paper-runbook.md``

본 테스트는 paper 운영 doc 의 setting 매트릭스가 실제 코드와 일관되는지를 자동
검증한다. 운영자가 doc 만 보고 .env / UI 입력 시 typo / 잘못된 조합 / 누락된
안전장치를 자동 검출.

본 테스트는 strategy / enricher / runner / KPI / ledger 어떤 코드도 호출하지
않으며 backtest 도 실행하지 않는다 — 순수한 config schema + parsing 검증.
"""

from __future__ import annotations

import json

import pytest

from auto_coin.config import Mode, Settings
from auto_coin.strategy import (
    EXPERIMENTAL_STRATEGIES,
    STRATEGY_REGISTRY,
    create_strategy,
)
from auto_coin.strategy.vwap_ema_pullback import VwapEmaPullbackStrategy

# Runbook §1.1 — paper run 환경변수 매트릭스
PAPER_ENV_BASE: dict[str, object] = {
    "mode": Mode.PAPER,
    "live_trading": False,
    "kill_switch": False,
    "strategy_name": "vwap_ema_pullback",
    "tickers": "KRW-BTC",
    "max_concurrent_positions": 1,
    "max_position_ratio": 0.50,
    "cooldown_minutes": 120,
    "daily_loss_limit": -0.03,  # -3% as decimal
    "check_interval_seconds": 3600,
    "paper_initial_krw": 1_000_000,
    "active_strategy_group": "vwap_ema_pullback_btc_paper",
}

# Runbook §1.2 — 3 candidate STRATEGY_PARAMS_JSON
VOL_W30_PARAMS = {
    "exit_mode": "atr_buffer_exit",
    "exit_atr_multiplier": 0.3,
    "min_ema_slope_ratio": 0.002,
    "max_vwap_cross_count": 2,
    "ema_touch_tolerance": 0.003,
    "volume_filter_mode": "ge_1_2",
    "volume_mean_window": 30,
    "htf_trend_filter_mode": "off",
    "rsi_filter_mode": "off",
    "daily_regime_filter_mode": "off",
}

VOL_1_4_PARAMS = {
    **VOL_W30_PARAMS,
    "volume_filter_mode": "ge_1_4",
    "volume_mean_window": 20,
}

ANCHOR_PARAMS = {
    **VOL_W30_PARAMS,
    "volume_filter_mode": "ge_1_2",
    "volume_mean_window": 20,
}


# ---------------------------------------------------------------------------
# §3.1-§3.5 Settings load / propagation
# ---------------------------------------------------------------------------

def test_btc_paper_config_loads_valid_settings():
    """Runbook §1.1 의 모든 setting 이 ValidationError 없이 로드."""
    s = Settings(
        _env_file=None,
        strategy_params_json=json.dumps(VOL_W30_PARAMS),
        **PAPER_ENV_BASE,
    )
    assert s.mode is Mode.PAPER
    assert s.live_trading is False
    assert s.kill_switch is False
    assert s.strategy_name == "vwap_ema_pullback"
    assert s.tickers == "KRW-BTC"
    assert s.portfolio_ticker_list == ["KRW-BTC"]
    assert s.max_concurrent_positions == 1
    assert s.max_position_ratio == 0.50
    assert s.cooldown_minutes == 120
    assert s.daily_loss_limit == -0.03
    assert s.check_interval_seconds == 3600
    assert s.paper_initial_krw == 1_000_000
    assert s.active_strategy_group == "vwap_ema_pullback_btc_paper"
    assert s.is_live is False  # paper 모드 → live 비활성


def test_btc_paper_strategy_params_json_parses_for_vol_w30():
    """Runbook §1.2 vol_w30 JSON → 유효 strategy 인스턴스."""
    params_json = json.dumps(VOL_W30_PARAMS)
    params = json.loads(params_json)
    strategy = create_strategy("vwap_ema_pullback", params)

    assert isinstance(strategy, VwapEmaPullbackStrategy)
    assert strategy.exit_mode == "atr_buffer_exit"
    assert strategy.exit_atr_multiplier == 0.3
    assert strategy.min_ema_slope_ratio == 0.002
    assert strategy.max_vwap_cross_count == 2
    assert strategy.ema_touch_tolerance == 0.003
    assert strategy.volume_filter_mode == "ge_1_2"
    assert strategy.volume_mean_window == 30
    assert strategy.htf_trend_filter_mode == "off"
    assert strategy.rsi_filter_mode == "off"
    assert strategy.daily_regime_filter_mode == "off"


def test_btc_paper_strategy_params_json_parses_for_vol_1_4():
    """Runbook §1.2 vol_1_4 JSON (alternative)."""
    strategy = create_strategy("vwap_ema_pullback", VOL_1_4_PARAMS)
    assert strategy.volume_filter_mode == "ge_1_4"
    assert strategy.volume_mean_window == 20


def test_btc_paper_strategy_params_json_parses_for_anchor():
    """Runbook §1.2 anchor (= P2.5 baseline) JSON (regression fallback)."""
    strategy = create_strategy("vwap_ema_pullback", ANCHOR_PARAMS)
    assert strategy.volume_filter_mode == "ge_1_2"
    assert strategy.volume_mean_window == 20


def test_btc_paper_active_strategy_group_propagates_to_settings():
    """active_strategy_group 이 Settings 필드로 정확히 보존됨 (KPI 분리 핵심)."""
    s = Settings(
        _env_file=None,
        active_strategy_group="vwap_ema_pullback_btc_paper",
    )
    assert s.active_strategy_group == "vwap_ema_pullback_btc_paper"


# ---------------------------------------------------------------------------
# §3.6-§3.8 live_active 안전장치 — paper 강제, kill_switch 강제
# ---------------------------------------------------------------------------

def test_btc_paper_mode_disables_live_active():
    """mode=paper → live_active 자동 False (3중 검증의 첫 단계)."""
    s = Settings(_env_file=None, mode=Mode.PAPER, live_trading=False, kill_switch=False)
    assert s.is_live is False


def test_btc_paper_mode_blocks_live_even_if_live_trading_true():
    """mode=paper 면 live_trading=True 라도 live_active=False — 안전장치."""
    s = Settings(_env_file=None, mode=Mode.PAPER, live_trading=True, kill_switch=False)
    assert s.is_live is False


def test_kill_switch_blocks_live_even_when_live_mode_active():
    """kill_switch=True 면 mode=live + live_trading=True 라도 live_active=False."""
    s = Settings(_env_file=None, mode=Mode.LIVE, live_trading=True, kill_switch=True)
    assert s.is_live is False


def test_live_active_only_true_when_all_three_conditions():
    """live_active 의 정확한 조건 (참고) — 본 runbook 에서는 절대 발생하면 안 됨."""
    s_live = Settings(
        _env_file=None, mode=Mode.LIVE, live_trading=True, kill_switch=False,
    )
    assert s_live.is_live is True  # 조건 만족 (다만 paper runbook 에서는 발생 금지)
    s_paper = Settings(
        _env_file=None, mode=Mode.PAPER, live_trading=True, kill_switch=False,
    )
    assert s_paper.is_live is False  # paper runbook 의 정상 상태


# ---------------------------------------------------------------------------
# §3.9-§3.10 EXPERIMENTAL guard / time_exit guard
# ---------------------------------------------------------------------------

def test_vwap_ema_pullback_remains_in_experimental_strategies():
    """본 runbook 이 EXPERIMENTAL 가드를 제거하지 않음을 강제."""
    assert "vwap_ema_pullback" in EXPERIMENTAL_STRATEGIES


def test_vwap_ema_pullback_in_strategy_registry():
    """registry 등록 자체는 유지."""
    assert "vwap_ema_pullback" in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY["vwap_ema_pullback"] is VwapEmaPullbackStrategy


def test_btc_paper_vwap_ema_pullback_time_exit_disabled():
    """vwap_ema_pullback 은 강제 청산 없음 (P2 결정 보존) — paper 에서도 불변."""
    s = Settings(_env_file=None, strategy_name="vwap_ema_pullback")
    assert s.time_exit_enabled is False


# ---------------------------------------------------------------------------
# Ticker whitelist 검증
# ---------------------------------------------------------------------------

def test_btc_paper_tickers_whitelist_only_krw_btc():
    """Runbook §1.1: TICKERS=KRW-BTC 단 1개. 다른 ticker 추가는 운영 절차 위반.

    `tickers` 는 comma-separated string. list 변환은 ``portfolio_ticker_list`` property.
    """
    s = Settings(
        _env_file=None,
        strategy_name="vwap_ema_pullback",
        tickers="KRW-BTC",
    )
    assert s.tickers == "KRW-BTC"
    assert s.portfolio_ticker_list == ["KRW-BTC"]
    assert len(s.portfolio_ticker_list) == 1


def test_btc_paper_tickers_whitelist_rejects_extra_tickers_at_list_level():
    """운영자가 실수로 multi-ticker 입력하면 portfolio_ticker_list 가 명확히 보여줌."""
    s = Settings(
        _env_file=None,
        strategy_name="vwap_ema_pullback",
        tickers="KRW-BTC,KRW-ETH",  # 운영 위반 시뮬레이션
    )
    # 본 PR 은 defensive guard 미구현 — 운영자가 이 list 길이로 확인해야 함.
    # runbook §2.2 의 체크리스트 "comma 추가 / 다른 ticker 0건" 가 해당.
    assert len(s.portfolio_ticker_list) == 2  # 운영 위반 자동 검출 가능


def test_btc_paper_max_concurrent_positions_one():
    """단일 ticker 환경 — 슬롯 1개만."""
    s = Settings(_env_file=None, max_concurrent_positions=1)
    assert s.max_concurrent_positions == 1


# ---------------------------------------------------------------------------
# Runbook 의 모든 candidate 가 P2.5 valid VOLUME_THRESHOLD_MAP 안에 있음
# ---------------------------------------------------------------------------

def test_runbook_candidates_use_valid_volume_modes():
    """Runbook §1.2 의 3 후보가 P2.5 _VALID_VOLUME_MODES 안의 mode 사용."""
    from auto_coin.strategy.vwap_ema_pullback import _VALID_VOLUME_MODES

    for params in (VOL_W30_PARAMS, VOL_1_4_PARAMS, ANCHOR_PARAMS):
        assert params["volume_filter_mode"] in _VALID_VOLUME_MODES


def test_runbook_candidates_share_same_exit_freq_anchor():
    """3 candidate 모두 P1 best (combined_atr) 의 exit/freq settings 공유."""
    for params in (VOL_W30_PARAMS, VOL_1_4_PARAMS, ANCHOR_PARAMS):
        assert params["exit_mode"] == "atr_buffer_exit"
        assert params["exit_atr_multiplier"] == 0.3
        assert params["min_ema_slope_ratio"] == 0.002
        assert params["max_vwap_cross_count"] == 2
        assert params["ema_touch_tolerance"] == 0.003


# ---------------------------------------------------------------------------
# Live 활성 config 가 runbook 에 포함되지 않음 — 부주의 검출
# ---------------------------------------------------------------------------

def test_runbook_paper_env_does_not_contain_live_settings():
    """PAPER_ENV_BASE 에 mode=live / live_trading=true 가 들어있지 않음."""
    assert PAPER_ENV_BASE["mode"] is Mode.PAPER
    assert PAPER_ENV_BASE["live_trading"] is False
    # 운영자 부주의 검증: kill_switch 도 False (시작 시) 명시
    assert PAPER_ENV_BASE["kill_switch"] is False


def test_runbook_candidates_do_not_enable_volume_profile():
    """3 candidate 모두 Volume Profile Phase 2 비활성 — PRD §1 Out of scope 강제."""
    for params in (VOL_W30_PARAMS, VOL_1_4_PARAMS, ANCHOR_PARAMS):
        # use_volume_profile 명시 안 한 candidate 가 default False 인지 검증.
        strategy = create_strategy("vwap_ema_pullback", params)
        assert strategy.use_volume_profile is False


# ---------------------------------------------------------------------------
# Settings.strategy_params_json round-trip
# ---------------------------------------------------------------------------

def test_btc_paper_strategy_params_json_round_trip():
    """STRATEGY_PARAMS_JSON env-string round-trip — 따옴표 / escape 안전."""
    params_json = json.dumps(VOL_W30_PARAMS)
    s = Settings(_env_file=None, strategy_params_json=params_json)
    parsed = json.loads(s.strategy_params_json)
    assert parsed["volume_filter_mode"] == "ge_1_2"
    assert parsed["volume_mean_window"] == 30


@pytest.mark.parametrize("invalid_json", [
    '{"volume_filter_mode": "ge_999"}',
    '{"volume_filter_mode": "ge_2_0"}',
])
def test_btc_paper_invalid_volume_mode_rejected_by_strategy(invalid_json: str):
    """잘못된 volume_filter_mode 는 strategy 인스턴스화 시점에 거부."""
    params = json.loads(invalid_json)
    with pytest.raises(ValueError, match="volume_filter_mode"):
        create_strategy("vwap_ema_pullback", params)
