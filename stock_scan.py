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
            print(f"{symbol}: {result['status']} — score {result.get('score', 0)}/100 ({result.get('checks_passed', 0)}/{result.get('checks_total', 0)} checks)")
        except ProviderError as exc:
            results.append({"symbol": symbol, "status": "DATA_UNAVAILABLE", "reason": str(exc)})
            print(f"{symbol}: DATA_UNAVAILABLE — {exc}")

    ranked = sorted(
        (x for x in results if x.get("status") in {"STRICT_RESEARCH_CANDIDATE", "WATCHLIST_CANDIDATE", "NO_QUALIFIED_SETUP"}),
        key=lambda x: (x.get("checks_passed", 0), x.get("volume_ratio") or 0),
        reverse=True,
    )
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER RESEARCH ONLY — no orders placed",
        "provider": "Alpha Vantage TIME_SERIES_DAILY_ADJUSTED",
        "symbols_requested": symbols,
        "results": results,
        "ranked_candidates": ranked[:5],
        "qualified_count": sum(x.get("status") == "STRICT_RESEARCH_CANDIDATE" for x in results),
        "watchlist_count": sum(x.get("status") == "WATCHLIST_CANDIDATE" for x in results),
        "warning": "A ranked candidate is not a prediction. Provider coverage, entitlement, adjustments, liquidity, costs, and corporate actions require validation.",
    }
    OUT.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(f"\nStrict candidates: {report['qualified_count']}; watchlist candidates: {report['watchlist_count']}")
    if ranked:
        print("Top research candidates (not trade instructions):")
        for item in ranked[:5]:
            missing = ", ".join(item.get("missing_confirmations", [])) or "none"
            print(f"  {item['symbol']}: {item['status']} | {item.get('score', 0)}/100 | missing: {missing}")
    else:
        print("No valid stock results to rank; check provider access and data quality.")
    print(f"Results written to {OUT}; no trades or Telegram alerts are sent by this prototype.")
    if not os.getenv("ALPHAVANTAGE_API_KEY", "").strip():
        print("Set repository secret ALPHAVANTAGE_API_KEY before running.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
