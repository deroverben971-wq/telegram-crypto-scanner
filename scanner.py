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
            return value
    except (OSError, ValueError):
        pass
    return {"signals": [], "completed": []}

def save_paper_state(state):
    """Atomic local write; workflow cache is best-effort persistence, not a database."""
    tmp = PAPER_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, allow_nan=False), encoding="utf-8")
    tmp.replace(PAPER_STATE)

def record_paper_signal(state, symbol, signal_close_ms, entry_ask, stop, target, spread_pct):
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
            "entry_spread_pct": spread_pct, "marks": {}
        })
        return True
    except (TypeError, ValueError, OverflowError):
        return False

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
        if not isinstance(quote, dict):
            continue
        try:
            bid, ask = float(quote["bid"]), float(quote["ask"])
            if not all(math.isfinite(x) and x > 0 for x in (bid, ask)) or bid >= ask:
                continue
            for horizon, delta in PAPER_HORIZONS_MS.items():
                due = signal["signal_close_ms"] + delta
                if now_ms < due or horizon in signal["marks"]:
                    continue
                entry_cost = signal["entry_ask"] * (1 + fee_rate + slippage_rate)
                exit_proceeds = bid * (1 - fee_rate - slippage_rate)
                delay_ms = now_ms - due
                # Never label a very late quote as if it were the intended horizon.
                # With a 30-minute scan cadence, a 1h mark should be observed within
                # one horizon; otherwise record a missed observation, not a fake return.
                if delay_ms > delta:
                    signal["marks"][horizon] = {
                        "observed_ms": now_ms, "delay_ms": delay_ms,
                        "missed": True, "reason": "no quote observed within horizon tolerance"
                    }
                    continue
                net_pct = (exit_proceeds / entry_cost - 1) * 100
                signal["marks"][horizon] = {
                    "observed_ms": now_ms, "delay_ms": delay_ms,
                    "missed": False, "bid": bid, "ask": ask, "net_return_pct": net_pct,
                    "stop_touched_by_snapshot": bid <= signal["stop"],
                    "target_touched_by_snapshot": bid >= signal["target"]
                }
        except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
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

