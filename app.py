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
st.title("🦅 NIFTY 50 - Smart Money & Market Monitor")


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


@st.cache_data(ttl=300)
def get_breadth():
    syms = [
        "ADANIENT.NS", "ASIANPAINT.NS", "AXISBANK.NS", "BAJFINANCE.NS",
        "BHARTIARTL.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
        "ITC.NS", "KOTAKBANK.NS", "LT.NS", "M&M.NS", "MARUTI.NS",
        "RELIANCE.NS", "SBIN.NS", "TCS.NS", "TATAMOTORS.NS", "TITAN.NS"
    ]
    out = []
    try:
        df = yf.download(
            syms, period="2d", interval="1d",
            group_by="ticker", progress=False, threads=True
        )
        for s in syms:
            try:
                h = df[s].dropna()
                if len(h) >= 2:
                    c = float(h["Close"].iloc[-1])
                    p = float(h["Close"].iloc[-2])
                    if p > 0:
                        out.append({
                            "sym": s.replace(".NS", ""),
                            "ltp": round(c, 2),
                            "chg": round(((c - p) / p) * 100, 2)
                        })
            except Exception:
                pass
    except Exception:
        pass
    return out


@st.cache_data(ttl=300)
def get_news():
    feeds = [
        "https://tamil.goodreturns.in/rss/feeds/tamil-money-news-fb.xml",
        "https://www.moneycontrol.com/rss/marketreports.xml",
    ]
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
    st.error("சந்தை தரவு சேவையகம் தற்காலிகமாக கிடைக்கவில்லை. சிறிது நேரம் கழித்து மீண்டும் முயற்சிக்கவும்.")
    st.stop()

if hist.empty or daily.empty or len(daily) < 2:
    st.error("Nifty தரவுகள் கிடைக்கவில்லை.")
    st.stop()

hist.index = pd.to_datetime(hist.index)
if hist.index.tz is not None:
    hist.index = hist.index.tz_convert("Asia/Kolkata")
else:
    hist.index = hist.index.tz_localize("Asia/Kolkata")

daily.index = pd.to_datetime(daily.index)
if daily.index.tz is not None:
    daily.index = daily.index.tz_convert("Asia/Kolkata")
else:
    daily.index = daily.index.tz_localize("Asia/Kolkata")

today = pd.Timestamp.now(tz="Asia/Kolkata").date()
session_date = today if (hist.index.date == today).any() else hist.index[-1].date()
session_hist = hist[hist.index.date == session_date].copy()
if session_hist.empty:
    st.error("இன்றைய அமர்வு தரவு கிடைக்கவில்லை.")
    st.stop()

spot_price = float(session_hist["Close"].iloc[-1])
_, nifty_5m = get_last_bar_change(session_hist)

previous_sessions = daily[pd.Index(daily.index.date) < session_date]
if previous_sessions.empty:
    st.error("முந்தைய நாளின் நிறைவுற்ற அமர்வு தரவு கிடைக்கவில்லை.")
    st.stop()

prev_day = previous_sessions.iloc[-1]
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
nifty_col = "#00b300" if (nifty_5m is not None and nifty_5m >= 0) else "#cc0000"
bn_col = "#00b300" if (bn_5m is not None and bn_5m >= 0) else "#cc0000"
vix_col = "#cc0000" if (vix_5m is not None and vix_5m >= 0) else "#00b300"
bn_s = "Rs {:,.2f}".format(bn_p) if bn_p is not None else "N/A"
vix_s = "{:.2f}".format(vix_v) if vix_v is not None else "N/A"

st.caption("Session Date: " + str(session_date))
st.write(
    '<div style="border:1px solid #333;border-radius:6px;padding:8px;font-family:monospace;background:#fff;margin-bottom:10px;">'
    '<div style="display:flex;border-bottom:1px solid #333;padding-bottom:5px;">'
    '<div style="flex:1;border-right:1px solid #333;padding:4px;">'
    '<span style="font-size:11px;color:#555;">NIFTY 50</span><br>'
    '<b style="font-size:16px;">Rs {:,.2f}</b><br>'.format(spot_price)
    + '<span style="font-size:11px;color:' + nifty_col + ';">' + nd_s + '</span></div>'
    '<div style="flex:1;padding:4px;padding-left:8px;">'
    '<span style="font-size:11px;color:#555;">BANK NIFTY</span><br>'
    '<b style="font-size:16px;">' + bn_s + '</b><br>'
    '<span style="font-size:11px;color:' + bn_col + ';">' + bd_s + '</span></div></div>'
    '<div style="border-bottom:1px solid #333;padding:4px 0;text-align:center;">'
    '<span style="font-size:11px;color:#555;">INDIA VIX</span><br>'
    '<b style="font-size:16px;">' + vix_s + '</b> '
    '<span style="font-size:11px;color:' + vix_col + ';">' + vd_s + '</span></div>'
    '<div style="display:flex;padding-top:5px;">'
    '<div style="flex:1;border-right:1px solid #333;padding:4px;">'
    '<span style="font-size:11px;color:#555;">PDH</span><br>'
    '<b style="font-size:15px;">Rs {:,.2f}</b></div>'.format(pdh)
    + '<div style="flex:1;padding:4px;padding-left:8px;">'
    '<span style="font-size:11px;color:#555;">PDL</span><br>'
    '<b style="font-size:15px;">Rs {:,.2f}</b></div></div></div>'.format(pdl),
    unsafe_allow_html=True,
)
st.caption("Nifty, Bank Nifty மற்றும் VIX ஆகியவை முந்தைய 5-நிமிட பார் உடனான மாற்றத்தைக் காட்டுகின்றன.")

