"""Five-year approximate historical backtest for Binance USDT spot setups.

Uses current high-volume symbols (survivorship bias), historical hourly candles,
and approximates 4h/daily candles from hourly data. Historical order-book depth
and spread are unavailable, so this is NOT an exact replay of live scanner alerts.
No orders are placed.
"""
import csv, math, time, bisect
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
import scanner

BASE = "https://data-api.binance.vision"
YEARS = 5
MAX_SYMBOLS = 50
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
            if len(group) == hours and group[-1]["time"] - group[0]["time"] == (hours - 1) * 3600000:
                out.append({"time": group[-1]["time"] + 3600000, "open": group[0]["open"],
                            "high": max(x["high"] for x in group), "low": min(x["low"] for x in group),
                            "close": group[-1]["close"], "volume": sum(x["volume"] for x in group)})
            group = []
        bucket = key
        group.append(row)
    if len(group) == hours and group[-1]["time"] - group[0]["time"] == (hours - 1) * 3600000:
        out.append({"time": group[-1]["time"] + 3600000, "open": group[0]["open"],
                    "high": max(x["high"] for x in group), "low": min(x["low"] for x in group),
                    "close": group[-1]["close"], "volume": sum(x["volume"] for x in group)})
    return out

def latest_closed_bar_index(bar_times, signal_close_time):
    """Return the latest higher-timeframe bar index closed by signal_close_time."""
    return bisect.bisect_right(bar_times, signal_close_time) - 1


def btc_regime_aligned(btc_rows, btc_times, btc_h4, btc_h4_times, btc_d1, btc_d1_times, signal_close_time):
    """Mirror the live scanner's BTC 1h/4h/daily EMA regime gate without look-ahead."""
    btc_i = bisect.bisect_right(btc_times, signal_close_time - 3600000) - 1
    h4_i = latest_closed_bar_index(btc_h4_times, signal_close_time)
    d1_i = latest_closed_bar_index(btc_d1_times, signal_close_time)
    if btc_i < 50 or h4_i < 50 or d1_i < 50:
        return False
    c1 = [x["close"] for x in btc_rows[max(0, btc_i-79):btc_i+1]]
    c4 = [x["close"] for x in btc_h4[max(0, h4_i-79):h4_i+1]]
    cd = [x["close"] for x in btc_d1[max(0, d1_i-79):d1_i+1]]
    return (scanner.ema(c1,20) > scanner.ema(c1,50) and c1[-1] > scanner.ema(c1,20)
            and scanner.ema(c4,20) > scanner.ema(c4,50) and c4[-1] > scanner.ema(c4,20)
            and scanner.ema(cd,20) > scanner.ema(cd,50) and cd[-1] > scanner.ema(cd,20))


