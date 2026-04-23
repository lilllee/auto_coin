"""Event study: does BTC regime + alt relative strength + 30m breakout have edge?

Analysis-only.  Does not register a strategy, touch the live bot, UI, KPI, or
walk-forward.  The goal is to validate whether a proposed
``regime_relative_breakout_30m`` signal family deserves to be built at all, by
measuring forward return and path statistics after six progressively tighter
condition sets.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyupbit

from auto_coin.data.candles import history_days_to_candles, project_higher_timeframe_features

AS_OF = "2026-04-23"
REPORT_PATH = Path("reports/2026-04-23-regime-relative-strength-event-study.json")
TICKERS = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]
REGIME_TICKER = "KRW-BTC"
FETCH_DAYS = 830
LOOKBACK_DAYS = 730
INTERVAL = "minute30"
FORWARD_BARS: list[int] = [4, 8, 16, 24, 48]
PATH_HORIZONS: list[int] = [16, 24, 48]
PRIOR_HIGH_WINDOW = 6
VOLUME_MA_WINDOW = 20
RSI_WINDOW = 14
RS_24H_BARS = 48
RS_7D_BARS = 336
EVENT_COOLDOWN_BARS = 8
SAMPLE_CAP = 20
BTC_DAILY_SMA_WINDOW = 100

CONDITION_SET_NAMES: list[str] = [
    "breakout_only",
    "regime_breakout",
    "regime_rs_breakout",
    "regime_rs_volume_breakout",
    "regime_rs_trend_volume_breakout",
    "regime_rs_pullback_rebreakout",
]

CONDITION_SET_DEFINITIONS: dict[str, str] = {
    "breakout_only": "close > prior_high_6 AND close_location_value >= 0.55",
    "regime_breakout": "breakout_only AND btc_daily_regime_on",
    "regime_rs_breakout": "regime_breakout AND target_rs_24h_vs_btc > 0 AND target_rs_7d_vs_btc > 0",
    "regime_rs_volume_breakout": "regime_rs_breakout AND volume > volume_ma20 * 1.2",
    "regime_rs_trend_volume_breakout": (
        "regime_rs_volume_breakout AND hourly_close > hourly_ema20 > hourly_ema60 "
        "AND hourly_ema20_slope_3 >= 0"
    ),
    "regime_rs_pullback_rebreakout": (
        "regime_rs_trend_volume_breakout AND hourly_pullback_return_8 in [-0.08, -0.008] "
        "AND rsi14 >= 50"
    ),
}


# ---------------------------------------------------------------------------
# Data fetch (script-local, mirrors existing stage-2 scripts)
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
# Pure feature helpers (tested offline)
# ---------------------------------------------------------------------------


def compute_close_location_value(df: pd.DataFrame) -> pd.Series:
    """CLV = (close - low) / (high - low); 0.5 when the candle range is zero."""
    rng = df["high"] - df["low"]
    raw = (df["close"] - df["low"]) / rng.where(rng > 0)
    return raw.fillna(0.5)


def compute_prior_high(high: pd.Series, lookback: int) -> pd.Series:
    """Rolling max of high over the previous ``lookback`` bars (shifted by 1)."""
    return high.rolling(window=lookback).max().shift(1)


def compute_volume_ma(volume: pd.Series, window: int) -> pd.Series:
    """Rolling mean of volume over the previous ``window`` bars (shifted by 1)."""
    return volume.rolling(window=window).mean().shift(1)


def compute_relative_strength(
    target_close: pd.Series,
    btc_close: pd.Series,
    bars: int,
) -> pd.Series:
    target_ret = target_close / target_close.shift(bars) - 1.0
    btc_ret = btc_close / btc_close.shift(bars) - 1.0
    return target_ret - btc_ret


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def dedupe_events(mask: pd.Series, cooldown: int) -> pd.Series:
    """Collapse clustered qualifying bars; keep first and require strict gap > cooldown."""
    arr = mask.fillna(False).to_numpy()
    accepted = np.zeros_like(arr, dtype=bool)
    last = -cooldown - 1
    for i, val in enumerate(arr):
        if val and (i - last) > cooldown:
            accepted[i] = True
            last = i
    return pd.Series(accepted, index=mask.index)


# ---------------------------------------------------------------------------
# Higher-timeframe feature calc + projection
# ---------------------------------------------------------------------------


def _compute_hourly_features(hourly_df: pd.DataFrame) -> pd.DataFrame:
    """1H feature block; shifted by 1 at the hourly level to avoid leaking into intra-hour 30m bars."""
    close = hourly_df["close"]
    feats = pd.DataFrame(index=hourly_df.index)
    feats["hourly_close"] = close
    feats["hourly_ema20"] = close.ewm(span=20, adjust=False).mean()
    feats["hourly_ema60"] = close.ewm(span=60, adjust=False).mean()
    feats["hourly_ema20_slope_3"] = feats["hourly_ema20"] - feats["hourly_ema20"].shift(3)
    feats["hourly_pullback_return_8"] = close / close.rolling(8).max().shift(1) - 1.0
    return feats.shift(1)


def _btc_daily_regime_projection(btc_daily: pd.DataFrame, target_index: pd.Index) -> pd.Series:
    sma = btc_daily["close"].rolling(BTC_DAILY_SMA_WINDOW).mean().shift(1)
    # shift(1) so that 30m bars inside day d see regime derived from day d-1's
    # close only; day d's close isn't confirmed until end of day d.
    regime_on = (btc_daily["close"] >= sma).astype("boolean").shift(1)
    proj = project_higher_timeframe_features(
        regime_on.to_frame("btc_daily_regime_on"),
        target_index,
        columns=["btc_daily_regime_on"],
    )
    return proj["btc_daily_regime_on"]


# ---------------------------------------------------------------------------
# Target enrichment (adds all features + forward returns + MFE/MAE)
# ---------------------------------------------------------------------------


def _enrich_target(
    target_30m: pd.DataFrame,
    btc_30m_aligned: pd.DataFrame,
    hourly_projection: pd.DataFrame,
    btc_regime_30m: pd.Series,
) -> pd.DataFrame:
    out = target_30m.copy()
    out["prior_high_6"] = compute_prior_high(out["high"], PRIOR_HIGH_WINDOW)
    out["volume_ma20"] = compute_volume_ma(out["volume"], VOLUME_MA_WINDOW)
    out["close_location_value"] = compute_close_location_value(out)
    out["rsi14"] = _rsi(out["close"], RSI_WINDOW)

    out["target_rs_24h_vs_btc"] = compute_relative_strength(
        out["close"], btc_30m_aligned["close"], RS_24H_BARS
    )
    out["target_rs_7d_vs_btc"] = compute_relative_strength(
        out["close"], btc_30m_aligned["close"], RS_7D_BARS
    )

    out["btc_daily_regime_on"] = btc_regime_30m.reindex(out.index)

    for col in (
        "hourly_close",
        "hourly_ema20",
        "hourly_ema60",
        "hourly_ema20_slope_3",
        "hourly_pullback_return_8",
    ):
        out[col] = hourly_projection[col].reindex(out.index)

    out["volume_ratio"] = out["volume"] / out["volume_ma20"]

    for h in FORWARD_BARS:
        out[f"fwd_ret_{h}"] = out["close"].shift(-h) / out["close"] - 1.0
        btc_fwd = btc_30m_aligned["close"].shift(-h) / btc_30m_aligned["close"] - 1.0
        out[f"fwd_excess_ret_{h}"] = out[f"fwd_ret_{h}"] - btc_fwd

    for h in PATH_HORIZONS:
        future_max_high = out["high"].rolling(h).max().shift(-h)
        future_min_low = out["low"].rolling(h).min().shift(-h)
        out[f"mfe_{h}"] = future_max_high / out["close"] - 1.0
        out[f"mae_{h}"] = future_min_low / out["close"] - 1.0
    return out


# ---------------------------------------------------------------------------
# Condition masks — operate on feature columns only (no forward-return cols)
# ---------------------------------------------------------------------------


def condition_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Return masks for each condition set; uses only feature columns, not fwd_ret*."""
    close = df["close"]
    breakout = (close > df["prior_high_6"]) & (df["close_location_value"] >= 0.55)
    breakout = breakout.fillna(False)

    regime = df["btc_daily_regime_on"].astype("boolean").fillna(False).astype(bool)
    rs_pos = (df["target_rs_24h_vs_btc"] > 0) & (df["target_rs_7d_vs_btc"] > 0)
    rs_pos = rs_pos.fillna(False)

    volume_ok = (df["volume"] > df["volume_ma20"] * 1.2).fillna(False)
    trend_ok = (
        (df["hourly_close"] > df["hourly_ema20"])
        & (df["hourly_ema20"] > df["hourly_ema60"])
        & (df["hourly_ema20_slope_3"] >= 0)
    ).fillna(False)
    pullback_ok = df["hourly_pullback_return_8"].between(-0.08, -0.008, inclusive="both").fillna(False)
    rsi_ok = (df["rsi14"] >= 50).fillna(False)

    sets: dict[str, pd.Series] = {}
    sets["breakout_only"] = breakout
    sets["regime_breakout"] = sets["breakout_only"] & regime
    sets["regime_rs_breakout"] = sets["regime_breakout"] & rs_pos
    sets["regime_rs_volume_breakout"] = sets["regime_rs_breakout"] & volume_ok
    sets["regime_rs_trend_volume_breakout"] = sets["regime_rs_volume_breakout"] & trend_ok
    sets["regime_rs_pullback_rebreakout"] = (
        sets["regime_rs_trend_volume_breakout"] & pullback_ok & rsi_ok
    )
    return sets


