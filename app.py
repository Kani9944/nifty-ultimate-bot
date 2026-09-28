# app.py – NIFTY Ultimate Bot (Live Chart & Pattern Version)
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

def detect_live_pattern(today_df, yesterday_high, yesterday_low):
    """Detect live intraday pattern (W, M, Uptrend, Downtrend)."""
    if len(today_df) < 15:
        return "Not enough data", None, None, None
        
    today_high = today_df['High'].max()
    today_low = today_df['Low'].min()
    current_price = today_df['Close'].iloc[-1]
    
    # Find local peaks and troughs (swing highs/lows)
    window = 5
    today_df = today_df.copy()
    today_df['LocalMin'] = today_df['Low'].rolling(window=window, center=True).min()
    today_df['LocalMax'] = today_df['High'].rolling(window=window, center=True).max()
    
    recent_lows = today_df[today_df['Low'] == today_df['LocalMin']]['Low'].values[-3:]
    recent_highs = today_df[today_df['High'] == today_df['LocalMax']]['High'].values[-3:]
    
    pattern = "Sideways / Undefined"
    
    # W-Pattern (Double Bottom)
    if len(recent_lows) >= 2:
        low1, low2 = recent_lows[-2], recent_lows[-1]
        if abs(low2 - low1) / low1 < 0.0015:  # 0.15% tolerance
            pattern = "W-Pattern (Double Bottom)"
            
    # M-Pattern (Double Top)
    if len(recent_highs) >= 2:
        high1, high2 = recent_highs[-2], recent_highs[-1]
        if abs(high2 - high1) / high1 < 0.0015:
            pattern = "M-Pattern (Double Top)"
            
    # Uptrend / Downtrend fallback
    if pattern == "Sideways / Undefined":
        if today_high > yesterday_high and today_low > yesterday_low:
            pattern = "Uptrend (HH, HL)"
        elif today_high < yesterday_high and today_low < yesterday_low:
            pattern = "Downtrend (LH, LL)"
        elif today_high > yesterday_high and today_low < yesterday_low:
            pattern = "Expanding Volatility (HH, LL)"
        elif today_high < yesterday_high and today_low > yesterday_low:
            pattern = "Contracting Volatility (LH, HL)"
            
    return pattern, today_high, today_low, current_price

def draw_live_chart(today_df, yesterday_high, yesterday_low, pattern_name):
    """Draw a live candlestick chart with High/Low and Pattern annotations."""
    fig = go.Figure()
    
    # Add Candlestick
    fig.add_trace(go.Candlestick(
        x=today_df.index,
        open=today_df['Open'], high=today_df['High'],
        low=today_df['Low'], close=today_df['Close'],
        name="NIFTY 5-min"
    ))
    
    # Add Yesterday's High and Low lines
    fig.add_hline(y=yesterday_high, line_dash="dash", line_color="gray",
                  annotation_text=f"Yesterday High ({yesterday_high:,.1f})",
                  annotation_position="top right")
    fig.add_hline(y=yesterday_low, line_dash="dash", line_color="gray",
                  annotation_text=f"Yesterday Low ({yesterday_low:,.1f})",
                  annotation_position="bottom right")
    
    # Add Today's High and Low lines
    today_high = today_df['High'].max()
    today_low = today_df['Low'].min()
    fig.add_hline(y=today_high, line_color="green",
                  annotation_text=f"Today High ({today_high:,.1f})",
                  annotation_position="top left")
    fig.add_hline(y=today_low, line_color="red",
                  annotation_text=f"Today Low ({today_low:,.1f})",
                  annotation_position="bottom left")
    
    # Add Pattern Annotation
    fig.add_annotation(
        x=today_df.index[len(today_df)//2],
        y=today_high,
        text=f"Pattern: {pattern_name}",
        showarrow=True, arrowhead=2, ax=0, ay=-40,
        bgcolor="yellow", bordercolor="black"
    )
    
    fig.update_layout(
        title="NIFTY Live Intraday Chart (5-min)",
        height=500,
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=50, b=10),
        yaxis_title="Price"
    )
    return fig

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

# 3. LIVE INTRADAY PATTERN ANALYSIS (WITH CHART)
st.subheader("📊 இன்றைய லைவ் மார்க்கெட் பேட்டன் & சார்ட்")
try:
    df_intra = fetch_ohlc(NIFTY, period="2d", interval="5m")
    df_intra['Date'] = df_intra.index.date
    dates = sorted(df_intra['Date'].unique())
    
    if len(dates) >= 2:
        yesterday_df = df_intra[df_intra['Date'] == dates[-2]]
        today_df = df_intra[df_intra['Date'] == dates[-1]]
        
        if not today_df.empty and not yesterday_df.empty:
            y_high = yesterday_df['High'].max()
            y_low = yesterday_df['Low'].min()
            
            pattern, t_high, t_low, curr_price = detect_live_pattern(today_df, y_high, y_low)
            
            # Display Today's Live OHLC
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Today's Live High", f"{t_high:,.2f}")
            c2.metric("Today's Live Low", f"{t_low:,.2f}")
            c3.metric("Current Price", f"{curr_price:,.2f}")
            c4.metric("Yesterday's High/Low", f"{y_high:,.0f} / {y_low:,.0f}")
            
            st.write("---")
            
            # Live Chart
            fig = draw_live_chart(today_df, y_high, y_low, pattern)
            st.plotly_chart(fig, use_container_width=True)
            
            st.write("---")
            st.markdown(f"### 📈 Today's Live Pattern: **{pattern}**")
            
            st.write("**Pattern Logic Check (Today Live vs Yesterday):**")
            h_sym = "Higher High (HH)" if t_high > y_high else "Lower High (LH)"
            l_sym = "Higher Low (HL)" if t_low > y_low else "Lower Low (LL)"
            st.write(f"• High: Today **{t_high:,.1f}** vs Yesterday **{y_high:,.1f}** ➔ {h_sym}")
            st.write(f"• Low:  Today **{t_low:,.1f}** vs Yesterday **{y_low:,.1f}** ➔ {l_sym}")
            
            st.write("---")
            
            # Actionable Insight
            if "W-Pattern" in pattern:
                st.success(f"🚀 **Market Implication:** W-Pattern (Double Bottom) detected! The market is showing a strong reversal signal. A breakout above the recent high could lead to a massive upward move. **Long (Buy) positions are favorable.**")
            elif "M-Pattern" in pattern:
                st.error(f"🔻 **Market Implication:** M-Pattern (Double Top) detected! The market is showing a strong reversal signal. A breakdown below the recent low could lead to a massive downward move. **Short (Sell) positions are favorable.**")
            elif "Downtrend" in pattern:
                st.error(f"🔻 **Market Implication:** Bearish trend continues. The market is making lower highs and lower lows. Selling on rallies (shorting) is favorable. Wait for the price to reach R1/R2 (Pivot Points) to enter a short trade.")
            elif "Uptrend" in pattern:
                st.success(f"🔺 **Market Implication:** Bullish trend continues. The market is making higher highs and higher lows. Buying on dips (long) is favorable. Wait for the price to reach S1/S2 (Pivot Points) to enter a long trade.")
            elif "Expanding" in pattern:
                st.warning(f"⚠️ **Market Implication:** High volatility. The market is moving wildly. Avoid trading until a clear direction emerges.")
            else:
                st.info(f"➡️ **Market Implication:** Consolidation phase. The market is stuck in a range. Wait for a breakout or breakdown.")
        else:
            st.warning("Not enough intraday data for today.")
    else:
        st.warning("Not enough daily data to compare.")
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
