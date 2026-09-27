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
    t = yf.Ticker(sym)
    return t.history(period="5y", interval="1d")


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
        df = yf.download(syms, period="2d", interval="1d",
                         group_by="ticker", progress=False, threads=True)
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
    st.error("Data source unavailable. Try again.")
    st.stop()

if hist.empty or daily.empty or len(daily) < 2:
    st.error("Nifty data unavailable.")
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
    st.error("Session data unavailable.")
    st.stop()

spot_price = float(session_hist["Close"].iloc[-1])
_, nifty_5m = get_last_bar_change(session_hist)

previous_sessions = daily[pd.Index(daily.index.date) < session_date]
if previous_sessions.empty:
    st.error("Previous session unavailable.")
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

st.markdown("---")
st.subheader("Classic Pivot Points (R3 / R2 / R1 / P / S1 / S2 / S3)")
P_classic = (pdh + pdl + pdc) / 3
R1_c = 2 * P_classic - pdl
S1_c = 2 * P_classic - pdh
R2_c = P_classic + (R1_c - S1_c)
S2_c = P_classic - (R1_c - S1_c)
R3_c = pdh + 2 * (P_classic - pdl)
S3_c = pdl - 2 * (pdh - P_classic)

cp1, cp2, cp3 = st.columns(3)
with cp1:
    st.metric("R3", "Rs {:,.2f}".format(R3_c))
    st.metric("R2", "Rs {:,.2f}".format(R2_c))
    st.metric("R1", "Rs {:,.2f}".format(R1_c))
with cp2:
    st.metric("Pivot", "Rs {:,.2f}".format(P_classic))
    st.metric("Spot", "Rs {:,.2f}".format(spot_price))
with cp3:
    st.metric("S1", "Rs {:,.2f}".format(S1_c))
    st.metric("S2", "Rs {:,.2f}".format(S2_c))
    st.metric("S3", "Rs {:,.2f}".format(S3_c))

st.markdown("---")
st.subheader("Gap Up / Gap Down (3-min Candle)")
try:
    hist_1m = get_stock_data("^NSEI", "5d", "1m")
    if not hist_1m.empty:
        hist_1m.index = pd.to_datetime(hist_1m.index)
        if hist_1m.index.tz is not None:
            hist_1m.index = hist_1m.index.tz_convert("Asia/Kolkata")
        else:
            hist_1m.index = hist_1m.index.tz_localize("Asia/Kolkata")

        df3 = hist_1m.resample("3min").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum"
        }).dropna()
        df3["Date"] = df3.index.date
        all_dates = sorted(df3["Date"].unique())

        if len(all_dates) >= 2:
            prev_c = df3[df3["Date"] == all_dates[-2]]
            today_c = df3[df3["Date"] == all_dates[-1]]
            if len(prev_c) > 0 and len(today_c) > 0:
                X1h = float(prev_c.iloc[-1]["High"])
                X2h = float(today_c.iloc[0]["High"])
                X1l = float(prev_c.iloc[-1]["Low"])
                X2l = float(today_c.iloc[0]["Low"])
                X3u = X2h - X1h
                X4u = X3u / 2
                X5u = X1h - X4u
                X3d = X2l - X1l
                X4d = X3d / 2
                X5d = X2l + X4d
                pc_val = float(prev_c["Close"].iloc[-1])
                to_val = float(today_c["Open"].iloc[0])
                gap_pts = to_val - pc_val
                gap_pct = (gap_pts / pc_val * 100) if pc_val != 0 else 0

                if gap_pts > 0:
                    gtype = "GAP UP"
                    gcol = "#00b300"
                elif gap_pts < 0:
                    gtype = "GAP DOWN"
                    gcol = "#cc0000"
                else:
                    gtype = "FLAT OPEN"
                    gcol = "#666666"

                st.markdown(
                    '<div style="padding:10px;background:#f8f9fa;border-radius:8px;border-left:4px solid ' + gcol + ';margin-bottom:10px;">'
                    '<b style="color:' + gcol + ';font-size:16px;">' + gtype + '</b><br>'
                    '<span style="font-size:13px;">Gap: <b>Rs {:,.2f} pts</b> ({:+.2f}%)</span><br>'.format(gap_pts, gap_pct)
                    + '<span style="font-size:12px;color:#666;">Prev Close: Rs {:,.2f} | Today Open: Rs {:,.2f}</span>'.format(pc_val, to_val)
                    + '</div>',
                    unsafe_allow_html=True,
                )

                g1, g2, g3 = st.columns(3)
                with g1:
                    st.markdown("**Gap Up**")
                    st.write("X1 High: Rs {:,.2f}".format(X1h))
                    st.write("X2 High: Rs {:,.2f}".format(X2h))
                    st.write("X3: {:+,.2f}".format(X3u))
                    st.write("X4: {:+,.2f}".format(X4u))
                    st.success("X5: Rs {:,.2f}".format(X5u))
                with g2:
                    st.markdown("**Gap Down**")
                    st.write("X1 Low: Rs {:,.2f}".format(X1l))
                    st.write("X2 Low: Rs {:,.2f}".format(X2l))
                    st.write("X3: {:+,.2f}".format(X3d))
                    st.write("X4: {:+,.2f}".format(X4d))
                    st.error("X5: Rs {:,.2f}".format(X5d))
                with g3:
                    st.markdown("**Insight**")
                    if gap_pts > 0:
                        st.info("Reversal at Rs {:,.2f}".format(X5u))
                    elif gap_pts < 0:
                        st.info("Upside at Rs {:,.2f}".format(X5d))
                    else:
                        st.info("No gap")
