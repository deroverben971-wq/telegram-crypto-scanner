"""Alpha Vantage daily adjusted data adapter for paper research only.

TIME_SERIES_DAILY_ADJUSTED is a premium endpoint. This adapter fails closed
when the key lacks access, rather than silently substituting incomplete data.
"""
import math
import os
import requests

BASE = "https://www.alphavantage.co/query"


class ProviderError(RuntimeError):
    pass


def fetch_daily_bars(symbol, api_key=None, session=requests):
    key = (api_key or os.getenv("ALPHAVANTAGE_API_KEY", "")).strip()
    if not key:
        raise ProviderError("Missing ALPHAVANTAGE_API_KEY secret")
    symbol = str(symbol).strip().upper()
    if not symbol or len(symbol) > 24 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_" for c in symbol):
        raise ProviderError("Invalid symbol")
    try:
        response = session.get(BASE, params={
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": symbol,
            "outputsize": "full",
            "apikey": key,
        }, timeout=(4, 15))
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError(f"Provider request failed ({type(exc).__name__})") from None
    if not isinstance(payload, dict):
        raise ProviderError("Provider returned malformed JSON")
    if any(k in payload for k in ("Note", "Information", "Error Message")):
        message = str(payload.get("Note") or payload.get("Information") or payload.get("Error Message"))
        raise ProviderError("Provider did not return data (rate limit, entitlement, or symbol issue): " + message[:180])
    series_key = "Time Series (Daily)"
    series = payload.get(series_key)
    if not isinstance(series, dict) or not series:
        raise ProviderError("No daily series returned; symbol coverage or API entitlement is unverified")
    bars = []
    for date, item in sorted(series.items()):
        try:
            close = float(item["4. close"])
            adjusted_close = float(item["5. adjusted close"])
            factor = adjusted_close / close
            o, h, low = (float(item[k]) * factor for k in ("1. open", "2. high", "3. low"))
            c = adjusted_close
            volume = float(item["6. volume"])
            if not all(math.isfinite(x) for x in (o, h, low, c, volume)):
                continue
            if min(o, h, low, c) <= 0 or volume < 0 or h < max(o, c, low) or low > min(o, c):
                continue
            bars.append({"date": date, "open": o, "high": h, "low": low, "close": c, "volume": volume})
        except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
            continue
    if len(bars) < 220:
        raise ProviderError(f"Only {len(bars)} valid daily bars returned; need at least 220")
    return bars
