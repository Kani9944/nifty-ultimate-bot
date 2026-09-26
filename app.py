import altair as alt
import feedparser
import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf

# ============ PAGE CONFIG ============
st.set_page_config(page_title="Nifty Monitor", layout="wide")
st_autorefresh(interval=30 * 1000, key="refresh")
st.title("🦅 NIFTY 50 - Smart Money & Market Monitor")


# ============ HELPERS ============
def format_lakhs(value):
    try:
        v = float(value)
    except Exception:
        return str(value)
    if v >= 10000000:
        return f"{v/10000000:.2f} Cr"
    if v >= 100000:
        return f"{v/100000:.2f} L"
    if v >= 1000:
        return f"{v/1000:.1f} K"
    return f"{v:,.0f}"


def get_last_bar_change(data):
    if data is None or len(data) < 2:
        return None, None
    curr = float(data["Close"].iloc[-1])
    prev = float(data["Close"].iloc[-2])
    if prev == 0:
        return curr, None
    return curr, ((curr - prev) / prev) * 100


def calculate_rsi(close, window=14):
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.rolling(window=window, min_periods=window).mean()
    avg_loss = losses.rolling(window=window, min_periods=window).mean()
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    return rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)


# ============ PAPER TRADING STATE ============
if "paper_trades" not in st.session_state:
    st.session_state.paper_trades = []
if "paper_trade_next_id" not in st.session_state:
    st.session_state.paper_trade_next_id = 1


def add_paper_trade(strike, opt_type, entry_price, qty):
    st.session_state.paper_trades.append({
        "id": st.session_state.paper_trade_next_id,
        "strike": int(strike),
        "type": opt_type,
        "entry": float(entry_price),
        "qty": int(qty),
        "exit": None,
        "pnl": 0.0,
        "status": "OPEN",
    })
    st.session_state.paper_trade_next_id += 1


def close_paper_trade(trade_id, exit_price):
    for t in st.session_state.paper_trades:
        if t["id"] == trade_id and t["status"] == "OPEN":
            t["exit"] = float(exit_price)
            t["pnl"] = round((float(exit_price) - t["entry"]) * t["qty"], 2)
            t["status"] = "CLOSED"
            break


# ============ DATA FETCH ============
@st.cache_data(ttl=25)
def get_stock_data(symbol, period, interval=None):
    ticker = yf.Ticker(symbol)
    return (
        ticker.history(period=period, interval=interval)
        if interval
        else ticker.history(period=period)
    )


@st.cache_data(ttl=120)
def get_nifty50_breadth():
    symbols = [
        "ADANIENT.NS", "ASIANPAINT.NS", "AXISBANK.NS", "BAJFINANCE.NS",
        "BHARTIARTL.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
        "ITC.NS", "KOTAKBANK.NS", "LT.NS", "M&M.NS", "MARUTI.NS",
        "RELIANCE.NS", "SBIN.NS", "TCS.NS", "TATAMOTORS.NS", "TITAN.NS",
    ]
    stocks = []
    for s in symbols:
        try:
            h = yf.Ticker(s).history(period="2d", interval="1d")
            if len(h) >= 2:
                c = float(h["Close"].iloc[-1])
                p = float(h["Close"].iloc[-2])
                if p > 0:
                    stocks.append({
                        "Symbol": s.replace(".NS", ""),
                        "LTP": round(c, 2),
                        "Change%": round(((c - p) / p) * 100, 2),
                    })
        except Exception:
            pass
    return (stocks, None) if stocks else (None, "Data unavailable")


@st.cache_data(ttl=120)
def get_sector_data():
    sec = {
        "Bank": "^NSEBANK",
        "IT": "^CNXIT",
        "Auto": "^CNXAUTO",
        "Pharma": "^CNXPHARMA",
        "FMCG": "^CNXFMCG",
        "Metal": "^CNXMETAL",
    }
    res = {}
    for k, sym in sec.items():
        try:
            h = yf.Ticker(sym).history(period="2d", interval="1d")
            if len(h) >= 2:
                c = float(h["Close"].iloc[-1])
                p = float(h["Close"].iloc[-2])
                if p > 0:
                    res[k] = round(((c - p) / p) * 100, 2)
        except Exception:
            pass
    return res


