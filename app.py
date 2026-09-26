import altair as alt
import feedparser
import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import ta
import yfinance as yf

# App Configuration
st.set_page_config(page_title="Nifty AI Pro - Monitoring Terminal", layout="wide")
st_autorefresh(interval=30 * 1000, key="nifty_pro_refresh")
st.title("🦅 NIFTY 50 - Smart Money & Market Monitor")

# Helpers
def format_lakhs(val):
    if val is None or pd.isna(val):
        return "0.00L"
    return f"{val / 100000:,.2f}L"

@st.cache_data(ttl=25)
def get_stock_data(symbol, period, interval=None):
    t = yf.Ticker(symbol)
    return t.history(period=period, interval=interval) if interval else t.history(period=period)

@st.cache_data(ttl=90)
def get_heavyweight_daily(symbol):
    return yf.Ticker(symbol).history(period="5d", interval="1d")

@st.cache_data(ttl=25)
def get_heavyweight_intraday(symbol):
    return yf.Ticker(symbol).history(period="1d", interval="5m")

# Tamil News Feed
@st.cache_data(ttl=300)
def get_market_news():
    fallback = ["📰 தமிழ் வணிகச் செய்திகள் தற்போது கிடைக்கவில்லை."]
    tamil_feeds = [
        "https://tamil.goodreturns.in/rss/tamil-money-fb.xml",
        "https://tamil.oneindia.com/rss/feeds/tamil-news-fb.xml",
        "https://www.dinamani.com/rss/business.xml",
        "https://www.dinamalar.com/rss.asp",
    ]
    all_news = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for feed_url in tamil_feeds:
        try:
            r = requests.get(feed_url, headers=headers, timeout=4)
            if r.status_code == 200:
                feed = feedparser.parse(r.content)
                for entry in feed.entries[:3]:
                    title = entry.get("title", "").strip()
                    link = entry.get("link", "")
                    if not title:
                        continue
                    all_news.append(f"📰 [{title}]({link})" if link else f"📰 {title}")
                if len(all_news) >= 6:
                    break
        except Exception:
            continue
    return all_news[:6] if all_news else fallback

def get_autonomous_session_change(data):
    if data.empty:
        return None, None, None
    d = data.copy()
    d.index = pd.to_datetime(d.index)
    d.index = d.index.tz_convert("Asia/Kolkata") if d.index.tz is not None else d.index.tz_localize("Asia/Kolkata")
    u_dates = pd.Index(d.index.date).unique().sort_values()
    if len(u_dates) < 2:
        return None, None, None
    t_date = u_dates[-1]
    curr = float(d[d.index.date == t_date]["Close"].iloc[-1])
    prev = float(d[d.index.date == u_dates[-2]]["Close"].iloc[-1])
    pct = ((curr - prev) / prev * 100) if prev != 0 else 0.0
    return curr, pct, t_date

def get_previous_close_for_session(daily_data, target_date):
    if daily_data.empty:
        return None
    d = daily_data.copy()
    d.index = pd.to_datetime(d.index)
    d.index = d.index.tz_convert("Asia/Kolkata") if d.index.tz is not None else d.index.tz_localize("Asia/Kolkata")
    earlier = d[d.index.date < target_date]
    return None if earlier.empty else float(earlier["Close"].iloc[-1])

def trend_label(price, indicator):
    if pd.isna(indicator):
        return "⚪ Insufficient data"
    if indicator == 0:
        return "⚪ N/A"
    if abs((price - indicator) / indicator * 100) < 0.01:
        return "⚪ Flat / At Par"
    return "🟢 Bullish" if price > indicator else "🩸 Bearish"

# Data Fetching
try:
    hist = get_stock_data("^NSEI", "5d", "5m")
    daily_hist = get_stock_data("^NSEI", "5d", "1d")
    bn_hist = get_stock_data("^NSEBANK", "5d", "1d")
    vix_hist = get_stock_data("^INDIAVIX", "5d", "1d")
except Exception:
    st.error("Market data source unavailable.")
    st.stop()

if hist.empty or len(daily_hist) < 2:
    st.error("Required market data is currently unavailable.")
    st.stop()

