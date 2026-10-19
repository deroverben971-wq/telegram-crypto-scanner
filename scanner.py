"""Alert-only Binance USDT spot scanner; never places orders."""
import json, os, time, math, sys
from datetime import datetime, timezone
from pathlib import Path
import requests
BASE="https://data-api.binance.vision"; TG="https://api.telegram.org"; STATE=Path(".state.json")
S=requests.Session(); S.headers.update({"User-Agent":"telegram-crypto-scanner/1.0"})

PAPER_STATE = Path(".paper_state.json")
PAPER_HORIZONS_MS = {"1h": 3600000, "4h": 4*3600000, "24h": 24*3600000, "72h": 72*3600000}

def load_paper_state():
    """Load persistent forward-paper observations; malformed state fails closed."""
    try:
        value = json.loads(PAPER_STATE.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("signals"), list):
            value.setdefault("completed", [])
            value.setdefault("discovery_signals", [])
            value.setdefault("discovery_completed", [])
            return value
    except (OSError, ValueError):
        pass
    return {"signals": [], "completed": [], "discovery_signals": [], "discovery_completed": []}

def save_paper_state(state):
    """Atomic local write; workflow cache is best-effort persistence, not a database."""
    tmp = PAPER_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, allow_nan=False), encoding="utf-8")
    tmp.replace(PAPER_STATE)

def record_paper_signal(state, symbol, signal_close_ms, entry_ask, stop, target, spread_pct, tier="research"):
    """Record one technical-screen event per symbol and closed 1h candle."""
    try:
        entry_ask, stop, target, spread_pct = map(float, (entry_ask, stop, target, spread_pct))
        if (not symbol or signal_close_ms <= 0 or not all(math.isfinite(x) for x in
                (entry_ask, stop, target, spread_pct)) or entry_ask <= 0
                or stop <= 0 or stop >= entry_ask or target <= entry_ask or spread_pct < 0):
            return False
        key = f"{symbol}:{int(signal_close_ms)}"
        if any(x.get("key") == key for x in state["signals"]) or any(x.get("key") == key for x in state["completed"]):
            return False
        state["signals"].append({
            "key": key, "symbol": symbol, "signal_close_ms": int(signal_close_ms),
            "entry_ask": entry_ask, "stop": stop, "target": target,
            "entry_spread_pct": spread_pct, "tier": str(tier), "marks": {}
        })
        return True
    except (TypeError, ValueError, OverflowError):
        return False

def record_discovery_candidate(state, symbol, candle_key_ms, observed_ms, price, score):
    """Record one discovery-only candidate per symbol and closed 1h candle."""
    try:
        price = float(price)
        score = int(score)
        if not symbol or candle_key_ms <= 0 or observed_ms <= 0 or not math.isfinite(price) or price <= 0 or not 0 <= score <= 100:
            return False
        key = f"{symbol}:{int(candle_key_ms)}"
        rows = state.setdefault("discovery_signals", [])
        done = state.setdefault("discovery_completed", [])
        if any(x.get("key") == key for x in rows) or any(x.get("key") == key for x in done):
            return False
        rows.append({"key": key, "symbol": symbol, "candle_key_ms": int(candle_key_ms),
                     "observed_ms": int(observed_ms), "entry_price": price, "discovery_score": score, "marks": {}})
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def update_discovery_marks(state, now_ms, quotes, fee_rate=0.001, slippage_rate=0.0005):
    """Mark discovery candidates at fixed horizons using observed bid quotes."""
    horizons = {"1h": 3600000, "4h": 4*3600000, "24h": 24*3600000, "72h": 72*3600000}
    signals = state.setdefault("discovery_signals", [])
    completed = state.setdefault("discovery_completed", [])
    for signal in list(signals):
        quote = quotes.get(signal.get("symbol"))
        bid = None
        if isinstance(quote, dict):
            try:
                candidate_bid = float(quote["bid"])
                if math.isfinite(candidate_bid) and candidate_bid > 0:
                    bid = candidate_bid
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
        for horizon, delta in horizons.items():
            due = signal["observed_ms"] + delta
            if now_ms < due or horizon in signal["marks"]:
                continue
            delay_ms = now_ms - due
            if delay_ms > delta:
                signal["marks"][horizon] = {"observed_ms": now_ms, "delay_ms": delay_ms, "missed": True}
            elif bid is not None:
                entry_cost = signal["entry_price"] * (1 + fee_rate + slippage_rate)
                exit_proceeds = bid * (1 - fee_rate - slippage_rate)
                signal["marks"][horizon] = {"observed_ms": now_ms, "delay_ms": delay_ms, "missed": False,
                    "bid": bid, "net_return_pct": (exit_proceeds / entry_cost - 1) * 100}
    state["discovery_signals"] = [s for s in signals if len(s.get("marks", {})) != len(horizons)]
    completed.extend(s for s in signals if len(s.get("marks", {})) == len(horizons))


