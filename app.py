import feedparser
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf

st.set_page_config(page_title="Nifty Smart Monitor", layout="wide")
st_autorefresh(interval=60 * 1000, key="refresh")
st.title("NIFTY 50 - Smart Money & Market Monitor")


def get_last_bar_change(d):
    if d is None or len(d) < 2:
        return None, None
    c = float(d["Close"].iloc[-1])
    p = float(d["Close"].iloc[-2])
    return c, (((c - p) / p) * 100 if p != 0 else None)


def calculate_rsi(close, w=14):
    d = close.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    ag = g.ewm(alpha=1 / w, adjust=False, min_periods=w).mean()
    al = l.ewm(alpha=1 / w, adjust=False, min_periods=w).mean()
    rs = ag / al
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.mask(al == 0, 100.0).mask((ag == 0) & (al == 0), 50.0)


@st.cache_data(ttl=60)
def get_stock_data(sym, p, itv=None):
    t = yf.Ticker(sym)
    return t.history(period=p, interval=itv) if itv else t.history(period=p)


@st.cache_data(ttl=3600)
def get_long_history(sym):
    return yf.Ticker(sym).history(period="5y", interval="1d")


@st.cache_data(ttl=300)
def get_breadth():
    syms = ["ADANIENT.NS", "ASIANPAINT.NS", "AXISBANK.NS", "BAJFINANCE.NS",
            "BHARTIARTL.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
            "ITC.NS", "KOTAKBANK.NS", "LT.NS", "M&M.NS", "MARUTI.NS",
            "RELIANCE.NS", "SBIN.NS", "TCS.NS", "TATAMOTORS.NS", "TITAN.NS"]
    out = []
    try:
        df = yf.download(syms, period="2d", interval="1d", group_by="ticker", progress=False, threads=True)
        for s in syms:
            try:
                h = df[s].dropna()
                if len(h) >= 2:
                    c = float(h["Close"].iloc[-1])
                    p = float(h["Close"].iloc[-2])
                    if p > 0:
                        out.append({"sym": s.replace(".NS", ""), "ltp": round(c, 2), "chg": round(((c - p) / p) * 100, 2)})
            except Exception:
                pass
    except Exception:
        pass
    return out


@st.cache_data(ttl=300)
def get_news():
    feeds = ["https://tamil.goodreturns.in/rss/feeds/tamil-money-news-fb.xml",
             "https://www.moneycontrol.com/rss/marketreports.xml"]
    out = []
    for u in feeds:
        try:
            r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            if r.status_code == 200:
                f = feedparser.parse(r.content)
                for e in f.entries[:3]:
                    t = e.get("title", "").strip()
                    l = e.get("link", "")
                    if t:
                        out.append("[" + t + "](" + l + ")" if l else t)
                if len(out) >= 6:
                    break
        except Exception:
            continue
    return out[:6] if out else ["வர்த்தக செய்திகள் தற்காலிகமாக கிடைக்கவில்லை."]


try:
    hist = get_stock_data("^NSEI", "5d", "5m")
    daily = get_stock_data("^NSEI", "5d", "1d")
    bn_hist = get_stock_data("^NSEBANK", "2d", "5m")
    vix_hist = get_stock_data("^INDIAVIX", "2d", "5m")
except Exception:
    st.error("Data source unavailable.")
    st.stop()

if hist.empty or daily.empty or len(daily) < 2:
    st.error("Nifty data unavailable.")
    st.stop()

hist.index = pd.to_datetime(hist.index)
hist.index = hist.index.tz_convert("Asia/Kolkata") if hist.index.tz is not None else hist.index.tz_localize("Asia/Kolkata")
daily.index = pd.to_datetime(daily.index)
daily.index = daily.index.tz_convert("Asia/Kolkata") if daily.index.tz is not None else daily.index.tz_localize("Asia/Kolkata")

today = pd.Timestamp.now(tz="Asia/Kolkata").date()
session_date = today if (hist.index.date == today).any() else hist.index[-1].date()
session_hist = hist[hist.index.date == session_date].copy()
if session_hist.empty:
    st.error("Session data unavailable.")
    st.stop()

spot_price = float(session_hist["Close"].iloc[-1])
_, nifty_5m = get_last_bar_change(session_hist)

prev_sessions = daily[pd.Index(daily.index.date) < session_date]
if prev_sessions.empty:
    st.error("Previous session unavailable.")
    st.stop()

prev_day = prev_sessions.iloc[-1]
pdh = float(prev_day["High"])
pdl = float(prev_day["Low"])
pdc = float(prev_day["Close"])