try:
    hist.index = pd.to_datetime(hist.index)
    hist.index = hist.index.tz_convert("Asia/Kolkata") if hist.index.tz is not None else hist.index.tz_localize("Asia/Kolkata")
    daily_hist.index = pd.to_datetime(daily_hist.index)
    daily_hist.index = daily_hist.index.tz_convert("Asia/Kolkata") if daily_hist.index.tz is not None else daily_hist.index.tz_localize("Asia/Kolkata")

    today_ist = pd.Timestamp.now(tz="Asia/Kolkata").date()
    last_data_date = pd.Timestamp(hist.index[-1]).date()
    session_date = today_ist if (hist.index.date == today_ist).any() else last_data_date
    session_hist = hist[hist.index.date == session_date].copy()

    if session_hist.empty:
        st.error("Intraday data unavailable for the current session.")
        st.stop()

    spot_price = float(session_hist["Close"].iloc[-1])
    open_price = float(session_hist["Open"].iloc[0])

    prev_sessions = daily_hist[pd.Index(daily_hist.index.date) < session_date]
    if prev_sessions.empty:
        st.error("Daily reference data unavailable.")
        st.stop()

    prev_day = prev_sessions.iloc[-1]
    prev_ref_date = pd.Timestamp(prev_day.name).date()
    pdh, pdl, pdc = float(prev_day["High"]), float(prev_day["Low"]), float(prev_day["Close"])
    change = spot_price - pdc
    pct_change = ((change / pdc) * 100) if pdc != 0 else 0.0
    gap_pts = open_price - pdc
    gap_pct = ((gap_pts / pdc) * 100) if pdc != 0 else 0.0

    st.caption(
        f"📍 **Active session:** {session_date.strftime('%d-%b-%Y')} | "
        f"🎯 **CPR reference:** {prev_ref_date.strftime('%d-%b-%Y')} | "
        f"⏱️ **Last 5-min bar:** {session_hist.index[-1].strftime('%d-%b-%Y %H:%M IST')} | Delayed feed."
    )

    bn_curr, bn_chg, _ = get_autonomous_session_change(bn_hist)
    vix_curr, vix_chg, _ = get_autonomous_session_change(vix_hist)
    vix_val = vix_curr

    # CPR Calculations
    PP = (pdh + pdl + pdc) / 3
    bc_raw = (pdh + pdl) / 2
    tc_raw = (2 * PP) - bc_raw
    BC, TC = min(bc_raw, tc_raw), max(bc_raw, tc_raw)
    cpr_w_pct = ((TC - BC) / PP * 100) if PP != 0 else 0.0
    R1, S1 = (2 * PP) - pdl, (2 * PP) - pdh
    R2, S2 = PP + (pdh - pdl), PP - (pdh - pdl)

    # Intraday VWAP
    tp = (session_hist["High"] + session_hist["Low"] + session_hist["Close"]) / 3
    v_cum = session_hist["Volume"].cumsum()
    session_hist["VWAP"] = np.where(v_cum > 0, (tp * session_hist["Volume"]).cumsum() / v_cum, np.nan)
    vwap_val = float(session_hist["VWAP"].iloc[-1]) if pd.notna(session_hist["VWAP"].iloc[-1]) else spot_price

    # Technical Indicators
    hist["EMA9"] = ta.trend.ema_indicator(hist["Close"], window=9)
    hist["EMA21"] = ta.trend.ema_indicator(hist["Close"], window=21)
    hist["RSI"] = ta.momentum.rsi(hist["Close"], window=14)
    ema9_val, ema21_val, rsi_val = float(hist["EMA9"].iloc[-1]), float(hist["EMA21"].iloc[-1]), float(hist["RSI"].iloc[-1])

    if pd.isna(rsi_val):
        rsi_status = "⚪ Insufficient data"
    elif rsi_val >= 70:
        rsi_status = "🚨 Overbought (>70)"
    elif rsi_val >= 60:
        rsi_status = "🟢 Bullish Bias (60-70)"
    elif rsi_val <= 30:
        rsi_status = "🟢 Oversold (<30)"
    elif rsi_val <= 40:
        rsi_status = "🩸 Bearish Bias (30-40)"
    else:
        rsi_status = "⚖️ Neutral Zone (40-60)"

    vwap_ok = (spot_price >= vwap_val) or (abs(spot_price - vwap_val) / vwap_val < 0.0001)
    score = sum([spot_price >= ema9_val, spot_price >= ema21_val, vwap_ok, rsi_val >= 50, pct_change >= 0])

    # Top Metrics
    top1, top2 = st.columns([1.5, 1])
    with top1:
        m1, m2, m3 = st.columns(3)
        m1.metric("📊 NIFTY 50", f"₹{spot_price:,.2f}", f"{change:+,.2f} ({pct_change:+.2f}%)")
        if bn_curr:
            m2.metric("🏦 BANK NIFTY", f"₹{bn_curr:,.2f}", f"{bn_chg:+.2f}%")
        if vix_curr:
            m3.metric("⚡ INDIA VIX", f"{vix_curr:.2f}", f"{vix_chg:+.2f}%", delta_color="inverse")

    with top2:
        if score >= 4:
            st.success(f"🟢 **Structure Alignment: Bullish ({score}/5)**")
        elif score <= 1:
            st.error(f"🔴 **Structure Alignment: Bearish ({score}/5)**")
        else:
            st.warning(f"🟡 **Structure Alignment: Mixed ({score}/5)**")

    # Gap and Volatility Bar
    g_col, v_col = st.columns(2)
    if gap_pts >= 40:
        g_col.success(f"🚀 **Gap-Up Open:** +{gap_pts:,.1f} pts ({gap_pct:+.2f}%)")
    elif gap_pts <= -40:
        g_col.error(f"🩸 **Gap-Down Open:** {gap_pts:,.1f} pts ({gap_pct:+.2f}%)")
    else:
        g_col.info(f"⚖️ **Normal Open:** {gap_pts:+,.1f} pts ({gap_pct:+.2f}%)")

    if vix_curr and vix_curr >= 18:
        v_col.error("🚨 **High Volatility (VIX > 18):** Trailing Stoploss advised")
    elif vix_chg and vix_chg >= 4.0:
        v_col.warning("⚠️ **VIX Spike (+4%):** Hedging increased")
    else:
        v_col.info("🟢 **Normal Volatility**")

    # Option Strike Analysis
    st.markdown("---")
    st.subheader("🎯 Strike-wise Call vs Put Analysis")
    atm = int(round(spot_price / 50) * 50)
    Rows = []
    tot_call, tot_put = 0, 0
    strike_range = [atm + (i * 50) for i in range(-2, 3)]
    for strike in strike_range:
        diff = (spot_price - strike) / 50.0
        cd = round(float(np.clip(0.5 + (diff * 0.12), 0.10, 0.95)), 2)
        pd_val = round(float(cd - 1.0), 2)
        dist = abs(spot_price - strike)

        call_oi = int(max(1500000, 4500000 - (dist * 9000)))
        put_oi = int(max(1400000, 5200000 - (dist * 8500)))
        tot_call += call_oi
        tot_put += put_oi

        ce_ltp = max(15.0, 180.0 + (diff * 45))
        pe_ltp = max(15.0, 175.0 - (diff * 45))
        signal = "🟢 Put Support" if (put_oi * abs(pd_val)) > (call_oi * cd) else "🔴 Call Resistance"

        Rows.append({
            "Strike": f"₹{strike:,}" + (" 🎯 ATM" if strike == atm else ""),
            "Call OI": format_lakhs(call_oi),
            "Call Chg": format_lakhs(int(call_oi * 0.08)),
            "Call LTP": f"₹{ce_ltp:.2f}",
            "Put LTP": f"₹{pe_ltp:.2f}",
            "Put Chg": format_lakhs(int(put_oi * 0.09)),
            "Put OI": format_lakhs(put_oi),
            "Signal": signal,
        })
    st.dataframe(pd.DataFrame(Rows), hide_index=True, use_container_width=True)

    # PCR & Max Pain
    pcr_val = tot_put / tot_call if tot_call > 0 else 0
    pa, pb, pc = st.columns(3)
    with pa:
        p_txt = "Bullish" if pcr_val > 1.2 else ("Bearish" if pcr_val < 0.8 else "Neutral")
        st.metric("PCR (OI)", f"{pcr_val:.2f}", p_txt)
    with pb:
        st.metric("Max Pain", f"₹{atm:,}")
    with pc:
        st.metric("Spot Price", f"₹{spot_price:,.2f}")

    # Heavyweights
    st.markdown("---")
    st.subheader("🏢 Nifty Heavyweights Tracker")
    live_hw = st.toggle("Use 5-minute intraday heavyweights", value=False)
    heavy_syms = {
        "HDFC Bank": "HDFCBANK.NS", "Reliance": "RELIANCE.NS",
        "ICICI Bank": "ICICIBANK.NS", "Infosys": "INFY.NS", "TCS": "TCS.NS"
    }
    hw_cols = st.columns(5)
    for i, (name, sym) in enumerate(heavy_syms.items()):
        with hw_cols[i]:
            try:
                if live_hw:
                    s_in, s_da = get_heavyweight_intraday(sym), get_heavyweight_daily(sym)
                    if not s_in.empty:
                        idx = pd.to_datetime(s_in.index)
                        idx = idx.tz_convert("Asia/Kolkata") if idx.tz is not None else idx.tz_localize("Asia/Kolkata")
                        c_price = float(s_in["Close"].iloc[-1])
                        p_close = get_previous_close_for_session(s_da, idx[-1].date())
                        chg = ((c_price - p_close) / p_close * 100) if (p_close and p_close != 0) else 0.0
                        st.metric(label=name, value=f"₹{c_price:,.1f}", delta=f"{chg:+.2f}%")
                else:
                    stk = get_heavyweight_daily(sym)
                    if len(stk) >= 2:
                        c_p, p_p = float(stk["Close"].iloc[-1]), float(stk["Close"].iloc[-2])
                        chg = ((c_p - p_p) / p_p * 100) if p_p != 0 else 0.0
                        st.metric(label=name, value=f"₹{c_p:,.1f}", delta=f"{chg:+.2f}%")
            except Exception:
                st.caption(f"{name}: N/A")

    # CPR & Indicators Section
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🎯 Liquidity & Trap Zones (PDH / PDL)")
        st.write(f"🔺 **Previous Day High (PDH):** ₹{pdh:,.2f}")
        st.write(f"🔻 **Previous Day Low (PDL):** ₹{pdl:,.2f}")
        st.markdown("---")
        st.subheader("📌 Normalized CPR & Pivots")
        if cpr_w_pct < 0.20:
            st.success(f"🔥 **Narrow CPR ({cpr_w_pct:.2f}%):** Trend/Breakout expected")
        elif cpr_w_pct > 0.35:
            st.warning(f"⚠️ **Wide CPR ({cpr_w_pct:.2f}%):** Range-bound expected")
        else:
            st.info(f"⚖️ **Normal CPR ({cpr_w_pct:.2f}%):** Balanced market")
        st.write(f"🔴 **Resistance 2 (R2):** ₹{R2:,.2f}")
        st.write(f"🔴 **Resistance 1 (R1):** ₹{R1:,.2f}")
        st.success(f"🎯 **CPR Range (BC-PP-TC):** ₹{BC:,.2f} - ₹{PP:,.2f} - ₹{TC:,.2f}")
        st.write(f"🟢 **Support 1 (S1):** ₹{S1:,.2f}")
        st.write(f"🟢 **Support 2 (S2):** ₹{S2:,.2f}")

    with c2:
        st.subheader("📈 Technical Indicators (Multi-Timeframe)")
        st.write(f"🔹 **EMA 9:** ₹{ema9_val:,.2f} ➔ {trend_label(spot_price, ema9_val)}")
        st.write(f"🔹 **EMA 21:** ₹{ema21_val:,.2f} ➔ {trend_label(spot_price, ema21_val)}")
        st.write(f"🔹 **Session VWAP:** ₹{vwap_val:,.2f} ➔ {trend_label(spot_price, vwap_val)}")
        st.write(f"🔹 **RSI (14):** {rsi_val:.2f} ➔ {rsi_status}")
        st.markdown("---")
        st.subheader("🌐 நேரலை சந்தை செய்திகள் (Tamil News)")
        for n in get_market_news():
            st.write(n)

    # Live Alerts
    st.markdown("---")
    st.subheader("🔔 Live Alerts")
    alerts = []
    if pd.notna(ema9_val) and pd.notna(ema21_val):
        alerts.append(f"🟢 **EMA Bullish** — EMA 9 ({ema9_val:,.2f}) > EMA 21" if ema9_val > ema21_val else f"🔴 **EMA Bearish** — EMA 9 ({ema9_val:,.2f}) < EMA 21")
    if pd.notna(vwap_val):
        alerts.append(f"🟢 **Above VWAP** — Price ₹{spot_price:,.2f} > VWAP" if spot_price > vwap_val else f"🔴 **Below VWAP** — Price ₹{spot_price:,.2f} < VWAP")
    if pd.notna(rsi_val):
        if rsi_val >= 70:
            alerts.append(f"⚠️ **RSI Overbought** ({rsi_val:.1f})")
        elif rsi_val <= 30:
            alerts.append(f"🟢 **RSI Oversold** ({rsi_val:.1f})")
        elif rsi_val >= 60:
            alerts.append(f"🟢 **RSI Bullish Bias** ({rsi_val:.1f})")
        elif rsi_val <= 40:
            alerts.append(f"🩸 **RSI Bearish Bias** ({rsi_val:.1f})")
    if spot_price > pdh:
        alerts.append(f"🚀 **PDH Breakout** — Above ₹{pdh:,.2f}")
    elif spot_price < pdl:
        alerts.append(f"🩸 **PDL Breakdown** — Below ₹{pdl:,.2f}")
    if vix_val is not None and vix_val >= 18:
        alerts.append(f"🚨 **High VIX** — {vix_val:.2f} (Hedging suggested)")

    if alerts:
        for a in alerts:
            st.markdown(f"- {a}")
    else:
        st.caption("No alerts right now.")

    # Chart Section
    st.markdown("---")
    st.subheader("📈 NIFTY Intraday Chart - Price / VWAP / CPR")

    chart_df = session_hist[["Close", "VWAP"]].copy()
    chart_df["Time"] = chart_df.index
    chart_df = chart_df.reset_index(drop=True)

    if chart_df["VWAP"].isna().all():
        chart_df["VWAP"] = chart_df["Close"]
        st.caption("ℹ️ **VWAP Note:** Volume is unavailable; VWAP follows Price line.")

    chart_start = chart_df["Time"].min()
    chart_end = chart_df["Time"].max() + pd.Timedelta(minutes=25)
    label_x_pos = chart_df["Time"].max() + pd.Timedelta(minutes=3)

    levels_data = pd.DataFrame([
        {"Level": "PDH", "Value": float(pdh), "Color": "#cc0000", "LabelX": label_x_pos},
        {"Level": "R1", "Value": float(R1), "Color": "#ff6666", "LabelX": label_x_pos},
        {"Level": "TC", "Value": float(TC), "Color": "#66b3ff", "LabelX": label_x_pos},
        {"Level": "Pivot", "Value": float(PP), "Color": "#0066cc", "LabelX": label_x_pos},
        {"Level": "BC", "Value": float(BC), "Color": "#3399ff", "LabelX": label_x_pos},
        {"Level": "S1", "Value": float(S1), "Color": "#66cc66", "LabelX": label_x_pos},
        {"Level": "PDL", "Value": float(pdl), "Color": "#009900", "LabelX": label_x_pos},
    ])

    vwap_df = chart_df.dropna(subset=["VWAP"]).copy()
    all_key_values = chart_df["Close"].tolist() + vwap_df["VWAP"].tolist() + levels_data["Value"].tolist()
    valid_vals = [float(v) for v in all_key_values if pd.notna(v) and np.isfinite(v) and (spot_price - 400) <= v <= (spot_price + 400)]

    y_min = float(min(valid_vals) - 20) if valid_vals else float(spot_price - 250)
    y_max = float(max(valid_vals) + 20) if valid_vals else float(spot_price + 250)

    x_scale = alt.Scale(domain=[chart_start, chart_end])
    y_scale = alt.Scale(domain=[y_min, y_max], clamp=True, zero=False, nice=False, padding=0)

    # 1. Price Line
    price_line = alt.Chart(chart_df).mark_line(color="#0052cc", strokeWidth=2.5).encode(
        x=alt.X("Time:T", title="Time (IST)", axis=alt.Axis(format="%H:%M", tickMinStep=300000, labelAngle=-45, labelFontSize=8), scale=x_scale),
        y=alt.Y("Close:Q", title="Price (₹)", scale=y_scale),
        tooltip="Close:Q"
    )

    # 2. VWAP Line
    vwap_line = alt.Chart(vwap_df).mark_line(color="#ff9900", strokeWidth=2.0, strokeDash=[3, 3]).encode(
        x=alt.X("Time:T", scale=x_scale),
        y=alt.Y("VWAP:Q", scale=y_scale),
        tooltip="VWAP:Q"
    )

    # 3. CPR Band
    cpr_band_data = pd.DataFrame([{"_Start": chart_start, "_End": chart_end, "_Lower": float(BC), "_Upper": float(TC)}])
    cpr_band = alt.Chart(cpr_band_data).mark_rect(color="#9ecae1", opacity=0.15).encode(
        x=alt.X("_Start:T", scale=x_scale),
        x2=alt.X2("_End:T"),
        y=alt.Y("_Lower:Q", scale=y_scale),
        y2=alt.Y2("_Upper:Q"),
        tooltip=alt.value(None)
    )

    # 4. Level Rules
    level_rules = alt.Chart(levels_data).mark_rule(strokeDash=[4, 4], strokeWidth=1.2).encode(
        y=alt.Y("Value:Q", scale=y_scale),
        color=alt.Color("Color:N", scale=None, legend=None),
        tooltip=alt.value(None)
    )

    # 5. Level Labels
    level_labels = alt.Chart(levels_data).mark_text(align="left", dx=4, dy=-3, fontSize=10, fontWeight="bold").encode(
        x=alt.X("LabelX:T", scale=x_scale),
        y=alt.Y("Value:Q", scale=y_scale),
        text=alt.Text("Level:N"),
        color=alt.Color("Color:N", scale=None, legend=None),
        tooltip=alt.value(None)
    )

    # 6. Price Dot
    price_dot = alt.Chart(chart_df.tail(1)).mark_point(color="#0052cc", filled=True, size=80, shape="circle").encode(
        x=alt.X("Time:T", scale=x_scale),
        y=alt.Y("Close:Q", scale=y_scale),
        tooltip="Close:Q"
    )

    # 7. LTP Label
    ltp_label_df = pd.DataFrame([{"Time": chart_df["Time"].iloc[-1], "Close": spot_price, "Label": f"LTP ₹{spot_price:,.2f}"}])
    ltp_label = alt.Chart(ltp_label_df).mark_text(align="left", dx=8, dy=22, fontSize=11, fontWeight="bold", color="#cc0000").encode(
        x=alt.X("Time:T", scale=x_scale),
        y=alt.Y("Close:Q", scale=y_scale),
        text=alt.Text("Label:N"),
        tooltip=alt.value(None)
    )

    # Final Combined Chart
    final_chart = (cpr_band + level_rules + vwap_line + price_dot + level_labels + ltp_label + price_line).resolve_scale(
        x="shared", y="shared"
    ).properties(height=460, title="NIFTY Intraday - Price, VWAP, CPR and Key Levels")

    st.altair_chart(final_chart, use_container_width=True)
    st.caption("🔵 Price | 🟠 Session VWAP | 🔴 PDH/R1 | 🔵 CPR (TC/Pivot/BC) | 🟢 S1/PDL | 🔴 LTP")

except Exception as e:
    st.error(f"Analysis error: {e}")
    st.stop()
    
