import altair as alt
import feedparser
import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf

# App Config
st.set_page_config(page_title="Nifty Monitor", layout="wide")
st_autorefresh(interval=30 * 1000, key="refresh")
st.title("🦅 NIFTY 50 - Smart Money & Market Monitor")


def format_lakhs(v):
  try:
    val = float(v)
    if val >= 10000000:
      return f"{val/10000000:.2f} Cr"
    if val >= 100000:
      return f"{val/100000:.2f} L"
    if val >= 1000:
      return f"{val/1000:.1f} K"
    return f"{val:,.0f}"
  except Exception:
    return str(v)


def get_last_bar_change(data):
  if data is None or len(data) < 2:
    return None, None
  c, p = float(data["Close"].iloc[-1]), float(data["Close"].iloc[-2])
  return c, (((c - p) / p) * 100 if p != 0 else None)


def calculate_rsi(close, window=14):
  delta = close.diff()
  gains, losses = delta.clip(lower=0), -delta.clip(upper=0)
  ag = gains.rolling(window=window, min_periods=window).mean()
  al = losses.rolling(window=window, min_periods=window).mean()
  rs = ag / al
  rsi = 100.0 - (100.0 / (1.0 + rs))
  rsi = rsi.mask((al == 0) & (ag > 0), 100.0)
  rsi = rsi.mask((ag == 0) & (al > 0), 0.0)
  return rsi.mask((ag == 0) & (al == 0), 50.0)


# Paper Trading State
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


def close_paper_trade(t_id, exit_p):
  for t in st.session_state.paper_trades:
    if t["id"] == t_id and t["status"] == "OPEN":
      t["exit"], t["status"] = float(exit_p), "CLOSED"
      t["pnl"] = round((float(exit_p) - t["entry"]) * t["qty"], 2)
      break


# Caching Fetches
@st.cache_data(ttl=25)
def get_stock_data(sym, period, interval=None):
  t = yf.Ticker(sym)
  return (
      t.history(period=period, interval=interval)
      if interval
      else t.history(period=period)
  )


@st.cache_data(ttl=120)
def get_nifty50_breadth():
  syms = [
      "ADANIENT.NS",
      "ASIANPAINT.NS",
      "AXISBANK.NS",
      "BAJFINANCE.NS",
      "BHARTIARTL.NS",
      "HDFCBANK.NS",
      "ICICIBANK.NS",
      "INFY.NS",
      "ITC.NS",
      "KOTAKBANK.NS",
      "LT.NS",
      "M&M.NS",
      "MARUTI.NS",
      "RELIANCE.NS",
      "SBIN.NS",
      "TCS.NS",
      "TATAMOTORS.NS",
      "TITAN.NS",
  ]
  stocks = []
  for s in syms:
    try:
      h = yf.Ticker(s).history(period="2d", interval="1d")
      if len(h) >= 2:
        c, p = float(h["Close"].iloc[-1]), float(h["Close"].iloc[-2])
        if p > 0:
          stocks.append({
              "Symbol": s.replace(".NS", ""),
              "LTP": round(c, 2),
              "Change%": round(((c - p) / p) * 100, 2),
          })
    except Exception:
      pass
  return (stocks, None) if stocks else (None, "Unavailable")


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
        c, p = float(h["Close"].iloc[-1]), float(h["Close"].iloc[-2])
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
          t, l = e.get("title", "").strip(), e.get("link", "")
          if t:
            news.append(f"📰 [{t}]({l})" if l else f"📰 {t}")
        if len(news) >= 6:
          break
    except Exception:
      continue
  return news[:6] if news else ["📰 தமிழ் வணிகச் செய்திகள் கிடைக்கவில்லை."]