# ---------------------------------------------------------------------------
# Summary stats + verdict
# ---------------------------------------------------------------------------


def empty_summary(
    horizons: list[int] = FORWARD_BARS,
    path_horizons: list[int] = PATH_HORIZONS,
) -> dict[str, Any]:
    return {
        "raw_event_count": 0,
        "event_count": 0,
        "horizons": {
            str(h): {
                "avg_return": 0.0,
                "median_return": 0.0,
                "win_rate": 0.0,
                "avg_excess_return": 0.0,
                "median_excess_return": 0.0,
                "excess_win_rate": 0.0,
            }
            for h in horizons
        },
        "path": {
            str(h): {
                "avg_mfe": 0.0,
                "median_mfe": 0.0,
                "avg_mae": 0.0,
                "median_mae": 0.0,
            }
            for h in path_horizons
        },
    }


def summarize_events(
    events_df: pd.DataFrame,
    raw_count: int,
    horizons: list[int] = FORWARD_BARS,
    path_horizons: list[int] = PATH_HORIZONS,
) -> dict[str, Any]:
    out = empty_summary(horizons, path_horizons)
    out["raw_event_count"] = int(raw_count)
    out["event_count"] = int(len(events_df))
    if events_df.empty:
        return out
    for h in horizons:
        fwd = events_df[f"fwd_ret_{h}"].dropna()
        exc = events_df[f"fwd_excess_ret_{h}"].dropna()
        bucket = out["horizons"][str(h)]
        if len(fwd):
            bucket["avg_return"] = float(fwd.mean())
            bucket["median_return"] = float(fwd.median())
            bucket["win_rate"] = float((fwd > 0).mean())
        if len(exc):
            bucket["avg_excess_return"] = float(exc.mean())
            bucket["median_excess_return"] = float(exc.median())
            bucket["excess_win_rate"] = float((exc > 0).mean())
    for h in path_horizons:
        mfe = events_df[f"mfe_{h}"].dropna()
        mae = events_df[f"mae_{h}"].dropna()
        bucket = out["path"][str(h)]
        if len(mfe):
            bucket["avg_mfe"] = float(mfe.mean())
            bucket["median_mfe"] = float(mfe.median())
        if len(mae):
            bucket["avg_mae"] = float(mae.mean())
            bucket["median_mae"] = float(mae.median())
    return out