except Exception:
    st.caption("3-min data unavailable.")

st.markdown("---")
st.subheader("5-Year Historical Analysis")
try:
    y5 = get_long_history("^NSEI")
    if not y5.empty:
        y5.index = pd.to_datetime(y5.index)
        if y5.index.tz is not None:
            y5.index = y5.index.tz_convert("Asia/Kolkata")
        else:
            y5.index = y5.index.tz_localize("Asia/Kolkata")

        y5_close = y5["Close"]
        yr_high = float(y5_close.max())
        yr_low = float(y5_close.min())
        yr_avg = float(y5_close.mean())
        curr_v = float(y5_close.iloc[-1])

        w52_high = float(y5_close.tail(252).max())
        w52_low = float(y5_close.tail(252).min())

        y1 = y5_close.tail(252)
        y1_ret = ((curr_v - float(y1.iloc[0])) / float(y1.iloc[0])) * 100

        h1, h2, h3, h4 = st.columns(4)
        h1.metric("5Y High", "Rs {:,.0f}".format(yr_high))
        h2.metric("5Y Low", "Rs {:,.0f}".format(yr_low))
        h3.metric("5Y Avg", "Rs {:,.0f}".format(yr_avg))
        h4.metric("1Y Return", "{:+.2f}%".format(y1_ret))

        h5, h6 = st.columns(2)
        h5.metric("52W High", "Rs {:,.0f}".format(w52_high))
        h6.metric("52W Low", "Rs {:,.0f}".format(w52_low))

        pos5 = ((curr_v - yr_low) / (yr_high - yr_low)) * 100 if yr_high != yr_low else 50
        st.caption("Current position in 5Y range: {:.1f}%".format(pos5))
except Exception:
    st.caption("5-year data unavailable.")

st.markdown("---")
st.subheader("Multi-Timeframe Trend")
try:
    tf_results = []
    for tf_name, tf_period, tf_itv in [("1 Hour", "5d", "1h"), ("15 min", "5d", "15m"), ("5 min", "5d", "5m")]:
        try:
            tf_df = get_stock_data("^NSEI", tf_period, tf_itv)
            if not tf_df.empty and len(tf_df) >= 21:
                tf_close = tf_df["Close"]
                tf_ema9 = tf_close.ewm(span=9, adjust=False).mean().iloc[-1]
                tf_ema21 = tf_close.ewm(span=21, adjust=False).mean().iloc[-1]
                tf_trend = "Bullish" if tf_ema9 > tf_ema21 else "Bearish"
                tf_last = float(tf_close.iloc[-1])
                tf_results.append((tf_name, tf_last, tf_ema9, tf_ema21, tf_trend))
        except Exception:
            pass

    if tf_results:
        for tfn, tfl, tfe9, tfe21, tftr in tf_results:
            col = "#00b300" if tftr == "Bullish" else "#cc0000"
            st.markdown(
                '<div style="padding:6px 12px;margin-bottom:4px;background:#f8f9fa;border-left:4px solid ' + col + ';border-radius:6px;">'
                '<b>' + tfn + '</b> | Last: Rs {:,.2f} | EMA9: Rs {:,.2f} | EMA21: Rs {:,.2f} | '.format(tfl, tfe9, tfe21)
                + '<span style="color:' + col + ';font-weight:bold;">' + tftr + '</span></div>',
                unsafe_allow_html=True,
            )
except Exception:
    st.caption("Multi-timeframe data unavailable.")

st.markdown("---")
st.subheader("Market Structure Alignment")
b_cond = [spot_price > TC, spot_price > vwap_val, ema9_val > ema21_val, rsi_val >= 55]
s_cond = [spot_price < BC, spot_price < vwap_val, ema9_val < ema21_val, rsi_val <= 45]
if all(b_cond):
    st.success("Bullish Alignment.")
elif all(s_cond):
    st.error("Bearish Alignment.")
else:
    st.info("Mixed / Range-Bound.")

