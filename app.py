# app.py – NIFTY Ultimate Bot (Zebu 3-Min Candle Logic)
import logging
import feedparser
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from streamlit_autorefresh import st_autorefresh

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nifty-bot")

st.set_page_config(page_title="NIFTY Ultimate Bot", layout="wide")
st_autorefresh(interval=60000, key="refresh")

NIFTY = "^NSEI"
BANKNIFTY = "^NSEBANK"
VIX = "^INDIAVIX"

HEAVYWEIGHTS = [
    "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "TCS.NS", "ITC.NS", "LT.NS", "SBIN.NS", "AXISBANK.NS",
    "KOTAKBANK.NS", "BHARTIARTL.NS", "HINDUNILVR.NS",
    "MARUTI.NS", "ASIANPAINT.NS", "BAJFINANCE.NS",
    "TITAN.NS", "SUNPHARMA.NS", "WIPRO.NS",
]

class DataError(Exception):
    pass

@st.cache_data(ttl=60, show_spinner=False)
def fetch_ohlc(symbol, period="5d", interval="5m"):
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
    except Exception as exc:
        raise DataError(f"fetch failed for {symbol}: {exc}") from exc
    if df is None or df.empty:
        raise DataError(f"no data for {symbol}")
    return df.dropna()

@st.cache_data(ttl=60, show_spinner=False)
def fetch_daily(symbol):
    return fetch_ohlc(symbol, period="1mo", interval="1d")

@st.cache_data(ttl=120, show_spinner=False)
def fetch_many(symbols, interval="5m"):
    out = {}
    for s in symbols:
        try:
            out[s] = fetch_ohlc(s, period="5d", interval=interval)
        except DataError as e:
            log.warning("skip %s: %s", s, e)
    return out