def classify_verdict(gates: dict[str, bool], stats: dict[str, float]) -> str:
    """PASS / HOLD / REVISE / STOP decision based on alt-only gates and excess stats."""
    if all(gates.values()):
        return "PASS"
    event_gates = [
        gates["alt_events_ge_50"],
        gates["eth_events_ge_15"],
        gates["xrp_events_ge_15"],
    ]
    edge_gates = [
        gates["avg_excess_16_positive"],
        gates["avg_excess_24_positive"],
        gates["median_excess_16_non_negative"],
        gates["median_excess_24_non_negative"],
        gates["excess_win_rate_16_ge_52pct"],
        gates["mae_24_not_extreme"],
    ]
    alt_event_count = stats.get("alt_event_count", 0)
    h16_avg = stats.get("h16_avg_excess", 0.0)
    h24_avg = stats.get("h24_avg_excess", 0.0)
    h16_med = stats.get("h16_median_excess", 0.0)
    h24_med = stats.get("h24_median_excess", 0.0)
    if (
        alt_event_count >= 30
        and h16_avg < 0
        and h24_avg < 0
        and h16_med < 0
        and h24_med < 0
    ):
        return "STOP"
    failed_edge = sum(1 for g in edge_gates if not g)
    if all(event_gates) and 1 <= failed_edge <= 3:
        return "REVISE"
    return "HOLD"