def discovery_performance_summary(state):
    signals = list(state.get("discovery_signals", [])) + list(state.get("discovery_completed", []))
    lines = ["DISCOVERY PAPER TRACKING — candidates are not trade signals"]
    lines.append(f"Discovery candidates tracked: {len(signals)} total; {len(state.get('discovery_signals', []))} in progress; {len(state.get('discovery_completed', []))} completed")
    for horizon in ("1h", "4h", "24h", "72h"):
        marks = [s.get("marks", {}).get(horizon, {}) for s in signals if horizon in s.get("marks", {})]
        valid = [m for m in marks if not m.get("missed") and isinstance(m.get("net_return_pct"), (int, float)) and math.isfinite(m["net_return_pct"])]
        missed = sum(1 for m in marks if m.get("missed"))
        if valid:
            wins = sum(m["net_return_pct"] > 0 for m in valid)
            mean = sum(m["net_return_pct"] for m in valid) / len(valid)
            lines.append(f"• {horizon}: n={len(valid)}, positive={wins}/{len(valid)} ({wins/len(valid)*100:.1f}%), mean net mark={mean:+.2f}%, missed={missed}")
        else:
            lines.append(f"• {horizon}: no valid observations yet; missed={missed}")
    lines.append("Quote-based estimates with modeled costs; small samples are inconclusive.")
    return chr(10).join(lines)

def update_paper_marks(state, now_ms, quotes, fee_rate=0.001, slippage_rate=0.0005):
    """Mark matured horizons using observed bid quotes; not actual fills.

    Each horizon is marked at the first scanner observation at/after its due time.
    Net return assumes fees and slippage on both sides; ask entry and bid exit
    already incorporate the observed spread. Late marks are explicitly recorded.
    """
    if not isinstance(now_ms, int) or now_ms <= 0 or fee_rate < 0 or slippage_rate < 0:
        raise ValueError("invalid paper-mark inputs")
    for signal in list(state["signals"]):
        quote = quotes.get(signal.get("symbol"))
        valid_quote = False
        bid = ask = None
        if isinstance(quote, dict):
            try:
                bid, ask = float(quote["bid"]), float(quote["ask"])
                valid_quote = all(math.isfinite(x) and x > 0 for x in (bid, ask)) and bid < ask
            except (KeyError, TypeError, ValueError, OverflowError):
                valid_quote = False
        for horizon, delta in PAPER_HORIZONS_MS.items():
            due = signal["signal_close_ms"] + delta
            if now_ms < due or horizon in signal["marks"]:
                continue
            delay_ms = now_ms - due
            # A missing/invalid quote must not leave a horizon pending forever.
            # Wait through one horizon of tolerance, then explicitly record it missing.
            if delay_ms > delta:
                signal["marks"][horizon] = {
                    "observed_ms": now_ms, "delay_ms": delay_ms,
                    "missed": True,
                    "reason": "no valid quote observed within horizon tolerance"
                }
                continue
            if not valid_quote:
                continue
            try:
                entry_cost = signal["entry_ask"] * (1 + fee_rate + slippage_rate)
                exit_proceeds = bid * (1 - fee_rate - slippage_rate)
                net_pct = (exit_proceeds / entry_cost - 1) * 100
                signal["marks"][horizon] = {
                    "observed_ms": now_ms, "delay_ms": delay_ms,
                    "missed": False, "bid": bid, "ask": ask, "net_return_pct": net_pct,
                    "stop_touched_by_snapshot": bid <= signal["stop"],
                    "target_touched_by_snapshot": bid >= signal["target"]
                }
            except (TypeError, ValueError, OverflowError, ZeroDivisionError):
                continue
    still_open, completed = [], state["completed"]
    for signal in state["signals"]:
        if len(signal.get("marks", {})) == len(PAPER_HORIZONS_MS):
            completed.append(signal)
        else:
            still_open.append(signal)
    state["signals"] = still_open
    state["completed"] = completed
    return state

def paper_performance_summary(state):
    """Summarize observed forward-paper marks without treating missed marks as returns."""
    signals = list(state.get("signals", [])) + list(state.get("completed", []))
    horizons = ("1h", "4h", "24h", "72h")
    lines = ["FORWARD PAPER TRACKING — observational only; not actual fills"]
    lines.append(f"Signals tracked: {len(signals)} total; {len(state.get('signals', []))} in progress; {len(state.get('completed', []))} completed")
    for horizon in horizons:
        marks = [s.get("marks", {}).get(horizon, {}) for s in signals if horizon in s.get("marks", {})]
        valid = [m for m in marks if not m.get("missed") and isinstance(m.get("net_return_pct"), (int, float)) and math.isfinite(m["net_return_pct"])]
        missed = sum(1 for m in marks if m.get("missed"))
        if valid:
            wins = sum(1 for m in valid if m["net_return_pct"] > 0)
            avg = sum(m["net_return_pct"] for m in valid) / len(valid)
            lines.append(f"• {horizon}: n={len(valid)}, positive={wins}/{len(valid)} ({wins/len(valid)*100:.1f}%), mean net mark={avg:+.2f}%, missed={missed}")
        else:
            lines.append(f"• {horizon}: no valid observations yet; missed={missed}")
    lines.append("Quote-based estimates with modeled costs, not verified fills. Small samples are inconclusive.")
    return "\n".join(lines)


