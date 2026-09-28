# app.py – NIFTY Ultimate Bot (Final Version with Detailed Pattern Analysis)
import logging
import feedparser
import numpy as np
import pandas as pd
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

# ---------- DATA FETCHING ----------

@st.cache_data(ttl=60, show_spinner=False)
def fetch_ohlc(symbol, period="5d", interval="5m"):
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
    except Exception as exc:
        raise DataError(f"fetch failed for {symbol}: {exc}") from exc
    
    if df is None or df.empty:
        raise DataError(f"no data for {symbol}")
    
    df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    return df

@st.cache_data(ttl=300, show_spinner=False)
def fetch_3m_data(symbol):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="5m")
        if df is None or df.empty:
            raise DataError(f"no 5m data for {symbol}")
        
        df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
        
        df_3m = df.resample('3min').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 
            'Close': 'last', 'Volume': 'sum'
        }).dropna(subset=['Open', 'High', 'Low', 'Close'])
        
        return df_3m
    except Exception as exc:
        log.warning("3m fetch failed for %s: %s", symbol, exc)
        raise DataError(f"3m data failed for {symbol}")

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

# ---------- INDICATORS ----------

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
    if v.isna().all() or v.sum() == 0:
        return tp.expanding().mean()
    return tp.mul(v).groupby(df.index.date).cumsum() / v.groupby(df.index.date).cumsum()

# ---------- ZEBU CALCULATIONS ----------

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

def calculate_3m_levels(df):
    df = df.copy()
    df['Date'] = df.index.date
    dates = sorted(df['Date'].unique())
    
    if len(dates) < 2:
        return None, None
        
    prev_day = df[df['Date'] == dates[-2]]
    today = df[df['Date'] == dates[-1]]
    
    if prev_day.empty or today.empty:
        return None, None
        
    x1_high = prev_day['High'].iloc[-1]
    x2_high = today['High'].iloc[0]
    x3_up = x2_high - x1_high
    x4_up = x3_up / 2
    x5_up = x1_high - x4_up
    
    x1_low = prev_day['Low'].iloc[-1]
    x2_low = today['Low'].iloc[0]
    x3_down = x2_low - x1_low
    x4_down = x3_down / 2
    x5_down = x2_low + x4_down
    
    gap_up = {
        "X1 (Prev Close 3m High)": x1_high, "X2 (Today Open 3m High)": x2_high, 
        "X3 (Difference X2-X1)": x3_up, "X4 (Half of X3)": x4_up, 
        "X5 (Reversal Level X1-X4)": x5_up
    }
    gap_down = {
        "X1 (Prev Close 3m Low)": x1_low, "X2 (Today Open 3m Low)": x2_low, 
        "X3 (Difference X2-X1)": x3_down, "X4 (Half of X3)": x4_down, 
        "X5 (Reversal Level X2+X4)": x5_down
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
    if av == 0 or ab == 0 or pd.isna(av):
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

# 1. MARKET OVERVIEW
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

# 2. MARKET STRUCTURE
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

# 3. DETAILED PATTERN ANALYSIS (UPDATED)
st.subheader("📊 Today's Market Levels & Pattern Match")
try:
    daily_df = fetch_daily(NIFTY)
    if len(daily_df) >= 3:
        d2 = daily_df.iloc[-3]  # Day before yesterday
        d1 = daily_df.iloc[-2]  # Yesterday
        today = daily_df.iloc[-1]  # Today
        
        # Display Today's OHLC
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Today's Open", f"{today['Open']:,.2f}")
        c2.metric("Today's High", f"{today['High']:,.2f}")
        c3.metric("Today's Low", f"{today['Low']:,.2f}")
        c4.metric("Current/Close", f"{today['Close']:,.2f}")
        
        st.write("---")
        
        # Pattern Logic
        curr_hh = today['High'] > d1['High']
        curr_hl = today['Low'] > d1['Low']
        prev_hh = d1['High'] > d2['High']
        prev_hl = d1['Low'] > d2['Low']
        
        def get_label(hh, hl):
            if hh and hl: return "Uptrend (HH, HL)"
            if not hh and not hl: return "Downtrend (LH, LL)"
            if hh and not hl: return "Expanding Volatility (HH, LL)"
            if not hh and hl: return "Contracting Volatility (LH, HL)"
            return "Sideways"
            
        curr_pattern = get_label(curr_hh, curr_hl)
        prev_pattern = get_label(prev_hh, prev_hl)
        
        st.markdown(f"### 📈 Today's Pattern: **{curr_pattern}**")
        
        # Show comparison in detail
        st.write("**Pattern Logic Check (Today vs Yesterday):**")
        h_sym = "Higher High (HH)" if curr_hh else "Lower High (LH)"
        l_sym = "Higher Low (HL)" if curr_hl else "Lower Low (LL)"
        st.write(f"• High: Today **{today['High']:,.1f}** vs Yesterday **{d1['High']:,.1f}** ➔ {h_sym}")
        st.write(f"• Low:  Today **{today['Low']:,.1f}** vs Yesterday **{d1['Low']:,.1f}** ➔ {l_sym}")
        
        st.write("---")
        
        # Actionable Insight
        if "Downtrend" in curr_pattern:
            st.error(f"🔻 **Market Implication:** Bearish trend continues. The market is making lower highs and lower lows. Selling on rallies (shorting) is favorable. Wait for the price to reach R1/R2 (Pivot Points) to enter a short trade.")
        elif "Uptrend" in curr_pattern:
            st.success(f"🔺 **Market Implication:** Bullish trend continues. The market is making higher highs and higher lows. Buying on dips (long) is favorable. Wait for the price to reach S1/S2 (Pivot Points) to enter a long trade.")
        elif "Expanding" in curr_pattern:
            st.warning(f"⚠️ **Market Implication:** High volatility. The market is moving wildly. Avoid trading until a clear direction emerges.")
        else:
            st.info(f"➡️ **Market Implication:** Consolidation phase. The market is stuck in a range. Wait for a breakout or breakdown.")
            
        st.write("---")
        
        # Show the previous pattern comparison
        if curr_pattern == prev_pattern:
            st.success(f"✅ Today's pattern **matches** the previous pattern: {prev_pattern}")
        else:
            st.warning(f"🔄 Today's pattern **shifted** from previous: {prev_pattern} ➔ {curr_pattern}")
            
    else:
        st.warning("Not enough daily data for pattern analysis.")
except DataError as e:
    st.error(str(e))

st.divider()

# 4. PIVOTS & GAP LEVELS
colA, colB = st.columns(2)
with colA:
    st.subheader("📐 Pivot Points (Zebu)")
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
        df3 = fetch_3m_data(NIFTY)
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

# 5. BREADTH
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

# 6. BIG PLAYER
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

# 7. NEWS
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
