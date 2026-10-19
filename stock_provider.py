"""No-key Yahoo Finance chart adapter for paper-research-only daily OHLCV.

This uses an unofficial public endpoint: availability, coverage, and terms can
change without notice. It is not an exchange-licensed feed or guaranteed SLA.
"""
import math
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests

BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"


class ProviderError(RuntimeError):
    pass


def fetch_daily_bars(symbol, api_key=None, session=requests):
    """Fetch up to five years of daily bars without a paid API key.

    US tickers use their normal symbol (AAPL); Yahoo-listed Philippine tickers
    commonly use the .PS suffix (for example, AC.PS). Coverage must be checked
    per symbol; unsupported or stale tickers fail closed.
    """
    symbol = str(symbol).strip().upper()
    if not symbol or len(symbol) > 32 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_^=" for c in symbol):
        raise ProviderError("Invalid symbol; use a ticker such as AAPL or a Yahoo suffix such as AC.PS")
    now = int(time.time())
    params = {
        "period1": now - 5 * 366 * 24 * 60 * 60,
        "period2": now,
        "interval": "1d",
        "events": "div,splits",
        "includeAdjustedClose": "true",
    }
    try:
        response = session.get(
            BASE + quote(symbol, safe=".-_^="),
            params=params,
            headers={"User-Agent": "Mozilla/5.0 (compatible; paper-stock-screener/1.0)"},
            timeout=(4, 15),
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError(f"Free market-data request failed ({type(exc).__name__})") from None
    if not isinstance(payload, dict):
        raise ProviderError("Provider returned malformed JSON")
    chart = payload.get("chart")
    if not isinstance(chart, dict) or chart.get("error"):
        error = chart.get("error") if isinstance(chart, dict) else None
        description = error.get("description", "unknown symbol or unavailable data") if isinstance(error, dict) else "unknown symbol or unavailable data"
        raise ProviderError(f"Free data unavailable for {symbol}: {str(description)[:160]}")
    results = chart.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise ProviderError(f"No daily data returned for {symbol}")
    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote_sets = indicators.get("quote") or []
    if not timestamps or not quote_sets or not isinstance(quote_sets[0], dict):
        raise ProviderError(f"Missing OHLCV series for {symbol}")
    q = quote_sets[0]
    adj_sets = indicators.get("adjclose") or []
    adj = adj_sets[0].get("adjclose", []) if adj_sets and isinstance(adj_sets[0], dict) else []
    fields = {key: q.get(key, []) for key in ("open", "high", "low", "close", "volume")}
    bars = []
    for i, stamp in enumerate(timestamps):
        try:
            close = float(fields["close"][i])
            adjusted_close = float(adj[i]) if i < len(adj) and adj[i] is not None else close
            if not math.isfinite(close) or close <= 0 or not math.isfinite(adjusted_close) or adjusted_close <= 0:
                continue
            factor = adjusted_close / close
            o, h, low = (float(fields[k][i]) * factor for k in ("open", "high", "low"))
            c = adjusted_close
            volume = float(fields["volume"][i])
            if not all(math.isfinite(x) for x in (o, h, low, c, volume)):
                continue
            if min(o, h, low, c) <= 0 or volume < 0 or h < max(o, c, low) or low > min(o, c):
                continue
            date = datetime.fromtimestamp(int(stamp), tz=timezone.utc).date().isoformat()
            bars.append({"date": date, "open": o, "high": h, "low": low, "close": c, "volume": volume})
        except (IndexError, TypeError, ValueError, OverflowError, OSError):
            continue
    bars.sort(key=lambda row: row["date"])
    if len(bars) < 220:
        raise ProviderError(f"Only {len(bars)} valid daily bars returned for {symbol}; need at least 220")
    # Fail closed for stale feeds; PSE/US holiday gaps are normal, but a bar
    # older than 10 calendar days usually indicates unsupported/stale coverage.
    latest_date = datetime.strptime(bars[-1]["date"], "%Y-%m-%d").date()
    if (datetime.now(timezone.utc).date() - latest_date).days > 10:
        raise ProviderError(f"Latest bar for {symbol} is stale ({bars[-1]['date']})")
    return bars
