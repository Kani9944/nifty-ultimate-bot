# app.py - NIFTY Ultimate Bot (compact, no syntax errors)
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import feedparser
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf
from streamlit_autorefresh import st_autorefresh

log = logging.getLogger("nifty-bot")
logging.basicConfig(level=logging.INFO)

IST = ZoneInfo("Asia/Kolkata")

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


def to_ist(df):
    df = df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("Asia/Kolkata")
    else:
        df.index = df.index.tz_convert("Asia/Kolkata")
    return df


def today_ist():
    return datetime.now(IST).date()


def get_confirmed_candles(df, interval_minutes=5):
    if df.empty:
        return df.copy()
    now_ist = datetime.now(IST)
    last_ts = df.index[-1]
    if last_ts.tzinfo is None:
        last_ts = last_ts.tz_localize("Asia/Kolkata")
    candle_end = last_ts + pd.Timedelta(minutes=interval_minutes)
    if now_ist < candle_end:
        return df.iloc[:-1].copy()
    return df.copy()


def session_change(df):
    df = to_ist(df)
    dates = sorted(set(df.index.date))
    last = float(df["Close"].iloc[-1])
    if len(dates) < 2:
        return last, np.nan
    prev = df[df.index.date == dates[-2]]["Close"].iloc[-1]
    return last, float(prev)


@st.cache_data(ttl=60, show_spinner=False)
def fetch_ohlc(symbol, period="5d", interval="5m"):
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
    except Exception as exc:
        raise DataError(f"fetch failed for {symbol}: {exc}") from exc
    if df is None or df.empty:
        raise DataError(f"no data for {symbol}")
    return df.dropna(subset=["Open", "High", "Low", "Close"])


@st.cache_data(ttl=60, show_spinner=False)
def fetch_3m_data(symbol):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="1m")
        if df is None or df.empty:
            raise DataError(f"no 1m data for {symbol}")
        df = to_ist(df).dropna(subset=["Open", "High", "Low", "Close"])
        df = df.between_time("09:15", "15:30")
        df_3m = df.resample("3min").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum",
        }).dropna(subset=["Open", "High", "Low", "Close"])
        return df_3m
    except Exception as exc:
        raise DataError(f"3m data failed for {symbol}: {exc}") from exc


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


def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()