st.markdown("---")
st.subheader("Market Structure Alignment")
b_cond = [spot_price > TC, spot_price > vwap_val, ema9_val > ema21_val, rsi_val >= 55]
s_cond = [spot_price < BC, spot_price < vwap_val, ema9_val < ema21_val, rsi_val <= 45]
if all(b_cond):
    st.success("Bullish Alignment: Price > TC & VWAP; EMA 9 > 21; RSI > 55.")
elif all(s_cond):
    st.error("Bearish Alignment: Price < BC & VWAP; EMA 9 < 21; RSI < 45.")
else:
    st.info("Mixed / Range-Bound: தெளிவான தொழில்நுட்ப திசை அமைப்பு இல்லை.")
st.caption("Levels: BC Rs {:,.2f} | TC Rs {:,.2f} | R1 Rs {:,.2f} | S1 Rs {:,.2f}".format(BC, TC, R1, S1))

st.markdown("---")
st.subheader("Market Breadth - 18 Watchlist")
st.caption("தேர்ந்தெடுக்கப்பட்ட முன்னணி Nifty 50 பங்குகள் மட்டுமே.")
b_stocks = get_breadth()
if b_stocks:
    b1, b2, b3 = st.columns(3)
    b1.metric("Advances", sum(1 for s in b_stocks if s["chg"] > 0.05))
    b2.metric("Declines", sum(1 for s in b_stocks if s["chg"] < -0.05))
    b3.metric("Avg Change", "{:+.2f}%".format(sum(s["chg"] for s in b_stocks) / len(b_stocks)))

    ss = sorted(b_stocks, key=lambda x: x["chg"], reverse=True)
    g_html = "".join(['<div style="border-bottom:1px solid #eee;padding:3px;"><b>' + s["sym"] + '</b><br>Rs {:,.2f} <span style="color:#00b300;">({:+.2f}%)</span></div>'.format(s["ltp"], s["chg"]) for s in ss[:5]])
    l_html = "".join(['<div style="border-bottom:1px solid #eee;padding:3px;"><b>' + s["sym"] + '</b><br>Rs {:,.2f} <span style="color:#cc0000;">({:+.2f}%)</span></div>'.format(s["ltp"], s["chg"]) for s in ss[-5:][::-1]])
    st.markdown('<div style="display:flex;gap:10px;margin-top:8px;"><div style="flex:1;"><div style="font-weight:bold;color:#00b300;">Top 5 Gainers</div>' + g_html + '</div><div style="flex:1;"><div style="font-weight:bold;color:#cc0000;">Top 5 Losers</div>' + l_html + '</div></div>', unsafe_allow_html=True)

st.markdown("---")
st.subheader("NIFTY Chart & CPR")
cdf = session_hist[["Close", "VWAP"]].copy()
cdf = cdf.replace([np.inf, -np.inf], np.nan)
cdf = cdf.dropna(subset=["Close"])
cdf = cdf[cdf["Close"] > 0].copy()

if not cdf.empty:
    fig = go.Figure()
    fig.add_hrect(y0=BC, y1=TC, fillcolor="LightSkyBlue", opacity=0.15, line_width=0, layer="below")
    fig.add_trace(go.Scatter(x=cdf.index, y=cdf["Close"], mode="lines", name="Price", line=dict(color="#0052cc", width=2)))
    fig.add_trace(go.Scatter(x=cdf.index, y=cdf["VWAP"], mode="lines", name="VWAP", line=dict(color="#ff9900", width=1.5, dash="dash")))

    for nm, vl, cl, ds in [("TC", TC, "#66b3ff", "dot"), ("Pivot", PP, "#0066cc", "dash"), ("BC", BC, "#3399ff", "dot"), ("R1", R1, "#ff6666", "dot"), ("S1", S1, "#66cc66", "dot"), ("PDH", pdh, "#cc0000", "solid"), ("PDL", pdl, "#00b300", "solid")]:
        fig.add_trace(go.Scatter(x=[cdf.index[0], cdf.index[-1]], y=[vl, vl], mode="lines", name=nm, line=dict(color=cl, width=1, dash=ds)))

    chart_vals = list(cdf["Close"].dropna()) + list(cdf["VWAP"].dropna()) + [pdh, pdl, R1, R2, S1, S2, PP, BC, TC]
    valid_vals = []
    for v in chart_vals:
        try:
            fv = float(v)
            if np.isfinite(fv) and abs(fv - spot_price) <= 500:
                valid_vals.append(fv)
        except Exception:
            continue

    if valid_vals:
        low_val = min(valid_vals + [spot_price])
        high_val = max(valid_vals + [spot_price])
        pad = max(75.0, (high_val - low_val) * 0.20)
        y_min = low_val - pad
        y_max = high_val + pad
        y_min = min(y_min, spot_price - 200)
        y_max = max(y_max, spot_price + 200)
    else:
        y_min = spot_price - 200
        y_max = spot_price + 200

    fig.update_layout(height=420, margin=dict(l=10, r=10, t=25, b=25),
                      xaxis=dict(tickformat="%H:%M"),
                      yaxis=dict(range=[y_min, y_max], fixedrange=False),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, width="stretch")
