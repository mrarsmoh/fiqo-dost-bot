import os, time, requests, math
from datetime import datetime
from dateutil.tz import tzlocal
import ccxt, pandas as pd, numpy as np, ta

# ---- YOUR CREDENTIALS (yahan apna token/chat id dalo) ----
TELEGRAM_TOKEN = "8415870032:AAHlVao0-KJdrlyCbvzwYap7gRRtNsSgsew"
CHAT_ID        = "904917014"

# ---- BASIC SETTINGS (abhi inko mat chhedo) ----
EXCHANGE_NAME  = "binance"                    # binance ya mexc
SYMBOLS        = "ETH/USDT,BTC/USDT".split(",")
TIMEFRAMES     = "15m,1h".split(",")          # scalping ke liye best
CANDLE_LIMIT   = 200
SLEEP_SECONDS  = 45
MIN_CONF       = 60

def load_exchange(name):
    ex = getattr(ccxt, name.lower())()
    ex.load_markets()
    return ex

ex = load_exchange(EXCHANGE_NAME)

def tg(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": text})
    except Exception as e:
        print("Telegram error:", e)

def fetch_df(symbol, tf, limit=CANDLE_LIMIT):
    data = ex.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
    df = pd.DataFrame(data, columns=["time","open","high","low","close","volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_convert(tzlocal())
    return df

def candle_patterns(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    tags = []
    # Engulfing
    if last.close > last.open and prev.close < prev.open and last.close >= prev.open and last.open <= prev.close:
        tags.append("Bullish Engulfing")
    if last.close < last.open and prev.close > prev.open and last.close <= prev.open and last.open >= prev.close:
        tags.append("Bearish Engulfing")
    # Hammer / Shooting Star
    body = abs(last.close - last.open)
    upper = last.high - max(last.close, last.open)
    lower = min(last.close, last.open) - last.low
    if body > 0:
        if lower >= 2*body and upper <= body*0.5: tags.append("Hammer")
        if upper >= 2*body and lower <= body*0.5: tags.append("Shooting Star")
    # Doji
    if body <= (last.high - last.low) * 0.1: tags.append("Doji")
    return tags

def analyze(df):
    df["EMA9"]  = ta.trend.ema_indicator(df["close"], window=9)
    df["EMA21"] = ta.trend.ema_indicator(df["close"], window=21)
    df["RSI"]   = ta.momentum.rsi(df["close"], window=14)
    macd = ta.trend.MACD(df["close"])
    df["MACD"]  = macd.macd(); df["MACDS"] = macd.macd_signal()
    df["VOL_SMA"] = df["volume"].rolling(20).mean()
    df["ATR"]     = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=14)

    last = df.iloc[-1]
    conf, reasons = 0, []
    reasons.append("EMA Bullish" if last.EMA9>last.EMA21 else "EMA Bearish"); conf += 20
    if last.RSI < 35: reasons.append("RSI Oversold"); conf += 15
    elif last.RSI > 70: reasons.append("RSI Overbought"); conf += 15
    reasons.append("MACD Bullish" if last.MACD>last.MACDS else "MACD Bearish"); conf += 15
    if last.volume > (last.VOL_SMA*1.3): reasons.append("Volume Spike"); conf += 10
    pats = candle_patterns(df)
    if any(p in pats for p in ["Bullish Engulfing","Hammer"]): reasons.append("Bullish Pattern"); conf += 10
    if any(p in pats for p in ["Bearish Engulfing","Shooting Star"]): reasons.append("Bearish Pattern"); conf += 10
    if "Doji" in pats: reasons.append("Doji")

    bull = sum(["Bullish" in x or x=="RSI Oversold" for x in reasons])
    bear = sum(["Bearish" in x or x=="RSI Overbought" for x in reasons])
    direction = "LONG" if bull>bear else ("SHORT" if bear>bull else None)

    atr = float(df["ATR"].dropna().iloc[-1])
    price = float(last.close); sl_dist = max(atr*0.8, price*0.002)
    tp1_mult, tp2_mult = 1.2, 2.0
    if direction=="LONG":
        sl = price-sl_dist; tp1 = price+sl_dist*tp1_mult; tp2 = price+sl_dist*tp2_mult
    elif direction=="SHORT":
        sl = price+sl_dist; tp1 = price-sl_dist*tp1_mult; tp2 = price-sl_dist*tp2_mult
    else:
        sl=tp1=tp2=None
    return direction, int(conf), reasons, price, sl, tp1, tp2, pats, df.iloc[-1]["time"]

last_sent={}
tg("🚀 Fiqo Auto-Analysis Bot started.")

while True:
    try:
        for sym in SYMBOLS:
            for tf in TIMEFRAMES:
                key=(sym,tf)
                df=fetch_df(sym,tf)
                last_time=df.iloc[-1]["time"]
                if last_sent.get(key)==last_time: 
                    continue
                direction,conf,reasons,price,sl,tp1,tp2,pats,tstamp=analyze(df)
                if direction and conf>=MIN_CONF and sl and tp1:
                    msg=f"""📊 {sym} | TF: {tf}
Signal: {direction} | Confidence: {conf}%
Price: {price:.2f}
SL: {sl:.2f}
TP1: {tp1:.2f}  TP2: {tp2:.2f}
Confluence: {", ".join(reasons)}
Patterns: {", ".join(pats) if pats else "-"}
Time: {tstamp.strftime("%Y-%m-%d %H:%M")}
——
ATR-based RR ≈ 2.0  |  Risk chhota, reward bada ✅
"""
                    tg(msg)
                last_sent[key]=last_time
        time.sleep(SLEEP_SECONDS)
    except Exception as e:
        print("Error:", e)
        time.sleep(5)
