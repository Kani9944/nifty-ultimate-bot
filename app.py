# app.py – NIFTY Ultimate Bot (Complete, No Syntax Errors)
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import feedparser
import requests
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

MARKET_KEYWORDS = [
    "nifty", "sensex", "share", "stock", "market",
    "bse", "nse", "பங்கு", "பங்குச்சந்தை",
    "சென்செக்ஸ்", "நிஃப்டி",
]

class DataError(Exception):
    pass

# ---------- TIMEZONE HELPERS ----------

def to_ist(df):
    df = df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("Asia/Kolkata")
    else:
        df.index = df.index.tz_convert("Asia/Kolkata")
    return df

def get_confirmed_candles(df, interval_minutes=5):
    if df.empty:
        return df.copy()
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    last_ts = df.index[-1]
    if last_ts.tzinfo is None:
        last_ts = last_ts.tz_localize("Asia/Kolkata")
    candle_end = last_ts + pd.Timedelta(minutes=interval_minutes)
    if now_ist < candle_end:
        return df.iloc[:-1].copy()
    return df.copy()

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

@st.cache_data(ttl=60, show_spinner=False)
def fetch_daily(symbol):
    return fetch_ohlc(symbol, period="1mo", interval="1d")

@st.cache_data(ttl=60, show_spinner=False)
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
    volume = df["Volume"].fillna(0)
    if volume.sum() <= 0:
        return pd.Series(np.nan, index=df.index)
    session = pd.Series(df.index.date, index=df.index)
    cumulative_pv = (tp * volume).groupby(session).cumsum()
    cumulative_volume = volume.groupby(session).cumsum()
    return cumulative_pv / cumulative_volume.replace(0, np.nan)

# ---------- ZEBU CALCULATIONS ----------

def pivots(h, l, c):
    p = (h + l + c) / 3
    r1 = 2 * p - l
    s1 = 2 * p - h
    r2 = p + (r1 - s1)
    s2 = p - (r1 - s1)
    r3 = h + 2 * (p - l)
    s3 = l - 2 * (h - p)
    return {"R3": r3, "R2": r2, "R1": r1, "Pivot": p,
            "S1": s1, "S2": s2, "S3": s3}

def cpr(h, l, c):
    p = (h + l + c) / 3
    bc = (h + l) / 2
    return max(p, bc), min(p, bc)

def calculate_5m_gap_levels(df):
    df = to_ist(df)
    df['Date'] = df.index.date
    dates = sorted(df['Date'].unique())
    if len(dates) < 2:
        return None, None, None
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
        "X1 (Prev Close 5m High)": x1_high,
        "X2 (Today Open 5m High)": x2_high,
        "X3 (Difference X2-X1)": x3_up,
        "X4 (Half of X3)": x4_up,
        "X5 (Reversal Level X1-X4)": x5_up,
    }
    gap_down = {
        "X1 (Prev Close 5m Low)": x1_low,
        "X2 (Today Open 5m Low)": x2_low,
        "X3 (Difference X2-X1)": x3_down,
        "X4 (Half of X3)": x4_down,
        "X5 (Reversal Level X2+X4)": x5_down,
    }
    prev_close = prev_day['Close'].iloc[-1]
    today_open = today['Open'].iloc[0]
    if today_open > prev_close:
        gap_direction = "GAP UP"
    elif today_open < prev_close:
        gap_direction = "GAP DOWN"
    else:
        gap_direction = "NO GAP"
    return gap_up, gap_down, gap_direction

def zigzag_swing_points(df, threshold_pct=0.0015):
    if len(df) < 4:
        return pd.DataFrame(), pd.DataFrame()
    highs = df["High"].to_numpy()
    lows = df["Low"].to_numpy()
    indices = df.index
    swing_highs = []
    swing_lows = []
    pivot_type = "H"
    pivot_price = highs[0]
    pivot_index = indices[0]
    for i in range(1, len(df)):
        high = highs[i]
        low = lows[i]
        index = indices[i]
        if pivot_type == "H":
            if high >= pivot_price:
                pivot_price = high
                pivot_index = index
            elif low <= pivot_price * (1 - threshold_pct):
                swing_highs.append({"Index": pivot_index, "Price": pivot_price})
                pivot_type = "L"
                pivot_price = low
                pivot_index = index
        else:
            if low <= pivot_price:
                pivot_price = low
                pivot_index = index
            elif high >= pivot_price * (1 + threshold_pct):
                swing_lows.append({"Index": pivot_index, "Price": pivot_price})
                pivot_type = "H"
                pivot_price = high
                pivot_index = index
    df_highs = pd.DataFrame(swing_highs)
    df_lows = pd.DataFrame(swing_lows)
    if not df_highs.empty:
        df_highs["Label"] = [f"H{i + 1}" for i in range(len(df_highs))]
    if not df_lows.empty:
        df_lows["Label"] = [f"L{i + 1}" for i in range(len(df_lows))]
    return df_highs, df_lows

