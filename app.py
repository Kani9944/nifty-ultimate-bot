# app.py – NIFTY Ultimate Bot (All Final Fixes Applied)
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
        return None, None, None  # Return gap_direction as well
        
    prev_day = df[df['Date'] == dates[-2]]
    today = df[df['Date'] == dates[-1]]
    
    if prev_day.empty or today.empty:
        return None, None, None
        
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
    
    # FIX 5: Determine gap direction automatically
    # If X2 > X1 (today's open high > prev close high) = Gap Up
    # If X2 < X1 (today's open low < prev close low) = Gap Down
    gap_direction = "GAP UP" if x2_high > x1_high else "GAP DOWN"
    
    return gap_up, gap_down, gap_direction

def zigzag_swing_points(df, threshold_pct=0.001, skip_first_n=12):
    """
    ZigZag algorithm with fixes:
    - skip_first_n=12: Skip first 12 candles (09:15-10:15) to avoid day open
    - Then remove the FIRST swing high (it's still usually the day open)
    """
    if len(df) < skip_first_n + 3:
        return pd.DataFrame(), pd.DataFrame()
    
    df_trimmed = df.iloc[skip_first_n:]
    
    highs = df_trimmed['High'].values
    lows = df_trimmed['Low'].values
    indices = df_trimmed.index
    
    swing_highs = []
    swing_lows = []
    
    last_pivot_type = 'H'
    last_pivot_price = highs[0]
    last_pivot_idx = indices[0]
    
    for i in range(1, len(df_trimmed)):
        curr_high = highs[i]
        curr_low = lows[i]
        curr_idx = indices[i]
        
        if last_pivot_type == 'H':
            if curr_high > last_pivot_price:
                last_pivot_price = curr_high
                last_pivot_idx = curr_idx
            elif curr_low < last_pivot_price * (1 - threshold_pct):
                swing_highs.append({'Index': last_pivot_idx, 'Price': last_pivot_price})
                last_pivot_type = 'L'
                last_pivot_price = curr_low
                last_pivot_idx = curr_idx
        else:
            if curr_low < last_pivot_price:
                last_pivot_price = curr_low
                last_pivot_idx = curr_idx
            elif curr_high > last_pivot_price * (1 + threshold_pct):
                swing_lows.append({'Index': last_pivot_idx, 'Price': last_pivot_price})
                last_pivot_type = 'H'
                last_pivot_price = curr_high
                last_pivot_idx = curr_idx

    if last_pivot_type == 'H':
        swing_highs.append({'Index': last_pivot_idx, 'Price': last_pivot_price})
    else:
        swing_lows.append({'Index': last_pivot_idx, 'Price': last_pivot_price})
        
    df_highs = pd.DataFrame(swing_highs)
    df_lows = pd.DataFrame(swing_lows)
    
    # FIX 6: Remove the FIRST swing high (usually the false one near day open)
    if not df_highs.empty and len(df_highs) > 1:
        df_highs = df_highs.iloc[1:].reset_index(drop=True)
    
    # Renumber labels H1, H2, H3...
    if not df_highs.empty:
        df_highs['Label'] = [f"H{i+1}" for i in range(len(df_highs))]
    if not df_lows.empty:
        df_lows['Label'] = [f"L{i+1}" for i in range(len(df_lows))]
        
    return df_highs, df_lows

def draw_neat_chart(today_df):
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=today_df.index, y=today_df['Close'],
        mode='lines', 
        line=dict(color='rgba(0,0,0,1)', width=2.5),
        name="NIFTY",
        connectgaps=True
    ))
    
    # FIX 6: skip_first_n=12 + remove first swing high
    swing_highs, swing_lows = zigzag_swing_points(today_df, threshold_pct=0.001, skip_first_n=12)
    
    for _, row in swing_highs.iterrows():
        fig.add_annotation(
            x=row['Index'], y=row['Price'],
            text=row['Label'],
            showarrow=False,
            yshift=18,
            font=dict(color="green", size=14, family="Arial Black")
        )
        
    for _, row in swing_lows.iterrows():
        fig.add_annotation(
            x=row['Index'], y=row['Price'],
            text=row['Label'],
            showarrow=False,
            yshift=-18,
            font=dict(color="red", size=14, family="Arial Black")
        )
    
    fig.update_layout(
        title=None,
        height=500,
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=30, b=10),
        yaxis_title="Price",
        plot_bgcolor='white',
        xaxis=dict(
            showgrid=True, 
            gridcolor='lightgray',
            rangebreaks=[
                dict(bounds=["sat", "mon"]),
                dict(bounds=[15.5, 9.25], pattern="hour")
            ]
        ),
        yaxis=dict(showgrid=True, gridcolor='lightgray')
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
        "https://www.dinamani.com/rss/business.xml",
        "https://tamil.business-standard.com/rss.xml",
        "https://www.dinamalar.com/rss/business.xml",
    ]
    items = []
    for url in feeds:
        try:
            f = feedparser.parse(url)
            for e in f.entries[:limit]:
                title = e.get("title", "").strip()
                link = e.get("link", "").strip()
                if title and len(title) > 10:
                    items.append((title, link))
        except Exception:
            log.exception("news fetch failed: %s", url)
    seen = set()
    unique_items = []
    for t, l in items:
        if t not in seen:
            seen.add(t)
            unique_items.append((t, l))
    return unique_items[:limit]

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