PP = (pdh + pdl + pdc) / 3
BC = min((pdh + pdl) / 2, (2 * PP) - ((pdh + pdl) / 2))
TC = max((pdh + pdl) / 2, (2 * PP) - ((pdh + pdl) / 2))
R1 = (2 * PP) - pdl
S1 = (2 * PP) - pdh
R2 = PP + (pdh - pdl)
S2 = PP - (pdh - pdl)

tp = (session_hist["High"] + session_hist["Low"] + session_hist["Close"]) / 3
cv = session_hist["Volume"].cumsum()
session_hist["VWAP"] = np.where(cv > 0, (tp * session_hist["Volume"]).cumsum() / cv, np.nan)
if session_hist["VWAP"].isna().all():
    session_hist["VWAP"] = session_hist["Close"]

bn_p, bn_5m = get_last_bar_change(bn_hist)
vix_v, vix_5m = get_last_bar_change(vix_hist)
ema9_val = float(session_hist["Close"].ewm(span=9, adjust=False).mean().iloc[-1])
ema21_val = float(session_hist["Close"].ewm(span=21, adjust=False).mean().iloc[-1])
rsi_series = calculate_rsi(session_hist["Close"], 14)
rsi_val = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50.0
vwap_val = float(session_hist["VWAP"].iloc[-1]) if pd.notna(session_hist["VWAP"].iloc[-1]) else spot_price

nd_s = "{:+.2f}% (5m)".format(nifty_5m) if nifty_5m is not None else "N/A"
bd_s = "{:+.2f}% (5m)".format(bn_5m) if bn_5m is not None else "N/A"
vd_s = "{:+.2f}% (5m)".format(vix_5m) if vix_5m is not None else "N/A"
nc = "#00b300" if (nifty_5m is not None and nifty_5m >= 0) else "#cc0000"
bc = "#00b300" if (bn_5m is not None and bn_5m >= 0) else "#cc0000"
vc = "#cc0000" if (vix_5m is not None and vix_5m >= 0) else "#00b300"
bn_s = "Rs {:,.2f}".format(bn_p) if bn_p is not None else "N/A"
vix_s = "{:.2f}".format(vix_v) if vix_v is not None else "N/A"

st.caption("Session: " + str(session_date))
st.write(
    '<div style="border:1px solid #333;border-radius:6px;padding:8px;font-family:monospace;background:#fff;">'
    '<div style="display:flex;border-bottom:1px solid #333;padding-bottom:5px;">'
    '<div style="flex:1;border-right:1px solid #333;padding:4px;">'
    '<b>NIFTY 50</b><br><b style="font-size:16px;">Rs {:,.2f}</b><br>'.format(spot_price)
    + '<span style="color:' + nc + ';">' + nd_s + '</span></div>'
    '<div style="flex:1;padding:4px;">'
    '<b>BANK NIFTY</b><br><b style="font-size:16px;">' + bn_s + '</b><br>'
    '<span style="color:' + bc + ';">' + bd_s + '</span></div></div>'
    '<div style="border-bottom:1px solid #333;padding:4px 0;text-align:center;">'
    '<b>INDIA VIX</b><br><b style="font-size:16px;">' + vix_s + '</b> '
    '<span style="color:' + vc + ';">' + vd_s + '</span></div>'
    '<div style="display:flex;padding-top:5px;">'
    '<div style="flex:1;border-right:1px solid #333;padding:4px;">'
    '<b>PDH</b><br><b>Rs {:,.2f}</b></div>'.format(pdh)
    + '<div style="flex:1;padding:4px;"><b>PDL</b><br><b>Rs {:,.2f}</b></div></div></div>'.format(pdl),
    unsafe_allow_html=True,
)

st.markdown("---")
st.subheader("Classic Pivots")
Pc = (pdh + pdl + pdc) / 3
R1c = 2 * Pc - pdl
S1c = 2 * Pc - pdh
R2c = Pc + (R1c - S1c)
S2c = Pc - (R1c - S1c)
R3c = pdh + 2 * (Pc - pdl)
S3c = pdl - 2 * (pdh - Pc)
c1, c2, c3 = st.columns(3)
c1.metric("R3", "Rs {:,.2f}".format(R3c))
c1.metric("R2", "Rs {:,.2f}".format(R2c))
c1.metric("R1", "Rs {:,.2f}".format(R1c))
c2.metric("Pivot", "Rs {:,.2f}".format(Pc))
c2.metric("Spot", "Rs {:,.2f}".format(spot_price))
c3.metric("S1", "Rs {:,.2f}".format(S1c))
c3.metric("S2", "Rs {:,.2f}".format(S2c))
c3.metric("S3", "Rs {:,.2f}".format(S3c))
