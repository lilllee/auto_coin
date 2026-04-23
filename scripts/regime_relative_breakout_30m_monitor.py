"""Read-only monitor for ``regime_relative_breakout_30m``.

Codex 0005 policy:

> regime_relative_breakout_30m is not a live/paper strategy right now.
> It is a conditional research candidate, waiting for BTC daily regime to
> turn back ON.  This monitor only reports whether the revisit trigger
> has fired and whether ETH/XRP are anywhere near full entry conditions.

Strictly forbidden, enforced by not importing those layers at all:

- no order execution / no ``UpbitClient`` calls beyond ``pyupbit.get_ohlcv``
- no paper / live trading
- no strategy entry/exit logic change
- no UI / KPI / settings touch
- no entry-condition loosening — the monitor evaluates the strategy's
  existing 9-condition stack exactly as coded in
  ``RegimeRelativeBreakout30mStrategy``
- no reversion exit, no parameter sweep

Output report (one snapshot per invocation):

    reports/latest-regime-relative-breakout-monitor.json

Verdict labels per Codex 0005:

- ``WAIT_REGIME_OFF``        — BTC daily regime off on the strategy's
  view at the latest 30m bar; strategy would not fire. Do nothing.
- ``WATCHLIST_REGIME_ON``    — BTC regime back on for the strategy, but
  no alt near entry.
- ``ENTRY_CONDITIONS_NEAR``  — BTC regime on, at least one alt has
  7 or 8 of the 9 conditions true right now.
- ``ENTRY_CONDITIONS_READY`` — All 9 entry conditions true on the
  latest 30m bar for at least one alt. This is an alarm, not a trade
  trigger: Codex re-review is still required.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import pandas as pd
import pyupbit

from auto_coin.data.candles import (
    enrich_regime_relative_breakout_30m,
    history_days_to_candles,
)

AS_OF_LABEL = "latest"
REPORT_PATH = Path("reports/latest-regime-relative-breakout-monitor.json")

REGIME_TICKER = "KRW-BTC"
ALT_TICKERS = ["KRW-ETH", "KRW-XRP"]
TICKERS = [REGIME_TICKER, *ALT_TICKERS]

FETCH_DAYS_DEFAULT = 365  # enough history for SMA100 + RS 7d + a year of flips

# Must match RegimeRelativeBreakout30mStrategy defaults exactly.
BASE_PARAMS: dict[str, Any] = {
    "daily_regime_ma_window": 100,
    "rs_24h_bars_30m": 48,
    "rs_7d_bars_30m": 336,
    "hourly_ema_fast": 20,
    "hourly_ema_slow": 60,
    "hourly_slope_lookback": 3,
    "breakout_lookback_30m": 6,
    "volume_window_30m": 20,
    "volume_mult": 1.2,
    "close_location_min": 0.55,
    "atr_window": 14,
}


# ---------------------------------------------------------------------------
# Data fetch (mirrors other scripts' helper — no new dependencies)
# ---------------------------------------------------------------------------


def _fetch_ohlcv(ticker: str, interval: str, days: int) -> pd.DataFrame:
    count = history_days_to_candles(days, interval)
    chunks: list[pd.DataFrame] = []
    to: str | None = None
    chunk_size = min(count, 5000)
    while sum(len(c) for c in chunks) < count:
        remaining = count - sum(len(c) for c in chunks)
        request_count = min(chunk_size, remaining)
        df = None
        for attempt in range(3):
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=request_count, to=to)
            if df is not None and not df.empty:
                break
            print(f"retry fetch {ticker} {interval} attempt={attempt + 2}/3")
            time.sleep(0.25)
        if df is None or df.empty:
            if chunks:
                break
            raise SystemExit(f"failed to fetch {interval} candles for {ticker}")
        chunks.append(df)
        oldest = df.index[0]
        to = oldest.strftime("%Y-%m-%d %H:%M:%S")
        time.sleep(0.12)
        if len(df) < request_count:
            break
    out = pd.concat(chunks).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out.tail(count)


# ---------------------------------------------------------------------------
# BTC daily regime history (raw, not shifted — these are completed-day states)
# ---------------------------------------------------------------------------


def regime_history(btc_daily: pd.DataFrame, ma_window: int) -> dict[str, Any]:
    """Current BTC daily regime state + consecutive run + last flip.

    Uses the no-lookahead shifted SMA exactly as the strategy's enricher:

        sma[t]        = rolling_mean(close, ma_window).shift(1)   # uses close[t-ma_window..t-1]
        regime_raw[t] = close[t] >= sma[t]

    The daily series of ``regime_raw`` is evaluated on *completed* daily
    bars only — the most recent entry is the regime status as of the last
    fetched daily close.  Note that the strategy's intraday view uses
    ``regime_raw.shift(1)``, which is why the verdict is computed from the
    30m bar's projected value, not the raw daily value here.
    """
    close = btc_daily["close"]
    sma = close.rolling(ma_window).mean().shift(1)
    regime_raw = (close >= sma).astype("boolean")
    valid = regime_raw.dropna()
    if valid.empty:
        return {
            "latest_completed_daily_date": None,
            "latest_completed_daily_close": None,
            "shifted_sma100": None,
            "regime_on_at_latest_completed_daily": None,
            "consecutive_state_days": 0,
            "regime_confirmed_2d_on": False,
            "last_flip_date": None,
            "days_since_last_flip": None,
            "history_days_considered": 0,
        }
    latest_idx = valid.index[-1]
    latest_state = bool(valid.iloc[-1])

    run = 1
    flip_date: pd.Timestamp | None = None
    for i in range(len(valid) - 2, -1, -1):
        if bool(valid.iloc[i]) == latest_state:
            run += 1
        else:
            flip_date = valid.index[i + 1]
            break
    # All completed days share the same state since warmup — report the
    # earliest valid day as the effective "flip" (strategy has seen one
    # continuous regime since data began).
    if flip_date is None:
        flip_date = valid.index[0]
    days_since_flip = int((latest_idx - flip_date).days)
    return {
        "latest_completed_daily_date": latest_idx.isoformat(),
        "latest_completed_daily_close": float(close.loc[latest_idx]),
        "shifted_sma100": float(sma.loc[latest_idx]),
        "regime_on_at_latest_completed_daily": latest_state,
        "consecutive_state_days": int(run),
        "regime_confirmed_2d_on": latest_state and run >= 2,
        "last_flip_date": flip_date.isoformat(),
        "days_since_last_flip": days_since_flip,
        "history_days_considered": int(len(valid)),
    }


# ---------------------------------------------------------------------------
# Per-ticker condition evaluation at the latest 30m bar
# ---------------------------------------------------------------------------


def _is_finite(value: Any) -> bool:
    if value is None:
        return False
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return not math.isnan(f) and not math.isinf(f)


def _num(value: Any) -> float | None:
    if not _is_finite(value):
        return None
    return float(value)


def _is_true(value: Any) -> bool:
    return value is True or value == 1  # pandas "boolean" True → True; False/NA → not True


def evaluate_conditions(row: pd.Series, params: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the 9 strategy entry conditions on a single enriched row.

    Columns expected (populated by ``enrich_regime_relative_breakout_30m``):

    - ``btc_daily_regime_on`` (boolean, shifted-at-daily-level so the 30m
      view is no-lookahead)
    - ``target_rs_24h_vs_btc``, ``target_rs_7d_vs_btc``
    - ``hourly_close``, ``hourly_ema{fast}``, ``hourly_ema{slow}``,
      ``hourly_ema{fast}_slope_{lb}``
    - ``close``, ``prior_high_{lb}``, ``close_location_value``
    - ``volume``, ``volume_ma_{window}``
    """
    fast_col = f"hourly_ema{params['hourly_ema_fast']}"
    slow_col = f"hourly_ema{params['hourly_ema_slow']}"
    slope_col = (
        f"hourly_ema{params['hourly_ema_fast']}_slope_{params['hourly_slope_lookback']}"
    )
    prior_high_col = f"prior_high_{params['breakout_lookback_30m']}"
    volume_ma_col = f"volume_ma_{params['volume_window_30m']}"

    regime_on_val = row.get("btc_daily_regime_on")
    rs24_val = row.get("target_rs_24h_vs_btc")
    rs7_val = row.get("target_rs_7d_vs_btc")
    hourly_close = row.get("hourly_close")
    hourly_fast = row.get(fast_col)
    hourly_slow = row.get(slow_col)
    slope = row.get(slope_col)
    close_val = row.get("close")
    prior_high = row.get(prior_high_col)
    clv = row.get("close_location_value")
    volume_val = row.get("volume")
    volume_ma = row.get(volume_ma_col)

    c1 = _is_true(regime_on_val)
    c2 = _is_finite(rs24_val) and float(rs24_val) > 0
    c3 = _is_finite(rs7_val) and float(rs7_val) > 0
    c4 = (
        _is_finite(hourly_close)
        and _is_finite(hourly_fast)
        and float(hourly_close) > float(hourly_fast)
    )
    c5 = (
        _is_finite(hourly_fast)
        and _is_finite(hourly_slow)
        and float(hourly_fast) > float(hourly_slow)
    )
    c6 = _is_finite(slope) and float(slope) >= 0
    c7 = (
        _is_finite(close_val)
        and _is_finite(prior_high)
        and float(close_val) > float(prior_high)
    )
    c8 = _is_finite(clv) and float(clv) >= params["close_location_min"]
    c9 = (
        _is_finite(volume_val)
        and _is_finite(volume_ma)
        and float(volume_val) > float(volume_ma) * params["volume_mult"]
    )

    conds = {
        "1_btc_daily_regime_on": c1,
        "2_rs_24h_vs_btc_positive": c2,
        "3_rs_7d_vs_btc_positive": c3,
        "4_hourly_close_above_ema20": c4,
        "5_hourly_ema20_above_ema60": c5,
        "6_hourly_ema20_slope_3_non_negative": c6,
        "7_close_above_prior_high_6": c7,
        "8_close_location_value_ge_055": c8,
        "9_volume_above_ma_mult": c9,
    }

    hourly_trend_ok = c4 and c5 and c6
    breakout_ok = c7 and c8
    rs_ok = c2 and c3

    near_miss = {
        "full_entry_except_volume": c1 and rs_ok and hourly_trend_ok and breakout_ok and not c9,
        "full_entry_except_breakout": c1 and rs_ok and hourly_trend_ok and c9 and not breakout_ok,
        "full_entry_except_rs_7d": c1 and c2 and (not c3) and hourly_trend_ok and breakout_ok and c9,
        "full_entry_except_hourly_trend": c1 and rs_ok and (not hourly_trend_ok) and breakout_ok and c9,
    }

    volume_ratio = None
    if _is_finite(volume_val) and _is_finite(volume_ma) and float(volume_ma) > 0:
        volume_ratio = float(volume_val) / float(volume_ma)

    return {
        "conditions": conds,
        "conditions_met_count": int(sum(1 for v in conds.values() if v)),
        "conditions_total": 9,
        "full_entry_met": all(conds.values()),
        "hourly_trend_ok": hourly_trend_ok,
        "breakout_ok": breakout_ok,
        "rs_ok": rs_ok,
        "near_miss": near_miss,
        "values": {
            "close": _num(close_val),
            "prior_high_6": _num(prior_high),
            "close_location_value": _num(clv),
            "volume": _num(volume_val),
            "volume_ma_20": _num(volume_ma),
            "volume_ratio": volume_ratio,
            "volume_threshold_ratio": params["volume_mult"],
            "target_rs_24h_vs_btc": _num(rs24_val),
            "target_rs_7d_vs_btc": _num(rs7_val),
            "hourly_close": _num(hourly_close),
            "hourly_ema20": _num(hourly_fast),
            "hourly_ema60": _num(hourly_slow),
            "hourly_ema20_slope_3": _num(slope),
        },
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def classify_monitor_verdict(per_ticker: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Produce one of the four Codex 0005 monitor labels + reason string.

    The gate for WAIT_REGIME_OFF is the strategy's *own* view of the
    regime at the latest 30m bar (``btc_daily_regime_on`` column in
    ``enrich_regime_relative_breakout_30m``, which already applies the
    shift(1) at the daily level).  That is the status the strategy would
    actually use if it were active.
    """
    if not per_ticker:
        return {
            "label": "WAIT_REGIME_OFF",
            "reason": "no per-ticker evaluation available",
        }
    # The regime column is identical across tickers (same BTC daily source,
    # same projection). Any ticker's latest 30m view tells us the strategy's
    # current regime gate.
    sample_view = next(iter(per_ticker.values()))
    regime_on_30m_now = bool(sample_view["conditions"]["1_btc_daily_regime_on"])
    if not regime_on_30m_now:
        return {
            "label": "WAIT_REGIME_OFF",
            "reason": (
                "BTC daily regime is OFF at the latest 30m bar using the "
                "no-lookahead rule; the strategy would not fire for any alt."
            ),
        }
    if any(t["full_entry_met"] for t in per_ticker.values()):
        return {
            "label": "ENTRY_CONDITIONS_READY",
            "reason": (
                "All 9 entry conditions are true on the latest 30m bar for at "
                "least one alt. This is a monitor alarm only — no trade, no "
                "paper. Codex review required before any action."
            ),
        }
    if any(t["conditions_met_count"] >= 7 for t in per_ticker.values()):
        return {
            "label": "ENTRY_CONDITIONS_NEAR",
            "reason": (
                "BTC regime ON; at least one alt has 7+ of 9 entry conditions "
                "true at the latest 30m bar. Watch more closely but take no "
                "action yet."
            ),
        }
    return {
        "label": "WATCHLIST_REGIME_ON",
        "reason": (
            "BTC regime ON at the strategy's 30m view but no alt is near full "
            "entry conditions. Passive watchlist."
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-days", type=int, default=FETCH_DAYS_DEFAULT)
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)

    print(f"fetch minute30 for {TICKERS}")
    thirty = {t: _fetch_ohlcv(t, "minute30", args.fetch_days) for t in TICKERS}
    print(f"fetch minute60 for {ALT_TICKERS}")
    hourly = {t: _fetch_ohlcv(t, "minute60", args.fetch_days) for t in ALT_TICKERS}
    print(f"fetch day for {REGIME_TICKER}")
    btc_daily = _fetch_ohlcv(REGIME_TICKER, "day", args.fetch_days)
    btc_30m = thirty[REGIME_TICKER]

    regime_info = regime_history(btc_daily, BASE_PARAMS["daily_regime_ma_window"])

    per_ticker: dict[str, dict[str, Any]] = {}
    for ticker in ALT_TICKERS:
        enriched = enrich_regime_relative_breakout_30m(
            thirty[ticker],
            daily_regime_df=btc_daily,
            daily_regime_ma_window=BASE_PARAMS["daily_regime_ma_window"],
            hourly_setup_df=hourly[ticker],
            hourly_ema_fast=BASE_PARAMS["hourly_ema_fast"],
            hourly_ema_slow=BASE_PARAMS["hourly_ema_slow"],
            hourly_slope_lookback=BASE_PARAMS["hourly_slope_lookback"],
            rs_reference_df=btc_30m,
            rs_24h_bars_30m=BASE_PARAMS["rs_24h_bars_30m"],
            rs_7d_bars_30m=BASE_PARAMS["rs_7d_bars_30m"],
            breakout_lookback_30m=BASE_PARAMS["breakout_lookback_30m"],
            volume_window_30m=BASE_PARAMS["volume_window_30m"],
            atr_window=BASE_PARAMS["atr_window"],
        )
        last_row = enriched.iloc[-1]
        last_ts = enriched.index[-1]
        evaluation = evaluate_conditions(last_row, BASE_PARAMS)
        evaluation["latest_30m_timestamp"] = last_ts.isoformat()
        per_ticker[ticker] = evaluation

    verdict = classify_monitor_verdict(per_ticker)

    report = {
        "as_of": pd.Timestamp.now().isoformat(),
        "strategy": "regime_relative_breakout_30m",
        "scope": (
            "read-only monitor per Codex 0005; no orders, no paper, no live, "
            "no strategy/ui/kpi changes"
        ),
        "fetch_days": args.fetch_days,
        "base_params": BASE_PARAMS,
        "btc_daily_regime": regime_info,
        "per_ticker": per_ticker,
        "verdict": verdict,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(args.out)
    print(
        json.dumps(
            {
                "btc_daily_regime": {
                    "regime_on_at_latest_completed_daily": regime_info[
                        "regime_on_at_latest_completed_daily"
                    ],
                    "consecutive_state_days": regime_info["consecutive_state_days"],
                    "regime_confirmed_2d_on": regime_info["regime_confirmed_2d_on"],
                    "last_flip_date": regime_info["last_flip_date"],
                },
                "per_ticker_counts": {
                    t: {
                        "conditions_met_count": v["conditions_met_count"],
                        "full_entry_met": v["full_entry_met"],
                    }
                    for t, v in per_ticker.items()
                },
                "verdict": verdict,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
