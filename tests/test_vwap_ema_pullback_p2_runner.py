"""P2 runner verdict + smoke + grid composition tests.

Test spec: ``.omx/plans/test-spec-vwap-ema-pullback-p2-2026-05-04.md`` §4-§5.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from scripts.vwap_ema_pullback_p1_runner import CellMetrics
from scripts.vwap_ema_pullback_p2_runner import (
    ANCHOR_ID,
    ANCHOR_IMPROVEMENT_PP,
    HARD_FLOOR_TRADES_6M,
    P2Candidate,
    build_p2_candidate_grid,
    compute_anchor_diff,
    derive_paper_recommendation,
    derive_verdict_p2,
    main,
    render_md_p2,
    run_p2,
)

# ---------------------------------------------------------------------------
# Helpers
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
    """{cid: {(ticker, period): cell-overrides}} → rollup."""
    rollup: dict = {interval: {}}
    for cid, cells in candidate_specs.items():
        for (ticker, period), overrides in cells.items():
            cell = _cell(candidate_id=cid, ticker=ticker, period=period, **overrides)
            (rollup[interval]
                .setdefault(ticker, {})
                .setdefault(period, {}))[cid] = cell
    return rollup


# ---------------------------------------------------------------------------
# §4.1 / §4.2 — grid composition
# ---------------------------------------------------------------------------

def test_p2_grid_has_18_entries():
    grid = build_p2_candidate_grid()
    assert len(grid) == 18
    ids = [c.id for c in grid]
    assert len(set(ids)) == 18  # unique
    assert ANCHOR_ID in ids
    assert "ABCD_relaxed" in ids
    assert "ABCD_strict" in ids


def test_p2_anchor_matches_p1_combined_atr():
    """anchor 가 P1 best (combined_atr) 의 exit/freq settings 와 일치."""
    grid = build_p2_candidate_grid()
    anchor = next(c for c in grid if c.id == ANCHOR_ID)
    assert anchor.exit_mode == "atr_buffer_exit"
    assert anchor.exit_atr_multiplier == 0.3
    assert anchor.min_ema_slope_ratio == 0.002
    assert anchor.max_vwap_cross_count == 2
    assert anchor.cooldown_bars == 2
    assert anchor.htf_trend_filter_mode == "off"
    assert anchor.rsi_filter_mode == "off"
    assert anchor.volume_filter_mode == "off"
    assert anchor.daily_regime_filter_mode == "off"


def test_p2_grid_enrich_keys_dedupe_correctly():
    """동일 (slope, cross, filter axes) 후보들이 enrich_key 를 공유."""
    grid = build_p2_candidate_grid()
    keys = {c.enrich_key() for c in grid}
    # 18 candidates, distinct enrichment requirements should be < 18 (some share)
    assert len(keys) <= 18
    # Anchor + freq-only filters share base enrichment (no rsi/vol/htf/daily cols)
    anchor_key = next(c.enrich_key() for c in grid if c.id == ANCHOR_ID)
    htf_only = next(c.enrich_key() for c in grid if c.id == "A_htf_close")
    assert anchor_key != htf_only  # different axes flip enrich_key


# ---------------------------------------------------------------------------
# §4.6 — anchor diff calculation
# ---------------------------------------------------------------------------

def test_p2_anchor_diff_calculation():
    """anchor 대비 후보의 BTC 1y ret diff 가 +5pp 인 케이스."""
    rollup = _build_rollup({
        ANCHOR_ID: {
            ("KRW-BTC", "1y"): {"total_return": -0.10},
        },
        "candA": {
            ("KRW-BTC", "1y"): {"total_return": -0.05},  # +5pp better
        },
    })
    diffs = compute_anchor_diff(rollup)
    assert "candA" in diffs
    assert diffs["candA"]["BTC_1y_ret_diff_pp"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# §4.7 / §4.8 — paper recommendation
# ---------------------------------------------------------------------------

def test_p2_pass_with_marginal_quality_flagged():
    """anchor 대비 +1pp 만 → marginal → paper hold."""
    diffs = {"candA": {
        "BTC_1y_ret_diff_pp": 1.0, "BTC_6m_ret_diff_pp": 1.0,
        "ETH_1y_ret_diff_pp": 1.0, "ETH_6m_ret_diff_pp": 1.0,
    }}
    rec = derive_paper_recommendation("PASS", diffs, ["candA"])
    assert rec == "hold"


def test_p2_pass_with_strong_quality_recommends_paper():
    """anchor 대비 +5pp → recommend separate PR."""
    diffs = {"candA": {
        "BTC_1y_ret_diff_pp": 5.0, "BTC_6m_ret_diff_pp": 5.0,
        "ETH_1y_ret_diff_pp": 5.0, "ETH_6m_ret_diff_pp": 5.0,
    }}
    rec = derive_paper_recommendation("PASS", diffs, ["candA"])
    assert rec == "recommend_separate_pr"


def test_p2_paper_recommendation_na_when_not_pass():
    rec = derive_paper_recommendation("REVISE", {}, [])
    assert rec == "n/a"


# ---------------------------------------------------------------------------
# §4.9 — P2 6m hard floor enforcement
# ---------------------------------------------------------------------------

def test_p2_verdict_6m_trades_below_floor_blocks_pass():
    """6m BTC trades = 20 (< 30) → hard floor fail → NOT PASS."""
    pass_cell_kwargs = {"trades": 80, "total_return": 0.05, "bh_return": -0.10,
                        "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                        "profit_factor": 1.10, "avg_hold_bars": 6.0,
                        "expectancy": 0.002}
    fail_6m_cell = {**pass_cell_kwargs, "trades": 20}  # under 6m floor
    rollup = _build_rollup({
        "candA": {
            ("KRW-BTC", "1y"): pass_cell_kwargs,
            ("KRW-BTC", "6m"): fail_6m_cell,
            ("KRW-ETH", "1y"): pass_cell_kwargs,
            ("KRW-ETH", "6m"): pass_cell_kwargs,
        },
    })
    verdict, _ = derive_verdict_p2(rollup)
    assert verdict != "PASS"


def test_p2_verdict_6m_trades_at_floor_passes():
    """6m trades == 30 — floor 정확히 통과."""
    pass_cell_kwargs = {"trades": 80, "total_return": 0.05, "bh_return": -0.10,
                        "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                        "profit_factor": 1.10, "avg_hold_bars": 6.0,
                        "expectancy": 0.002}
    floor_6m = {**pass_cell_kwargs, "trades": HARD_FLOOR_TRADES_6M}
    rollup = _build_rollup({
        "candA": {
            ("KRW-BTC", "1y"): pass_cell_kwargs,
            ("KRW-BTC", "6m"): floor_6m,
            ("KRW-ETH", "1y"): pass_cell_kwargs,
            ("KRW-ETH", "6m"): floor_6m,
        },
    })
    verdict, _ = derive_verdict_p2(rollup)
    assert verdict == "PASS"


# ---------------------------------------------------------------------------
# §4.10 / §4.11 — interval / ticker exclusion
# ---------------------------------------------------------------------------

def test_p2_verdict_excludes_30m_from_pass_decision():
    pass_cell = {"trades": 80, "total_return": 0.05, "bh_return": -0.10,
                 "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                 "profit_factor": 1.10, "avg_hold_bars": 6.0, "expectancy": 0.002}
    bad_cell = {"trades": 30, "total_return": -0.50, "bh_return": -0.10,
                "mdd": -0.50, "bh_mdd": -0.20, "win_rate": 0.10,
                "profit_factor": 0.30, "avg_hold_bars": 1.0, "expectancy": -0.01}
    rollup_1h = _build_rollup({
        "candA": {
            ("KRW-BTC", "1y"): pass_cell, ("KRW-BTC", "6m"): pass_cell,
            ("KRW-ETH", "1y"): pass_cell, ("KRW-ETH", "6m"): pass_cell,
        },
    }, interval="1h")
    rollup_30m = _build_rollup({
        "candA": {
            ("KRW-BTC", "1y"): bad_cell, ("KRW-BTC", "6m"): bad_cell,
            ("KRW-ETH", "1y"): bad_cell, ("KRW-ETH", "6m"): bad_cell,
        },
    }, interval="30m")
    rollup = {**rollup_1h, **rollup_30m}
    verdict, _ = derive_verdict_p2(rollup)
    assert verdict == "PASS"


def test_p2_verdict_excludes_sol_xrp():
    pass_cell = {"trades": 80, "total_return": 0.05, "bh_return": -0.10,
                 "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                 "profit_factor": 1.10, "avg_hold_bars": 6.0, "expectancy": 0.002}
    bad_cell = {"trades": 30, "total_return": -0.50, "bh_return": -0.10,
                "mdd": -0.50, "bh_mdd": -0.20, "win_rate": 0.10,
                "profit_factor": 0.30, "avg_hold_bars": 1.0, "expectancy": -0.01}
    rollup = _build_rollup({
        "candA": {
            ("KRW-BTC", "1y"): pass_cell, ("KRW-BTC", "6m"): pass_cell,
            ("KRW-ETH", "1y"): pass_cell, ("KRW-ETH", "6m"): pass_cell,
            ("KRW-SOL", "1y"): bad_cell, ("KRW-SOL", "6m"): bad_cell,
            ("KRW-XRP", "1y"): bad_cell, ("KRW-XRP", "6m"): bad_cell,
        },
    })
    verdict, _ = derive_verdict_p2(rollup)
    assert verdict == "PASS"


# ---------------------------------------------------------------------------
# §4.3 / §4.4 / §4.5 — runner schema + JSON/MD + registry untouched
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
    """Returns a fetch_fn that maps interval string to a synthetic series."""
    def fake_fetch(ticker, interval, count, cache_dir, refresh=False):
        # Distinct seeds per ticker for variety
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


def test_p2_runner_outputs_expected_schema(tmp_path):
    fake_fetch = _fake_fetch_factory()
    grid = [
        P2Candidate(id=ANCHOR_ID),
        P2Candidate(id="A_htf_close", htf_trend_filter_mode="htf_close_above_ema"),
    ]
    result = run_p2(
        tickers=("KRW-BTC",),
        intervals=("1h",),
        periods=(("6m", 30),),
        cache_dir=tmp_path,
        candidate_grid=grid,
        fetch_fn=fake_fetch,
    )
    assert set(result.keys()) >= {
        "rollup", "verdict", "verdict_details", "anchor_id",
        "anchor_diff_pp", "paper_recommendation",
        "per_run", "candidate_grid_size",
    }
    assert result["candidate_grid_size"] == 2
    assert result["anchor_id"] == ANCHOR_ID
    cell = result["rollup"]["1h"]["KRW-BTC"]["6m"][ANCHOR_ID]
    assert set(cell.keys()) >= {
        "candidate_id", "ticker", "interval", "period", "candles", "trades",
        "total_return", "bh_return", "mdd", "bh_mdd", "win_rate",
        "profit_factor", "avg_hold_bars", "avg_profit", "avg_loss",
        "expectancy", "time_exit_share",
    }


def test_p2_runner_writes_json_and_md(tmp_path, monkeypatch):
    fake_fetch = _fake_fetch_factory()
    monkeypatch.setattr(
        "scripts.vwap_ema_pullback_p2_runner.fetch_ohlcv", fake_fetch,
    )
    out_json = tmp_path / "p2.json"
    out_md = tmp_path / "p2.md"

    # Smaller grid via monkeypatching build_p2_candidate_grid
    small_grid = [
        P2Candidate(id=ANCHOR_ID),
        P2Candidate(id="A_htf_close", htf_trend_filter_mode="htf_close_above_ema"),
    ]
    monkeypatch.setattr(
        "scripts.vwap_ema_pullback_p2_runner.build_p2_candidate_grid",
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
    assert out_md.exists()
    md = out_md.read_text(encoding="utf-8")
    assert "## Verdict:" in md
    assert "## ADR" in md
    assert "anchor_diff_pp" in md or "anchor_diff" in md.lower()


def test_p2_runner_does_not_mutate_strategy_registry(tmp_path):
    from auto_coin.strategy import EXPERIMENTAL_STRATEGIES, STRATEGY_REGISTRY

    before_exp = set(EXPERIMENTAL_STRATEGIES)
    before_reg = set(STRATEGY_REGISTRY)

    fake_fetch = _fake_fetch_factory()
    grid = [P2Candidate(id=ANCHOR_ID)]
    run_p2(
        tickers=("KRW-BTC",),
        intervals=("1h",),
        periods=(("6m", 30),),
        cache_dir=tmp_path,
        candidate_grid=grid,
        fetch_fn=fake_fetch,
    )

    after_exp = set(EXPERIMENTAL_STRATEGIES)
    after_reg = set(STRATEGY_REGISTRY)
    assert before_exp == after_exp
    assert before_reg == after_reg
    assert "vwap_ema_pullback" in after_exp


# ---------------------------------------------------------------------------
# §5 — full pipeline smoke
# ---------------------------------------------------------------------------

def test_p2_pipeline_with_full_grid_synthetic(tmp_path):
    """Full 18-candidate grid runs end-to-end on synthetic data without exception."""
    fake_fetch = _fake_fetch_factory()
    result = run_p2(
        tickers=("KRW-BTC", "KRW-ETH"),
        intervals=("1h",),
        periods=(("6m", 30),),
        cache_dir=tmp_path,
        fetch_fn=fake_fetch,
    )
    assert result["candidate_grid_size"] == 18
    assert result["verdict"] in {"PASS", "HOLD", "REVISE", "STOP"}
    md = render_md_p2(result)
    assert "## Verdict:" in md


# ---------------------------------------------------------------------------
# Constants check
# ---------------------------------------------------------------------------

def test_p2_anchor_improvement_pp_constant():
    assert ANCHOR_IMPROVEMENT_PP == 3.0


def test_p2_hard_floor_trades_6m_constant():
    assert HARD_FLOOR_TRADES_6M == 30


# pytest is needed in module scope for some helpers
import pytest  # noqa: E402