def get(path,params=None):
    """Request Binance data with bounded retries and respect server retry hints."""
    for i in range(3):
        try:
            r=S.get(BASE+path,params=params,timeout=(3,10))
            if r.status_code in (418,429) or r.status_code>=500:
                if i < 2:
                    try:
                        retry_after = float(r.headers.get("Retry-After", 0))
                    except (TypeError, ValueError):
                        retry_after = 0
                    # Bound waiting to the workflow's execution budget; never hammer
                    # an endpoint that is rate-limiting or temporarily unavailable.
                    wait = min(20.0, max(retry_after, 2 ** i))
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"Binance temporarily unavailable (HTTP {r.status_code})")
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if i == 2:
                raise RuntimeError("Binance request failed after retries") from None
            time.sleep(min(8.0, 2 ** i))
    raise RuntimeError("Binance request failed after retries")
def ema(a,n):
    if len(a)<n:return None
    v=sum(a[:n])/n; k=2/(n+1)
    for x in a[n:]:v=x*k+v*(1-k)
    return v
def rsi(a,n=14):
    if len(a)<n+1:return None
    d=[a[i]-a[i-1] for i in range(1,len(a))]
    g=[max(0,x) for x in d]; l=[max(0,-x) for x in d]
    ag=sum(g[:n])/n; al=sum(l[:n])/n
    for i in range(n,len(d)):ag=((n-1)*ag+g[i])/n; al=((n-1)*al+l[i])/n
    return 100 if al==0 and ag>0 else 50 if al==0 else 100-100/(1+ag/al)

def atr(candles_rows, n=14):
    """Average True Range as a price-unit volatility measure; informational only."""
    if len(candles_rows) < n + 1:
        return None
    tr=[]
    for i in range(1, len(candles_rows)):
        cur, prev = candles_rows[i], candles_rows[i-1]
        tr.append(max(cur["high"]-cur["low"], abs(cur["high"]-prev["close"]), abs(cur["low"]-prev["close"])))
    if len(tr) < n:
        return None
    value=sum(tr[:n])/n
    for x in tr[n:]:
        value=((n-1)*value+x)/n
    return value


def bollinger(values, n=20, deviations=2):
    """Return middle, lower, upper bands and normalized band position."""
    if len(values) < n:
        return None
    window=values[-n:]
    mean=sum(window)/n
    variance=sum((x-mean)**2 for x in window)/n
    sd=math.sqrt(variance)
    lower, upper = mean-deviations*sd, mean+deviations*sd
    position=(values[-1]-lower)/(upper-lower) if upper>lower else None
    return mean, lower, upper, position

def macd(values, fast=12, slow=26, signal=9):
    """Return latest MACD line, signal line, and histogram; informational only."""
    if len(values) < slow + signal:
        return None
    line=[]
    for i in range(slow-1, len(values)):
        fast_value=ema(values[:i+1], fast)
        slow_value=ema(values[:i+1], slow)
        if fast_value is not None and slow_value is not None:
            line.append(fast_value-slow_value)
    if len(line) < signal:
        return None
    signal_value=ema(line, signal)
    return (line[-1], signal_value, line[-1]-signal_value) if signal_value is not None else None

def adx(candles_rows, n=14):
    """Wilder ADX trend-strength estimate (0-100), not a direction predictor."""
    if len(candles_rows) < 2*n + 1:
        return None
    plus_dm=[]; minus_dm=[]; true_ranges=[]
    for i in range(1, len(candles_rows)):
        cur, prev = candles_rows[i], candles_rows[i-1]
        up=cur["high"]-prev["high"]
        down=prev["low"]-cur["low"]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        true_ranges.append(max(cur["high"]-cur["low"], abs(cur["high"]-prev["close"]), abs(cur["low"]-prev["close"])))
    tr=sum(true_ranges[:n]); plus=sum(plus_dm[:n]); minus=sum(minus_dm[:n]); dx=[]
    for i in range(n, len(true_ranges)):
        tr=tr-tr/n+true_ranges[i]
        plus=plus-plus/n+plus_dm[i]
        minus=minus-minus/n+minus_dm[i]
        if tr <= 0:
            dx.append(0.0); continue
        pdi=100*plus/tr; mdi=100*minus/tr
        dx.append(100*abs(pdi-mdi)/(pdi+mdi) if pdi+mdi else 0.0)
    if len(dx) < n:
        return None
    value=sum(dx[:n])/n
    for x in dx[n:]:
        value=((n-1)*value+x)/n
    return value


def market_regime(candles_rows, short_window=24, long_window=72):
    """Describe recent volatility and normalized momentum; never a standalone signal."""
    try:
        closes = [float(x["close"]) for x in candles_rows]
        if len(closes) < long_window + 2 or any(not math.isfinite(x) or x <= 0 for x in closes[-long_window-1:]):
            return {"label": "unknown", "vol_ratio": None, "direction": "unknown"}
        returns = [closes[i] / closes[i-1] - 1 for i in range(1, len(closes))]
        short, long = returns[-short_window:], returns[-long_window:]
        def stdev(values):
            mean = sum(values) / len(values)
            return math.sqrt(sum((x-mean)**2 for x in values) / max(1, len(values)-1))
        short_vol, long_vol = stdev(short), stdev(long)
        vol_ratio = short_vol / long_vol if long_vol > 0 else None
        av = atr(candles_rows)
        atr_pct = av / closes[-1] if av and closes[-1] > 0 else None
        momentum = closes[-1] / closes[-1-short_window] - 1
        norm_momentum = momentum / (atr_pct * math.sqrt(short_window)) if atr_pct and atr_pct > 0 else None
        if vol_ratio is None:
            label = "unknown"
        elif vol_ratio >= 1.25:
            label = "volatility expansion"
        elif vol_ratio <= 0.75:
            label = "volatility contraction"
        else:
            label = "normal volatility"
        if norm_momentum is not None and norm_momentum >= 1:
            direction = "positive momentum"
        elif norm_momentum is not None and norm_momentum <= -1:
            direction = "negative momentum"
        else:
            direction = "weak/mixed momentum"
        return {"label": label, "vol_ratio": vol_ratio, "direction": direction,
                "normalized_momentum": norm_momentum, "atr_pct": atr_pct}
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        return {"label": "unknown", "vol_ratio": None, "direction": "unknown"}