def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def rsi(s, period=14):
    d = s.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    ag = g.ewm(alpha=1/period, adjust=False).mean()
    al = l.ewm(alpha=1/period, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def vwap(df):
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    v = df["Volume"].replace(0, np.nan)
    return tp.mul(v).groupby(df.index.date).cumsum() / v.groupby(df.index.date).cumsum()

def pivots(h, l, c):
    p = (h + l + c) / 3
    r1 = 2 * p - l
    s1 = 2 * p - h
    r2 = p + (r1 - s1)
    s2 = p - (r1 - s1)
    r3 = h + 2 * (p - l)
    s3 = l - 2 * (h - p)
    return {"R3": r3, "R2": r2, "R1": r1, "Pivot": p, "S1": s1, "S2": s2, "S3": s3}

def cpr(h, l, c):
    p = (h + l + c) / 3
    bc = (h + l) / 2
    return max(p, bc), min(p, bc)

def atr(df, period=14):
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def calculate_3m_levels(df):
    """Calculate X1-X5 based on Zebu 3-min candle logic."""
    df = df.copy()
    df['Date'] = df.index.date
    dates = sorted(df['Date'].unique())
    
    if len(dates) < 2:
        return None, None
        
    prev_day = df[df['Date'] == dates[-2]]
    today = df[df['Date'] == dates[-1]]
    
    if prev_day.empty or today.empty:
        return None, None
        
    # Gap Up Logic
    x1_high = prev_day['High'].iloc[-1]
    x2_high = today['High'].iloc[0]
    x3_up = x2_high - x1_high
    x4_up = x3_up / 2
    x5_up = x1_high - x4_up
    
    # Gap Down Logic
    x1_low = prev_day['Low'].iloc[-1]
    x2_low = today['Low'].iloc[0]
    x3_down = x2_low - x1_low
    x4_down = x3_down / 2
    x5_down = x2_low + x4_down
    
    gap_up = {
        "X1": x1_high, "X2": x2_high, "X3": x3_up, 
        "X4": x4_up, "X5": x5_up
    }
    gap_down = {
        "X1": x1_low, "X2": x2_low, "X3": x3_down, 
        "X4": x4_down, "X5": x5_down
    }
    return gap_up, gap_down

def big_player(df, vol_mult=2.5, body_mult=1.5):
    if len(df) < 25:
        return None
    comp = df.iloc[:-1]
    last = comp.iloc[-1]
    ref = comp.iloc[-21:-1]
    av = ref["Volume"].mean()
    ab = (ref["Close"] - ref["Open"]).abs().mean()
    if av == 0 or ab == 0:
        return None
    body = abs(last["Close"] - last["Open"])
    if last["Volume"] >= vol_mult * av and body >= body_mult * ab:
        return "BUY" if last["Close"] > last["Open"] else "SELL"
    return None

def structure(df):
    c = df["Close"]
    price = c.iloc[-1]
    vw = vwap(df).iloc[-1]
    e9 = ema(c, 9).iloc[-1]
    e21 = ema(c, 21).iloc[-1]
    r = rsi(c).iloc[-1]
    if price > vw and e9 > e21 and r > 50:
        return "Bullish", price, vw, e9, e21, r
    if price < vw and e9 < e21 and r < 50:
        return "Bearish", price, vw, e9, e21, r
    return "Mixed", price, vw, e9, e21, r

@st.cache_data(ttl=180, show_spinner=False)
def load_news(limit=6):
    feeds = [
        "https://tamil.business-standard.com/rss.xml",
        "https://www.dinamalar.com/rss/business.xml",
    ]
    items = []
    for url in feeds:
        try:
            f = feedparser.parse(url)
            for e in f.entries[:limit]:
                items.append((e.get("title", ""), e.get("link", "")))
        except Exception:
            log.exception("news fetch failed: %s", url)
    return items[:limit]

# ---------- UI ----------
st.title("🇮🇳 NIFTY Ultimate Bot")
st.caption("Data via Yahoo Finance – may be delayed by up to 15 minutes.")

st.subheader("📊 Market Overview")
c1, c2, c3 = st.columns(3)
try:
    n = fetch_ohlc(NIFTY)
    spot = n["Close"].iloc[-1]
    prev = n["Close"].iloc[-2]
    c1.metric("NIFTY 50", f"{spot:,.2f}",
              f"{spot-prev:+.2f} ({(spot-prev)/prev*100:+.2f}%)")
except DataError as e:
    c1.error(str(e))

for col, (lbl, sym) in zip([c2, c3],
                           [("Bank Nifty", BANKNIFTY), ("India VIX", VIX)]):
    try:
        d = fetch_ohlc(sym)
        v = d["Close"].iloc[-1]
        p = d["Close"].iloc[-2]
        col.metric(lbl, f"{v:,.2f}", f"{v-p:+.2f}")
    except DataError as e:
        col.error(str(e))

st.divider()

st.subheader("🧭 Market Structure")
try:
    df5 = fetch_ohlc(NIFTY, period="2d", interval="5m")
    verdict, price, vw, e9, e21, r = structure(df5)
    icon = {"Bullish": "🟢", "Bearish": "🔴", "Mixed": "🟡"}[verdict]
    st.markdown(f"### {icon} {verdict}")
    st.write(f"Price {price:,.1f} | VWAP {vw:,.1f} | "
             f"EMA9 {e9:,.1f} | EMA21 {e21:,.1f} | RSI {r:.1f}")
except DataError as e:
    st.error(str(e))

st.divider()

colA, colB = st.columns(2)
with colA:
    st.subheader("📐 Pivot Points")
    try:
        dy = fetch_daily(NIFTY)
        if len(dy) < 2:
            st.warning("not enough daily candles")
        else:
            pdh = dy["High"].iloc[-2]
            pdl = dy["Low"].iloc[-2]
            pdc = dy["Close"].iloc[-2]
            lv = pivots(pdh, pdl, pdc)
            top, bot = cpr(pdh, pdl, pdc)
            for k, v in lv.items():
                st.write(f"**{k}**: {v:,.1f}")
            st.write(f"**CPR Top**: {top:,.1f}")
            st.write(f"**CPR Bot**: {bot:,.1f}")
    except DataError as e:
        st.error(str(e))

with colB:
    st.subheader("🎯 3-Min Gap Levels (Zebu)")
    try:
        df3 = fetch_ohlc(NIFTY, period="5d", interval="3m")
        gap_up, gap_down = calculate_3m_levels(df3)
        
        if gap_up is None:
            st.warning("not enough 3-min data")
        else:
            tab1, tab2 = st.tabs(["📈 GAP UP", "📉 GAP DOWN"])
            with tab1:
                for k, v in gap_up.items():
                    st.write(f"**{k}**: {v:,.2f}")
            with tab2:
                for k, v in gap_down.items():
                    st.write(f"**{k}**: {v:,.2f}")
    except DataError as e:
        st.error(str(e))

st.divider()

st.subheader("📈 NIFTY Intraday Chart")
try:
    dfc = fetch_ohlc(NIFTY, period="2d", interval="5m").copy()
    dfc["EMA9"] = ema(dfc["Close"], 9)
    dfc["EMA21"] = ema(dfc["Close"], 21)
    dfc["VWAP"] = vwap(dfc)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=dfc.index, open=dfc["Open"],
                                  high=dfc["High"], low=dfc["Low"],
                                  close=dfc["Close"], name="NIFTY"))
    fig.add_trace(go.Scatter(x=dfc.index, y=dfc["EMA9"], name="EMA 9",
                              line=dict(color="orange")))
    fig.add_trace(go.Scatter(x=dfc.index, y=dfc["EMA21"], name="EMA 21",
                              line=dict(color="blue")))
    fig.add_trace(go.Scatter(x=dfc.index, y=dfc["VWAP"], name="VWAP",
                              line=dict(color="purple", dash="dot")))
    fig.update_layout(height=500, xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)