def rsi(s, period=14):
    d = s.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    ag = g.ewm(alpha=1 / period, adjust=False).mean()
    al = l.ewm(alpha=1 / period, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def vwap(df):
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    volume = df["Volume"].fillna(0)
    if volume.sum() <= 0:
        return pd.Series(np.nan, index=df.index)
    session = pd.Series(df.index.date, index=df.index)
    cpv = (tp * volume).groupby(session).cumsum()
    cv = volume.groupby(session).cumsum()
    return cpv / cv.replace(0, np.nan)


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


def calculate_3m_gap_levels(df):
    df = to_ist(df)
    df["Date"] = df.index.date
    dates = sorted(df["Date"].unique())
    if len(dates) < 2:
        return None, None, None
    prev_day = df[df["Date"] == dates[-2]]
    today = df[df["Date"] == dates[-1]]
    if prev_day.empty or today.empty:
        return None, None, None

    x1_high = prev_day["High"].iloc[-1]
    x1_low = prev_day["Low"].iloc[-1]
    x2_high = today["High"].iloc[0]
    x2_low = today["Low"].iloc[0]

    x3_up = x2_high - x1_high
    x4_up = x3_up / 2
    x5_up = x1_high - x4_up

    x3_down = x2_low - x1_low
    x4_down = x3_down / 2
    x5_down = x2_low + x4_down

    gap_up = {
        "X1 (Prev Last 3m High)": x1_high,
        "X2 (Today First 3m High)": x2_high,
        "X3 (X2 - X1)": x3_up,
        "X4 (X3 / 2)": x4_up,
        "X5 (Reversal = X1 - X4)": x5_up,
    }
    gap_down = {
        "X1 (Prev Last 3m Low)": x1_low,
        "X2 (Today First 3m Low)": x2_low,
        "X3 (X2 - X1)": x3_down,
        "X4 (X3 / 2)": x4_down,
        "X5 (Reversal = X2 + X4)": x5_down,
    }

    prev_close = prev_day["Close"].iloc[-1]
    today_open = today["Open"].iloc[0]
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


def draw_neat_chart(today_df, threshold_pct=0.0015):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=today_df.index,
        open=today_df["Open"], high=today_df["High"],
        low=today_df["Low"], close=today_df["Close"],
        name="NIFTY",
        increasing_line_color="#16A34A",
        decreasing_line_color="#DC2626",
        increasing_fillcolor="#16A34A",
        decreasing_fillcolor="#DC2626",
    ))

    confirmed = get_confirmed_candles(today_df, interval_minutes=5)
    swing_source = confirmed.between_time("09:15", "15:25")
    swing_highs, swing_lows = zigzag_swing_points(
        swing_source, threshold_pct=threshold_pct
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

    day = today_df.index[0].strftime("%Y-%m-%d")
    fig.update_layout(
        height=560,
        margin=dict(l=10, r=10, t=35, b=10),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hovermode="x unified",
        showlegend=False,
        xaxis=dict(
            type="date", showgrid=True, gridcolor="#E5E7EB",
            tickformat="%H:%M",
            range=[f"{day} 09:10", f"{day} 15:35"],
            rangeslider=dict(visible=False),
        ),
        yaxis=dict(
            title="NIFTY", showgrid=True, gridcolor="#E5E7EB",
            side="right", tickformat=".0f",
        ),
    )
    return fig


def big_player(df, vol_mult=2.5, body_mult=1.5, lookback=20):
    comp = get_confirmed_candles(df, interval_minutes=5)
    if len(comp) < lookback + 2:
        return None
    last = comp.iloc[-1]
    ref = comp.iloc[-(lookback + 1):-1]
    av = ref["Volume"].mean()
    ab = (ref["Close"] - ref["Open"]).abs().mean()
    if pd.isna(av) or av <= 0 or pd.isna(ab) or ab <= 0:
        return None
    body = abs(last["Close"] - last["Open"])
    ratio = last["Volume"] / av
    if ratio >= vol_mult and body >= body_mult * ab:
        return {
            "Side": "BUY" if last["Close"] > last["Open"] else "SELL",
            "Volume x": round(float(ratio), 1),
            "Price": round(float(last["Close"]), 2),
            "Time": comp.index[-1].strftime("%d-%b %H:%M"),
        }
    return None


def big_player_scan(data):
    hits = []
    for sym, df in data.items():
        try:
            res = big_player(to_ist(df))
        except Exception as exc:
            log.warning("big player skip %s: %s", sym, exc)
            continue
        if res:
            res["Stock"] = sym.replace(".NS", "")
            hits.append(res)
    return hits


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


@st.cache_data(ttl=300, show_spinner=False)
def load_news(limit=60):
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
                    items.append({"source": source, "title": title, "link": link})
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


def show_metric(col, label, symbol):
    try:
        df = fetch_ohlc(symbol)
    except DataError as e:
        col.error(str(e))
        return
    last, prev = session_change(df)
    if np.isnan(prev) or prev == 0:
        col.metric(label, f"{last:,.2f}")
    else:
        diff = last - prev
        col.metric(label, f"{last:,.2f}",
                   f"{diff:+.2f} ({diff / prev * 100:+.2f}%)")


# ---------- UI ----------
st.title("🇮🇳 NIFTY Ultimate Bot")
st.caption("Data via Yahoo Finance - may be delayed by up to 15 minutes.")

st.subheader("📊 Market Overview")
c1, c2, c3 = st.columns(3)
show_metric(c1, "NIFTY 50", NIFTY)
show_metric(c2, "Bank Nifty", BANKNIFTY)
show_metric(c3, "India VIX", VIX)

st.divider()

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

st.subheader("📈 NIFTY Intraday Chart (Candlestick + ZigZag H/L)")
st.caption("ZigZag sensitivity: lower = more swings, higher = fewer swings")
zz_pct = st.slider("ZigZag sensitivity (%)", 0.05, 0.50, 0.15, 0.01,
                   key="zz_pct")
try:
    df_intra = to_ist(fetch_ohlc(NIFTY, period="5d", interval="5m"))
    latest_trade_date = df_intra.index[-1].date()
    today_df = df_intra[
        df_intra.index.date == latest_trade_date
    ].between_time("09:15", "15:30").copy()

    if len(today_df) < 5:
        st.warning("Insufficient intraday candles for the latest session.")
    else:
        fig = draw_neat_chart(today_df, threshold_pct=zz_pct / 100)
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

colA, colB = st.columns(2)
with colA:
    st.subheader("📐 Pivot Points (Zebu)")
    try:
        dy = to_ist(fetch_daily(NIFTY))
        if len(dy) < 2:
            st.warning("not enough daily candles")
        else:
            ref_idx = -2 if dy.index[-1].date() == today_ist() else -1
            pdh = dy["High"].iloc[ref_idx]
            pdl = dy["Low"].iloc[ref_idx]
            pdc = dy["Close"].iloc[ref_idx]
            lv = pivots(pdh, pdl, pdc)
            top, bot = cpr(pdh, pdl, pdc)
            pivot_rows = [
                ("R3 (Call)", lv["R3"], "green"),
                ("R2 (Call)", lv["R2"], "green"),
                ("R1 (Call)", lv["R1"], "green"),
                ("Pivot", lv["Pivot"], None),
                ("S1 (Put)", lv["S1"], "red"),
                ("S2 (Put)", lv["S2"], "red"),
                ("S3 (Put)", lv["S3"], "red"),
                ("CPR Top", top, "green"),
                ("CPR Bot", bot, "red"),
            ]
            for label, val, colr in pivot_rows:
                if colr:
                    st.markdown(
                        f"<span style='color:{colr};'>**{label}**: {val:,.1f}</span>",
                        unsafe_allow_html=True)
                else:
                    st.markdown(f"**{label}**: {val:,.1f}")
    except DataError as e:
        st.error(str(e))

with colB:
    st.subheader("🎯 3-Min Gap Levels (Zebu)")
    st.caption("Accurate 3-min candles (1-min data resampled)")
    try:
        df3 = fetch_3m_data(NIFTY)
        result = calculate_3m_gap_levels(df3)
        if result[0] is None:
            st.warning("not enough 3-min data")
        else:
            gap_up, gap_down, gap_direction = result
            if gap_direction == "NO GAP":
                st.info("No gap detected.")
            else:
                up_active = gap_direction == "GAP UP"
                tab1, tab2 = st.tabs([
                    "📈 GAP UP (Active)" if up_active else "📈 GAP UP",
                    "📉 GAP DOWN" if up_active else "📉 GAP DOWN (Active)",
                ])
                with tab1:
                    for k, v in gap_up.items():
                        st.write(f"**{k}**: {v:,.2f}")
                with tab2:
                    for k, v in gap_down.items():
                        st.write(f"**{k}**: {v:,.2f}")
    except DataError as e:
        st.error(str(e))

st.divider()

st.subheader(f"🌐 Market Breadth ({len(HEAVYWEIGHTS)} Heavyweights)")
data = fetch_many(tuple(HEAVYWEIGHTS))
rows = []
for sym, dd in data.items():
    last_px, prev_px = session_change(dd)
    if np.isnan(prev_px) or prev_px == 0:
        continue
    rows.append({
        "Symbol": sym.replace(".NS", ""),
        "Price": last_px,
        "Change %": (last_px - prev_px) / prev_px * 100,
    })

if rows:
    tbl = pd.DataFrame(rows)[["Symbol", "Price", "Change %"]]
    tbl["Price"] = pd.to_numeric(tbl["Price"], errors="coerce").round(2)
    tbl = tbl.sort_values("Change %", ascending=False)
    adv = int((tbl["Change %"] > 0).sum())
    dec = int((tbl["Change %"] < 0).sum())

    a, b, c = st.columns(3)
    a.markdown("<span style='color:green;'>**Advancing**</span>",
               unsafe_allow_html=True)
    a.markdown(f"<h2 style='color:green;'>{adv}</h2>", unsafe_allow_html=True)
    b.markdown("<span style='color:red;'>**Declining**</span>",
               unsafe_allow_html=True)
    b.markdown(f"<h2 style='color:red;'>{dec}</h2>", unsafe_allow_html=True)
    c.metric("Avg Change %", f"{tbl['Change %'].mean():+.2f}%")

    def color_symbol_and_change(row):
        color = ("color: green; font-weight: bold"
                 if row["Change %"] > 0
                 else "color: red; font-weight: bold")
        return [color, "", color]

    styled = tbl.style.apply(color_symbol_and_change, axis=1).format({
        "Price": "{:.2f}",
        "Change %": "{:+.2f}%",
    })
    st.dataframe(styled, use_container_width=True, hide_index=True)
else:
    st.warning("Breadth data unavailable right now.")

st.divider()

st.subheader("🐘 Big Player Entry (பிக் பிளேயர்)")
hits = big_player_scan(data)

if hits:
    bp_tbl = pd.DataFrame(hits)[["Stock", "Side", "Volume x", "Price", "Time"]]
    bp_tbl = bp_tbl.sort_values("Volume x", ascending=False)

    buys = int((bp_tbl["Side"] == "BUY").sum())
    sells = int((bp_tbl["Side"] == "SELL").sum())
    total = buys + sells

    col_bar, col_donut = st.columns([2, 1])

    with col_bar:
        ratio_fig = go.Figure()
        ratio_fig.add_trace(go.Bar(
            y=["BUY", "SELL"],
            x=[buys, sells],
            orientation="h",
            marker=dict(
                color=["#16A34A", "#DC2626"],
                line=dict(color="#111827", width=1),
            ),
            text=[f"{buys} stocks", f"{sells} stocks"],
            textposition="outside",
        ))
        ratio_fig.update_layout(
            title="BUY vs SELL Pressure",
            height=220,
            margin=dict(l=10, r=40, t=40, b=10),
            plot_bgcolor="white",
            showlegend=False,
            xaxis=dict(showgrid=True, gridcolor="#E5E7EB",
                       title="Number of Stocks"),
            yaxis=dict(showgrid=False),
        )
        st.plotly_chart(ratio_fig, use_container_width=True)

    with col_donut:
        if total > 0:
            donut_fig = go.Figure()
            donut_fig.add_trace(go.Pie(
                labels=["BUY", "SELL"],
                values=[buys, sells],
                hole=0.55,
                marker=dict(colors=["#16A34A", "#DC2626"]),
                textinfo="label+percent",
                textfont=dict(size=13, color="white"),
            ))
            donut_fig.update_layout(
                title="Ratio",
                height=220,
                margin=dict(l=10, r=10, t=40, b=10),
                showlegend=False,
            )
            st.plotly_chart(donut_fig, use_container_width=True)

    st.dataframe(bp_tbl, use_container_width=True, hide_index=True)

    if buys > sells:
        st.success(f"🟢 பெரிய வாங்குதல் அதிகம்: BUY {buys} / SELL {sells}")
    elif sells > buys:
        st.error(f"🔴 பெரிய விற்பனை அதிகம்: SELL {sells} / BUY {buys}")
    else:
        st.info(f"🟡 கலவையான நிலை: BUY {buys} / SELL {sells}")
else:
    st.caption("கடைசி 5m கேண்டிலில் பெரிய வால்யூம் என்ட்ரி எதுவும் இல்லை.")

st.caption("Volume-spike based estimate, not actual FII/DII data.")

st.divider()

st.subheader("📰 Market News (தமிழ்)")
try:
    news_all, feed_status = load_news()
except Exception as exc:
    news_all, feed_status = [], pd.DataFrame()
    st.error(f"News load failed: {exc}")

matched = [
    n for n in news_all
    if any(k in n["title"].lower() for k in MARKET_KEYWORDS)
]
shown = (matched or news_all)[:10]
if shown:
    for n in shown:
        st.markdown(
            f"- [{n['title']}]({n['link']})  \n  <small>{n['source']}</small>",
            unsafe_allow_html=True,
        )
else:
    st.info("News feeds returned no headlines right now.")

if not feed_status.empty:
    with st.expander("News feed status"):
        st.dataframe(feed_status, use_container_width=True, hide_index=True)

st.caption("Educational tool only. Not financial advice.")
