"""Five-year approximate historical backtest for Binance USDT spot setups.

Uses current high-volume symbols (survivorship bias), historical hourly candles,
and approximates 4h/daily candles from hourly data. Historical order-book depth
and spread are unavailable, so this is NOT an exact replay of live scanner alerts.
No orders are placed.
"""
import csv, math, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
import scanner

BASE = "https://data-api.binance.vision"
YEARS = 5
MAX_SYMBOLS = 15
FEE_RATE = 0.001  # illustrative 0.1% each side; change to match your fee tier
SLIPPAGE_RATE = 0.0005  # illustrative 0.05% each side
MAX_HOLD_HOURS = 72
OUT = Path("backtest_results.csv")
S = requests.Session()
S.headers.update({"User-Agent": "telegram-crypto-scanner-backtest/1.0"})

def api(path, params=None):
    for attempt in range(5):
        try:
            r = S.get(BASE + path, params=params, timeout=(5, 20))
            if r.status_code in (418, 429) or r.status_code >= 500:
                time.sleep(2 + attempt * 2)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == 4:
                raise
            time.sleep(2 + attempt * 2)
    raise RuntimeError("Binance API unavailable after retries")

def history(symbol, start_ms):
    rows, cursor = [], start_ms
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    while cursor < now_ms:
        batch = api("/api/v3/klines", {
            "symbol": symbol, "interval": "1h", "startTime": cursor,
            "endTime": now_ms, "limit": 1000
        })
        if not batch:
            break
        for k in batch:
            try:
                row = {"time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
                       "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
                if all(math.isfinite(row[x]) for x in ("open","high","low","close","volume")) and row["low"] > 0 and row["volume"] >= 0:
                    rows.append(row)
            except (ValueError, TypeError, IndexError):
                continue
        next_cursor = int(batch[-1][0]) + 3600000
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < 1000:
            break
        time.sleep(0.12)
    # Deduplicate by candle open time, keep only closed candles.
    cutoff = int(datetime.now(timezone.utc).timestamp() * 1000) - 3600000
    return [v for _, v in sorted({x["time"]: x for x in rows if x["time"] <= cutoff}.items())]

def aggregate(rows, hours):
    out = []
    if not rows:
        return out
    bucket = None
    group = []
    for row in rows:
        key = row["time"] // (hours * 3600000)
        if bucket is not None and key != bucket:
            if len(group) == hours:
                out.append({"time": group[-1]["time"], "open": group[0]["open"],
                            "high": max(x["high"] for x in group), "low": min(x["low"] for x in group),
                            "close": group[-1]["close"], "volume": sum(x["volume"] for x in group)})
            group = []
        bucket = key
        group.append(row)
    if len(group) == hours:
        out.append({"time": group[-1]["time"], "open": group[0]["open"],
                    "high": max(x["high"] for x in group), "low": min(x["low"] for x in group),
                    "close": group[-1]["close"], "volume": sum(x["volume"] for x in group)})
    return out

def backtest_symbol(symbol, rows, btc_rows):
    # Index BTC closes by hourly candle timestamp for relative-strength comparison.
    btc_by_time = {r["time"]: r["close"] for r in btc_rows}
    h4, d1 = aggregate(rows, 4), aggregate(rows, 24)
    h4_by_time = {r["time"]: i for i, r in enumerate(h4)}
    d1_by_time = {r["time"]: i for i, r in enumerate(d1)}
    trades, i = [], 120
    while i < len(rows) - 2:
        r = rows[i]
        # Avoid lookahead: higher timeframe bars must have closed at/before signal time.
        h4i = max((j for t, j in h4_by_time.items() if t <= r["time"]), default=-1)
        d1i = max((j for t, j in d1_by_time.items() if t <= r["time"]), default=-1)
        if h4i < 50 or d1i < 50:
            i += 1; continue
        hourly = rows[max(0, i-79):i+1]
        c1 = [x["close"] for x in hourly]
        c4 = [x["close"] for x in h4[max(0,h4i-79):h4i+1]]
        cd = [x["close"] for x in d1[max(0,d1i-79):d1i+1]]
        if min(len(c1),len(c4),len(cd)) < 50:
            i += 1; continue
        # Closed hourly candle at i; all indicators use data through i.
        rsi = scanner.rsi(c1)
        prior = rows[max(0,i-20):i]
        if len(prior) < 20:
            i += 1; continue
        breakout = (r["close"] / max(x["high"] for x in prior) - 1) * 100
        avg_vol = sum(x["volume"] for x in prior) / len(prior)
        vol_ratio = r["volume"] / avg_vol if avg_vol else 0
        btc_now, btc_prev = btc_by_time.get(r["time"]), btc_by_time.get(r["time"] - 24*3600000)
        rs = 0
        if btc_now and btc_prev and btc_prev > 0:
            rs = ((r["close"] / rows[i-24]["close"] - 1) -
                  (btc_now / btc_prev - 1)) * 100 if i >= 24 and rows[i-24]["close"] > 0 else 0
        trend = (scanner.ema(c1,20) > scanner.ema(c1,50) and r["close"] > scanner.ema(c1,20)
                 and scanner.ema(c4,20) > scanner.ema(c4,50) and c4[-1] > scanner.ema(c4,20)
                 and scanner.ema(cd,20) > scanner.ema(cd,50) and cd[-1] > scanner.ema(cd,20))
        if not (trend and rsi is not None and 52 <= rsi <= 68 and 0 <= breakout <= 1.2
                and vol_ratio >= 1.3 and rs >= 1.5):
            i += 1; continue
        entry_i = i + 1
        entry = rows[entry_i]["open"] * (1 + SLIPPAGE_RATE)
        stop = min(x["low"] for x in rows[max(0,i-4):i+1])
        risk = entry - stop
        if stop <= 0 or not 0.005 <= risk / entry <= 0.03:
            i += 1; continue
        target = entry + 2 * risk
        exit_i, exit_price, reason = min(len(rows)-1, entry_i+MAX_HOLD_HOURS), None, "time"
        for j in range(entry_i, min(len(rows), entry_i+MAX_HOLD_HOURS+1)):
            # Conservative rule: if stop and target are both touched in one candle, assume stop first.
            if rows[j]["low"] <= stop:
                exit_i, exit_price, reason = j, stop * (1 - SLIPPAGE_RATE), "stop"
                break
            if rows[j]["high"] >= target:
                exit_i, exit_price, reason = j, target * (1 - SLIPPAGE_RATE), "target"
                break
        if exit_price is None:
            exit_price = rows[exit_i]["close"] * (1 - SLIPPAGE_RATE)
        gross = exit_price / entry - 1
        net = gross - 2 * FEE_RATE
        trades.append({"symbol":symbol, "entry_time":datetime.fromtimestamp(rows[entry_i]["time"]/1000,timezone.utc).isoformat(),
                       "exit_time":datetime.fromtimestamp(rows[exit_i]["time"]/1000,timezone.utc).isoformat(),
                       "entry":round(entry,10), "exit":round(exit_price,10), "reason":reason,
                       "gross_return_pct":round(gross*100,4), "net_return_pct":round(net*100,4),
                       "win":int(net > 0), "bars_held":exit_i-entry_i})
        i = exit_i + 1  # one position at a time per symbol
    return trades

def main():
    start = int((datetime.now(timezone.utc) - timedelta(days=365.25*YEARS)).timestamp()*1000)
    tickers = api("/api/v3/ticker/24hr")
    info = api("/api/v3/exchangeInfo")
    valid = {x["symbol"] for x in info.get("symbols",[]) if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("isSpotTradingAllowed",True)}
    excluded = {"USDC","FDUSD","TUSD","USDP","DAI","USDE","BUSD","EUR","TRY","BRL","USTC"}
    universe = []
    for t in tickers:
        sym = t.get("symbol","")
        try: vol = float(t["quoteVolume"])
        except (ValueError,TypeError,KeyError): continue
        base = sym[:-4] if sym.endswith("USDT") else ""
        if sym in valid and base and base not in excluded and not base.endswith(("UP","DOWN","BULL","BEAR")) and vol >= 3_000_000:
            universe.append((vol,sym))
    symbols = [s for _,s in sorted(universe,reverse=True)[:MAX_SYMBOLS]]
    if "BTCUSDT" not in symbols:
        symbols[-1:] = ["BTCUSDT"]
    print(f"Downloading up to {YEARS} years of hourly candles for {len(symbols)} currently liquid USDT spot pairs...")
    print("This can take a while and is an approximate backtest, not a replay of historical order books.")
    all_rows, errors = {}, []
    for idx, sym in enumerate(symbols,1):
        try:
            all_rows[sym] = history(sym,start)
            print(f"[{idx}/{len(symbols)}] {sym}: {len(all_rows[sym])} hourly candles")
        except Exception as e:
            errors.append((sym,type(e).__name__))
            print(f"[{idx}/{len(symbols)}] {sym}: download failed ({type(e).__name__})")
    btc = all_rows.get("BTCUSDT",[])
    if not btc:
        raise SystemExit("Cannot backtest: BTCUSDT historical candles unavailable.")
    results = []
    for sym, rows in all_rows.items():
        if sym == "BTCUSDT": continue
        results.extend(backtest_symbol(sym,rows,btc))
    fields = ["symbol","entry_time","exit_time","entry","exit","reason","gross_return_pct","net_return_pct","win","bars_held"]
    with OUT.open("w",newline="",encoding="utf-8") as f:
        w = csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(results)
    n = len(results)
    wins = sum(t["win"] for t in results)
    gross_wins = [t["net_return_pct"] for t in results if t["net_return_pct"] > 0]
    gross_losses = [t["net_return_pct"] for t in results if t["net_return_pct"] < 0]
    profit_factor = sum(gross_wins)/abs(sum(gross_losses)) if gross_losses else (float("inf") if gross_wins else 0)
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for t in sorted(results,key=lambda x:x["exit_time"]):
        equity *= 1 + t["net_return_pct"]/100
        peak = max(peak,equity)
        max_dd = max(max_dd,(peak-equity)/peak if peak else 0)
    print("\n=== FIVE-YEAR APPROXIMATE BACKTEST ===")
    print(f"Data window: {datetime.fromtimestamp(start/1000,timezone.utc).date()} to {datetime.now(timezone.utc).date()}")
    print(f"Pairs with data: {len(all_rows)}; failed downloads: {len(errors)}")
    print(f"Completed simulated trades: {n}")
    print(f"Win rate: {wins/n*100:.2f}%" if n else "Win rate: n/a (no trades)")
    print(f"Net compounded return across sequential per-symbol trades: {(equity-1)*100:.2f}%")
    print(f"Profit factor (net trade returns): {profit_factor:.3f}")
    print(f"Max drawdown of pooled trade sequence: {max_dd*100:.2f}%")
    print(f"Average net trade: {sum(t['net_return_pct'] for t in results)/n:.3f}%" if n else "Average net trade: n/a")
    print(f"CSV saved to: {OUT}")
    print("\nIMPORTANT: current top-volume universe creates survivorship bias; order-book filters, historic delistings, token news, and true fill/slippage are not reconstructed. Results are exploratory, not proof of future profitability.")
if __name__ == "__main__":
    main()