def draw_neat_chart(today_df):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=today_df.index,
        open=today_df["Open"],
        high=today_df["High"],
        low=today_df["Low"],
        close=today_df["Close"],
        name="NIFTY",
        increasing_line_color="#16A34A",
        decreasing_line_color="#DC2626",
        increasing_fillcolor="#16A34A",
        decreasing_fillcolor="#DC2626",
    ))
    confirmed = get_confirmed_candles(today_df, interval_minutes=5)
    swing_source = confirmed.between_time("09:15", "15:25")
    swing_highs, swing_lows = zigzag_swing_points(
        swing_source, threshold_pct=0.0015
    )
    swing_points = []
    for _, row in swing_highs.iterrows():
        swing_points.append((row["Index"], row["Price"], row["Label"], "high"))
    for _, row in swing_lows.iterrows():
        swing_points.append((row["Index"], row["Price"], row["Label"], "low"))
    swing_points.sort(key=lambda x: x[0])
    if swing_points:
        fig.add_trace(go.Scatter(
            x=[x[0] for x in swing_points],
            y=[x[1] for x in swing_points],
            mode="lines+markers+text",
            text=[x[2] for x in swing_points],
            textposition=[
                "top center" if x[3] == "high" else "bottom center"
                for x in swing_points
            ],
            marker=dict(
                size=9,
                color=[
                    "#16A34A" if x[3] == "high" else "#DC2626"
                    for x in swing_points
                ],
            ),
            line=dict(color="#2563EB", width=1.5, dash="dot"),
            textfont=dict(size=12, color="#111827"),
            name="Confirmed swings",
            hovertemplate=(
                "%{text}<br>"
                "Time: %{x|%H:%M}<br>"
                "Price: %{y:.2f}<extra></extra>"
            ),
        ))
    fig.update_layout(
        height=560,
        margin=dict(l=10, r=10, t=35, b=10),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hovermode="x unified",
        showlegend=False,
        xaxis=dict(
            type="date",
            showgrid=True,
            gridcolor="#E5E7EB",
            tickformat="%H:%M",
            rangeslider=dict(visible=False),
        ),
        yaxis=dict(
            title="NIFTY",
            showgrid=True,
            gridcolor="#E5E7EB",
            side="right",
            tickformat=".0f",
        ),
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

def structure(session_df):
    if len(session_df) < 25:
        return "Insufficient Data", np.nan, np.nan, np.nan, np.nan, np.nan
    c = session_df["Close"]
    price = c.iloc[-1]
    vw = vwap(session_df).iloc[-1]
    e9 = ema(c, 9).iloc[-1]
    e21 = ema(c, 21).iloc[-1]
    r = rsi(c).iloc[-1]
    if pd.isna(vw):
        if e9 > e21 and r > 50:
            return "Bullish (VWAP N/A)", price, vw, e9, e21, r
        if e9 < e21 and r < 50:
            return "Bearish (VWAP N/A)", price, vw, e9, e21, r
        return "Mixed (VWAP N/A)", price, vw, e9, e21, r
    if price > vw and e9 > e21 and r > 50:
        return "Bullish", price, vw, e9, e21, r
    if price < vw and e9 < e21 and r < 50:
        return "Bearish", price, vw, e9, e21, r
    return "Mixed", price, vw, e9, e21, r

# ---------- NEWS ----------

@st.cache_data(ttl=300, show_spinner=False)
def load_news(limit=10):
    feeds = [
        ("Dinamani Business", "https://www.dinamani.com/rss/business.xml"),
        ("Business Standard Tamil", "https://tamil.business-standard.com/rss.xml"),
        ("Dinamalar Business", "https://www.dinamalar.com/rss/business.xml"),
    ]
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        ),
        "Accept": (
            "application/rss+xml, application/xml, text/xml, "
            "application/atom+xml, text/html;q=0.9, */*;q=0.8"
        ),
    }
    items = []
    status_rows = []
    for source, url in feeds:
        try:
            response = requests.get(url, headers=headers, timeout=12)
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            status_rows.append({
                "Source": source,
                "HTTP": response.status_code,
                "Entries": len(parsed.entries),
                "Parser warning": "Yes" if parsed.bozo else "No",
            })
            for entry in parsed.entries:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if title and len(title) > 10:
                    items.append({
                        "source": source,
                        "title": title,
                        "link": link,
                    })
        except Exception as exc:
            log.warning("News feed failed [%s]: %s", source, exc)
            status_rows.append({
                "Source": source,
                "HTTP": "Failed",
                "Entries": 0,
                "Parser warning": str(exc)[:80],
            })
    seen = set()
    unique = []
    for item in items:
        key = item["title"].strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:limit], pd.DataFrame(status_rows)

