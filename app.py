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
  elif v >= 100000:
    return f"{v/100000:.2f} L"
  elif v >= 1000:
    return f"{v/1000:.1f} K"
  return f"{v:,.0f}"


def get_last_bar_change(data):
  if data is None or len(data) < 2:
    return None, None
  curr, prev = float(data["Close"].iloc[-1]), float(data["Close"].iloc[-2])
  return curr, (((curr - prev) / prev) * 100 if prev != 0 else None)


def calculate_rsi(close, window=14):
  delta = close.diff()
  gains, losses = delta.clip(lower=0), -delta.clip(upper=0)
  avg_gain = gains.rolling(window=window, min_periods=window).mean()
  avg_loss = losses.rolling(window=window, min_periods=window).mean()
  rs = avg_gain / avg_loss
  rsi = 100.0 - (100.0 / (1.0 + rs))
  rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
  rsi = rsi.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
  return rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)


# ============ PAPER TRADING HELPERS ============
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
  t = yf.Ticker(symbol)
  return (
      t.history(period=period, interval=interval)
      if interval
      else t.history(period=period)
  )


@st.cache_data(ttl=120)
def get_nifty50_breadth():
  symbols = [
      "ADANIENT.NS",
      "ADANIPORTS.NS",
      "ASIANPAINT.NS",
      "AXISBANK.NS",
      "BAJAJ-AUTO.NS",
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
  for s in symbols:
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
    st.error("Session data கிடைக்கவில்லை.")
    st.stop()

  spot_price = float(session_hist["Close"].iloc[-1])
  _, nifty_5m_change = get_last_bar_change(session_hist)
  prev_sessions = daily[pd.Index(daily.index.date) < session_date]
  if prev_sessions.empty:
    st.error("Previous session data கிடைக்கவில்லை.")
    st.stop()

  prev_day = prev_sessions.iloc[-1]
  pdh, pdl, pdc = (
      float(prev_day["High"]),
      float(prev_day["Low"]),
      float(prev_day["Close"]),
  )

  PP = (pdh + pdl + pdc) / 3
  BC, TC = min((pdh + pdl) / 2, (2 * PP) - ((pdh + pdl) / 2)), max(
      (pdh + pdl) / 2, (2 * PP) - ((pdh + pdl) / 2)
  )
  R1, S1 = (2 * PP) - pdl, (2 * PP) - pdh
  R2, S2 = PP + (pdh - pdl), PP - (pdh - pdl)

  typical = (
      session_hist["High"] + session_hist["Low"] + session_hist["Close"]
  ) / 3
  cum_vol = session_hist["Volume"].cumsum()
  session_hist["VWAP"] = np.where(
      cum_vol > 0, (typical * session_hist["Volume"]).cumsum() / cum_vol, np.nan
  )
  if session_hist["VWAP"].isna().all():
    session_hist["VWAP"] = session_hist["Close"]

  bn_price, bn_5m_change = get_last_bar_change(bn_hist)
  vix_val, vix_5m_change = get_last_bar_change(vix_hist)

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

  # ============ TOP METRICS ============
  m1, m2, m3, m4, m5 = st.columns(5)
  m1.metric(
      "NIFTY 50",
      f"₹{spot_price:,.2f}",
      (
          f"{nifty_5m_change:+.2f}% (5m)"
          if nifty_5m_change is not None
          else None
      ),
  )
  m2.metric(
      "BANK NIFTY",
      f"₹{bn_price:,.2f}" if bn_price is not None else "N/A",
      f"{bn_5m_change:+.2f}% (5m)" if bn_5m_change is not None else None,
  )
  m3.metric(
      "INDIA VIX",
      f"{vix_val:.2f}" if vix_val is not None else "N/A",
      f"{vix_5m_change:+.2f}% (5m)" if vix_5m_change is not None else None,
      delta_color="inverse",
  )
  m4.metric("PDH", f"₹{pdh:,.2f}")
  m5.metric("PDL", f"₹{pdl:,.2f}")

  # ============ LIVE ALERTS ============
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
        f"🚨 **Elevated VIX** — {vix_val:.2f}; intraday price swings"
        " அதிகரிக்கலாம்."
    )

  if alerts:
    for a in alerts:
      st.markdown(f"- {a}")
  else:
    st.caption("No active technical alerts at the moment.")

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

    sorted_stocks = sorted(
        breadth_stocks, key=lambda x: x["Change%"], reverse=True
    )
    g_col, l_col = st.columns(2)
    with g_col:
      st.markdown("### Top 5 Gainers")
      for s in sorted_stocks[:5]:
        st.write(f"**{s['Symbol']}**: ₹{s['LTP']:,.2f} ({s['Change%']:+.2f}%)")
    with l_col:
      st.markdown("### Top 5 Losers")
      for s in sorted_stocks[-5:][::-1]:
        st.write(f"**{s['Symbol']}**: ₹{s['LTP']:,.2f} ({s['Change%']:+.2f}%)")

  # ============ SECTOR PERFORMANCE ============
  st.markdown("---")
  st.subheader("Sector Performance")
  sector_data = get_sector_data()
  if sector_data:
    cols = st.columns(len(sector_data))
    for i, (name, pct) in enumerate(sector_data.items()):
      with cols[i]:
        st.success(f"{name}: +{pct:.2f}%") if pct >= 0 else st.error(
            f"{name}: {pct:.2f}%"
        )

  # ============ OPTION CHAIN ============
  st.markdown("---")
  st.subheader("Strike-wise Call vs Put (Estimated Model)")
  st.caption(
      "⚠️ **குறிப்பு:** இது நேரடி NSE Option Chain தரவு அல்ல. இதில் உள்ள OI,"
      " LTP, மற்றும் PCR மதிப்புகள் ஸ்பாட் விலையைக் கொண்டு உருவாக்கப்பட்ட மாதிரி"
      " அனாலிசிஸ் (Illustrative Model) மட்டுமே."
  )

  atm = int(round(spot_price / 50) * 50)
  strike_range = [atm + (i * 50) for i in range(-2, 3)]
  rows = []
  tot_call, tot_put = 0, 0

  for s in strike_range:
    dist = abs(spot_price - s)
    call_oi, put_oi = int(max(1500000, 4500000 - (dist * 9000))), int(
        max(1400000, 5200000 - (dist * 8500))
    )
    diff = (spot_price - s) / 50.0
    c_ltp, p_ltp = round(max(5.0, 180.0 + (diff * 45)), 2), round(
        max(5.0, 175.0 - (diff * 45)), 2
    )
    tot_call += call_oi
    tot_put += put_oi
    sig = (
        "🟢 Put Support"
        if put_oi > call_oi * 1.15
        else ("🔴 Call Resistance" if call_oi > put_oi * 1.15 else "⚖️ Neutral")
    )
    rows.append({
        "Strike": f"₹{s:,}" + (" 🎯 ATM" if s == atm else ""),
        "Call OI": format_lakhs(call_oi),
        "Call Chg": format_lakhs(int(call_oi * 0.08)),
        "Call LTP": f"₹{c_ltp}",
        "Put LTP": f"₹{p_ltp}",
        "Put Chg": format_lakhs(int(put_oi * 0.06)),
        "Put OI": format_lakhs(put_oi),
        "Signal": sig,
    })

  pcr_val = tot_put / tot_call if tot_call > 0 else 0
  pa, pb, pc = st.columns(3)
  pa.metric(
      "📊 Model PCR",
      f"{pcr_val:.2f}",
      (
          "🟢 Bullish"
          if pcr_val > 1.2
          else ("🔴 Bearish" if pcr_val < 0.8 else "⚖️ Neutral")
      ),
  )
  pb.metric("🎯 Model ATM Reference", f"₹{atm:,}")
  pc.metric("📍 Nifty Spot", f"₹{spot_price:,.2f}")

  opt_df = pd.DataFrame(rows)
  st.dataframe(opt_df, hide_index=True, use_container_width=True)
  st.download_button(
      "📥 Download Option Model CSV",
      opt_df.to_csv(index=False).encode("utf-8"),
      "nifty_option_model.csv",
      "text/csv",
  )

  # ============ MODEL-BASED PAPER TRADING ============
  st.markdown("---")
  st.subheader("📝 Model-based Paper Trading")
  st.caption(
      "⚠️ **Model Notice:** Premium மற்றும் Open P&L அனைத்தும் ஸ்பாட் விலையை"
      " அடிப்படையாகக் கொண்ட மாதிரி கணக்கீடுகள் மட்டுமே."
  )
  pt_col1, pt_col2 = st.columns([1, 2])

  with pt_col1:
    with st.form("open_paper_trade_form"):
      pt_strike = st.selectbox(
          "Strike", [atm + (i * 50) for i in range(-2, 3)], index=2
      )
      pt_type = st.radio("Type", ["CE", "PE"], horizontal=True)
      lot_size = st.number_input(
          "Lot Size (units)", min_value=1, value=25, step=1
      )
      lots = st.number_input("Number of Lots", min_value=1, value=1, step=1)
      pt_qty = int(lot_size * lots)
      est_price = (
          round(max(5.0, 180.0 + ((spot_price - pt_strike) / 50.0 * 45)), 2)
          if pt_type == "CE"
          else round(
              max(5.0, 175.0 - ((spot_price - pt_strike) / 50.0 * 45)), 2
          )
      )
      st.write(
          f"Model Premium: **₹{est_price:,.2f}** | Total Units: **{pt_qty}**"
      )
      place_trade = st.form_submit_button("🚀 Place Model Trade")

    if place_trade:
      add_paper_trade(pt_strike, pt_type, est_price, pt_qty)
      st.success(f"Added {pt_strike} {pt_type} virtual trade.")
      st.rerun()

  with pt_col2:
    if st.session_state.paper_trades:
      trade_rows = []
      for t in st.session_state.paper_trades:
        curr_p = (
            round(
                max(5.0, 180.0 + ((spot_price - t["strike"]) / 50.0 * 45)), 2
            )
            if t["type"] == "CE"
            else round(
                max(5.0, 175.0 - ((spot_price - t["strike"]) / 50.0 * 45)), 2
            )
        )
        live_pnl = (
            round((curr_p - t["entry"]) * t["qty"], 2)
            if t["status"] == "OPEN"
            else t["pnl"]
        )
        trade_rows.append({
            "ID": t["id"],
            "Trade": f"{t['strike']} {t['type']}",
            "Entry": f"₹{t['entry']}",
            "Qty": t["qty"],
            "LTP/Exit": f"₹{curr_p if t['status'] == 'OPEN' else t['exit']}",
            "PnL": f"₹{live_pnl:+,.2f}",
            "Status": t["status"],
        })
      st.dataframe(pd.DataFrame(trade_rows), hide_index=True)

      open_trades = [
          t for t in st.session_state.paper_trades if t["status"] == "OPEN"
      ]
      if open_trades:
        with st.form("close_paper_trade_form"):
          close_id = st.selectbox(
              "Select Open Trade to Close", [t["id"] for t in open_trades]
          )
          close_submit = st.form_submit_button("❌ Close Selected Trade")
        if close_submit:
          t_obj = next(t for t in open_trades if t["id"] == close_id)
          c_exit = (
              round(
                  max(
                      5.0, 180.0 + ((spot_price - t_obj["strike"]) / 50.0 * 45)
                  ),
                  2,
              )
              if t_obj["type"] == "CE"
              else round(
                  max(
                      5.0, 175.0 - ((spot_price - t_obj["strike"]) / 50.0 * 45)
                  ),
                  2,
              )
          )
          close_paper_trade(close_id, c_exit)
          st.rerun()
    else:
      st.info("No active paper trades. Place a trade from the left panel.")

  # ============ LIQUIDITY & CPR ============
  st.markdown("---")
  c1, c2 = st.columns(2)
  with c1:
    st.subheader("Liquidity & Trap Zones")
    st.write(f"🔺 **PDH:** ₹{pdh:,.2f} | 🔻 **PDL:** ₹{pdl:,.2f}")
    st.markdown("---")
    st.subheader("CPR & Pivots")
    st.write(f"🔴 **R2:** ₹{R2:,.2f} | 🔴 **R1:** ₹{R1:,.2f}")
    st.success(f"🎯 **CPR:** ₹{BC:,.2f} - ₹{PP:,.2f} - ₹{TC:,.2f}")
    st.write(f"🟢 **S1:** ₹{S1:,.2f} | 🟢 **S2:** ₹{S2:,.2f}")

  with c2:
    st.subheader("Technical Indicators")
    st.write(
        f"🔹 **EMA 9:** ₹{ema9_val:,.2f} | 🔹 **EMA 21:** ₹{ema21_val:,.2f}"
    )
    st.write(f"🔹 **VWAP:** ₹{vwap_val:,.2f} | 🔹 **RSI (14):** {rsi_val:.2f}")
    st.markdown("---")
    st.subheader("🌐 நேரலை சந்தை செய்திகள் (Tamil News)")
    for n in get_market_news():
      st.write(n)

  # ============ CHART (COMPACT & ROBUST) ============
  st.markdown("---")
  st.subheader("📈 NIFTY Intraday Chart - Price / VWAP / CPR")

  chart_df = session_hist[["Close", "VWAP"]].copy()
  chart_df["Time"] = chart_df.index
  chart_df = (
      chart_df.replace([np.inf, -np.inf], np.nan)
      .dropna(subset=["Close"])
      .reset_index(drop=True)
  )
  chart_df = chart_df[chart_df["Close"] > 0]

  if chart_df.empty:
    st.warning("Chart data unavailable.")
    st.stop()

  vwap_df = chart_df.dropna(subset=["VWAP"])
  chart_start, chart_end = chart_df["Time"].min(), chart_df[
      "Time"
  ].max() + pd.Timedelta(minutes=25)
  label_x_pos = chart_df["Time"].max() + pd.Timedelta(minutes=3)

  levels_data = pd.DataFrame([
      {
          "Level": "PDH",
          "Value": float(pdh),
          "Color": "#cc0000",
          "LabelX": label_x_pos,
      },
      {
          "Level": "R1",
          "Value": float(R1),
          "Color": "#ff6666",
          "LabelX": label_x_pos,
      },
      {
          "Level": "TC",
          "Value": float(TC),
          "Color": "#66b3ff",
          "LabelX": label_x_pos,
      },
      {
          "Level": "Pivot",
          "Value": float(PP),
          "Color": "#0066cc",
          "LabelX": label_x_pos,
      },
      {
          "Level": "BC",
          "Value": float(BC),
          "Color": "#3399ff",
          "LabelX": label_x_pos,
      },
      {
          "Level": "S1",
          "Value": float(S1),
          "Color": "#66cc66",
          "LabelX": label_x_pos,
      },
      {
          "Level": "PDL",
          "Value": float(pdl),
          "Color": "#009900",
          "LabelX": label_x_pos,
      },
  ])

  all_key_values = (
      chart_df["Close"].tolist()
      + vwap_df["VWAP"].tolist()
      + levels_data["Value"].tolist()
  )
  valid_vals = [
      float(v)
      for v in all_key_values
      if pd.notna(v)
      and np.isfinite(v)
      and (spot_price - 400) <= v <= (spot_price + 400)
  ]

  if valid_vals:
    raw_min, raw_max = min(valid_vals), max(valid_vals)
    chart_pad = max(25.0, (raw_max - raw_min) * 0.10)
    y_min, y_max = float(raw_min - chart_pad), float(raw_max + chart_pad)
  else:
    y_min, y_max = float(spot_price - 250), float(spot_price + 250)

  x_scale = alt.Scale(domain=[chart_start, chart_end])
  y_scale = alt.Scale(
      domain=[y_min, y_max], clamp=True, zero=False, nice=False, padding=0
  )

  price_line = (
      alt.Chart(chart_df)
      .mark_line(color="#0052cc", strokeWidth=2.5)
      .encode(
          x=alt.X(
              "Time:T",
       