def backtest_symbol(symbol, rows, btc_rows, tier="strict"):
    """Backtest strict baseline or a clearly labeled relaxed research tier."""
    # Index BTC closes by hourly candle timestamp for relative-strength comparison.
    btc_by_time = {r["time"]: r["close"] for r in btc_rows}
    btc_h4, btc_d1 = aggregate(btc_rows, 4), aggregate(btc_rows, 24)
    btc_times = [x["time"] for x in btc_rows]
    btc_h4_times = [x["time"] for x in btc_h4]
    btc_d1_times = [x["time"] for x in btc_d1]
    h4, d1 = aggregate(rows, 4), aggregate(rows, 24)
    h4_times = [x["time"] for x in h4]
    d1_times = [x["time"] for x in d1]
    trades, i = [], 120
    while i < len(rows) - 2:
        r = rows[i]
        # Hourly timestamps are candle OPEN times. The signal uses the completed
        # hourly candle, so its information is available at open_time + 1 hour.
        # Only higher-timeframe bars closed by that instant may be used.
        signal_close_time = r["time"] + 3600000
        if not btc_regime_aligned(btc_rows, btc_times, btc_h4, btc_h4_times, btc_d1, btc_d1_times, signal_close_time):
            i += 1; continue
        h4i = latest_closed_bar_index(h4_times, signal_close_time)
        d1i = latest_closed_bar_index(d1_times, signal_close_time)
        if h4i < 50 or d1i < 50:
            i += 1; continue
        hourly = rows[max(0, i-79):i+1]
        c1 = [x["close"] for x in hourly]
        c4 = [x["close"] for x in h4[max(0,h4i-79):h4i+1]]
        cd = [x["close"] for x in d1[max(0,d1i-79):d1i+1]]
        if min(len(c1),len(c4),len(cd)) < 50:
            i += 1; continue
        # Higher-timeframe inputs must be contiguous too. A gap can otherwise
        # make an EMA appear to cover a shorter/irregular calendar window.        h4_window = h4[max(0, h4i-49):h4i+1]
        d1_window = d1[max(0, d1i-49):d1i+1]
        if (len(h4_window) < 50 or len(d1_window) < 50
                or any(h4_window[k]["time"]-h4_window[k-1]["time"] != 4*3600000 for k in range(1,len(h4_window)))
                or any(d1_window[k]["time"]-d1_window[k-1]["time"] != 24*3600000 for k in range(1,len(d1_window)))):
            i += 1; continue
        # Closed hourly candle at i; all indicators use data through i.
        rsi = scanner.rsi(c1)
        prior = rows[max(0,i-20):i]
        if len(prior) < 20:
            i += 1; continue
        breakout = (r["close"] / max(x["high"] for x in prior) - 1) * 100
        candle_range = r["high"] - r["low"]
        close_location = (r["close"] - r["low"]) / candle_range if candle_range > 0 else 0
        avg_vol = sum(x["volume"] for x in prior) / len(prior)
        vol_ratio = r["volume"] / avg_vol if avg_vol else 0
        # Require contiguous hourly data for the lookback windows. Do not silently
        # treat 24 array rows as 24 hours when an exchange candle is missing.
        hourly_times = [x["time"] for x in hourly]
        if any(hourly_times[k] - hourly_times[k-1] != 3600000 for k in range(1, len(hourly_times))):
            i += 1; continue
        btc_now = btc_by_time.get(r["time"])
        btc_prev = btc_by_time.get(r["time"] - 24*3600000)
        asset_prev = next((x["close"] for x in rows[max(0, i-30):i]
                           if x["time"] == r["time"] - 24*3600000), None)
        rs = 0
        if btc_now is not None and btc_prev is not None and btc_prev > 0 and asset_prev is not None and asset_prev > 0:
            rs = ((r["close"] / asset_prev - 1) -
                  (btc_now / btc_prev - 1)) * 100
        trend_1h4h = (scanner.ema(c1,20) > scanner.ema(c1,50) and r["close"] > scanner.ema(c1,20)
                      and scanner.ema(c4,20) > scanner.ema(c4,50) and c4[-1] > scanner.ema(c4,20))
        trend_daily = scanner.ema(cd,20) > scanner.ema(cd,50) and cd[-1] > scanner.ema(cd,20)
        if tier == "strict":
            passes = (trend_1h4h and trend_daily and rsi is not None and 52 <= rsi <= 68
                      and 0 <= breakout <= 1.2 and vol_ratio >= 1.3 and rs >= 1.5
                      and close_location >= 0.65)
        elif tier == "relaxed":
            # Research-only candidate: 1h/4h trend, looser momentum/volume/RS filters.
            # Daily trend is recorded by tier comparison but not required here.
            passes = (trend_1h4h and rsi is not None and 48 <= rsi <= 72
                      and 0 <= breakout <= 1.8 and vol_ratio >= 1.1 and rs >= 0.0
                      and close_location >= 0.55)
        else:
            raise ValueError("tier must be 'strict' or 'relaxed'")
        if not passes:
            i += 1; continue
        entry_i = i + 1
        # Live scanner rejects a scan price that has drifted >0.75% from the
        # last closed 1h candle. The next candle open is the closest reproducible
        # historical proxy; this still cannot model intra-hour scan timing.
        next_open = rows[entry_i]["open"]
        if abs(next_open / r["close"] - 1) * 100 > 0.75:
            i += 1; continue
        entry = next_open * (1 + SLIPPAGE_RATE)
        stop = min(x["low"] for x in rows[max(0,i-5):i])
        risk = entry - stop
        if stop <= 0 or not 0.005 <= risk / entry <= 0.03:
            i += 1; continue
        target = entry + 2 * risk
        exit_i, exit_price, reason = min(len(rows)-1, entry_i+MAX_HOLD_HOURS), None, "time"
        for j in range(entry_i, min(len(rows), entry_i+MAX_HOLD_HOURS+1)):
            # Conservative rule: if stop and target are both touched in one candle, assume stop first.
            # A gap below the stop fills at the candle open, not magically at the stop price.
            if rows[j]["low"] <= stop:
                stop_reference = min(stop, rows[j]["open"])
                exit_i, exit_price, reason = j, stop_reference * (1 - SLIPPAGE_RATE), "stop"
                break
            if rows[j]["high"] >= target:
                exit_i, exit_price, reason = j, target * (1 - SLIPPAGE_RATE), "target"
                break
        if exit_price is None:
            exit_price = rows[exit_i]["close"] * (1 - SLIPPAGE_RATE)
        gross = exit_price / entry - 1
        net = gross - 2 * FEE_RATE
        trades.append({"symbol":symbol, "entry_time":datetime.fromtimestamp(rows[entry_i]["time"]/1000,timezone.utc).isoformat(),
                       "exit_time":datetime.fromtimestamp((rows[exit_i]["time"]+3600000)/1000,timezone.utc).isoformat(),
                       "entry":round(entry,10), "exit":round(exit_price,10), "reason":reason,
                       "gross_return_pct":round(gross*100,4), "net_return_pct":round(net*100,4),
                       "win":int(net > 0), "bars_held":exit_i-entry_i, "risk_pct":round(risk/entry*100,6)})
        i = exit_i + 1  # one position at a time per symbol
    return trades