# ---------- UI ----------
st.title("🇮🇳 NIFTY Ultimate Bot")
st.caption("Data via Yahoo Finance – may be delayed by up to 15 minutes.")

# 1. MARKET OVERVIEW
st.subheader("📊 Market Overview")
c1, c2, c3 = st.columns(3)
try:
    n = to_ist(fetch_ohlc(NIFTY))
    spot = n["Close"].iloc[-1]
    prev = n["Close"].iloc[-2]
    c1.metric("NIFTY 50", f"{spot:,.2f}",
              f"{spot-prev:+.2f} ({(spot-prev)/prev*100:+.2f}%)")
except DataError as e:
    c1.error(str(e))

for col, (lbl, sym) in zip([c2, c3],
                           [("Bank Nifty", BANKNIFTY), ("India VIX", VIX)]):
    try:
        d = to_ist(fetch_ohlc(sym))
        v = d["Close"].iloc[-1]
        p = d["Close"].iloc[-2]
        col.metric(lbl, f"{v:,.2f}", f"{v-p:+.2f}")
    except DataError as e:
        col.error(str(e))

st.divider()

# 2. MARKET STRUCTURE
st.subheader("🧭 Market Structure (Intraday)")
try:
    df5 = to_ist(fetch_ohlc(NIFTY, period="5d", interval="5m"))
    latest_trade_date = df5.index[-1].date()
    session_df = df5[
        df5.index.date == latest_trade_date
    ].between_time("09:15", "15:30")
    verdict, price, vw, e9, e21, r = structure(session_df)
    if verdict == "Insufficient Data":
        st.info("Not enough candles for structure analysis yet.")
    else:
        icon = ("🟢" if "Bullish" in verdict
                else ("🔴" if "Bearish" in verdict else "🟡"))
        st.markdown(f"### {icon} {verdict}")
        vw_str = f"{vw:,.1f}" if not pd.isna(vw) else "N/A (no volume)"
        st.write(f"Price {price:,.1f} | VWAP {vw_str} | "
                 f"EMA9 {e9:,.1f} | EMA21 {e21:,.1f} | RSI {r:.1f}")
except DataError as e:
    st.error(str(e))

st.divider()

# 3. CANDLESTICK CHART
st.subheader("📈 NIFTY Intraday Chart (Candlestick + ZigZag H/L)")
try:
    df_intra = to_ist(fetch_ohlc(NIFTY, period="5d", interval="5m"))
    latest_trade_date = df_intra.index[-1].date()
    today_df = df_intra[
        df_intra.index.date == latest_trade_date
    ].between_time("09:15", "15:30").copy()

    if len(today_df) < 5:
        st.warning("Insufficient intraday candles for the latest session.")
    else:
        fig = draw_neat_chart(today_df)
        st.plotly_chart(fig, use_container_width=True,
                        config={"displaylogo": False})
        last_time = today_df.index[-1]
        first_time = today_df.index[0]
        st.caption(
            f"Session: {first_time.strftime('%d-%m-%Y %H:%M %Z')} "
            f"to {last_time.strftime('%d-%m-%Y %H:%M %Z')} | "
            f"Candles received: {len(today_df)}"
        )
        with st.expander("Chart Feed Diagnostics"):
            st.write({
                "Timezone": str(today_df.index.tz),
                "First candle": str(today_df.index[0]),
                "Last candle": str(today_df.index[-1]),
                "Candle count": len(today_df),
                "Latest OHLC": {
                    "Open": float(today_df["Open"].iloc[-1]),
                    "High": float(today_df["High"].iloc[-1]),
                    "Low": float(today_df["Low"].iloc[-1]),
                    "Close": float(today_df["Close"].iloc[-1]),
                },
            })
            st.dataframe(today_df.tail(10), use_container_width=True)
except DataError as e:
    st.error(str(e))

st.divider()

