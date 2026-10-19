"""Manual stock research scan. No brokerage or order-placement functionality."""
import json
import os
import sys
import requests
from datetime import datetime, timezone
from pathlib import Path

from stock_provider import ProviderError, fetch_daily_bars
from stock_research import evaluate_daily_bars

OUT = Path("stock_research_results.json")


def main():
    symbols = [s.strip().upper() for s in os.getenv("STOCK_SYMBOLS", "AAPL,MSFT,NVDA,AMZN,GOOGL,SPY,QQQ").split(",") if s.strip()]
    if len(symbols) > 50:
        print("Refusing to scan more than 50 symbols per run to limit free-provider load.")
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
        "provider": "Yahoo Finance public chart endpoint (unofficial; no API key)",
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
    # Optional Telegram summary; the scan still produces an artifact if Telegram is unset.
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        lines = [
            "📊 FREE STOCK SCAN — PAPER RESEARCH ONLY",
            f"Scanned: {len(symbols)} symbols | Strict: {report['qualified_count']} | Watchlist: {report['watchlist_count']}",
            "No orders placed. Scores are rule confluence, not win probabilities.",
        ]
        if ranked:
            lines.append("Top research candidates:")
            for item in ranked[:5]:
                missing = ", ".join(item.get("missing_confirmations", [])) or "none"
                lines.append(f"• {item['symbol']}: {item.get('status')} — {item.get('score', 0)}/100; missing: {missing}")
        else:
            lines.append("No valid candidates ranked. Check provider errors/artifact.")
        lines.append("Data source is an unofficial free endpoint; coverage and freshness can vary.")
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": "\n".join(lines), "disable_web_page_preview": True},
                timeout=(4, 10),
            )
            response.raise_for_status()
            if not response.json().get("ok"):
                raise ValueError("Telegram API returned ok=false")
            print("Telegram stock summary sent.")
        except (requests.RequestException, ValueError) as exc:
            print(f"Telegram notification failed ({type(exc).__name__}); artifact still contains results.")
    else:
        print("Telegram secrets not configured; results remain available as workflow artifact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