def recommendation_for(label: str) -> str:
    if label == "PASS":
        return "Implement regime_relative_breakout_30m strategy next."
    if label == "REVISE":
        return "Revise thresholds within bounded ranges; no strategy implementation yet."
    if label == "STOP":
        return "Reject this signal family; do not build regime_relative_breakout_30m."
    return "Event count insufficient or edge mixed; expand tickers or adjust event definition before strategy."


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def _score_condition_set(alt_only: dict[str, Any]) -> float:
    h = alt_only["horizons"]
    return (
        h["16"]["avg_excess_return"] * 0.35
        + h["24"]["avg_excess_return"] * 0.35
        + h["16"]["median_excess_return"] * 0.15
        + h["24"]["median_excess_return"] * 0.15
    )


def rank_condition_sets(results: dict[str, Any]) -> list[str]:
    viable = [(name, r) for name, r in results.items() if r["alt_only"]["event_count"] >= 30]
    pool = viable if viable else list(results.items())
    ranked = sorted(pool, key=lambda kv: _score_condition_set(kv[1]["alt_only"]), reverse=True)
    return [name for name, _ in ranked]


# ---------------------------------------------------------------------------
# Sample row extraction + JSON helpers
# ---------------------------------------------------------------------------


def _row_to_sample(ticker: str, ts: pd.Timestamp, row: pd.Series) -> dict[str, Any]:
    def _num(key: str) -> float | None:
        v = row.get(key)
        if v is None:
            return None
        if isinstance(v, float) and np.isnan(v):
            return None
        if hasattr(v, "item"):
            try:
                return v.item()
            except (ValueError, TypeError):
                return float(v)
        return float(v)

    regime = row.get("btc_daily_regime_on")
    regime_bool: bool | None
    if regime is None or (isinstance(regime, float) and np.isnan(regime)):
        regime_bool = None
    else:
        regime_bool = bool(regime)

    return {
        "ticker": ticker,
        "timestamp": ts.isoformat() if isinstance(ts, pd.Timestamp) else str(ts),
        "close": _num("close"),
        "btc_daily_regime_on": regime_bool,
        "target_rs_24h_vs_btc": _num("target_rs_24h_vs_btc"),
        "target_rs_7d_vs_btc": _num("target_rs_7d_vs_btc"),
        "volume_ratio": _num("volume_ratio"),
        "hourly_pullback_return_8": _num("hourly_pullback_return_8"),
        "fwd_ret_16": _num("fwd_ret_16"),
        "fwd_excess_ret_16": _num("fwd_excess_ret_16"),
        "mfe_24": _num("mfe_24"),
        "mae_24": _num("mae_24"),
    }