def get(path,params=None):
    for i in range(3):
        try:
            r=S.get(BASE+path,params=params,timeout=(3,10))
            if r.status_code in (418,429) or r.status_code>=500:
                if i<2: time.sleep(i+1)
                continue
            r.raise_for_status(); return r.json()
        except (requests.RequestException,ValueError):
            if i==2: raise RuntimeError("Binance request failed after retries") from None
            time.sleep(i+1)
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
    u=sorted(u,reverse=True)[:60]
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
    now=time.time(); count=0; watch_candidates=[]
    # Forward paper validation: re-quote pending signal pairs and record marks
    # at 1h/4h/24h/72h horizons. This is observational, not actual execution.
    paper_state = load_paper_state()
    paper_quotes = {}
    pending_symbols = sorted({x.get("symbol") for x in paper_state["signals"] if x.get("symbol")})
    for paper_symbol in pending_symbols:
        try:
            book = orderbook_metrics(get("/api/v3/depth", {"symbol": paper_symbol, "limit": 100}))
            if book:
                paper_quotes[paper_symbol] = {"bid": book["bid"], "ask": book["ask"]}
        except (RuntimeError, ValueError, requests.RequestException, KeyError, TypeError):
            pass
    update_paper_marks(paper_state, int(time.time()*1000), paper_quotes)
    save_paper_state(paper_state)
    stats={"considered":0,"cooldown":0,"insufficient_history":0,"trend":0,"momentum_breakout_volume_rs":0,"orderbook_spread_depth":0,"stop_risk":0,"api_errors":0,"qualified":0,"watch_only":0}
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
            if not strict_trend and not watch_trend:
                stats["trend"]+=1; continue
            prior=h1[-21:-1]; rr=rsi(a); br=(a[-1]/max(x["high"] for x in prior)-1)*100; av=sum(x["volume"] for x in prior)/20; vr=h1[-1]["volume"]/av if av else 0; candle_range=h1[-1]["high"]-h1[-1]["low"]; close_location=(a[-1]-h1[-1]["low"])/candle_range if candle_range>0 else 0
            # Compare equal 24-hour windows using closed candles, not rolling ticker
            # percentages that can have slightly different observation timestamps.
            rs=relative_strength(h1,btc)
            if rs is None:
                stats["insufficient_history"]+=1; continue
            strict_momentum = (rr is not None and 52<=rr<=68 and 0<=br<=1.2 and vr>=1.3 and rs>=1.5 and close_location>=.65)
            watch_momentum = (rr is not None and 45<=rr<=72 and -0.5<=br<=1.8 and vr>=1.0 and rs>=0 and close_location>=.50)
            is_confirmed = strict_trend and strict_momentum
            if not is_confirmed and not (watch_trend and watch_momentum):
                stats["momentum_breakout_volume_rs"]+=1; continue
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
            msg=(f"⚠️ {tier} — NOT a buy signal\nPair: {s}\nLast price: {p:.8g} USDT; ask-side entry reference: {entry_ref:.8g} USDT\nRSI: {rr:.1f}; volume: {vr:.2f}x; breakout: {br:.2f}%; relative strength vs BTC: {rs:+.2f} pp\nTrend checks: 1h={'pass' if trend_1h else 'fail'}, 4h={'pass' if trend_4h else 'partial/fail'}, daily={'pass' if trend_1d else 'fail'}\nIllustrative invalidation: {stop:.8g}; 2R target from ask reference: {target:.8g}\n24h quote volume: {q:,.0f} USDT; spread: {book["spread_pct"]:.3f}%\nTechnical-only; news, token unlocks, security and regulatory risks are not checked. Fees/slippage change results. No profit/probability guaranteed. No orders placed.")
            stats["qualified"]+=1
            # Log every qualifying technical setup, including BTC-gated watch-only
            # candidates, so evaluation is not conditioned on alert delivery.
            record_paper_signal(
                paper_state, s, h1[-1]["time"] + 3600000, entry_ref, stop,
                target, book["spread_pct"]
            )
            save_paper_state(paper_state)
            if is_confirmed and btc_regime_ok:
                send(msg)
                state["alerts"][s]=now
                tmp=STATE.with_suffix(".tmp");tmp.write_text(json.dumps(state,allow_nan=False));tmp.replace(STATE)
                count+=1
                if count>=3:break
            else:
                # Relaxed candidates and BTC-gated candidates are watch-only.
                watch_candidates.append(f"{s} | {tier} | price {p:.8g} USDT | RSI {rr:.1f} | volume {vr:.2f}x | breakout {br:.2f}% | RS vs BTC {rs:+.2f} pp | spread {book['spread_pct']:.3f}%")
                stats["watch_only"]+=1
        except (RuntimeError,ValueError,requests.RequestException,KeyError,TypeError,ZeroDivisionError) as e:
            stats["api_errors"]+=1; print(f"Skip {s}: {type(e).__name__}")
    print("\nScan diagnostics:")
    for key,value in stats.items(): print(f"  {key.replace(chr(95), chr(32))}: {value}")
    if watch_candidates and not btc_regime_ok:
        summary = "🔎 WATCH ONLY — BTC gate failed; no bullish alerts sent"
    elif watch_candidates:
        summary = "🔎 WATCHLIST — early candidates found; only strict setups can trigger bullish alerts"
    else:
        summary = (
            f"🔎 SCANNER STATUS — {count} setup alert(s) sent"
            if count else
            "🔎 SCANNER STATUS — NO TRADE"
        )
    reasons = [
        ("cooldown (recent alert suppressed)", stats["cooldown"]),
        ("insufficient history or candle gaps", stats["insufficient_history"]),
        ("multi-timeframe trend failed", stats["trend"]),
        ("RSI/breakout/volume/relative-strength/close-location/price-drift filter failed", stats["momentum_breakout_volume_rs"]),
        ("spread/order-book depth filter failed", stats["orderbook_spread_depth"]),
        ("stop-distance/risk filter failed", stats["stop_risk"]),
        ("API/data errors while checking pairs", stats["api_errors"]),
        ("passed individual technical filters", stats["qualified"]),
        ("watch-only candidates blocked by BTC gate", stats["watch_only"]),
    ]
    detail = "\n".join(f"• {label}: {value}" for label, value in reasons)
    if watch_candidates:
        candidates_text = "\n".join(f"• {item}" for item in watch_candidates[:3])
        if len(watch_candidates) > 3:
            candidates_text += f"\n• ...and {len(watch_candidates)-3} more watch-only candidate(s)"
        note = (f"{btc_regime_reason}\nThese are watch-only, not bullish alerts or buy recommendations."
                if not btc_regime_ok else
                "These candidates failed one or more strict confirmation conditions. They are watch-only, not bullish alerts or buy recommendations.")
        report = f"{summary}\nPairs considered: {stats['considered']}\n{detail}\n\nWatch-only candidates (up to 3 shown):\n{candidates_text}\n\n{note}\nNo orders placed."
    else:
        note = ("At least one setup passed the technical screen; this is not a buy recommendation."
                if count else
                "No pair passed every required filter this scan. Filters are deliberately strict; this does not predict that prices will fall.")
        report = f"{summary}\nPairs considered: {stats['considered']}\n{detail}\n\n{note}\nNo orders placed; technical-only screening."
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
