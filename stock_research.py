"""Paper-research-only stock screening and candidate ranking; never places orders."""
from __future__ import annotations

import math
from typing import Iterable

MIN_DAILY_BARS = 220
WATCHLIST_MIN_CHECKS = 3


def ema(values: list[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2 / (period + 1)
    for item in values[period:]:
        value = alpha * item + (1 - alpha) * value
    return value


def evaluate_daily_bars(bars: Iterable[dict]) -> dict:
    """Rank a stock from 0-5 checks while preserving strict confirmation.

    Input bars must be chronological, split-adjusted daily OHLCV. Three or
    four checks creates a WATCHLIST_CANDIDATE, never a confirmed setup.
    """
    rows = list(bars)
    if len(rows) < MIN_DAILY_BARS:
        return {"status": "INSUFFICIENT_DATA", "reason": f"Need at least {MIN_DAILY_BARS} daily bars"}
    previous = None
    for row in rows:
        try:
            o, h, low, c, v = (float(row[k]) for k in ("open", "high", "low", "close", "volume"))
            if not all(math.isfinite(x) for x in (o, h, low, c, v)):
                raise ValueError
            if min(o, h, low, c) <= 0 or v < 0 or h < max(o, c, low) or low > min(o, c):
                raise ValueError
            if previous is not None and str(row["date"]) <= previous:
                raise ValueError
            previous = str(row["date"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return {"status": "INVALID_DATA", "reason": "Malformed, non-finite, or non-chronological OHLCV bars"}

    closes = [float(x["close"]) for x in rows]
    volumes = [float(x["volume"]) for x in rows]
    fast, medium, slow = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    latest = closes[-1]
    average_volume = sum(volumes[-20:-1]) / 19
    volume_ratio = volumes[-1] / average_volume if average_volume > 0 else None
    prior_high = max(float(x["high"]) for x in rows[-21:-1])
    breakout_pct = (latest / prior_high - 1) * 100
    checks = {
        "price_above_20d_ema": latest > fast,
        "ema20_above_50": fast > medium,
        "ema50_above_200": medium > slow,
        "breakout_not_overextended": 0 <= breakout_pct <= 2.0,
        "volume_confirmation": volume_ratio is not None and volume_ratio >= 1.2,
    }
    passed = sum(checks.values())
    status = ("STRICT_RESEARCH_CANDIDATE" if passed == len(checks)
              else "WATCHLIST_CANDIDATE" if passed >= WATCHLIST_MIN_CHECKS
              else "NO_QUALIFIED_SETUP")
    missing = [name for name, ok in checks.items() if not ok]
    return {
        "status": status,
        "score": passed * 20,
        "date": str(rows[-1]["date"]),
        "close": latest,
        "ema20": fast,
        "ema50": medium,
        "ema200": slow,
        "breakout_pct": breakout_pct,
        "volume_ratio": volume_ratio,
        "checks": checks,
        "checks_passed": passed,
        "checks_total": len(checks),
        "missing_confirmations": missing,
        "note": "Daily-bar research screen only; scores rank rule confluence, not win probability or expected return.",
    }