def _json_default(o: Any) -> Any:
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(f"not serializable: {type(o)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _slice_window(df: pd.DataFrame, days: int) -> pd.DataFrame:
    if df.empty:
        return df
    start = df.index.max() - pd.Timedelta(days=days)
    return df.loc[df.index >= start].copy()


def _evaluate_condition_set(
    cs_name: str,
    enriched: dict[str, pd.DataFrame],
    regime_ticker: str,
) -> dict[str, Any]:
    by_ticker: dict[str, Any] = {}
    all_events: list[pd.DataFrame] = []
    alt_events: list[pd.DataFrame] = []
    total_raw = 0
    alt_raw = 0
    for ticker, df in enriched.items():
        masks = condition_masks(df)
        raw_mask = masks[cs_name]
        deduped = dedupe_events(raw_mask, EVENT_COOLDOWN_BARS)
        events_df = df.loc[deduped].copy()
        events_df["ticker"] = ticker
        raw_count = int(raw_mask.sum())
        by_ticker[ticker] = summarize_events(events_df, raw_count=raw_count)
        all_events.append(events_df)
        total_raw += raw_count
        if ticker != regime_ticker:
            alt_events.append(events_df)
            alt_raw += raw_count
    overall_df = pd.concat(all_events) if all_events else pd.DataFrame()
    alt_df = pd.concat(alt_events) if alt_events else pd.DataFrame()
    overall = summarize_events(overall_df, raw_count=total_raw)
    alt_only = summarize_events(alt_df, raw_count=alt_raw)

    samples: list[dict[str, Any]] = []
    for df_ in all_events:
        if df_.empty:
            continue
        for ts, row in df_.head(SAMPLE_CAP).iterrows():
            samples.append(_row_to_sample(str(row["ticker"]), ts, row))
            if len(samples) >= SAMPLE_CAP:
                break
        if len(samples) >= SAMPLE_CAP:
            break

    return {
        "overall": overall,
        "alt_only": alt_only,
        "by_ticker": by_ticker,
        "samples": samples,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=TICKERS)
    parser.add_argument("--regime-ticker", default=REGIME_TICKER)
    parser.add_argument("--fetch-days", type=int, default=FETCH_DAYS)
    parser.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--interval", default=INTERVAL)
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)

    print(f"fetch {args.interval} for {args.tickers} (fetch_days={args.fetch_days})")
    thirty = {t: _fetch_ohlcv(t, args.interval, args.fetch_days) for t in args.tickers}
    print(f"fetch minute60 for {args.tickers}")
    hourly = {t: _fetch_ohlcv(t, "minute60", args.fetch_days) for t in args.tickers}
    print(f"fetch day for {args.regime_ticker}")
    btc_daily = _fetch_ohlcv(args.regime_ticker, "day", args.fetch_days)

    if args.regime_ticker in thirty:
        btc_30m = thirty[args.regime_ticker]
    else:
        btc_30m = _fetch_ohlcv(args.regime_ticker, args.interval, args.fetch_days)

    enriched: dict[str, pd.DataFrame] = {}
    for ticker in args.tickers:
        target = thirty[ticker]
        btc_aligned = btc_30m.reindex(target.index).ffill()
        hourly_feats = _compute_hourly_features(hourly[ticker])
        hourly_proj = project_higher_timeframe_features(hourly_feats, target.index)
        btc_regime_30m = _btc_daily_regime_projection(btc_daily, target.index)
        full = _enrich_target(target, btc_aligned, hourly_proj, btc_regime_30m)
        enriched[ticker] = _slice_window(full, args.lookback_days)

    results: dict[str, Any] = {}
    for cs_name in CONDITION_SET_NAMES:
        results[cs_name] = _evaluate_condition_set(cs_name, enriched, args.regime_ticker)

    ranked = rank_condition_sets(results)
    best_cs = ranked[0] if ranked else CONDITION_SET_NAMES[0]
    best_alt = results[best_cs]["alt_only"]
    by = results[best_cs]["by_ticker"]
    alt_count = best_alt["event_count"]
    eth_count = by.get("KRW-ETH", {}).get("event_count", 0)
    xrp_count = by.get("KRW-XRP", {}).get("event_count", 0)
    h16 = best_alt["horizons"]["16"]
    h24 = best_alt["horizons"]["24"]
    p24 = best_alt["path"]["24"]
    gates = {
        "alt_events_ge_50": alt_count >= 50,
        "eth_events_ge_15": eth_count >= 15,
        "xrp_events_ge_15": xrp_count >= 15,
        "avg_excess_16_positive": h16["avg_excess_return"] > 0,
        "avg_excess_24_positive": h24["avg_excess_return"] > 0,
        "median_excess_16_non_negative": h16["median_excess_return"] >= 0,
        "median_excess_24_non_negative": h24["median_excess_return"] >= 0,
        "excess_win_rate_16_ge_52pct": h16["excess_win_rate"] >= 0.52,
        "mae_24_not_extreme": p24["avg_mae"] > -0.035,
    }
    stats = {
        "alt_event_count": alt_count,
        "h16_avg_excess": h16["avg_excess_return"],
        "h24_avg_excess": h24["avg_excess_return"],
        "h16_median_excess": h16["median_excess_return"],
        "h24_median_excess": h24["median_excess_return"],
    }
    label = classify_verdict(gates, stats)
    recommendation = recommendation_for(label)

    report = {
        "as_of": AS_OF,
        "study": "regime_relative_strength_event_study",
        "scope": "event-study only; no strategy/live/walk-forward",
        "tickers": args.tickers,
        "regime_ticker": args.regime_ticker,
        "interval": args.interval,
        "fetch_days": args.fetch_days,
        "lookback_days": args.lookback_days,
        "forward_bars": FORWARD_BARS,
        "path_horizons": PATH_HORIZONS,
        "event_cooldown_bars": EVENT_COOLDOWN_BARS,
        "condition_sets": CONDITION_SET_DEFINITIONS,
        "results": results,
        "ranked_condition_sets": ranked,
        "best_condition_set": best_cs,
        "verdict": {
            "label": label,
            "gates": gates,
            "stats": stats,
            "recommendation": recommendation,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n"
    )
    print(args.out)
    print(
        json.dumps(
            {
                "best_condition_set": best_cs,
                "verdict": report["verdict"],
            },
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