def trend_structure(candles_rows):
    """Describe EMA structure and ADX trend strength; not a price prediction."""
    try:
        closes = [float(x["close"]) for x in candles_rows]
        fast, slow, strength = ema(closes, 20), ema(closes, 50), adx(candles_rows)
        if fast is None or slow is None:
            direction = "unknown"
        elif closes[-1] > fast > slow:
            direction = "uptrend"
        elif closes[-1] < fast < slow:
            direction = "downtrend"
        else:
            direction = "mixed/range"
        strength_label = "trend strength elevated" if strength is not None and strength >= 25 else "trend strength weak/unclear" if strength is not None else "ADX unavailable"
        return {"direction": direction, "adx": strength, "strength_label": strength_label}
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"direction": "unknown", "adx": None, "strength_label": "ADX unavailable"}

def relative_strength(asset, benchmark, hours=24):
    """Return asset minus benchmark return over the same closed-candle window, in pp."""
    if not asset or not benchmark:
        return None
    end_time=asset[-1].get("time")
    # Require both markets to have the same latest closed candle; stale data
    # must not silently pass as a synchronized relative-strength comparison.
    if end_time is None or benchmark[-1].get("time") != end_time:
        return None
    start_time=end_time-hours*3600000
    asset_now=asset[-1].get("close")
    asset_prev=next((x.get("close") for x in reversed(asset[:-1]) if x.get("time")==start_time),None)
    bench_now=next((x.get("close") for x in reversed(benchmark) if x.get("time")==end_time),None)
    bench_prev=next((x.get("close") for x in reversed(benchmark) if x.get("time")==start_time),None)
    if not all(isinstance(x,(int,float)) and math.isfinite(x) and x>0 for x in (asset_now,asset_prev,bench_now,bench_prev)):
        return None
    return ((asset_now/asset_prev-1)-(bench_now/bench_prev-1))*100

def eligible_live_symbol(symbol, valid_symbols, excluded_bases=None):
    """Keep the live scanner universe aligned with the backtest's spot-crypto universe."""
    excluded = set(excluded_bases or ()) | {
        "USDC", "FDUSD", "TUSD", "USDP", "DAI", "USDE", "BUSD",
        "USD1", "RLUSD", "EUR", "TRY", "BRL", "USTC", "XAUT",
        "NVDAB", "TSLAB", "MSTRB", "CRCLB", "SNDKB", "SOXLB",
    }
    if not symbol.endswith("USDT") or symbol not in valid_symbols:
        return False
    base = symbol[:-4]
    if not base or base in excluded:
        return False
    if base.endswith(("UP", "DOWN", "BULL", "BEAR", "2L", "2S", "3L", "3S", "5L", "5S")):
        return False
    return True


def safe_timestamp(value):
    """Parse cooldown timestamps defensively; malformed state must not abort a scan."""
    try:
        parsed=float(value or 0)
        return parsed if math.isfinite(parsed) and parsed>=0 else 0.0
    except (TypeError,ValueError,OverflowError):
        return 0.0

def contiguous_recent(rows, interval_ms, count=55):
    """Fail closed unless the latest requested candles are evenly spaced."""
    if len(rows)<count:
        return False
    recent=rows[-count:]
    return all(recent[i]["time"]-recent[i-1]["time"]==interval_ms for i in range(1,len(recent)))

def recent_and_contiguous(rows, interval_ms, count=55, now_ms=None):
    """Require enough evenly spaced candles and reject stale market data."""
    if not contiguous_recent(rows, interval_ms, count):
        return False
    now_ms = int(datetime.now(timezone.utc).timestamp()*1000) if now_ms is None else now_ms
    age_ms = now_ms - (rows[-1]["time"] + interval_ms)
    return -interval_ms <= age_ms <= 2 * interval_ms

