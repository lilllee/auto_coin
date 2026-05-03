"""P1 runner verdict + smoke tests.

Test spec: ``.omx/plans/test-spec-vwap-ema-pullback-p1-2026-05-03.md`` §3-§4.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from scripts.vwap_ema_pullback_p1_runner import (
    HARD_FLOOR_TRADES,
    PERF_PF_MIN,
    PERF_WIN_RATE_MIN,
    Candidate,
    CellMetrics,
    build_candidate_grid,
    derive_verdict,
    main,
    render_md,
    run_p1,
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
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "ticker": ticker,
        "interval": "1h",
        "period": period,
        "candles": 1000,
        "trades": trades,
        "total_return": total_return,
        "bh_return": bh_return,
        "mdd": mdd,
        "bh_mdd": bh_mdd,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_hold_bars": avg_hold_bars,
        "avg_profit": avg_profit,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "time_exit_share": time_exit_share,
    }


def _build_rollup(
    candidate_specs: dict[str, dict[tuple[str, str], dict[str, Any]]],
    *,
    interval: str = "1h",
) -> dict:
    """{cid: {(ticker, period): cell-overrides}} → rollup.
    `cell-overrides` 는 _cell() 의 kwargs.
    """
    rollup: dict = {interval: {}}
    for cid, cells in candidate_specs.items():
        for (ticker, period), overrides in cells.items():
            cell_dict = _cell(candidate_id=cid, ticker=ticker, period=period, **overrides)
            cell = CellMetrics(**cell_dict)
            (rollup[interval]
                .setdefault(ticker, {})
                .setdefault(period, {}))[cid] = cell
    return rollup


# ---------------------------------------------------------------------------
# Verdict logic — test spec §3
# ---------------------------------------------------------------------------

def test_derive_verdict_pass_when_all_gates_pass():
    """모든 4 cell (BTC/ETH × 1y/6m) PASS 인 candidate 가 있으면 PASS."""
    pass_cell = {"trades": 80, "total_return": 0.05, "bh_return": -0.10,
                 "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                 "profit_factor": 1.10, "avg_hold_bars": 6.0, "expectancy": 0.002}
    rollup = _build_rollup({
        "candA": {
            ("KRW-BTC", "1y"): pass_cell,
            ("KRW-BTC", "6m"): pass_cell,
            ("KRW-ETH", "1y"): pass_cell,
            ("KRW-ETH", "6m"): pass_cell,
        },
    })
    verdict, details = derive_verdict(rollup)
    assert verdict == "PASS"
    assert "candA" in details["pass_candidates"]


def test_derive_verdict_stop_when_hard_floor_fails():
    """모든 candidate 가 hard floor (trades<60 등) fail 이면 STOP."""
    fail_cell = {"trades": 30, "total_return": 0.05, "bh_return": -0.10,
                 "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                 "profit_factor": 1.10, "avg_hold_bars": 6.0, "expectancy": 0.002}
    rollup = _build_rollup({
        "candA": {
            ("KRW-BTC", "1y"): fail_cell,
            ("KRW-BTC", "6m"): fail_cell,
            ("KRW-ETH", "1y"): fail_cell,
            ("KRW-ETH", "6m"): fail_cell,
        },
    })
    verdict, _ = derive_verdict(rollup)
    assert verdict == "STOP"


def test_derive_verdict_hold_when_some_cells_pass():
    """4 cell 중 일부만 PASS → HOLD."""
    pass_cell = {"trades": 80, "total_return": 0.05, "bh_return": -0.10,
                 "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                 "profit_factor": 1.10, "avg_hold_bars": 6.0, "expectancy": 0.002}
    fail_perf = {"trades": 80, "total_return": -0.20, "bh_return": -0.10,  # ret < BH
                 "mdd": -0.15, "bh_mdd": -0.20, "win_rate": 0.30,
                 "profit_factor": 0.70,  # PF below threshold
                 "avg_hold_bars": 6.0, "expectancy": -0.001}
    rollup = _build_rollup({
        "candA": {
            ("KRW-BTC", "1y"): pass_cell,
            ("KRW-BTC", "6m"): pass_cell,
            ("KRW-ETH", "1y"): pass_cell,
            ("KRW-ETH", "6m"): fail_perf,  # 1 cell fails perf gates
        },
    })
    verdict, details = derive_verdict(rollup)
    assert verdict == "HOLD"
    assert "candA" in details["partial_candidates"]


def test_derive_verdict_revise_when_hard_floor_pass_but_perf_fail():
    """모든 candidate 가 hard floor 만 통과하고 perf gate 0건 → REVISE."""
    hard_only = {"trades": 80, "total_return": -0.20, "bh_return": -0.10,
                 "mdd": -0.30, "bh_mdd": -0.20,  # MDD-BH_MDD = -0.10 < -0.05 fail
                 "win_rate": 0.20,  # < 0.25 fail
                 "profit_factor": 0.70,  # < 0.85 fail
                 "avg_hold_bars": 6.0, "expectancy": -0.002}
    rollup = _build_rollup({
        "candA": {
            ("KRW-BTC", "1y"): hard_only,
            ("KRW-BTC", "6m"): hard_only,
            ("KRW-ETH", "1y"): hard_only,
            ("KRW-ETH", "6m"): hard_only,
        },
    })
    verdict, details = derive_verdict(rollup)
    assert verdict == "REVISE"
    assert "candA" in details["hard_pass_candidates"]


def test_derive_verdict_uses_only_1h_for_pass_decision():
    """30m 결과는 verdict 에 영향 없음."""
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
    verdict, _ = derive_verdict(rollup)
    assert verdict == "PASS"  # 30m bad 무시


def test_derive_verdict_excludes_sol_xrp_from_pass():
    """SOL/XRP 셀이 모두 STOP 수준이라도 BTC/ETH PASS 면 PASS."""
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
            ("KRW-SOL", "1y"): bad_cell,  ("KRW-SOL", "6m"): bad_cell,
            ("KRW-XRP", "1y"): bad_cell,  ("KRW-XRP", "6m"): bad_cell,
        },
    })
    verdict, _ = derive_verdict(rollup)
    assert verdict == "PASS"


# ---------------------------------------------------------------------------
# Smoke — runner integration with mocked fetch
# ---------------------------------------------------------------------------

def _synthetic_ohlcv(n: int = 400, freq: str = "60min") -> pd.DataFrame:
    np.random.seed(42)
    close = 100.0 + np.cumsum(np.random.normal(0, 0.5, n))
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.random.uniform(50, 150, n),
        },
        index=pd.date_range("2025-05-01", periods=n, freq=freq),
    )


def test_runner_outputs_expected_schema(tmp_path, monkeypatch):
    """runner 가 rollup + verdict + per_run + grid_size 키를 채워서 반환."""
    def fake_fetch(ticker, interval, count, cache_dir, refresh=False):
        return _synthetic_ohlcv(n=400)

    grid = [
        Candidate(id="anchor", exit_mode="close_below_ema"),
        Candidate(id="body", exit_mode="body_below_ema"),
    ]
    result = run_p1(
        tickers=("KRW-BTC",),
        intervals=("1h",),
        periods=(("6m", 30),),
        cache_dir=tmp_path,
        candidate_grid=grid,
        fetch_fn=fake_fetch,
    )
    assert set(result.keys()) >= {"rollup", "verdict", "verdict_details",
                                  "per_run", "candidate_grid_size"}
    assert result["candidate_grid_size"] == 2
    assert "1h" in result["rollup"]
    assert "KRW-BTC" in result["rollup"]["1h"]
    cell = result["rollup"]["1h"]["KRW-BTC"]["6m"]["anchor"]
    assert set(cell.keys()) >= {
        "candidate_id", "ticker", "interval", "period", "candles", "trades",
        "total_return", "bh_return", "mdd", "bh_mdd", "win_rate",
        "profit_factor", "avg_hold_bars", "avg_profit", "avg_loss",
        "expectancy", "time_exit_share",
    }


def test_runner_writes_json_and_md(tmp_path, monkeypatch):
    """main() 가 JSON + MD 둘 다 생성하고 MD 에 Verdict 헤더가 들어있다."""
    def fake_fetch(ticker, interval, count, cache_dir, refresh=False):
        return _synthetic_ohlcv(n=400)

    monkeypatch.setattr(
        "scripts.vwap_ema_pullback_p1_runner.fetch_ohlcv", fake_fetch,
    )
    out_json = tmp_path / "p1.json"
    out_md = tmp_path / "p1.md"
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
    assert out_md.exists()
    md = out_md.read_text(encoding="utf-8")
    assert "## Verdict:" in md
    assert any(v in md for v in ["PASS", "HOLD", "REVISE", "STOP"])
    assert "## ADR" in md


def test_runner_does_not_mutate_strategy_registry(monkeypatch, tmp_path):
    """runner 호출 전후 EXPERIMENTAL_STRATEGIES + STRATEGY_REGISTRY 동일."""
    from auto_coin.strategy import EXPERIMENTAL_STRATEGIES, STRATEGY_REGISTRY

    before_exp = set(EXPERIMENTAL_STRATEGIES)
    before_reg = set(STRATEGY_REGISTRY)

    def fake_fetch(ticker, interval, count, cache_dir, refresh=False):
        return _synthetic_ohlcv(n=400)

    grid = [Candidate(id="anchor", exit_mode="close_below_ema")]
    run_p1(
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
# Sanity — candidate grid composition
# ---------------------------------------------------------------------------

def test_candidate_grid_has_14_entries():
    grid = build_candidate_grid()
    assert len(grid) == 14
    ids = [c.id for c in grid]
    assert len(set(ids)) == 14  # unique
    assert "baseline" in ids
    assert "combined_body" in ids
    assert "tolerance_005" in ids


def test_candidate_grid_baseline_uses_close_below_ema():
    grid = build_candidate_grid()
    baseline = next(c for c in grid if c.id == "baseline")
    assert baseline.exit_mode == "close_below_ema"
    assert baseline.cooldown_bars == 0
    assert baseline.min_ema_slope_ratio == 0.001
    assert baseline.max_vwap_cross_count == 3


def test_render_md_handles_stop_verdict():
    """STOP verdict 도 MD 가 깨지지 않아야 한다."""
    result = {
        "rollup": {"1h": {}},
        "verdict": "STOP",
        "verdict_details": {"details": {}},
        "per_run": [],
        "candidate_grid_size": 14,
    }
    md = render_md(result)
    assert "STOP" in md
    assert "## Verdict:" in md


# Constants exported per spec
def test_threshold_constants_match_prd():
    assert HARD_FLOOR_TRADES == 60
    assert PERF_PF_MIN == 0.85
    assert PERF_WIN_RATE_MIN == 0.25