@st.cache_data(ttl=300)
def get_market_news():
    feeds = [
        "https://tamil.goodreturns.in/rss/tamil-money-fb.xml",
        "https://tamil.oneindia.com/rss/feeds/tamil-news-fb.xml",
        "https://www.dinamani.com/rss/business.xml",
    ]
    news = []
    for url in feeds:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=2)
            if r.status_code == 200:
                f = feedparser.parse(r.content)
                for e in f.entries[:3]:
                    t = e.get("title", "").strip()
                    l = e.get("link", "")
                    if t:
                        news.append(f"📰 [{t}]({l})" if l else f"📰 {t}")
                if len(news) >= 6:
                    break
        except Exception:
            continue
    return news[:6] if news else ["📰 தமிழ் வணிகச் செய்திகள் தற்போது கிடைக்கவில்லை."]


# ============ MAIN APP ============
try:
    hist = get_stock_data("^NSEI", "5d", "5m")
    daily = get_stock_data("^NSEI", "5d", "1d")
    bn_hist = get_stock_data("^NSEBANK", "2d", "5m")
    vix_hist = get_stock_data("^INDIAVIX", "2d", "5m")

    if hist.empty or daily.empty or len(daily) < 2:
        st.error("Nifty data கிடைக்கவில்லை. மீண்டும் முயற்சிக்கவும்.")
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
        st.error("Session data கிடைக்கவில்லை.")
        st.stop()

    spot_price = float(session_hist["Close"].iloc[-1])
    _, nifty_5m_change = get_last_bar_change(session_hist)

    prev_sessions = daily[pd.Index(daily.index.date) < session_date]
    if prev_sessions.empty:
        st.error("Previous session data கிடைக்கவில்லை.")
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

    typical = (session_hist["High"] + session_hist["Low"] + session_hist["Close"]) / 3
    cum_vol = session_hist["Volume"].cumsum()
    session_hist["VWAP"] = np.where(
        cum_vol > 0,
        (typical * session_hist["Volume"]).cumsum() / cum_vol,
        np.nan,
    )
    if session_hist["VWAP"].isna().all():
        session_hist["VWAP"] = session_hist["Close"]

    bn_price, bn_5m_change = get_last_bar_change(bn_hist)
    vix_val, vix_5m_change = get_last_bar_change(vix_hist)

    ema9_val = float(hist["Close"].ewm(span=9, adjust=False).mean().iloc[-1])
    ema21_val = float(hist["Close"].ewm(span=21, adjust=False).mean().iloc[-1])

    rsi_series = calculate_rsi(hist["Close"], window=14)
    rsi_val = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50.0

    vwap_val = (
        float(session_hist["VWAP"].iloc[-1])
        if pd.notna(session_hist["VWAP"].iloc[-1])
        else spot_price
    )

    # ============ TOP METRICS (Force Side-by-Side) ============
    nifty_delta = f"{nifty_5m_change:+.2f}% (5m)" if nifty_5m_change is not None else ""
    bn_delta = f"{bn_5m_change:+.2f}% (5m)" if bn_5m_change is not None else ""
    vix_delta = f"{vix_5m_change:+.2f}% (5m)" if vix_5m_change is not None else ""

    nifty_color = "#00b300" if (nifty_5m_change or 0) >= 0 else "#cc0000"
    bn_color = "#00b300" if (bn_5m_change or 0) >= 0 else "#cc0000"
    vix_color = "#cc0000" if (vix_5m_change or 0) >= 0 else "#00b300"

    bn_disp = f"₹{bn_price:,.2f}" if bn_price is not None else "N/A"
    vix_disp = f"{vix_val:.2f}" if vix_val is not None else "N/A"

    st.markdown(
        f"""
        <div style="display:flex; gap:8px; flex-wrap:nowrap; margin-bottom:8px;">
          <div style="flex:1; padding:10px; background:#f8f9fa; border-radius:8px; border-left:4px solid #0052cc;">
            <div style="font-size:12px; color:#666;">NIFTY 50</div>
            <div style="font-size:20px; font-weight:bold;">₹{spot_price:,.2f}</div>
            <div style="font-size:12px; color:{nifty_color};">{nifty_delta}</div>
          </div>
          <div style="flex:1; padding:10px; background:#f8f9fa; border-radius:8px; border-left:4px solid #0052cc;">
            <div style="font-size:12px; color:#666;">BANK NIFTY</div>
            <div style="font-size:20px; font-weight:bold;">{bn_disp}</div>
            <div style="font-size:12px; color:{bn_color};">{bn_delta}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div style="display:flex; justify-content:center; margin-bottom:8px;">
          <div style="padding:10px 30px; background:#f8f9fa; border-radius:8px; border-left:4px solid #ff9900; text-align:center;">
            <div style="font-size:12px; color:#666;">INDIA VIX</div>
            <div style="font-size:20px; font-weight:bold;">{vix_disp}</div>
            <div style="font-size:12px; color:{vix_color};">{vix_delta}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div style="display:flex; gap:8px; flex-wrap:nowrap;">
          <div style="flex:1; padding:10px; background:#f8f9fa; border-radius:8px; border-left:4px solid #cc0000;">
            <div style="font-size:12px; color:#666;">PDH</div>
            <div style="font-size:18px; font-weight:bold;">₹{pdh:,.2f}</div>
          </div>
          <div style="flex:1; padding:10px; background:#f8f9fa; border-radius:8px; border-left:4px solid #00b300;">
            <div style="font-size:12px; color:#666;">PDL</div>
            <div style="font-size:18px; font-weight:bold;">₹{pdl:,.2f}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ============ LIVE ALERTS ============
    st.markdown("---")
    st.subheader("🔔 Live Alerts")
    alerts = []

    if pd.notna(ema9_val) and pd.notna(ema21_val):
        if ema9_val > ema21_val:
            alerts.append(
                f"🟢 **EMA Bullish** — EMA 9 (₹{ema9_val:,.2f}) > "
                f"EMA 21 (₹{ema21_val:,.2f})"
            )
        else:
            alerts.append(
                f"🔴 **EMA Bearish** — EMA 9 (₹{ema9_val:,.2f}) < "
                f"EMA 21 (₹{ema21_val:,.2f})"
            )

    if pd.notna(vwap_val):
        if spot_price > vwap_val:
            alerts.append(
                f"🟢 **Above VWAP** — Price (₹{spot_price:,.2f}) > "
                f"VWAP (₹{vwap_val:,.2f})"
            )
        else:
            alerts.append(
                f"🔴 **Below VWAP** — Price (₹{spot_price:,.2f}) < "
                f"VWAP (₹{vwap_val:,.2f})"
            )

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
        alerts.append(f"🚨 **Elevated VIX** — {vix_val:.2f}")

    if alerts:
        for a in alerts:
            st.markdown(f"- {a}")
    else:
        st.caption("No active alerts.")

    # ============ MARKET BREADTH ============
    st.markdown("---")
    st.subheader("Market Breadth - Nifty 50")
    breadth_stocks, breadth_err = get_nifty50_breadth()

    if breadth_err or not breadth_stocks:
        st.warning(f"Breadth unavailable: {breadth_err}")
    else:
        adv = sum(1 for s in breadth_stocks if s["Change%"] > 0.05)
        dec = sum(1 for s in breadth_stocks if s["Change%"] < -0.05)
        avg_c = sum(s["Change%"] for s in breadth_stocks) / len(breadth_stocks)

        b1, b2, b3 = st.columns(3)
        b1.metric("Advances", adv)
        b2.metric("Declines", dec)
        b3.metric("Avg Change", f"{avg_c:+.2f}%")

        sorted_stocks = sorted(breadth_stocks, key=lambda x: x["Change%"], reverse=True)

        # Top 5 side by side (Force)
        gainers_html = "".join(
            f'<div style="padding:5px 0; border-bottom:1px solid #eee;">'
            f'<b>{s["Symbol"]}</b><br>'
            f'<span style="font-size:12px;">₹{s["LTP"]:,.2f} '
            f'<span style="color:#00b300;">({s["Change%"]:+.2f}%)</span></span>'
            f'</div>'
            for s in sorted_stocks[:5]
        )
        losers_html = "".join(
            f'<div style="padding:5px 0; border-bottom:1px solid #eee;">'
            f'<b>{s["Symbol"]}</b><br>'
            f'<span style="font-size:12px;">₹{s["LTP"]:,.2f} '
            f'<span style="color:#cc0000;">({s["Change%"]:+.2f}%)</span></span>'
            f'</div>'
            for s in sorted_stocks[-5:][::-1]
        )

        st.markdown(
            f"""
            <div style="display:flex; gap:10px; flex-wrap:nowrap;">
              <div style="flex:1;">
                <div style="font-size:15px; font-weight:bold; color:#00b300; margin-bottom:6px;">🟢 Top 5 Gainers</div>
                {gainers_html}
              </div>
              <div style="flex:1;">
                <div style="font-size:15px; font-weight:bold; color:#cc0000; margin-bottom:6px;">🔴 Top 5 Losers</div>
                {losers_html}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ============ SECTOR PERFORMANCE ============
    st.markdown("---")
    st.subheader("Sector Performance")
    sector_data = get_sector_data()
    if sector_data:
        cols = st.columns(len(sector_data))
        for i, (name, pct) in enumerate(sector_data.items()):
            with cols[i]:
                if pct >= 0:
                    st.success(f"{name}: +{pct:.2f}%")
                else:
                    st.error(f"{name}: {pct:.2f}%")

    # ============ OPTION CHAIN ============
    st.markdown("---")
    st.subheader("Strike-wise Call vs Put (Estimated Model)")
    st.caption("⚠️ இது மாதிரி மதிப்பீடு மட்டுமே; நேரடி NSE OI அல்ல.")

    atm = int(round(spot_price / 50) * 50)
    rows = []
    tot_call, tot_put = 0, 0

    for s in [atm + (i * 50) for i in range(-2, 3)]:
        d = abs(spot_price - s)
        c_oi = int(max(1500000, 4500000 - (d * 9000)))
        p_oi = int(max(1400000, 5200000 - (d * 8500)))
        diff = (spot_price - s) / 50.0
        c_ltp = round(max(5.0, 180.0 + (diff * 45)), 2)
        p_ltp = round(max(5.0, 175.0 - (diff * 45)), 2)
        tot_call += c_oi
        tot_put += p_oi
        if p_oi > c_oi * 1.15:
            sig = "🟢 Put Support"
        elif c_oi > p_oi * 1.15:
            sig = "🔴 Call Resistance"
        else:
            sig = "⚖️ Neutral"
        rows.append({
            "Strike": f"₹{s:,}" + (" 🎯 ATM" if s == atm else ""),
            "Call OI": format_lakhs(c_oi),
            "Call LTP": f"₹{c_ltp}",
            "Put LTP": f"₹{p_ltp}",
            "Put OI": format_lakhs(p_oi),
            "Signal": sig,
        })

    pcr = tot_put / tot_call if tot_call > 0 else 0
    pa, pb, pc = st.columns(3)
    if pcr > 1.2:
        pa.metric("📊 Model PCR", f"{pcr:.2f}", "🟢 Bullish")
    elif pcr < 0.8:
        pa.metric("📊 Model PCR", f"{pcr:.2f}", "🔴 Bearish")
    else:
        pa.metric("📊 Model PCR", f"{pcr:.2f}", "⚖️ Neutral")
    pb.metric("🎯 Model ATM", f"₹{atm:,}")
    pc.metric("📍 Nifty Spot", f"₹{spot_price:,.2f}")

    opt_df = pd.DataFrame(rows)
    st.dataframe(opt_df, hide_index=True, use_container_width=True)

    # ============ PAPER TRADING ============
    st.markdown("---")
    st.subheader("📝 Model-based Paper Trading")
    st.caption("⚠️ விர்ச்சுவல் டிரேடிங் — real order போகாது.")

    p_col1, p_col2 = st.columns([1, 2])

    with p_col1:
        with st.form("open_trade_form"):
            pt_strike = st.selectbox("Strike", [atm + (i * 50) for i in range(-2, 3)], index=2)
            pt_type = st.radio("Type", ["CE", "PE"], horizontal=True)
            lot_size = st.number_input("Lot Size", min_value=1, value=25)
            lots = st.number_input("Lots", min_value=1, value=1)
            pt_qty = int(lot_size * lots)

            if pt_type == "CE":
                est_p = round(max(5.0, 180.0 + ((spot_price - pt_strike) / 50.0 * 45)), 2)
            else:
                est_p = round(max(5.0, 175.0 - ((spot_price - pt_strike) / 50.0 * 45)), 2)

            st.write(f"Model Premium: **₹{est_p:,.2f}** | Units: **{pt_qty}**")
            submitted = st.form_submit_button("🚀 Place Model Trade")

        if submitted:
            add_paper_trade(pt_strike, pt_type, est_p, pt_qty)
            st.rerun()

    with p_col2:
        if st.session_state.paper_trades:
            t_rows = []
            for t in st.session_state.paper_trades:
                if t["type"] == "CE":
                    cur_p = round(max(5.0, 180.0 + ((spot_price - t["strike"]) / 50.0 * 45)), 2)
                else:
                    cur_p = round(max(5.0, 175.0 - ((spot_price - t["strike"]) / 50.0 * 45)), 2)
                pnl = round((cur_p - t["entry"]) * t["qty"], 2) if t["status"] == "OPEN" else t["pnl"]
                t_rows.append({
                    "ID": t["id"],
                    "Trade": f"{t['strike']} {t['type']}",
                    "Entry": f"₹{t['entry']}",
                    "Qty": t["qty"],
                    "LTP/Exit": f"₹{cur_p if t['status'] == 'OPEN' else t['exit']}",
                    "PnL": f"₹{pnl:+,.2f}",
                    "Status": t["status"],
                })
            st.dataframe(pd.DataFrame(t_rows), hide_index=True)

            open_t = [t for t in st.session_state.paper_trades if t["status"] == "OPEN"]
            if open_t:
                with st.form("close_trade_form"):
                    c_id = st.selectbox("Close Trade ID", [t["id"] for t in open_t])
                    closed = st.form_submit_button("❌ Close Trade")
                if closed:
                    t_obj = next(t for t in open_t if t["id"] == c_id)
                    if t_obj["type"] == "CE":
                        c_ext = round(max(5.0, 180.0 + ((spot_price - t_obj["strike"]) / 50.0 * 45)), 2)
                    else:
                        c_ext = round(max(5.0, 175.0 - ((spot_price - t_obj["strike"]) / 50.0 * 45)), 2)
                    close_paper_trade(c_id, c_ext)
                    st.rerun()
        else:
            st.info("செயலில் உள்ள டிரேடுகள் இல்லை.")

    # ============ CHART ============
    st.markdown("---")
    st.subheader("📈 NIFTY Intraday Chart - Price & VWAP")

    chart_df = session_hist[["Close", "VWAP"]].copy().dropna(subset=["Close"])

    if not chart_df.empty:
        chart_df.index = pd.to_datetime(chart_df.index)
        if chart_df.index.tz is n
