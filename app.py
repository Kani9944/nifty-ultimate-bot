# nifty_core.py - data + indicator logic for NIFTY Ultimate Bot
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

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nifty-bot")

IST = ZoneInfo("Asia/Kolkata")

# NOTE: st.set_page_config + st_autorefresh MUST be called from app.py
# (Streamlit page config can only be set once, and only in the entry script).
# We keep the 90s refresh interval as a module constant so app.py can use it.
REFRESH_INTERVAL_MS = 90_000

NIFTY = "^NSEI"
BANKNIFTY = "^NSEBANK"
VIX = "^INDIAVIX"
INDEX_SYMBOLS = [NIFTY, BANKNIFTY, VIX]

HEAVYWEIGHTS = [
    "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "TCS.NS", "ITC.NS", "LT.NS", "SBIN.NS", "AXISBANK.NS",
    "KOTAKBANK.NS", "BHARTIARTL.NS", "HINDUNILVR.NS",
    "MARUTI.NS", "ASIANPAINT.NS", "BAJFINANCE.NS",
    "TITAN.NS", "SUNPHARMA.NS", "WIPRO.NS",
]

# Free yfinance has no reliable SGX/GIFT Nifty feed, so global sentiment
# is shown via major world indices instead.
GLOBAL_MARKETS = [
    ("Dow Jones", "^DJI"),
    ("Nasdaq", "^IXIC"),
    ("S&P 500", "^GSPC"),
    ("Nikkei 225", "^N225"),
    ("Hang Seng", "^HSI"),
    ("FTSE 100", "^FTSE"),
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
    """Convert a DataFrame's index to IST (tz-aware). Handles tz-naive input."""
    if df is None or df.empty:
        return df
    df = df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("Asia/Kolkata")
    else:
        df.index = df.index.tz_convert("Asia/Kolkata")
    return df


def today_ist():
    return datetime.now(IST).date()


def get_confirmed_candles(df, interval_minutes=5):
    """Drop the last candle if it is still forming."""
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
    """Return (last close, previous session close) from intraday/daily data."""
    df = to_ist(df)
    if df is None or df.empty:
        return np.nan, np.nan
    dates = sorted(set(df.index.date))
    last = float(df["Close"].iloc[-1])
    if len(dates) < 2:
        return last, np.nan
    prev = df[df.index.date == dates[-2]]["Close"].iloc[-1]
    return last, float(prev)


# ---------- BATCHED DATA FETCHING ----------
# One yf.download call per group instead of one call per symbol - this is
# the main speed fix (previously ~22 sequential network calls every refresh).

@st.cache_data(ttl=60, show_spinner=False)
def fetch_batch(symbols, period="10d", interval="5m"):
    """Fetch many symbols in a single yf.download call. Returns {symbol: DataFrame}."""
    symbols = list(symbols)
    if not symbols:
        return {}

    try:
        raw = yf.download(
            tickers=" ".join(symbols),
            period=period,
            interval=interval,
            group_by="ticker",
            threads=True,
            progress=False,
            auto_adjust=False,
        )
    except Exception as exc:
        log.warning("batch download failed %s: %s", symbols, exc)
        return {}

    if raw is None or raw.empty:
        return {}

    out = {}

    # Case A: MultiIndex columns -> detect which level holds the symbol.
    if isinstance(raw.columns, pd.MultiIndex):
        lvl0 = list(raw.columns.get_level_values(0))
        # If any of our requested symbols sits in level 0, symbols are first.
        sym_level = 0 if any(s in lvl0 for s in symbols) else 1
        for sym in symbols:
            try:
                d = raw.xs(sym, axis=1, level=sym_level)
            except KeyError:
                continue
            d = d.dropna(subset=["Open", "High", "Low", "Close"], how="any")
            if not d.empty:
                out[sym] = d

    # Case B: single-level columns -> only valid when exactly one symbol requested.
    elif len(symbols) == 1:
        d = raw.dropna(subset=["Open", "High", "Low", "Close"], how="any")
        if not d.empty:
            out[symbols[0]] = d

    return out


def fetch_one(cache, symbol):
    """Pull one symbol's frame out of a fetch_batch() result, or raise."""
    df = cache.get(symbol)
    if df is None or df.empty:
        raise DataError(f"no data for {symbol}")
    return df


@st.cache_data(ttl=60, show_spinner=False)
def fetch_daily(symbol):
    """Daily candles, tz-normalised to IST."""
    try:
        df = yf.Ticker(symbol).history(period="1mo", interval="1d")
    except Exception as exc:
        raise DataError(f"fetch failed for {symbol}: {exc}") from exc
    if df is None or df.empty:
        raise DataError(f"no data for {symbol}")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return to_ist(df)


# ---------- INDICATORS ----------

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
    df["Date"] = df.index.date
    dates = sorted(df["Date"].unique())
    if len(dates) < 2:
        return None, None, None
    prev_day = df[df["Date"] == dates[-2]]
    today = df[df["Date"] == dates[-1]]
    if prev_day.empty or today.empty:
        return None, None, None

    x1_high = prev_day["High"].iloc[-1]
    x2_high = today["High"].iloc[0]
    x3_up = x2_high - x1_high
    x4_up = x3_up / 2
    x5_up = x1_high - x4_up

    x1_low = prev_day["Low"].iloc[-1]
    x2_low = today["Low"].iloc[0]
    x3_down = x2_low - x1_low
    x4_down = x3_down / 2
    x5_down = x2_low + x4_down

    gap_up = {
        "X1 (Prev Close 5m High)": x1_high,
        "X2 (Latest Open 5m High)": x2_high,
        "X3 (Difference X2-X1)": x3_up,
        "X4 (Half of X3)": x4_up,
        "X5 (Reversal Level X1-X4)": x5_up,
    }
    gap_down = {
        "X1 (Prev Close 5m Low)": x1_low,
        "X2 (Latest Open 5m Low)": x2_low,
        "X3 (Difference X2-X1)": x3_down,
        "X4 (Half of X3)": x4_down,
        "X5 (Reversal Level X2+X4)": x5_down,
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


def zigzag_swing_points(df, threshold_pct=0.0008):
    """ZigZag swing high/low detection. Default 0.08% is intraday-friendly."""
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


def draw_neat_chart(today_df, threshold_pct=0.0008):
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
            type="date",
            showgrid=True,
            gridcolor="#E5E7EB",
            tickformat="%H:%M",
            range=[f"{day} 09:10", f"{day} 15:35"],
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


# ---------- BIG PLAYER (VOLUME SPIKE) ----------

def big_player(df, vol_mult=2.5, body_mult=1.5, lookback=20,
               body_to_range_min=0.6):
    """Check the last confirmed 5m candle for a volume + body spike.

    body_to_range_min filters out wicky/doji candles (needs >= 60% body/range).
    """
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
    rng = last["High"] - last["Low"]
    if rng <= 0:
        return None
    body_ratio = body / rng
    if body_ratio < body_to_range_min:
        return None  # wicky candle -> unreliable direction

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


# ---------- MARKET STRUCTURE ----------

def structure(session_df):
    """Return (verdict, price, vwap, ema9, ema21, rsi).

    Returns 'Insufficient Data' if any indicator is NaN.
    """
    if len(session_df) < 25:
        return "Insufficient Data", np.nan, np.nan, np.nan, np.nan, np.nan
    c = session_df["Close"]
    price = c.iloc[-1]
    vw = vwap(session_df).iloc[-1]
    e9 = ema(c, 9).iloc[-1]
    e21 = ema(c, 21).iloc[-1]
    r = rsi(c).iloc[-1]

    if pd.isna(price) or pd.isna(e9) or pd.isna(e21) or pd.isna(r):
        return "Insufficient Data", price, vw, e9, e21, r

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
def load_news(limit=60):
    feeds = [
        ("Dinamani Business", "https://www.dinamani.com/rss/business.xml"),
        ("Dinamalar Business", "https://www.dinamalar.com/rss/business.xml"),
        ("Oneindia Tamil Business",
         "https://tamil.oneindia.com/rss/tamil-business-fb.xml"),
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


# ---------- UI HELPERS ----------

def show_metric_from(col, label, df):
    last, prev = session_change(df)
    if np.isnan(last):
        col.metric(label, "N/A")
        return
    if np.isnan(prev) or prev == 0:
        col.metric(label, f"{last:,.2f}")
    else:
        diff = last - prev
        col.metric(label, f"{last:,.2f}",
                   f"{diff:+.2f} ({diff / prev * 100:+.2f}%)")
