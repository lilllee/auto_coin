"""P2.5 runner verdict + smoke + grid composition + per-ticker rec tests.

Test spec: ``.omx/plans/test-spec-vwap-ema-pullback-p25-2026-05-04.md`` §3-§6.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from scripts.vwap_ema_pullback_p1_runner import CellMetrics
from scripts.vwap_ema_pullback_p2_runner import (
    P2Candidate,
    derive_verdict_p2,
)
from scripts.vwap_ema_pullback_p25_runner import (
    P25_ANCHOR_ID,
    build_p25_candidate_grid,
    compute_anchor_diff_p25,
    derive_per_ticker_paper_recommendation,
    main,
    render_md_p25,
    run_p25,
)

# ---------------------------------------------------------------------------
# Helpers (mirror P2 runner test helpers)
# ---------------------------------------------------------------------------

def _cell(
    *,
    candidate_id: str = "x",
    ticker: str = "KRW-BTC",
    period: str = "1y",
    trades: int = 80,
    total_return: float = 0.05,
    bh_return: float = -0.10,
    mdd: float = -0.15,
    bh_mdd: float = -0.20,
    win_rate: float = 0.30,
    profit_factor: float = 1.10,
    avg_hold_bars: float = 6.0,
    avg_profit: float = 0.01,
    avg_loss: float = -0.005,
    expectancy: float = 0.002,
    time_exit_share: float = 0.0,
) -> CellMetrics:
    return CellMetrics(
        candidate_id=candidate_id, ticker=ticker, interval="1h", period=period,
        candles=1000, trades=trades,
        total_return=total_return, bh_return=bh_return,
        mdd=mdd, bh_mdd=bh_mdd,
        win_rate=win_rate, profit_factor=profit_factor,
        avg_hold_bars=avg_hold_bars, avg_profit=avg_profit, avg_loss=avg_loss,
        expectancy=expectancy, time_exit_share=time_exit_share,
    )


def _build_rollup(
    candidate_specs: dict[str, dict[tuple[str, str], dict[str, Any]]],
    *,
    interval: str = "1h",
) -> dict:
    rollup: dict = {interval: {}}
    for cid, cells in candidate_specs.items():
        for (ticker, period), overrides in cells.items():
            cell = _cell(candidate_id=cid, ticker=ticker, period=period, **overrides)
            (rollup[interval]
                .setdefault(ticker, {})
                .setdefault(period, {}))[cid] = cell
    return rollup


# ---------------------------------------------------------------------------
# §3 — Grid composition
# ---------------------------------------------------------------------------

def test_p25_grid_has_12_entries():
    grid = build_p25_candidate_grid()
    assert len(grid) == 12
    ids = [c.id for c in grid]
    assert len(set(ids)) == 12  # unique
    expected_ids = {
        "anchor", "vol_1_1", "vol_1_3", "vol_1_4",
        "vol_w10", "vol_w30", "vol_w40",
        "vol_1_3_w30", "vol_1_2_htf_fs", "vol_1_3_htf_fs",
        "htf_fs_only", "htf_close_only",
    }
    assert set(ids) == expected_ids


def test_p25_anchor_matches_p2_c_vol_1_2():
    grid = build_p25_candidate_grid()
    anchor = next(c for c in grid if c.id == "anchor")
    assert anchor.exit_mode == "atr_buffer_exit"
    assert anchor.exit_atr_multiplier == 0.3
    assert anchor.min_ema_slope_ratio == 0.002
    assert anchor.max_vwap_cross_count == 2
    assert anchor.cooldown_bars == 2
    assert anchor.volume_filter_mode == "ge_1_2"
    assert anchor.volume_mean_window == 20
    assert anchor.htf_trend_filter_mode == "off"
    assert anchor.rsi_filter_mode == "off"
    assert anchor.daily_regime_filter_mode == "off"


def test_p25_vol_w10_uses_window_10():
    grid = build_p25_candidate_grid()
    cand = next(c for c in grid if c.id == "vol_w10")
    assert cand.volume_filter_mode == "ge_1_2"
    assert cand.volume_mean_window == 10


def test_p25_vol_1_3_w30_combines_both():
    grid = build_p25_candidate_grid()
    cand = next(c for c in grid if c.id == "vol_1_3_w30")
    assert cand.volume_filter_mode == "ge_1_3"
    assert cand.volume_mean_window == 30


def test_p25_vol_1_2_htf_fs_combines_axes():
    grid = build_p25_candidate_grid()
    cand = next(c for c in grid if c.id == "vol_1_2_htf_fs")
    assert cand.volume_filter_mode == "ge_1_2"
    assert cand.htf_trend_filter_mode == "htf_ema_fast_slow"


def test_p25_htf_baselines_for_sanity():
    grid = build_p25_candidate_grid()
    htf_fs = next(c for c in grid if c.id == "htf_fs_only")
    assert htf_fs.volume_filter_mode == "off"
    assert htf_fs.htf_trend_filter_mode == "htf_ema_fast_slow"
    htf_close = next(c for c in grid if c.id == "htf_close_only")
    assert htf_close.volume_filter_mode == "off"
    assert htf_close.htf_trend_filter_mode == "htf_close_above_ema"


def test_p25_grid_enrich_keys_dedupe():
    keys = {c.enrich_key() for c in build_p25_candidate_grid()}
    # 12 candidates, 4 distinct windows + HTF on/off → 일부 dedupe
    assert 4 <= len(keys) <= 12


# ---------------------------------------------------------------------------
# §4 — Verdict logic compat with P2
# ---------------------------------------------------------------------------

def test_p25_uses_p2_verdict_function():
    """P2.5 runner 가 P2 derive_verdict_p2 그대로 import 사용."""
    from scripts.vwap_ema_pullback_p2_runner import derive_verdict_p2 as orig
    from scripts.vwap_ema_pullback_p25_runner import derive_verdict_p2 as imported
    assert imported is orig


def test_p25_verdict_pass_when_all_gates_pass():
    pass_cell = {"trades": 80, "total_return": 0.05, "bh_return": -0.10,
                 "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                 "profit_factor": 1.10, "avg_hold_bars": 6.0, "expectancy": 0.002}
    rollup = _build_rollup({
        "candA": {
            ("KRW-BTC", "1y"): pass_cell, ("KRW-BTC", "6m"): pass_cell,
            ("KRW-ETH", "1y"): pass_cell, ("KRW-ETH", "6m"): pass_cell,
        },
    })
    verdict, _ = derive_verdict_p2(rollup)
    assert verdict == "PASS"


def test_p25_verdict_hold_when_btc_passes_eth_fails():
    """P2 의 C_vol_1_2 패턴 — BTC 4/4, ETH 부분 fail → HOLD."""
    pass_cell = {"trades": 80, "total_return": 0.05, "bh_return": -0.10,
                 "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                 "profit_factor": 1.10, "avg_hold_bars": 6.0, "expectancy": 0.002}
    eth_1y_fail = {**pass_cell, "total_return": -0.025, "bh_return": 0.353}
    eth_6m_fail = {**pass_cell, "expectancy": -0.0004}
    rollup = _build_rollup({
        "candA": {
            ("KRW-BTC", "1y"): pass_cell, ("KRW-BTC", "6m"): pass_cell,
            ("KRW-ETH", "1y"): eth_1y_fail, ("KRW-ETH", "6m"): eth_6m_fail,
        },
    })
    verdict, _ = derive_verdict_p2(rollup)
    assert verdict == "HOLD"


# ---------------------------------------------------------------------------
# §5 — Per-ticker paper recommendation
# ---------------------------------------------------------------------------

def test_per_ticker_rec_recommend_btc_only_when_btc_pass_eth_partial():
    """BTC 4/4 perf_gates_pass + ETH cell ret 이 anchor 보다 개선 → BTC-only paper."""
    pass_cell = {"trades": 80, "total_return": 0.05, "bh_return": -0.10,
                 "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                 "profit_factor": 1.10, "avg_hold_bars": 6.0, "expectancy": 0.002}
    anchor_eth_1y = {**pass_cell, "total_return": -0.05, "bh_return": 0.353}
    anchor_eth_6m = {**pass_cell, "expectancy": -0.0004}
    cand_eth_1y = {**pass_cell, "total_return": +0.05, "bh_return": 0.353}  # improved over anchor
    cand_eth_6m = {**pass_cell, "expectancy": -0.0004}

    rollup = _build_rollup({
        P25_ANCHOR_ID: {
            ("KRW-BTC", "1y"): pass_cell, ("KRW-BTC", "6m"): pass_cell,
            ("KRW-ETH", "1y"): anchor_eth_1y, ("KRW-ETH", "6m"): anchor_eth_6m,
        },
        "candA": {
            ("KRW-BTC", "1y"): pass_cell, ("KRW-BTC", "6m"): pass_cell,
            ("KRW-ETH", "1y"): cand_eth_1y, ("KRW-ETH", "6m"): cand_eth_6m,
        },
    })
    rec = derive_per_ticker_paper_recommendation(rollup, {}, "HOLD", [])
    assert rec["BTC"] == "recommend_btc_only_paper"
    assert rec["ETH"] == "hold"


def test_per_ticker_rec_full_recommend_when_pass_strong():
    diffs = {"candA": {
        "BTC_1y_ret_diff_pp": 5.0, "BTC_6m_ret_diff_pp": 5.0,
        "ETH_1y_ret_diff_pp": 5.0, "ETH_6m_ret_diff_pp": 5.0,
    }}
    rec = derive_per_ticker_paper_recommendation({}, diffs, "PASS", ["candA"])
    assert rec["BTC"] == "recommend_separate_pr"
    assert rec["ETH"] == "recommend_separate_pr"


def test_per_ticker_rec_hold_when_pass_marginal():
    diffs = {"candA": {
        "BTC_1y_ret_diff_pp": 1.0, "BTC_6m_ret_diff_pp": 1.0,
        "ETH_1y_ret_diff_pp": 1.0, "ETH_6m_ret_diff_pp": 1.0,
    }}
    rec = derive_per_ticker_paper_recommendation({}, diffs, "PASS", ["candA"])
    assert rec["BTC"] == "hold"
    assert rec["ETH"] == "hold"


def test_per_ticker_rec_consider_retire_when_revise():
    rec = derive_per_ticker_paper_recommendation({}, {}, "REVISE", [])
    assert rec["BTC"] == "consider_retire"
    assert rec["ETH"] == "consider_retire"


def test_per_ticker_rec_retire_when_stop():
    rec = derive_per_ticker_paper_recommendation({}, {}, "STOP", [])
    assert rec["BTC"] == "retire"
    assert rec["ETH"] == "retire"


def test_per_ticker_rec_btc_only_requires_btc_4_4_perf():
    """BTC 4/4 못 채우면 (예: BTC 6m perf_fail) BTC-only 권고 금지."""
    pass_cell = {"trades": 80, "total_return": 0.05, "bh_return": -0.10,
                 "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                 "profit_factor": 1.10, "avg_hold_bars": 6.0, "expectancy": 0.002}
    btc_6m_fail = {**pass_cell, "profit_factor": 0.5}  # PF below 0.85
    cand_eth_1y_improved = {**pass_cell, "total_return": +0.05, "bh_return": 0.353}

    rollup = _build_rollup({
        P25_ANCHOR_ID: {
            ("KRW-BTC", "1y"): pass_cell, ("KRW-BTC", "6m"): pass_cell,
            ("KRW-ETH", "1y"): {**pass_cell, "total_return": -0.05, "bh_return": 0.353},
            ("KRW-ETH", "6m"): pass_cell,
        },
        "candA": {
            ("KRW-BTC", "1y"): pass_cell, ("KRW-BTC", "6m"): btc_6m_fail,
            ("KRW-ETH", "1y"): cand_eth_1y_improved,
            ("KRW-ETH", "6m"): pass_cell,
        },
    })
    rec = derive_per_ticker_paper_recommendation(rollup, {}, "HOLD", [])
    assert rec["BTC"] != "recommend_btc_only_paper"


def test_per_ticker_rec_btc_only_requires_eth_meaningful_improvement():
    """BTC 4/4 통과해도 ETH 개선 신호 0 이면 hold."""
    pass_cell = {"trades": 80, "total_return": 0.05, "bh_return": -0.10,
                 "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                 "profit_factor": 1.10, "avg_hold_bars": 6.0, "expectancy": 0.002}
    anchor_eth = {**pass_cell, "total_return": -0.05, "bh_return": 0.353}

    rollup = _build_rollup({
        P25_ANCHOR_ID: {
            ("KRW-BTC", "1y"): pass_cell, ("KRW-BTC", "6m"): pass_cell,
            ("KRW-ETH", "1y"): anchor_eth, ("KRW-ETH", "6m"): anchor_eth,
        },
        "candA": {
            ("KRW-BTC", "1y"): pass_cell, ("KRW-BTC", "6m"): pass_cell,
            ("KRW-ETH", "1y"): {**anchor_eth, "total_return": -0.07},  # WORSE
            ("KRW-ETH", "6m"): {**anchor_eth, "total_return": -0.06},  # WORSE
        },
    })
    rec = derive_per_ticker_paper_recommendation(rollup, {}, "HOLD", [])
    # anchor 자체는 BTC 4/4 통과 — BTC-only 자기 자신 권고 가능 (PRD §6 정책).
    # candA 의 ETH 개선 신호 없음.
    # anchor 만 BTC-only 권고 자격 — ETH meaningful improvement = False.
    assert rec["BTC"] in {"recommend_btc_only_paper", "hold"}
    assert rec["ETH"] == "hold"


# ---------------------------------------------------------------------------
# §6 — Smoke / runner integration
# ---------------------------------------------------------------------------

def _synth_ohlcv(n: int, freq: str, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": rng.uniform(50, 150, n),
        },
        index=pd.date_range("2025-05-01", periods=n, freq=freq),
    )


def _fake_fetch_factory():
    def fake_fetch(ticker, interval, count, cache_dir, refresh=False):
        seed = hash(ticker) & 0xFFFF
        if interval == "minute60":
            return _synth_ohlcv(min(count, 600), "60min", seed=seed)
        if interval == "minute30":
            return _synth_ohlcv(min(count, 800), "30min", seed=seed)
        if interval == "minute240":
            return _synth_ohlcv(min(count, 200), "4h", seed=seed)
        if interval == "day":
            return _synth_ohlcv(min(count, 365), "D", seed=seed)
        return _synth_ohlcv(200, "60min", seed=seed)
    return fake_fetch


def test_p25_runner_outputs_expected_schema(tmp_path):
    fake_fetch = _fake_fetch_factory()
    grid = [
        P2Candidate(id=P25_ANCHOR_ID,
                    volume_filter_mode="ge_1_2", volume_mean_window=20),
        P2Candidate(id="vol_1_3",
                    volume_filter_mode="ge_1_3", volume_mean_window=20),
    ]
    result = run_p25(
        tickers=("KRW-BTC",),
        intervals=("1h",),
        periods=(("6m", 30),),
        cache_dir=tmp_path,
        candidate_grid=grid,
        fetch_fn=fake_fetch,
    )
    assert set(result.keys()) >= {
        "rollup", "verdict", "verdict_details",
        "anchor_id", "anchor_diff_pp",
        "paper_recommendation",
        "per_ticker_recommendation",
        "per_run", "candidate_grid_size",
    }
    assert result["candidate_grid_size"] == 2
    assert result["anchor_id"] == P25_ANCHOR_ID
    assert "BTC" in result["per_ticker_recommendation"]
    assert "ETH" in result["per_ticker_recommendation"]


def test_p25_runner_writes_json_and_md(tmp_path, monkeypatch):
    fake_fetch = _fake_fetch_factory()
    monkeypatch.setattr(
        "scripts.vwap_ema_pullback_p25_runner.fetch_ohlcv", fake_fetch,
    )
    out_json = tmp_path / "p25.json"
    out_md = tmp_path / "p25.md"

    small_grid = [
        P2Candidate(id=P25_ANCHOR_ID,
                    volume_filter_mode="ge_1_2", volume_mean_window=20),
        P2Candidate(id="vol_1_3",
                    volume_filter_mode="ge_1_3", volume_mean_window=20),
    ]
    monkeypatch.setattr(
        "scripts.vwap_ema_pullback_p25_runner.build_p25_candidate_grid",
        lambda: small_grid,
    )

    rc = main([
        "--tickers", "KRW-BTC,KRW-ETH",
        "--intervals", "1h",
        "--out", str(out_json),
        "--md-out", str(out_md),
        "--cache-dir", str(tmp_path / "cache"),
    ])
    assert rc == 0
    assert out_json.exists()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["verdict"] in {"PASS", "HOLD", "REVISE", "STOP"}
    assert payload["paper_recommendation"] in {"n/a", "hold", "recommend_separate_pr"}
    assert "BTC" in payload["per_ticker_recommendation"]
    assert "ETH" in payload["per_ticker_recommendation"]
    assert out_md.exists()
    md = out_md.read_text(encoding="utf-8")
    assert "## Verdict:" in md
    assert "## ADR" in md
    assert "Per-ticker paper recommendation" in md


def test_p25_runner_does_not_mutate_strategy_registry(tmp_path):
    from auto_coin.strategy import EXPERIMENTAL_STRATEGIES, STRATEGY_REGISTRY

    before_exp = set(EXPERIMENTAL_STRATEGIES)
    before_reg = set(STRATEGY_REGISTRY)

    fake_fetch = _fake_fetch_factory()
    grid = [P2Candidate(id=P25_ANCHOR_ID,
                        volume_filter_mode="ge_1_2", volume_mean_window=20)]
    run_p25(
        tickers=("KRW-BTC",),
        intervals=("1h",),
        periods=(("6m", 30),),
        cache_dir=tmp_path,
        candidate_grid=grid,
        fetch_fn=fake_fetch,
    )

    assert set(EXPERIMENTAL_STRATEGIES) == before_exp
    assert set(STRATEGY_REGISTRY) == before_reg
    assert "vwap_ema_pullback" in EXPERIMENTAL_STRATEGIES


def test_p25_pipeline_with_full_grid_synthetic(tmp_path):
    fake_fetch = _fake_fetch_factory()
    result = run_p25(
        tickers=("KRW-BTC", "KRW-ETH"),
        intervals=("1h",),
        periods=(("6m", 30),),
        cache_dir=tmp_path,
        fetch_fn=fake_fetch,
    )
    assert result["candidate_grid_size"] == 12
    assert result["verdict"] in {"PASS", "HOLD", "REVISE", "STOP"}
    md = render_md_p25(result)
    assert "## Verdict:" in md
    assert "Per-ticker paper recommendation" in md


# ---------------------------------------------------------------------------
# Anchor diff sanity
# ---------------------------------------------------------------------------

def test_p25_anchor_diff_uses_p25_anchor_id():
    """anchor_diff 가 P25_ANCHOR_ID 를 reference 로 사용."""
    pass_cell = {"trades": 80, "total_return": -0.05, "bh_return": -0.10,
                 "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                 "profit_factor": 1.10, "avg_hold_bars": 6.0, "expectancy": 0.002}
    rollup = _build_rollup({
        P25_ANCHOR_ID: {
            ("KRW-BTC", "1y"): pass_cell,
        },
        "candA": {
            ("KRW-BTC", "1y"): {**pass_cell, "total_return": -0.02},  # +3pp better
        },
    })
    diffs = compute_anchor_diff_p25(rollup)
    assert "candA" in diffs
    assert diffs["candA"]["BTC_1y_ret_diff_pp"] > 2.5  # ≈+3pp