def simulate_portfolio(trades, starting_equity=1000.0, risk_fraction=0.005, max_positions=3):
    """Event-driven approximation with fixed fractional risk and a concurrency cap.

    Realized P&L is applied in exit-time order. Position sizing is based on the
    stop-distance risk as a fraction of notional. This is not a full exchange
    simulator: capital constraints and correlated exposure remain simplified.
    """
    entries = []
    for t in trades:
        try:
            entry = datetime.fromisoformat(t["entry_time"]).timestamp()
            exit_ = datetime.fromisoformat(t["exit_time"]).timestamp()
            risk_pct = float(t["risk_pct"]) / 100.0
            net_pct = float(t["net_return_pct"]) / 100.0
            if exit_ < entry or risk_pct <= 0 or not math.isfinite(net_pct):
                continue
            entries.append({"entry_time": entry, "exit_time": exit_,
                            "risk_pct": risk_pct, "net_pct": net_pct})
        except (KeyError, ValueError, TypeError):
            continue
    entries.sort(key=lambda x: (x["entry_time"], x["exit_time"]))
    if starting_equity <= 0 or risk_fraction <= 0 or max_positions < 1:
        raise ValueError("starting_equity and risk_fraction must be positive; max_positions must be >= 1")
    equity = float(starting_equity)
    peak = equity
    max_dd = 0.0
    active = []
    taken = skipped = 0
    max_concurrent_positions = 0
    max_open_risk_cash = 0.0
    for trade in entries:
        still_active = []
        closed = []
        for pos in active:
            if pos["exit_time"] <= trade["entry_time"]:
                closed.append(pos)
            else:
                still_active.append(pos)
        active = still_active
        for pos in sorted(closed, key=lambda x: x["exit_time"]):
            equity += pos["risk_cash"] * pos["net_pct"] / pos["risk_pct"]
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)
        if len(active) >= max_positions:
            skipped += 1
            continue
        active.append({**trade, "risk_cash": equity * risk_fraction})
        taken += 1
        max_concurrent_positions = max(max_concurrent_positions, len(active))
        max_open_risk_cash = max(max_open_risk_cash, sum(p["risk_cash"] for p in active))
    for pos in sorted(active, key=lambda x: x["exit_time"]):
        equity += pos["risk_cash"] * pos["net_pct"] / pos["risk_pct"]
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)
    return {"ending_equity": equity, "net_return_pct": (equity / starting_equity - 1) * 100,
            "max_drawdown_pct": max_dd * 100, "trades_taken": taken, "trades_skipped": skipped,
            "max_concurrent_positions": max_concurrent_positions,
            "max_open_risk_cash": max_open_risk_cash,
            "drawdown_method": "closed-trade realized equity only; excludes unrealized intratrade drawdown"}

def period_summary(trades, label):
    n = len(trades)
    wins = sum(float(t["net_return_pct"]) > 0 for t in trades)
    pos = sum(float(t["net_return_pct"]) for t in trades if float(t["net_return_pct"]) > 0)
    neg = -sum(float(t["net_return_pct"]) for t in trades if float(t["net_return_pct"]) < 0)
    pf = pos / neg if neg else (float("inf") if pos else 0.0)
    avg = sum(float(t["net_return_pct"]) for t in trades) / n if n else 0.0
    print(f"{label}: trades={n}, win_rate={(wins/n*100 if n else 0):.2f}%, trade_PF={pf:.3f}, avg_net_trade={avg:.3f}%")