def long_setup_levels(book, stop):
    """Use ask-side price as the illustrative entry reference for a long setup."""
    try:
        ask, stop = float(book["ask"]), float(stop)
        if not math.isfinite(ask) or not math.isfinite(stop) or ask <= 0 or stop <= 0 or stop >= ask:
            return None
        risk_pct = (ask - stop) / ask
        if not 0.005 <= risk_pct <= 0.03:
            return None
        return {"entry_reference": ask, "stop": stop, "risk_pct": risk_pct,
                "target": ask + 2 * (ask - stop)}
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def orderbook_metrics(ob):
    """Validate book levels and return spread and nearby USD depth, or None."""
    try:
        bids = [(float(x[0]), float(x[1])) for x in ob.get("bids", []) if len(x) >= 2]
        asks = [(float(x[0]), float(x[1])) for x in ob.get("asks", []) if len(x) >= 2]
        bids = [(p, q) for p, q in bids if math.isfinite(p) and math.isfinite(q) and p > 0 and q > 0]
        asks = [(p, q) for p, q in asks if math.isfinite(p) and math.isfinite(q) and p > 0 and q > 0]
        if not bids or not asks:
            return None
        bid, ask = max(x[0] for x in bids), min(x[0] for x in asks)
        mid = (bid + ask) / 2
        if not math.isfinite(mid) or mid <= 0 or ask <= bid:
            return None
        spread_pct = (ask - bid) / mid * 100
        bid_depth = sum(p*q for p, q in bids if p >= mid*0.995)
        ask_depth = sum(p*q for p, q in asks if p <= mid*1.005)
        if not all(math.isfinite(x) for x in (spread_pct, bid_depth, ask_depth)):
            return None
        return {"bid": bid, "ask": ask, "mid": mid, "spread_pct": spread_pct,
                "bid_depth": bid_depth, "ask_depth": ask_depth}
    except (TypeError, ValueError, KeyError, OverflowError):
        return None

def candles(sym,iv):
    raw=get("/api/v3/klines",{"symbol":sym,"interval":iv,"limit":80}); now=int(datetime.now(timezone.utc).timestamp()*1000); out=[]
    for x in raw:
        try:
            if len(x)<7 or int(x[6])>=now:continue
            o,h,l,c,v=map(float,x[1:6])
            if not all(math.isfinite(z) for z in (o,h,l,c,v)) or min(o,h,l,c)<=0 or v<0 or h<max(o,c,l) or l>min(o,c):continue
            out.append({"time":int(x[0]),"high":h,"low":l,"close":c,"volume":v})
        except (ValueError,TypeError,IndexError):continue
    return out
def send(msg):
    token=os.getenv("TELEGRAM_BOT_TOKEN","").strip(); chat=os.getenv("TELEGRAM_CHAT_ID","").strip()
    if not token or not chat:raise RuntimeError("Missing Telegram secrets")
    try:r=requests.post(f"{TG}/bot{token}/sendMessage",data={"chat_id":chat,"text":msg,"disable_web_page_preview":True},timeout=(3,8)); d=r.json()
    except (requests.RequestException,ValueError) as e:raise RuntimeError(f"Telegram request failed ({type(e).__name__}); credentials hidden") from None
    if r.status_code>=400 or not isinstance(d,dict) or not d.get("ok"):raise RuntimeError(f"Telegram rejected message (HTTP {r.status_code})")