else:
    st.warning("Chart தரவுகள் கிடைக்கவில்லை.")

st.markdown("---")
st.subheader("Chart Pattern Detection")
p_data = session_hist[["High", "Low", "Close"]].copy().dropna()
patterns = []

if len(p_data) >= 20:
    hi = p_data["High"].values
    lo = p_data["Low"].values
    cl = p_data["Close"].values

    if len(hi) >= 10:
        if max(hi[-5:]) > max(hi[-10:-5]) and min(lo[-5:]) > min(lo[-10:-5]):
            patterns.append(("UPWARD BIAS", "Recent 5-bar highs & lows are above prior range.", "#00b300"))
        elif max(hi[-5:]) < max(hi[-10:-5]) and min(lo[-5:]) < min(lo[-10:-5]):
            patterns.append(("DOWNWARD BIAS", "Recent 5-bar highs & lows are below prior range.", "#cc0000"))

    r_hi = hi[-30:] if len(hi) >= 30 else hi
    r_lo = lo[-30:] if len(lo) >= 30 else lo

    if len(r_hi) >= 10:
        mx_h = max(r_hi)
        mx_i = list(r_hi).index(mx_h)
        sec_mx_list = [h for i, h in enumerate(r_hi) if abs(i - mx_i) > 5]
        if sec_mx_list:
            sec_mx = max(sec_mx_list)
            if sec_mx > 0 and abs(mx_h - sec_mx) / mx_h < 0.003 and cl[-1] < mx_h * 0.995:
                patterns.append(("POSSIBLE DOUBLE TOP", "Two similar peaks detected; breakdown confirmation is needed.", "#cc0000"))

    if len(r_lo) >= 10:
        mn_l = min(r_lo)
        mn_i = list(r_lo).index(mn_l)
        sec_mn_list = [l for i, l in enumerate(r_lo) if abs(i - mn_i) > 5]
        if sec_mn_list:
            sec_mn = min(sec_mn_list)
            if abs(mn_l - sec_mn) / mn_l < 0.003 and cl[-1] > mn_l * 1.005:
                patterns.append(("POSSIBLE DOUBLE BOTTOM", "Two similar dips detected; breakout confirmation is needed.", "#00b300"))

    if len(hi) >= 20 and min(lo[-20:]) > 0:
        rng_p = (max(hi[-20:]) - min(lo[-20:])) / min(lo[-20:]) * 100
        if rng_p < 0.5:
            patterns.append(("CONSOLIDATION", "Narrow range - breakout pending.", "#ff9900"))

if patterns:
    for nm, desc, col in patterns:
        st.markdown(
            '<div style="padding:8px 12px;margin-bottom:6px;background:#f8f9fa;border-left:4px solid ' + col + ';border-radius:6px;">'
            '<b style="color:' + col + ';">' + nm + '</b><br>'
            '<span style="font-size:13px;color:#555;">' + desc + '</span></div>',
            unsafe_allow_html=True)
else:
    st.caption("தெளிவான Chart pattern எதுவும் கண்டறியப்படவில்லை.")

st.caption("Rule-based patterns; confirm with session volume and candle closes.")

st.markdown("---")
st.subheader("Technical Indicators (Intraday)")
i1, i2, i3, i4 = st.columns(4)
i1.metric("EMA 9", "Rs {:,.2f}".format(ema9_val))
i2.metric("EMA 21", "Rs {:,.2f}".format(ema21_val))
i3.metric("VWAP", "Rs {:,.2f}".format(vwap_val))
if rsi_val >= 70:
    rsi_label = "Overbought"
elif rsi_val <= 30:
    rsi_label = "Oversold"
else:
    rsi_label = "Neutral"
i4.metric("RSI (Wilder)", "{:.2f}".format(rsi_val), rsi_label)

st.markdown("---")
st.subheader("வர்த்தக செய்திகள்")
for item in get_news():
    st.markdown(item)

st.caption("Yahoo Finance data may be delayed or incomplete. Technical signals and pattern detections are rule-based analysis only; not financial advice.")
