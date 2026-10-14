"""Alert-only Binance USDT spot scanner; never places orders."""
import json, os, time, math, sys
from datetime import datetime, timezone
from pathlib import Path
import requests
BASE="https://data-api.binance.vision"; TG="https://api.telegram.org"; STATE=Path(".state.json")
S=requests.Session(); S.headers.update({"User-Agent":"telegram-crypto-scanner/1.0"})
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
def candles(sym,iv):
    raw=get("/api/v3/klines",{"symbol":sym,"interval":iv,"limit":80}); now=int(datetime.now(timezone.utc).timestamp()*1000); out=[]
    for x in raw:
        try:
            if len(x)<7 or int(x[6])>=now:continue
            o,h,l,c,v=map(float,x[1:6])
            if not all(math.isfinite(z) for z in (o,h,l,c,v)) or min(o,h,l,c)<=0 or v<0 or h<max(o,c,l) or l>min(o,c):continue
            out.append({"high":h,"low":l,"close":c,"volume":v})
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
    ts=get("/api/v3/ticker/24hr"); ex={"USDC","FDUSD","TUSD","USDP","DAI","USDE","BUSD","EUR","TRY","BRL","USTC"}; u=[]
    for t in ts:
        s=t.get("symbol","")
        try:q=float(t["quoteVolume"]); ch=float(t["priceChangePercent"]); p=float(t["lastPrice"])
        except (ValueError,TypeError,KeyError):continue
        b=s[:-4] if s.endswith("USDT") else ""
        if s in valid and b and b not in ex and not b.endswith(("UP","DOWN","BULL","BEAR")) and q>=3000000 and p>0:u.append((q,s,ch,p))
    u=sorted(u,reverse=True)[:60]; btcch=next((x[2] for x in u if x[1]=="BTCUSDT"),0)
    btc=candles("BTCUSDT","1h")
    if len(btc)<55 or ema([x["close"] for x in btc],20)<=ema([x["close"] for x in btc],50):
        print("NO TRADE: BTC hourly trend filter failed.");return
    try:state=json.loads(STATE.read_text())
    except (OSError,ValueError):state={"alerts":{}}
    if not isinstance(state,dict) or not isinstance(state.get("alerts"),dict):state={"alerts":{}}
    now=time.time(); count=0
    stats={"considered":0,"cooldown":0,"insufficient_history":0,"trend":0,"momentum_breakout_volume_rs":0,"orderbook_spread_depth":0,"stop_risk":0,"api_errors":0,"qualified":0}
    for q,s,ch,p in u:
        if s=="BTCUSDT": continue
        stats["considered"]+=1
        if now-float(state["alerts"].get(s,0) or 0)<21600:
            stats["cooldown"]+=1; continue
        try:
            h1=candles(s,"1h"); h4=candles(s,"4h"); d1=candles(s,"1d")
            if min(len(h1),len(h4),len(d1))<55:
                stats["insufficient_history"]+=1; continue
            a=[x["close"] for x in h1]; b=[x["close"] for x in h4]; d=[x["close"] for x in d1]
            if not(ema(a,20)>ema(a,50) and a[-1]>ema(a,20) and ema(b,20)>ema(b,50) and b[-1]>ema(b,20) and ema(d,20)>ema(d,50) and d[-1]>ema(d,20)):
                stats["trend"]+=1; continue
            prior=h1[-21:-1]; rr=rsi(a); br=(a[-1]/max(x["high"] for x in prior)-1)*100; av=sum(x["volume"] for x in prior)/20; vr=h1[-1]["volume"]/av if av else 0; rs=ch-btcch; drift=(p/a[-1]-1)*100
            if rr is None or not 52<=rr<=68 or not 0<=br<=1.2 or vr<1.3 or rs<1.5 or abs(drift)>.75:
                stats["momentum_breakout_volume_rs"]+=1; continue
            ob=get("/api/v3/depth",{"symbol":s,"limit":100}); bids=[(float(x[0]),float(x[1])) for x in ob.get("bids",[]) if len(x)>=2]; asks=[(float(x[0]),float(x[1])) for x in ob.get("asks",[]) if len(x)>=2]
            if not bids or not asks:
                stats["orderbook_spread_depth"]+=1; continue
            bid=max(x[0] for x in bids); ask=min(x[0] for x in asks); mid=(bid+ask)/2
            if mid<=0 or ask<=bid or (ask-bid)/mid*100>.15:
                stats["orderbook_spread_depth"]+=1; continue
            bd=sum(x*y for x,y in bids if x>=mid*.995); ad=sum(x*y for x,y in asks if x<=mid*1.005)
            if min(bd,ad)<15000:
                stats["orderbook_spread_depth"]+=1; continue
            stop=min(x["low"] for x in h1[-6:-1]); risk=p-stop
            if stop<=0 or not .005<=risk/p<=.03:
                stats["stop_risk"]+=1; continue
            target=p+2*risk
            msg=(f"⚠️ WATCH — technical screen passed, NOT a buy signal\nPair: {s}\nScan price: {p:.8g} USDT\nRSI: {rr:.1f}; volume: {vr:.2f}x; breakout: {br:.2f}%; relative strength vs BTC: {rs:+.2f} pp\nIllustrative invalidation: {stop:.8g}; 2R target: {target:.8g}\n24h quote volume: {q:,.0f} USDT; spread: {(ask-bid)/mid*100:.3f}%\nTechnical-only; news, token unlocks, security and regulatory risks are not checked. Fees/slippage change results. No profit/probability guaranteed. No orders placed.")
            send(msg);state["alerts"][s]=now;tmp=STATE.with_suffix(".tmp");tmp.write_text(json.dumps(state,allow_nan=False));tmp.replace(STATE);count+=1;stats["qualified"]+=1
            if count>=3:break
        except (RuntimeError,ValueError,requests.RequestException,KeyError,TypeError,ZeroDivisionError) as e:
            stats["api_errors"]+=1; print(f"Skip {s}: {type(e).__name__}")
    print("\nScan diagnostics:")
    for key,value in stats.items(): print(f"  {key.replace(chr(95), chr(32))}: {value}")
    print(f"Scan complete; alerts sent: {count}" if count else "NO TRADE: no candidate passed every filter.")
if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--test-telegram":send("Telegram scanner connectivity test only; no signal generated.");print("Telegram test sent.")
    else:scan()