def scan():
    info=get("/api/v3/exchangeInfo"); valid={x["symbol"] for x in info.get("symbols",[]) if x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT" and x.get("isSpotTradingAllowed",True)}
    ts=get("/api/v3/ticker/24hr"); u=[]
    for t in ts:
        s=t.get("symbol","")
        try:q=float(t["quoteVolume"]); ch=float(t["priceChangePercent"]); p=float(t["lastPrice"])
        except (ValueError,TypeError,KeyError):continue
        if eligible_live_symbol(s, valid) and q>=3000000 and p>0:u.append((q,s,ch,p))
    u=sorted(u,reverse=True)
    print(f"Eligible USDT spot pairs meeting the liquidity filter: {len(u)} (no top-60 cap)")
    btc=candles("BTCUSDT","1h"); btc4=candles("BTCUSDT","4h"); btcd=candles("BTCUSDT","1d")
    btc_regime_ok = False
    btc_regime_reason = "BTC market-regime unavailable; candidates are watch-only."
    btc_data_ok = (recent_and_contiguous(btc,3600000) and recent_and_contiguous(btc4,4*3600000)
                   and recent_and_contiguous(btcd,24*3600000))
    if btc_data_ok:
        btc1c=[x["close"] for x in btc]; btc4c=[x["close"] for x in btc4]; btcdc=[x["close"] for x in btcd]
        # BTC is an alert gate, not a reason to skip analyzing individual altcoins.
        btc_regime_ok = (
            ema(btc1c,20)>ema(btc1c,50) and btc1c[-1]>ema(btc1c,20)
            and ema(btc4c,20)>ema(btc4c,50) and btc4c[-1]>ema(btc4c,20)
            and ema(btcdc,20)>ema(btcdc,50) and btcdc[-1]>ema(btcdc,20)
        )
        if not btc_regime_ok:
            btc_regime_reason = "BTC trend gate failed on at least one of 1h, 4h, or daily; candidates will be WATCH ONLY."
    else:
        btc_regime_reason = "Insufficient or discontinuous BTC candle history on at least one timeframe; candidates will be WATCH ONLY."
    if not btc_regime_ok:
        print("BTC gate: " + btc_regime_reason)
    try:state=json.loads(STATE.read_text())
    except (OSError,ValueError):state={"alerts":{}}
    if not isinstance(state,dict) or not isinstance(state.get("alerts"),dict):state={"alerts":{}}
    now=time.time(); count=0; watch_candidates=[]; discovery_candidates=[]
    # Forward paper validation: re-quote pending signal pairs and record marks
    # at 1h/4h/24h/72h horizons. This is observational, not actual execution.
    paper_state = load_paper_state()
    paper_quotes = {}
    pending_symbols = sorted(
        {x.get("symbol") for x in paper_state["signals"] if x.get("symbol")} |
        {x.get("symbol") for x in paper_state.get("discovery_signals", []) if x.get("symbol")}
    )
    for paper_symbol in pending_symbols:
        try:
            book = orderbook_metrics(get("/api/v3/depth", {"symbol": paper_symbol, "limit": 100}))
            if book:
                paper_quotes[paper_symbol] = {"bid": book["bid"], "ask": book["ask"]}
        except (RuntimeError, ValueError, requests.RequestException, KeyError, TypeError):
            pass
    paper_now_ms = int(time.time()*1000)
    update_paper_marks(paper_state, paper_now_ms, paper_quotes)
    update_discovery_marks(paper_state, paper_now_ms, paper_quotes)
    save_paper_state(paper_state)
    stats={"considered":0,"cooldown":0,"insufficient_history":0,"trend":0,"momentum_breakout_volume_rs":0,"orderbook_spread_depth":0,"stop_risk":0,"api_errors":0,"qualified":0,"watch_only":0,"alert_cap_suppressed":0}
    for q,s,ch,p in u:
        if s=="BTCUSDT": continue
        stats["considered"]+=1
        if now-safe_timestamp(state["alerts"].get(s,0))<21600:
            stats["cooldown"]+=1; continue
        try:
            h1=candles(s,"1h"); h4=candles(s,"4h"); d1=candles(s,"1d")
            if not (recent_and_contiguous(h1,3600000) and recent_and_contiguous(h4,4*3600000)
                    and recent_and_contiguous(d1,24*3600000)):
                stats["insufficient_history"]+=1; continue
            a=[x["close"] for x in h1]; b=[x["close"] for x in h4]; d=[x["close"] for x in d1]
            trend_1h = ema(a,20)>ema(a,50) and a[-1]>ema(a,20)
            trend_4h = ema(b,20)>ema(b,50) and b[-1]>ema(b,20)
            trend_1d = ema(d,20)>ema(d,50) and d[-1]>ema(d,20)
            strict_trend = trend_1h and trend_4h and trend_1d
            # Relaxed tier is watch-only: still requires 1h strength and at least
            # a constructive 4h structure; it never bypasses liquidity/risk gates.
            watch_trend = trend_1h and (trend_4h or (b[-1]>ema(b,20) and ema(b,20)>=ema(b,50)))
            prior=h1[-21:-1]; rr=rsi(a); br=(a[-1]/max(x["high"] for x in prior)-1)*100; av=sum(x["volume"] for x in prior)/20; vr=h1[-1]["volume"]/av if av else 0; candle_range=h1[-1]["high"]-h1[-1]["low"]; close_location=(a[-1]-h1[-1]["low"])/candle_range if candle_range>0 else 0
            # Compare equal 24-hour windows using closed candles, not rolling ticker
            # percentages that can have slightly different observation timestamps.
            rs=relative_strength(h1,btc)
            # Widely used additional indicators are reported for evaluation only.
            # Do not gate alerts on them until forward/out-of-sample evidence supports it.
            adx_value=adx(h1)
            atr_value=atr(h1)
            atr_pct=(atr_value/a[-1]*100) if atr_value is not None and a[-1] > 0 else None
            regime=market_regime(h1)
            structure=trend_structure(h1)
            macd_values=macd(a)
            bb_values=bollinger(a)
            bb_text=(f"BB(20,2σ) position {bb_values[3]:.2f}" if bb_values and bb_values[3] is not None else "BB unavailable")
            # Strategy-family labels are diagnostic only: no new family can trigger alerts until validated.
            strategy_tags=[]
            if trend_1h and trend_4h and trend_1d and macd_values and macd_values[2] > 0:
                strategy_tags.append("trend/momentum alignment")
            if br >= 0 and vr >= 1.3 and close_location >= .65:
                strategy_tags.append("volume breakout candidate")
            if bb_values and rr is not None and rr <= 35 and a[-1] <= bb_values[1]:
                strategy_tags.append("BB+RSI mean-reversion watch (counter-trend risk)")
            strategy_text=", ".join(strategy_tags) if strategy_tags else "no additional strategy-family confluence" 
            macd_text=(f"MACD hist {macd_values[2]:+.6g} ({'bullish' if macd_values[2] > 0 else 'non-bullish'})" if macd_values else "MACD unavailable")
            adx_text=(f"ADX(14) {adx_value:.1f}" if adx_value is not None else "ADX unavailable")
            atr_text=(f"ATR(14) {atr_pct:.2f}% of price" if atr_pct is not None else "ATR unavailable")
            regime_text=(f"{regime['label']}; volatility ratio {regime['vol_ratio']:.2f}x; {regime['direction']}" if regime.get("vol_ratio") is not None else "regime unavailable")
            structure_text=(f"{structure['direction']}; {structure['strength_label']}" + (f" (ADX {structure['adx']:.1f})" if structure.get("adx") is not None else ""))
            if rs is None:
                stats["insufficient_history"]+=1; continue
            strict_momentum = (rr is not None and 52<=rr<=68 and 0<=br<=1.2 and vr>=1.3 and rs>=1.5 and close_location>=.65)
            watch_momentum = (rr is not None and 45<=rr<=72 and -0.5<=br<=1.8 and vr>=1.0 and rs>=0 and close_location>=.50)
            is_confirmed = strict_trend and strict_momentum
            discovery_checks = [
                trend_1h, trend_4h, trend_1d,
                rr is not None and 45 <= rr <= 72,
                -0.5 <= br <= 1.8,
                vr >= 1.0,
                rs >= 0,
                close_location >= .50,
            ]
            discovery_score = round(sum(discovery_checks) / len(discovery_checks) * 100)
            discovery_missing = [label for label, ok in zip(
                ("1h trend", "4h trend", "daily trend", "RSI range",
                 "breakout not overextended", "volume expansion",
                 "relative strength vs BTC", "strong candle close"),
                discovery_checks
            ) if not ok]
            record_discovery_candidate(paper_state, s, h1[-1]["time"], int(now*1000), p, discovery_score)
            discovery_candidates.append((
                discovery_score,
                f"{s} | discovery score {discovery_score}/100 ({sum(discovery_checks)}/8 checks) | price {p:.8g} USDT | "
                f"RSI {rr:.1f} | volume {vr:.2f}x | breakout {br:.2f}% | "
                f"RS vs BTC {rs:+.2f} pp | missing: {', '.join(discovery_missing) if discovery_missing else 'none'}"
            ))
            if not strict_trend and not watch_trend:
                stats["trend"]+=1
            if not is_confirmed and not (watch_trend and watch_momentum):
                stats["momentum_breakout_volume_rs"]+=1
                continue
            ob=get("/api/v3/depth",{"symbol":s,"limit":100}); book=orderbook_metrics(ob)
            if book is None or book["spread_pct"]>.15 or min(book["bid_depth"],book["ask_depth"])<15000:
                stats["orderbook_spread_depth"]+=1; continue
            bid,ask,mid=book["bid"],book["ask"],book["mid"]
            # Last price can understate the cost of crossing the spread.
            drift=(ask/a[-1]-1)*100
            if abs(drift)>.75:
                stats["momentum_breakout_volume_rs"]+=1; continue
            stop=min(x["low"] for x in h1[-6:-1])
            levels=long_setup_levels(book,stop)
            if levels is None:
                stats["stop_risk"]+=1; continue
            entry_ref,target=levels["entry_reference"],levels["target"]
            tier = "CONFIRMED TECHNICAL SCREEN" if is_confirmed else "EARLY WATCHLIST — RELAXED FILTERS"
            msg=(f"⚠️ {tier} — PAPER RESEARCH ONLY; NOT a buy signal\nEvaluation horizons: 1h / 4h / 24h / 72h\nPair: {s}\nLast price: {p:.8g} USDT; ask-side entry reference: {entry_ref:.8g} USDT\nRSI: {rr:.1f}; volume: {vr:.2f}x; breakout: {br:.2f}%; relative strength vs BTC: {rs:+.2f} pp\nMarket regime (diagnostic only): {regime_text}; trend structure: {structure_text}\nExtra indicators (informational, not proven filters): {adx_text}; {macd_text}; {atr_text}; {bb_text}\nStrategy-family diagnostics (paper research only): {strategy_text}\nTrend checks: 1h={'pass' if trend_1h else 'fail'}, 4h={'pass' if trend_4h else 'partial/fail'}, daily={'pass' if trend_1d else 'fail'}\nIllustrative invalidation: {stop:.8g}; 2R target from ask reference: {target:.8g}\n24h quote volume: {q:,.0f} USDT; spread: {book["spread_pct"]:.3f}%\nTechnical-only; news, token unlocks, security and regulatory risks are not checked. Fees/slippage change results. No profit/probability guaranteed. No orders placed.")
            stats["qualified"]+=1
            # Log every qualifying technical setup, including BTC-gated watch-only
            # candidates, so evaluation is not conditioned on alert delivery.
            record_paper_signal(
                paper_state, s, h1[-1]["time"] + 3600000, entry_ref, stop,
                target, book["spread_pct"],
                tier="strict" if is_confirmed else "relaxed_watch"
            )
            save_paper_state(paper_state)
            if is_confirmed and btc_regime_ok:
                if count < 3:
                    send(msg)
                    state["alerts"][s]=now
                    tmp=STATE.with_suffix(".tmp");tmp.write_text(json.dumps(state,allow_nan=False));tmp.replace(STATE)
                    count+=1
                else:
                    # Continue scanning the full universe, but limit Telegram signal
                    # messages per run to avoid flooding the user.
                    stats["alert_cap_suppressed"]+=1
            else:
                # Relaxed candidates and BTC-gated candidates are watch-only.
                score_checks = [
                    trend_1h, trend_4h, trend_1d,
                    48 <= rr <= 65,
                    0 <= br <= 1.2,
                    vr >= 1.3,
                    rs >= 1.5,
                    close_location >= .65,
                    book["spread_pct"] <= .10,
                ]
                score = round(sum(score_checks) / len(score_checks) * 100)
                missing = [label for label, ok in zip(
                    ("1h trend", "4h trend", "daily trend", "RSI sweet spot",
                     "not-overextended breakout", "volume expansion",
                     "relative strength vs BTC", "strong candle close", "tight spread"),
                    score_checks
                ) if not ok]
                watch_candidates.append((
                    score,
                    f"{s} | score {score}/100 | {tier} | price {p:.8g} USDT | "
                    f"RSI {rr:.1f} | volume {vr:.2f}x | breakout {br:.2f}% | "
                    f"RS vs BTC {rs:+.2f} pp | spread {book['spread_pct']:.3f}% | "
                    f"missing: {', '.join(missing) if missing else 'none'}"
                ))
                stats["watch_only"]+=1
        except (RuntimeError,ValueError,requests.RequestException,KeyError,TypeError,ZeroDivisionError) as e:
            stats["api_errors"]+=1; print(f"Skip {s}: {type(e).__name__}")
    save_paper_state(paper_state)
    print("\nScan diagnostics:")
    for key,value in stats.items(): print(f"  {key.replace(chr(95), chr(32))}: {value}")
    if count:
        summary = f"🔎 SCAN RESULT — {count} confirmed technical alert(s) sent"
    else:
        summary = "⛔ NO TRADE — no coin passed every strict confirmation rule"

    reasons = [
        ("Pairs considered", stats["considered"]),
        ("Recent-alert cooldown", stats["cooldown"]),
        ("Insufficient history / candle gaps", stats["insufficient_history"]),
        ("Multi-timeframe trend failed", stats["trend"]),
        ("Momentum / breakout / volume / relative-strength filters failed", stats["momentum_breakout_volume_rs"]),
        ("Spread / order-book depth failed", stats["orderbook_spread_depth"]),
        ("Stop-distance / risk failed", stats["stop_risk"]),
        ("API / data errors", stats["api_errors"]),
        ("Passed technical filters", stats["qualified"]),
        ("Watch-only technical candidates", stats["watch_only"]),
    ]
    detail = "\n".join(f"• {label}: {value}" for label, value in reasons)

    if watch_candidates:
        # Rank all candidates internally, but show only the single highest-ranked one.
        watch_candidates.sort(key=lambda item: item[0], reverse=True)
        candidates_text = f"• {watch_candidates[0][1]}"
        watch_note = (
            f"{btc_regime_reason}\n"
            "This is the highest-ranked unconfirmed monitoring candidate—not a buy signal. "
            "Wait for strict confirmation and check news/token risks."
            if not btc_regime_ok else
            "This candidate did not meet every strict confirmation condition. Watchlist only—not a buy signal."
        )
    elif discovery_candidates:
        # Use an actual newline when composing Telegram text; only display the top discovery candidate.
        discovery_candidates.sort(key=lambda item: item[0], reverse=True)
        candidates_text = f"• {discovery_candidates[0][1]}"
        watch_note = (
            "No coin passed the relaxed technical watchlist filters. This is the highest-ranked "
            "technical discovery candidate among symbols with valid candle history—not a qualified setup, "
            "recommendation, or buy signal. Order-book/risk checks may not have passed; verify news and token risks."
        )
    else:
        # Only use a liquid market reference when data is too incomplete to calculate a technical rank.
        fallback = next((item for item in u if item[1] != "BTCUSDT"), None)
        if fallback:
            fq, fs, fch, fp = fallback
            candidates_text = (
                f"• {fs} | MARKET MONITOR ONLY (not technically qualified) | "
                f"price {fp:.8g} USDT | 24h change {fch:+.2f}% | "
                f"24h quote volume {fq:,.0f} USDT"
            )
            watch_note = (
                "No coin passed the relaxed technical watchlist filters. This named asset is shown only as a liquid market reference; "
                "it is NOT a qualified candidate, recommendation, or buy signal. Do not trade it based on this report."
            )
        else:
            candidates_text = "• No eligible non-BTC USDT spot pair was available to name this scan."
            watch_note = "No candidate qualified. Do not force a pick."

    note = "No automatic orders are placed. Nothing in this report predicts or guarantees a winning trade."
    report = (
        f"{summary}\n\n"
        f"📊 SCAN DIAGNOSTICS\n{detail}\n\n"
        f"👀 WATCHLIST / MARKET MONITOR\n{candidates_text}\n\n"
        f"{watch_note}\n\n{paper_performance_summary(paper_state)}\n\n"
        f"{discovery_performance_summary(paper_state)}\n\n{note}"
    )
    print(report)
    send(report)
if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--test-telegram":
        send("Telegram scanner connectivity test only; no signal generated.")
        print("Telegram test sent.")
    else:
        try:
            scan()
        except Exception as e:
            # Send an operational failure notice when early market-data calls fail.
            # Never include exception text, request URLs, or credentials in Telegram.
            print(f"Scanner stopped before completing the scan: {type(e).__name__}")
            try:
                send("🚨 SCANNER ERROR — market scan did not complete. Check the latest GitHub Actions logs. No orders placed.")
            except Exception as notify_error:
                print(f"Could not send scanner failure notice: {type(notify_error).__name__}")
            raise