def eligible_backtest_symbol(symbol, valid_symbols, excluded_bases=None):
    """Filter stablecoin, leveraged, and known tokenized-equity symbols from the research universe."""
    excluded = excluded_bases or set()
    if not symbol.endswith("USDT") or symbol not in valid_symbols:
        return False
    base = symbol[:-4]
    if not base or base in excluded:
        return False
    if base.endswith(("UP", "DOWN", "BULL", "BEAR", "2L", "2S", "3L", "3S", "5L", "5S")):
        return False
    # Known Binance tokenized-equity / index proxy base assets, not ordinary crypto assets.
    if base in {"NVDAB", "TSLAB", "MSTRB", "CRCLB", "SNDKB", "SOXLB"}:
        return False
    return True



def chronological_splits(trades, start_ms, end_ms, purge_ms=MAX_HOLD_HOURS * 3600000):
    """Return development/validation/holdout trades with boundary-crossing trades purged.

    A trade is included only when its entry and exit are both inside the same
    chronological window. This prevents a position opened in one split from
    using an exit outcome that extends into the next split.
    """
    span = max(1, int(end_ms) - int(start_ms))
    cut1 = int(start_ms) + int(span * 0.60)
    cut2 = int(start_ms) + int(span * 0.80)
    # Purge a buffer around split boundaries as an extra guard against overlap.
    bounds = [(int(start_ms), cut1), (cut1, cut2), (cut2, int(end_ms) + 1)]
    buckets = [[], [], []]
    for trade in trades:
        try:
            entry = int(datetime.fromisoformat(trade["entry_time"]).timestamp() * 1000)
            exit_ = int(datetime.fromisoformat(trade["exit_time"]).timestamp() * 1000)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        for idx, (left, right) in enumerate(bounds):
            lower = left + (purge_ms if idx > 0 else 0)
            upper = right - (purge_ms if idx < 2 else 0)
            if lower <= entry < upper and entry <= exit_ < right:
                buckets[idx].append(trade)
                break
    return tuple(buckets)