# Main Execution
try:
  hist = get_stock_data("^NSEI", "5d", "5m")
  daily = get_stock_data("^NSEI", "5d", "1d")
  bn_hist = get_stock_data("^NSEBANK", "2d", "5m")
  vix_hist = get_stock_data("^INDIAVIX", "2d", "5m")

  if hist.empty or daily.empty or len(daily) < 2:
    st.error("Nifty தரவுகள் கிடைக்கவில்லை. மீண்டும் முயற்சிக்கவும்.")
    st.stop()

  hist.index = pd.to_datetime(hist.index)
  hist.index = (
      hist.index.tz_convert("Asia/Kolkata")
      if hist.index.tz is not None
      else hist.index.tz_localize("Asia/Kolkata")
  )
  daily.index = pd.to_datetime(daily.index)
  daily.index = (
      daily.index.tz_convert("Asia/Kolkata")
      if daily.index.tz is not None
      else daily.index.tz_localize("Asia/Kolkata")
  )

  today = pd.Timestamp.now(tz="Asia/Kolkata").date()
  session_date = (
      today if (hist.index.date == today).any() else hist.index[-1].date()
  )
  session_hist = hist[hist.index.date == session_date].copy()
  if session_hist.empty:
    st.error("Session தரவுகள் கிடைக்கவில்லை.")
    st.stop()

  spot_price = float(session_hist["Close"].iloc[-1])
  _, nifty_5m_chg = get_last_bar_change(session_hist)
  prev_sessions = daily[pd.Index(daily.index.date) < session_date]
  if prev_sessions.empty:
    st.error("Previous session தரவுகள் கிடைக்கவில்லை.")
    st.stop()

  prev_day = prev_sessions.iloc[-1]
  pdh, pdl, pdc = (
      float(prev_day["High"]),
      float(prev_day["Low"]),
      float(prev_day["Close"]),
  )

  PP = (pdh + pdl + pdc) / 3
  BC = min((pdh + pdl) / 2, (2 * PP) - ((pdh + pdl) / 2))
  TC = max((pdh + pdl) / 2, (2 * PP) - ((pdh + pdl) / 2))
  R1, S1 = (2 * PP) - pdl, (2 * PP) - pdh
  R2, S2 = PP + (pdh - pdl), PP - (pdh - pdl)

  tp = (session_hist["High"] + session_hist["Low"] + session_hist["Close"]) / 3
  v_cum = session_hist["Volume"].cumsum()
  session_hist["VWAP"] = np.where(
      v_cum > 0, (tp * session_hist["Volume"]).cumsum() / v_cum, np.nan
  )
  if session_hist["VWAP"].isna().all():
    session_hist["VWAP"] = session_hist["Close"]

  bn_price, bn_5m_chg = get_last_bar_change(bn_hist)
  vix_val, vix_5m_chg = get_last_bar_change(vix_hist)
  ema9_val = float(hist["Close"].ewm(span=9, adjust=False).mean().iloc[-1])
  ema21_val = float(hist["Close"].ewm(span=21, adjust=False).mean().iloc[-1])
  rsi_series = calculate_rsi(hist["Close"], window=14)
  rsi_val = (
      float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50.0
  )
  vwap_val = (
      float(session_hist["VWAP"].iloc[-1])
      if pd.notna(session_hist["VWAP"].iloc[-1])
      else spot_price
  )

  # Top Metrics
  m1, m2, m3, m4, m5 = st.columns(5)
  m1.metric(
      "NIFTY 50",
      f"₹{spot_price:,.2f}",
      f"{nifty_5m_chg:+.2f}% (5m)" if nifty_5m_chg is not None else None,
  )
  m2.metric(
      "BANK NIFTY",
      f"₹{bn_price:,.2f}" if bn_price is not None else "N/A",
      f"{bn_5m_chg:+.2f}% (5m)" if bn_5m_chg is not None else None,
  )
  m3.metric(
      "INDIA VIX",
      f"{vix_val:.2f}" if vix_val is not None else "N/A",
      f"{vix_5m_chg:+.2f}% (5m)" if vix_5m_chg is not None else None,
      delta_color="inverse",
  )
  m4.metric("PDH", f"₹{pdh:,.2f}")
  m5.metric("PDL", f"₹{pdl:,.2f}")

  # Live Alerts
  st.markdown("---")
  st.subheader("🔔 Live Alerts")
  alerts = []
  if pd.notna(ema9_val) and pd.notna(ema21_val):
    alerts.append(
        f"🟢 **EMA Bullish** — EMA 9 (₹{ema9_val:,.2f}) > EMA 21"
        f" (₹{ema21_val:,.2f})"
        if ema9_val > ema21_val
        else f"🔴 **EMA Bearish** — EMA 9 (₹{ema9_val:,.2f}) < EMA 21"
        f" (₹{ema21_val:,.2f})"
    )

  if pd.notna(vwap_val):
    alerts.append(
        f"🟢 **Above VWAP** — Price (₹{spot_price:,.2f}) > VWAP"
        f" (₹{vwap_val:,.2f})"
        if spot_price > vwap_val
        else f"🔴 **Below VWAP** — Price (₹{spot_price:,.2f}) < VWAP"
        f" (₹{vwap_val:,.2f})"
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
    alerts.append(
        f"🚨 **Elevated VIX** — {vix_val:.2f}; intraday swings அதிகரிக்கலாம்."
    )

  if alerts:
    for a in alerts:
      st.markdown(f"- {a}")
  else:
    st.caption("No active technical alerts at the moment.")

  # Breadth & Sectors
  st.markdown("---")
  st.subheader("Market Breadth & Sectors")
  b_stocks, b_err = get_nifty50_breadth()
  if b_stocks:
    c_a, c_b, c_c = st.columns(3)
    c_a.metric("Advances", sum(1 for s in b_stocks if s["Change%"] > 0.05))
    c_b.metric("Declines", sum(1 for s in b_stocks if s["Change%"] < -0.05))
    c_c.metric(
        "Avg Change",
        f"{sum(s['Change%'] for s in b_stocks)/len(b_stocks):+.2f}%",
    )

  sec_data = get_sector_data()
  if sec_data:
    cols = st.columns(len(sec_data))
    for i, (name, pct) in enumerate(sec_data.items()):
      with cols[i]:
        st.success(f"{name}: +{pct:.2f}%") if pct >= 0 else st.error(
            f"{name}: {pct:.2f}%"
        )

  # Option Chain Model
  st.markdown("---")
  st.subheader("Strike-wise Call vs Put (Estimated Model)")
  st.caption(
      "⚠️ **குறிப்பு:** இது மாதிரி மதிப்பீடு (Illustrative Model) மட்டுமே; நேரடி"
      " NSE OI தரவு அல்ல."
  )
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
    sig = (
        "🟢 Put Support"
        if p_oi > c_oi * 1.15
        else ("🔴 Call Resistance" if c_oi > p_oi * 1.15 else "⚖️ Neutral")
    )
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
  pa.metric(
      "📊 Model PCR",
      f"{pcr:.2f}",
      (
          "🟢 Bullish"
          if pcr > 1.2
          else ("🔴 Bearish" if pcr < 0.8 else "⚖️ Neutral")
      ),
  )
  pb.metric("🎯 Model ATM Reference", f"₹{atm:,}")
  pc.metric("📍 Nifty Spot", f"₹{spot_price:,.2f}")
  st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

  # Paper Trading
  st.markdown("---")
  st.subheader("📝 Model-based Paper Trading")
  st.caption("⚠️ மாதிரி விலைகளை அடிப்படையாகக் கொண்ட விர்ச்சுவல் டிரேடிங்.")
  p_col1, p_col2 = st.columns([1, 2])
  with p_col1:
    with st.form("open_trade_form"):
      pt_strike = st.selectbox(
          "Strike", [atm + (i * 50) for i in range(-2, 3)], index=2
      )
      pt_type = st.radio("Type", ["CE", "PE"], horizontal=True)
      lot_size = st.number_input("Lot Size", min_value=1, value=25)
      lots = st.number_input("Lots", min_value=1, value=1)
      pt_qty = int(lot_size * lots)
      est_p = (
          round(max(5.0, 180.0 + ((spot_price - pt_strike) / 50.0 * 45)), 2)
          if pt_type == "CE"
          else round(
              max(5.0, 175.0 - ((spot_price - pt_strike) / 50.0 * 45)), 2
          )
      )
      st.write(f"Model Premium: **₹{est_p:,.2f}** | Units: **{pt_qty}**")
      if st.form_submit_button("🚀 Place Model Trade"):
        add_paper_trade(pt_strike, pt_type, est_p, pt_qty)
        st.rerun()

  with p_col2:
    if st.session_state.paper_trades:
      t_rows = []
      for t in st.session_state.paper_trades:
        cur_p = (
            round(
                max(5.0, 180.0 + ((spot_price - t["strike"]) / 50.0 * 45)), 2
            )
            if t["type"] == "CE"
            else round(
                max(5.0, 175.0 - ((spot_price - t["strike"]) / 50.0 * 45)), 2
            )
        )
        pnl = (
            round((cur_p - t["entry"]) * t["qty"], 2)
            if t["status"] == "OPEN"
            else t["pnl"]
        )
        t_rows.append({
            "ID": t["id"],
            "Trade": f"{t['strike']} {t['type']}",
            "Entry": f"₹{t['entry']}",
            "Qty": t["qty"],
            "LTP/Exit": f"₹{cur_p if t['status']=='OPEN' else t['exit']}",
            "PnL": f"₹{pnl:+,.2f}",
            "Status": t["status"],
        })
      st.dataframe(pd.DataFrame(t_rows), hide_index=True)
      open_t = [
          t for t in st.session_state.paper_trades if t["status"] == "OPEN"
      ]
      if open_t:
        with st.form("close_trade_form"):
          c_id = st.selectbox(
              "Close Trade ID", [t["id"] for t in open_t], key="cls_id"
          )
          if st.form_submit_button("❌ Close Trade"):
            t_obj = next(t for t in open_t if t["id"] == c_id)
            c_ext = (
                round(
                    max(
                        5.0,
                        180.0 + ((spot_price - t_obj["strike"]) / 50.0 * 45),
                    ),
                    2,
                )
                if t_obj["type"] == "CE"
                else round(
                    max(
                        5.0,
                        175.0 - ((spot_price - t_obj["strike"]) / 50.0 * 45),
                    ),
                    2,
                )
            )
            close_paper_trade(c_id, c_ext)
            st.rerun()
    else:
      st.info("செயலில் உள்ள விர்ச்சுவல் டிரேடுகள் இல்லை.")

  # Levels & News
  st.markdown("---")
  c1, c2 = st.columns(2)
  with c1:
    st.subheader("Liquidity & CPR")
    st.write(f"🔺 **PDH:** ₹{pdh:,.2f} | 🔻 **PDL:** ₹{pdl:,.2f}")
    st.write(f"🔴 **R2:** ₹{R2:,.2f} | 🔴 **R1:** ₹{R1:,.2f}")
    st.success(f"🎯 **CPR:** ₹{BC:,.2f} - ₹{PP:,.2f} - ₹{TC:,.2f}")
    st.write(f"🟢 **S1:** ₹{S1:,.2f} | 🟢 **S2:** ₹{S2:,.2f}")
  with c2:
    st.subheader("Technical Indicators & News")
    st.write(
        f"🔹 **EMA 9:** ₹{ema9_val:,.2f} | 🔹 **EMA 21:** ₹{ema21_val:,.2f}"
    )
    st.write(f"🔹 **VWAP:** ₹{vwap_val:,.2f} | 🔹 **RSI (14):** {rsi_val:.2f}")
    for n in get_market_news():
      st.write(n)

  # Chart Section
  st.markdown("---")
  st.subheader("📈 NIFTY Intraday Chart - Price / VWAP / CPR")

  chart_data = pd.DataFrame({
      "Time": session_hist.index,
      "Close": session_hist["Close"].values,
      "VWAP": session_hist["VWAP"].values,
  }).dropna(subset=["Close"])
  chart_data = chart_data[chart_data["Close"] > 0].copy()

  if chart_data.empty:
    st.warning("Chart data unavailable.")
  else:
    c_start = chart_data["Time"].min()
    c_end = chart_data["Time"].max() + pd.Timedelta(minutes=25)
    l_x = chart_data["Time"].max() + pd.Timedelta(minutes=3)

    ldf = pd.DataFrame([
        {"Level": "PDH", "Value": pdh, "Color": "#cc0000", "LX": l_x},
        {"Level": "R1", "Value": R1, "Color": "#ff6666", "LX": l_x},
        {"Level": "TC", "Value": TC, "Color": "#66b3ff", "LX": l_x},
        {"Level": "Pivot", "Value": PP, "Color": "#0066cc", "LX": l_x},
        {"Level": "BC", "Value": BC, "Color": "#3399ff", "LX": l_x},
        {"Level": "S1", "Value": S1, "Color": "#66cc66", "LX": l_x},
        {"Level": "PDL", "Value": pdl, "Color": "#009900", "LX": l_x},
    ])

    all_v = [
        float(v)
        for v in (
            chart_data["Close"].tolist()
            + chart_data["VWAP"].dropna().tolist()
            + ldf["Value"].tolist()
        )
        if pd.notna(v) and np.isfinite(v) and (spot_price - 400) <= v <= (spot_price + 400)
    ]
    if all_v:
      mn, mx = min(all_v), max(all_v)
      pad = max(25.0, (mx - mn) * 0.10)
      y_min, y_max = float(mn - pad), float(mx + pad)
    else:
      y_min, y_max = float(spot_price - 250), float(spot_price + 250)

    x_scale = alt.Scale(domain=[c_start, c_end])
    y_scale = alt.Scale(
        domain=[y_min, y_max], clamp=True, zero=False, nice=False, padding=0
    )

    p_line = (
        alt.Chart(chart_data)
        .mark_line(color="#0052cc", strokeWidth=2.5)
        .encode(
            x=alt.X(
                "Time:T",
                title="Time (IST)",
                axis=alt.Axis(format="%H:%M", tickMinStep=300000),
                scale=x_scale,
            ),
            y=alt.Y("Close:Q", title="Price (₹)", scale=y_scale),
        )
    )

    v_line = (
        alt.Chart(chart_data.dropna(subset=["VWAP"]))
        .mark_line(color="#ff9900", strokeWidth=2.0, strokeDash=[3, 3])
        .encode(
            x=alt.X("Time:T", scale=x_scale),
            y=alt.Y("VWAP:Q", scale=y_scale),
        )
    )

    c_box = (
        alt.Chart(
            pd.DataFrame([{"_S": c_start, "_E": c_end, "_L": BC, "_U": TC}])
        )
        .mark_rect(color="#9ecae1", opacity=0.15)
        .encode(
            x=alt.X("_S:T", scale=x_scale),
            x2="_E:T",
            y=alt.Y("_L:Q", scale=y_scale),
            y2="_U:Q",
        )
    )

    rules = (
        alt.Chart(ldf)
        .mark_rule(strokeDash=[4, 4], strokeWidth=1.2)
        .encode(
            y=alt.Y("Value:Q", scale=y_scale),
            color=alt.Color("Color:N", scale=None, legend=None),
        )
    )

    lbls = (
        alt.Chart(ldf)
        .mark_text(align="left", dx=4, dy=-3, fontSize=10, fontWeight="bold")
        .encode(
            x=alt.X("LX:T", scale=x_scale),
            y=alt.Y("Value:Q", scale=y_scale),
            text="Level:N",
            color=alt.Color("Color:N", scale=None, legend=None),
        )
    )

    dot = (
        alt.Chart(chart_data.tail(1))
        .mark_point(color="#0052cc", filled=True, size=80, shape="circle")
        .encode(
            x=alt.X("Time:T", scale=x_scale),
            y=alt.Y("Close:Q", scale=y_scale),
        )
    )

    ltp = (
        alt.Chart(
            pd.DataFrame([{
                "Time": l_x,
                "Close": spot_price,
                "Label": f"LTP ₹{spot_price:,.2f}",
            }])
        )
        .mark_text(
            align="left",
            dx=4,
            dy=14,
            fontSize=11,
            fontWeight="bold",
            color="#cc0000",
        )
        .encode(
            x=alt.X("Time:T", scale=x_scale),
            y=alt.Y("Close:Q", scale=y_scale),
            text="Label:N",
        )
    )

    st.altair_chart(
        (c_box + rules + v_line + p_line + dot + lbls + ltp).properties(
            height=460
        ),
        use_container_width=True,
    )
    st.caption(
        "🔵 Price | 🟠 Session VWAP | 🔴 PDH/R1/R2 | 🔵 CPR (TC/Pivot/BC) | 🟢"
        " S1/S2/PDL | 🔴 LTP"
    )

except Exception as err:
  st.error(f"பிழை விவரம்: {err}")
  st.stop()
    