# 3. LIVE NEAT CHART WITH ZIGZAG H/L
st.subheader("📈 NIFTY Intraday Chart (ZigZag H = High, L = Low)")
try:
    df_intra = fetch_ohlc(NIFTY, period="2d", interval="5m")
    df_intra['Date'] = df_intra.index.date
    dates = sorted(df_intra['Date'].unique())
    
    if len(dates) >= 2:
        today_df = df_intra[df_intra['Date'] == dates[-1]]
        
        if not today_df.empty:
            fig = draw_neat_chart(today_df)
            st.plotly_chart(fig, use_container_width=True)
            
            st.write("---")
            st.info("ℹ️ **Chart Explanation:** 'H1, H2...' are the true Swing Highs (Green) and 'L1, L2...' are the true Swing Lows (Red). First 12 candles skipped + first false swing removed.")
        else:
            st.warning("Not enough intraday data for today.")
    else:
        st.warning("Not enough daily data to compare.")
except DataError as e:
    st.error(str(e))

st.divider()

# 4. PIVOTS & GAP LEVELS (Colored Call/Put)
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
            
            st.markdown(f"<span style='color:green;'>**R3 (Call)**: {lv['R3']:,.1f}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='color:green;'>**R2 (Call)**: {lv['R2']:,.1f}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='color:green;'>**R1 (Call)**: {lv['R1']:,.1f}</span>", unsafe_allow_html=True)
            
            st.markdown(f"**Pivot**: {lv['Pivot']:,.1f}")
            
            st.markdown(f"<span style='color:red;'>**S1 (Put)**: {lv['S1']:,.1f}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='color:red;'>**S2 (Put)**: {lv['S2']:,.1f}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='color:red;'>**S3 (Put)**: {lv['S3']:,.1f}</span>", unsafe_allow_html=True)
            
            st.markdown(f"<span style='color:green;'>**CPR Top**: {top:,.1f}</span>", unsafe_allow_html=True)
            st.markdown(f"<span style='color:red;'>**CPR Bot**: {bot:,.1f}</span>", unsafe_allow_html=True)
            
    except DataError as e:
        st.error(str(e))

with colB:
    st.subheader("🎯 3-Min Gap Levels (Zebu)")
    try:
        df3 = fetch_3m_data(NIFTY)
        result = calculate_3m_levels(df3)
        
        if result[0] is None:
            st.warning("not enough 3-min data")
        else:
            gap_up, gap_down, gap_direction = result
            
            # FIX 5: Auto-detect gap direction and show appropriate tab first
            if gap_direction == "GAP UP":
                tab1, tab2 = st.tabs(["📈 GAP UP (Active)", "📉 GAP DOWN"])
                with tab1:
                    for k, v in gap_up.items():
                        st.write(f"**{k}**: {v:,.2f}")
                with tab2:
                    for k, v in gap_down.items():
                        st.write(f"**{k}**: {v:,.2f}")
            else:
                tab1, tab2 = st.tabs(["📈 GAP UP", "📉 GAP DOWN (Active)"])
                with tab1:
                    for k, v in gap_up.items():
                        st.write(f"**{k}**: {v:,.2f}")
                with tab2:
                    for k, v in gap_down.items():
                        st.write(f"**{k}**: {v:,.2f}")
    except DataError as e:
        st.error(str(e))

st.divider()

# 5. BREADTH (FIXED: Symbol colored + Price 2 decimals + Change % format)
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
    tbl = pd.DataFrame(rows)
    tbl = tbl[["Symbol", "Price", "Change %"]]
    tbl['Price'] = pd.to_numeric(tbl['Price'], errors='coerce').round(2)
    tbl = tbl.sort_values("Change %", ascending=False)
    
    adv = (tbl["Change %"] > 0).sum()
    dec = (tbl["Change %"] < 0).sum()
    
    a, b, c = st.columns(3)
    a.markdown(f"<span style='color:green;'>**Advancing**</span>", unsafe_allow_html=True)
    a.markdown(f"<h2 style='color:green;'>{adv}</h2>", unsafe_allow_html=True)
    
    b.markdown(f"<span style='color:red;'>**Declining**</span>", unsafe_allow_html=True)
    b.markdown(f"<h2 style='color:red;'>{dec}</h2>", unsafe_allow_html=True)
    
    c.metric("Avg Change %", f"{tbl['Change %'].mean():+.2f}%")
    
    # FIX 1 & 4: Color Symbol based on Change % + format numbers
    def color_symbol_and_change(row):
        color = 'color: green; font-weight: bold' if row['Change %'] > 0 else 'color: red; font-weight: bold'
        return [color, '', color]
    
    styled = tbl.style.apply(color_symbol_and_change, axis=1).format({
        'Price': '{:.2f}',
        'Change %': '{:+.2f}%'
    })
    
    st.dataframe(styled, use_container_width=True, hide_index=True)
else:
    st.warning("no breadth data")

st.divider()

# 6. BIG PLAYER (FIXED: Symbol colored + Price 2 decimals)
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
    df_hits = pd.DataFrame(hits)
    df_hits = df_hits[["Symbol", "Signal", "Price"]]
    df_hits['Price'] = pd.to_numeric(df_hits['Price'], errors='coerce').round(2)
    
    # FIX 1: Color Symbol based on Signal + format Price
    def color_symbol_and_signal(row):
        if row['Signal'] == 'BUY':
            return ['color: green; font-weight: bold', 'color: green; font-weight: bold', '']
        else:
            return ['color: red; font-weight: bold', 'color: red; font-weight: bold', '']
    
    styled_hits = df_hits.style.apply(color_symbol_and_signal, axis=1).format({
        'Price': '{:.2f}'
    })
    
    st.dataframe(styled_hits, use_container_width=True, hide_index=True)
                 
    b = sum(1 for h in hits if h["Signal"] == "BUY")
    s = len(hits) - b
    st.markdown(f"<span style='color:green;'><b>Buy pressure: {b}</b></span> | <span style='color:red;'><b>Sell pressure: {s}</b></span>", unsafe_allow_html=True)
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
    st.info("No news available. RSS feeds may be temporarily blocked.")