def main():
    start = int((datetime.now(timezone.utc) - timedelta(days=365.25*YEARS)).timestamp()*1000)
    tickers = api("/api/v3/ticker/24hr")
    info = api("/api/v3/exchangeInfo")
    valid = {x["symbol"] for x in info.get("symbols",[]) if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("isSpotTradingAllowed",True)}
    excluded = {"USDC","FDUSD","TUSD","USDP","DAI","USDE","BUSD","USD1","RLUSD","EUR","TRY","BRL","USTC","XAUT"}
    universe = []
    for t in tickers:
        sym = t.get("symbol","")
        try: vol = float(t["quoteVolume"])
        except (ValueError,TypeError,KeyError): continue
        if eligible_backtest_symbol(sym, valid, excluded) and vol >= 3_000_000:
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
    results, relaxed_results = [], []
    for sym, rows in all_rows.items():
        if sym == "BTCUSDT": continue
        results.extend(backtest_symbol(sym,rows,btc,tier="strict"))
        relaxed_results.extend(backtest_symbol(sym,rows,btc,tier="relaxed"))
    fields = ["symbol","entry_time","exit_time","entry","exit","reason","gross_return_pct","net_return_pct","win","bars_held","risk_pct"]
    with OUT.open("w",newline="",encoding="utf-8") as f:
        w = csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(results)
    relaxed_out = OUT.with_name("backtest_relaxed_results.csv")
    with relaxed_out.open("w",newline="",encoding="utf-8") as f:
        w = csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(relaxed_results)
    n = len(results)
    wins = sum(t["win"] for t in results)
    gross_wins = [t["net_return_pct"] for t in results if t["net_return_pct"] > 0]
    gross_losses = [t["net_return_pct"] for t in results if t["net_return_pct"] < 0]
    profit_factor = sum(gross_wins)/abs(sum(gross_losses)) if gross_losses else (float("inf") if gross_wins else 0)
    portfolio = simulate_portfolio(results, starting_equity=1000.0, risk_fraction=0.005, max_positions=3)
    print("\n=== FIVE-YEAR APPROXIMATE BACKTEST ===")
    print(f"Data window: {datetime.fromtimestamp(start/1000,timezone.utc).date()} to {datetime.now(timezone.utc).date()}")
    print(f"Pairs with data: {len(all_rows)}; failed downloads: {len(errors)}")
    print(f"Completed simulated trades: {n}")
    print(f"Win rate: {wins/n*100:.2f}%" if n else "Win rate: n/a (no trades)")
    print("Portfolio starting equity: 1000.00 USDT; risk budget: 0.5% equity per trade; maximum concurrent positions: 3")
    print("Portfolio ending equity: {:.2f} USDT".format(portfolio["ending_equity"]))
    print("Portfolio net return: {:.2f}%".format(portfolio["net_return_pct"]))
    print("Portfolio max drawdown (realized closed-trade equity only; excludes open P&L): {:.2f}%".format(portfolio["max_drawdown_pct"]))
    print("Maximum concurrent positions: {}".format(portfolio["max_concurrent_positions"]))
    print("Maximum simultaneous planned stop-risk budget: {:.2f} USDT".format(portfolio["max_open_risk_cash"]))
    print("Portfolio trades taken / skipped at position cap: {} / {}".format(portfolio["trades_taken"], portfolio["trades_skipped"]))
    print(f"Profit factor (net trade returns): {profit_factor:.3f}")
    print("Note: trade-level profit factor is not a portfolio-level risk-adjusted metric.")
    print(f"Average net trade: {sum(t['net_return_pct'] for t in results)/n:.3f}%" if n else "Average net trade: n/a")
    # Chronological split with boundary purging to avoid cross-window outcomes.
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    train, valid_test, holdout = chronological_splits(results, start, end_ms)
    print("Boundary purge: trades must enter and exit inside one split; 72-hour buffer around split boundaries.")
    print("\n=== CHRONOLOGICAL VALIDATION (not independent if rules were tuned on all years) ===")
    period_summary(train, "Development 60%")
    period_summary(valid_test, "Validation 20%")
    period_summary(holdout, "Final holdout 20%")
    holdout_positive = sum(float(t["net_return_pct"]) for t in holdout if float(t["net_return_pct"]) > 0)
    holdout_negative = -sum(float(t["net_return_pct"]) for t in holdout if float(t["net_return_pct"]) < 0)
    holdout_pf = holdout_positive / holdout_negative if holdout_negative else (float("inf") if holdout_positive else 0.0)
    print("\n=== EVIDENCE GATE ===")
    if len(holdout) < 30:
        print(f"NOT VALIDATED: final holdout has only {len(holdout)} trades; too little evidence.")
    elif holdout_pf <= 1.0 or sum(float(t["net_return_pct"]) for t in holdout) <= 0:
        print(f"NOT VALIDATED: holdout profit factor={holdout_pf:.3f}; holdout net trade returns are not positive.")
    else:
        print(f"Preliminary pass only: holdout profit factor={holdout_pf:.3f}; this is not proof of future profitability.")
    print("\n=== FEE SENSITIVITY (per-side fee; same simulated entries/exits) ===")
    for fee in (0.001, 0.0015, 0.002):
        adjusted = [dict(t, net_return_pct=round(float(t["gross_return_pct"])-2*fee*100,4)) for t in results]
        p = simulate_portfolio(adjusted, starting_equity=1000.0, risk_fraction=0.005, max_positions=3)
        print(f"Fee {fee*100:.2f}% per side: portfolio return={p['net_return_pct']:.2f}%, max drawdown={p['max_drawdown_pct']:.2f}%, trades={p['trades_taken']}")
    print(f"CSV saved to: {OUT}")
    print(f"Relaxed research CSV saved to: {relaxed_out}")
    print("\n=== STRICT VS RELAXED COMPARISON ===")
    for label, sample in (("Strict baseline", results), ("Relaxed research tier", relaxed_results)):
        period_summary(sample, label + " overall")
        _, _, sample_holdout = chronological_splits(sample, start, end_ms)
        period_summary(sample_holdout, label + " holdout")
        if len(sample_holdout) < 30:
            print(f"{label}: NOT VALIDATED (fewer than 30 holdout trades)")
        else:
            wins_net = sum(float(t["net_return_pct"]) for t in sample_holdout if float(t["net_return_pct"]) > 0)
            losses_net = -sum(float(t["net_return_pct"]) for t in sample_holdout if float(t["net_return_pct"]) < 0)
            pf_net = wins_net / losses_net if losses_net else (float("inf") if wins_net else 0.0)
            print(f"{label}: holdout net PF={pf_net:.3f}; aggregate net trade return={sum(float(t['net_return_pct']) for t in sample_holdout):.2f}%")
    print("\nIMPORTANT: current top-volume universe creates survivorship bias; order-book filters, historic delistings, token news, and true fill/slippage are not reconstructed. Results are exploratory, not proof of future profitability.")
if __name__ == "__main__":
    main()