# 4. PIVOTS & GAP LEVELS
colA, colB = st.columns(2)
with colA:
    st.subheader("📐 Pivot Points (Zebu)")
    try:
        dy = to_ist(fetch_daily(NIFTY))
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
    st.subheader("🎯 5-Min Gap Levels (Zebu)")
    try:
        df5 = fetch_ohlc(NIFTY, period="5d", interval="5m")
        result = calculate_5m_gap_levels(df5)
        if result[0] is None:
            st.warning("not enough 5-min data")
        else:
            gap_up, gap_down, gap_direction = result
            if gap_direction == "GAP UP":
                tab1, tab2 = st.tabs(["📈 GAP UP (Active)", "📉 GAP DOWN"])
                with tab1:
                    for k, v in gap_up.items():
                        st.write(f"**{k}**: {v:,.2f}")
                with tab2:
                    for k, v in gap_down.items():
                        st.write(f"**{k}**: {v:,.2f}")
            elif gap_direction == "GAP DOWN":
                tab1, tab2 = st.tabs(["📈 GAP UP", "📉 GAP DOWN (Active)"])
                with tab1:
                    for k, v in gap_up.items():
                        st.write(f"**{k}**: {v:,.2f}")
                with tab2:
                    for k, v in gap_down.items():
                        st.write(f"**{k}**: {v:,.2f}")
            else:
                st.info("No gap detected.")
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
    rows.append({
        "Symbol": sym.replace(".NS", ""),
        "Price": dd["Close"].iloc[-1],
        "Change %": ch * 100,
    })

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

    def color_symbol_and_change(row):
        color = ('color: green; font-weight: bold'
                 if row['Change %'] > 0
                 else 'color: red; font-weight: bold')
        return [color, '', color]

    styled = tbl.style.apply(color_symbol_and_change, axis=1).format({
        'Price': '{:.2f}',
        'Change %': '{:+.2f}%',
    })
    st.dataframe(styled, use_container_width=True, hide_index=True)
else:
    st.warning("no breadth data")

st.divider()

# 6. BIG PLAYER
st.subheader("🐋 Big Player Alert")
st.caption(
    "Volume spike (≥2.5×) + strong body (≥1.5×) "
    "on the last completed 5-minute candle."
)

hits = []
for sym, dd in data.items():
    try:
        dd = to_ist(dd)
        latest_day = dd.index[-1].date()
        session_dd = dd[
            dd.index.date == latest_day
        ].between_time("09:15", "15:30").copy()
        sig = big_player(session_dd)
        if sig:
            hits.append({
                "Symbol": sym.replace(".NS", ""),
                "Signal": sig,
                "Price": session_dd["Close"].iloc[-2],
            })
    except Exception as exc:
        log.warning("Big-player calculation failed for %s: %s", sym, exc)

if hits:
    df_hits = pd.DataFrame(hits)
    df_hits = df_hits[["Symbol", "Signal", "Price"]]
    df_hits["Price"] = pd.to_numeric(
        df_hits["Price"], errors="coerce"
    ).round(2)

    def color_symbol_and_signal(row):
        if row["Signal"] == "BUY":
            return [
                "color: green; font-weight: bold",
                "color: green; font-weight: bold",
                "",
            ]
        return [
            "color: red; font-weight: bold",
            "color: red; font-weight: bold",
            "",
        ]

    styled_hits = df_hits.style.apply(
        color_symbol_and_signal, axis=1
    ).format({"Price": "{:.2f}"})
    st.dataframe(styled_hits, use_container_width=True, hide_index=True)

    buy_count = sum(1 for hit in hits if hit["Signal"] == "BUY")
    sell_count = len(hits) - buy_count
    st.markdown(
        f"<span style='color:green;'><b>Buy pressure: "
        f"{buy_count}</b></span> | "
        f"<span style='color:red;'><b>Sell pressure: "
        f"{sell_count}</b></span>",
        unsafe_allow_html=True,
    )
else:
    st.info("No Big Player signals on the last completed 5-minute candle.")

st.divider()

# 7. NEWS
st.subheader("📰 Tamil Financial News")
news, news_status = load_news()

if news:
    for item in news:
        source = item["source"]
        title = item["title"]
        link = item["link"]
        if link:
            st.markdown(f"- **{source}:** [{title}]({link})")
        else:
            st.markdown(f"- **{source}:** {title}")
else:
    st.warning(
        "No news entries were returned. "
        "Check the News Feed Diagnostics section."
    )

with st.expander("News Feed Diagnostics"):
    st.dataframe(news_status, use_container_width=True, hide_index=True)