st.markdown("---")
st.subheader("Market Breadth - 18 Watchlist")
b_stocks = get_breadth()
if b_stocks:
    b1, b2, b3 = st.columns(3)
    b1.metric("Advances", sum(1 for s in b_stocks if s["chg"] > 0.05))
    b2.metric("Declines", sum(1 for s in b_stocks if s["chg"] < -0.05))
    b3.metric("Avg Change", "{:+.2f}%".format(sum(s["chg"] for s in b_stocks) / len(b_stocks)))
    ss = sorted(b_stocks, key=lambda x: x["chg"], reverse=True)
    gh = ""
    for s in ss[:5]:
        gh = gh + '<div style="border-bottom:1px solid #eee;padding:3px;"><b>' + s["sym"] + '</b> Rs {:,.2f} <span style="color:#00b300;">({:+.2f}%)</span></div>'.format(s["ltp"], s["chg"])
    lh = ""
    for s in ss[-5:][::-1]:
        lh = lh + '<div style="border-bottom:1px solid #eee;padding:3px;"><b>' + s["sym"] + '</b> Rs {:,.2f} <span style="color:#cc0000;">({:+.2f}%)</span></div>'.format(s["ltp"], s["chg"])
    st.markdown(
        '<div style="display:flex;gap:10px;"><div style="flex:1;"><div style="font-weight:bold;color:#00b300;">Top 5 Gainers</div>' + gh + '</div><div style="flex:1;"><div style="font-weight:bold;color:#cc0000;">Top 5 Losers</div>' + lh + '</div></div>',
        unsafe_allow_html=True,
    )

st.markdown("---")
st.subheader("NIFTY Chart & CPR")
cdf = session_hist[["Close", "VWAP"]].copy()
cdf = cdf.replace([np.inf, -np.inf], np.nan).dropna(subset=["Close"])
cdf = cdf[cdf["Close"] > 0].copy()

if not cdf.empty:
    fig = go.Figure()
    fig.add_hrect(y0=BC, y1=TC, fillcolor="LightSkyBlue", opacity=0.15, line_width=0, layer="below")
    fig.add_trace(go.Scatter(x=cdf.index, y=cdf["Close"], mode="lines", name="Price", line=dict(color="#0052cc", width=2)))
    fig.add_trace(go.Scatter(x=cdf.index, y=cdf["VWAP"], mode="lines", name="VWAP", line=dict(color="#ff9900", width=1.5, dash="dash")))
    lv_list = [("TC", TC, "#66b3ff", "dot"), ("Pivot", PP, "#0066cc", "dash"), ("BC", BC, "#3399ff", "dot"), ("R1", R1, "#ff6666", "dot"), ("S1", S1, "#66cc66", "dot"), ("PDH", pdh, "#cc0000", "solid"), ("PDL", pdl, "#00b300", "solid")]
    for nm, vl, cl, ds in lv_list:
        fig.add_trace(go.Scatter(x=[cdf.index[0], cdf.index[-1]], y=[vl, vl], mode="lines", name=nm, line=dict(color=cl, width=1, dash=ds)))

    cvals = list(cdf["Close"]) + list(cdf["VWAP"].dropna()) + [pdh, pdl, R1, R2, S1, S2, PP, BC, TC]
    valid = [float(v) for v in cvals if pd.notna(v) and np.isfinite(v) and abs(float(v) - spot_price) <= 500]
    if valid:
        lo = min(valid + [spot_price])
        hi = max(valid + [spot_price])
        pad = max(75.0, (hi - lo) * 0.20)
        y_min = lo - pad
        y_max = hi + pad
        y_min = min(y_min, spot_price - 200)
        y_max = max(y_max, spot_price + 200)
    else:
        y_min = spot_price - 200
        y_max = spot_price + 200

    fig.update_layout(
        height=420,
        margin=dict(l=10, r=10, t=25, b=25),
        xaxis=dict(tickformat="%H:%M"),
        yaxis=dict(range=[y_min, y_max], fixedrange=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("Chart unavailable.")

st.markdown("---")
st.subheader("Buy/Sell Volume Per Candle (Estimated)")
try:
    vdf2 = session_hist[["Open", "High", "Low", "Close", "Volume"]].copy().dropna()
    vdf2 = vdf2[vdf2["Volume"] > 0]
    if len(vdf2) >= 5:
        agg = vdf2.resample("15min").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum"
        }).dropna()
        if len(agg) >= 2:
            bvol = []
            svol = []
            tlist = []
            for idx, row in agg.iterrows():
                tv = float(row["Volume"])
                o = float(row["Open"])
                c = float(row["Close"])
                h = float(row["High"])
                l = float(row["Low"])
                rng = h - l if h > l else 1
                if c >= o:
                    br = (c - o) / rng if rng > 0 else 0.5
                    buy_r = 0.5 + (br * 0.4)
                    if buy_r > 0.85:
                        buy_r = 0.85
                else:
                    br = (o - c) / rng if rng > 0 else 0.5
                    buy_r = 0.5 - (br * 0.4)
                    if buy_r < 0.15:
                        buy_r = 0.15
                bvol.append(tv * buy_r)
                svol.append(tv * (1 - buy_r))
                tlist.append(idx.strftime("%H:%M"))

            fv = go.Figure()
            fv.add_trace(go.Bar(x=tlist, y=bvol, name="Buy Vol (Est)", marker_color="#00b300"))
            fv.add_trace(go.Bar(x=tlist, y=svol, name="Sell Vol