except DataError as e:
    st.error(str(e))

st.divider()

st.subheader("🌐 Market Breadth (18 Heavyweights)")
data = fetch_many(tuple(HEAVYWEIGHTS))
rows = []
for sym, dd in data.items():
    if len(dd) < 2:
        continue
    ch = (dd["Close"].iloc[-1] - dd["Close"].iloc[-2]) / dd["Close"].iloc[-2]
    rows.append({"Symbol": sym.replace(".NS", ""),
                 "Price": dd["Close"].iloc[-1],
                 "Change %": ch * 100})
if rows:
    tbl = pd.DataFrame(rows).sort_values("Change %", ascending=False)
    adv = (tbl["Change %"] > 0).sum()
    dec = (tbl["Change %"] < 0).sum()
    a, b, c = st.columns(3)
    a.metric("Advancing", adv)
    b.metric("Declining", dec)
    c.metric("Avg Change %", f"{tbl['Change %'].mean():+.2f}%")
    st.dataframe(tbl, use_container_width=True, hide_index=True)
else:
    st.warning("no breadth data")

st.divider()

st.subheader("🐋 Big Player Alert")
st.caption("Volume spike (≥2.5×) + strong body (≥1.5×) on last completed 5-min candle")
hits = []
for sym, dd in data.items():
    sig = big_player(dd)
    if sig:
        hits.append({"Symbol": sym.replace(".NS", ""),
                     "Signal": sig,
                     "Price": dd["Close"].iloc[-1]})
if hits:
    st.dataframe(pd.DataFrame(hits), use_container_width=True, hide_index=True)
    b = sum(1 for h in hits if h["Signal"] == "BUY")
    s = len(hits) - b
    st.success(f"Buy pressure: {b} | Sell pressure: {s}")
else:
    st.info("No Big Player signals on the last completed candle.")

st.divider()

st.subheader("📰 Tamil Financial News")
news = load_news()
if news:
    for t, l in news:
        if l:
            st.markdown(f"- [{t}]({l})")
        else:
            st.markdown(f"- {t}")
else:
    st.info("No news available.")
