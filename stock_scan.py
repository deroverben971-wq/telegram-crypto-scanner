"""Manual stock research scan. No brokerage or order-placement functionality."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from stock_provider import ProviderError, fetch_daily_bars
from stock_research import evaluate_daily_bars

OUT = Path("stock_research_results.json")


def main():
    symbols = [s.strip().upper() for s in os.getenv("STOCK_SYMBOLS", "AAPL,MSFT,NVDA,AMZN,GOOGL,SPY,QQQ").split(",") if s.strip()]
    if len(symbols) > 20:
        print("Refusing to scan more than 20 symbols per run to limit API usage.")
        return 2
    symbols = list(dict.fromkeys(symbols))
    results = []
    for symbol in symbols:
        try:
            bars = fetch_daily_bars(symbol)
            result = evaluate_daily_bars(bars)
            results.append({"symbol": symbol, **result})
            print(f"{symbol}: {result['status']} ({result.get('checks_passed', 0)}/{result.get('checks_total', 0)} checks)")
        except ProviderError as exc:
            results.append({"symbol": symbol, "status": "DATA_UNAVAILABLE", "reason": str(exc)})
            print(f"{symbol}: DATA_UNAVAILABLE — {exc}")
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER RESEARCH ONLY — no orders placed",
        "provider": "Alpha Vantage TIME_SERIES_DAILY_ADJUSTED",
        "symbols_requested": symbols,
        "results": results,
        "qualified_count": sum(x.get("status") == "STRICT_RESEARCH_CANDIDATE" for x in results),
        "warning": "Provider coverage, entitlement, price adjustments, volume, costs, and corporate actions require validation. A screen is not a forecast.",
    }
    OUT.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(f"\nQualified research candidates: {report['qualified_count']}")
    print(f"Results written to {OUT}; no trades or Telegram alerts are sent by this prototype.")
    if not os.getenv("ALPHAVANTAGE_API_KEY", "").strip():
        print("Set repository secret ALPHAVANTAGE_API_KEY before running.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
