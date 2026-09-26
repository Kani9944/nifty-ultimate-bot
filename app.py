import feedparser
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf

# App Config
st.set_page_config(page_title="Nifty Monitor & Strategy", layout="wide")
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


def close_paper_trade(trade_id, exit_price):
  for t in st.session_state.paper_trades:
    if t["id"] == trade_id and t["status"] == "OPEN":
      t["exit"], t["status"] = float(exit_price), "CLOSED"
      t["pnl"] = round((float(exit_price) - t["entry"]) * t["qty"], 2)
      break


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
      "https://tamil.goodreturns.in/rss/feeds/tamil-money-news-fb.xml",
      "https://www.moneycontrol.com/rss/marketreports.xml",
      "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
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
            news.append(f"🌐 [{t}]({l})" if l else f"🌐 {t}")
        if len(news) >= 6:
          break
    except Exception:
      continue
  return news[:6] if news else ["🌐 வர்த்தகச் செய்திகள் தற்காலிகமாக கிடைக்கவில்லை."]


try:
  hist = get_stock_data("^NSEI", "5d", "5m")
  daily = get_stock_data("^NSEI", "5d", "1d")
  bn_hist = get_stock_data("^NSEBANK", "2d", "5m")
  vix_hist = get_stock_data("^INDIAVIX", "2d", "5m")

  if hist.empty or daily.empty or len(daily) < 2:
    st.error("Nifty data கிடைக்கவில்லை.")
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
  session_date = (
      today if (hist.index.date == today).any() else hist.index[-1].date()
  )
  session_hist = hist[hist.index.date == session_date].copy()

  if session_hist.empty:
    st.error("Session data கிடைக்கவில்லை.")
    st.stop()

  spot_price = float(session_hist["Close"].iloc[-1])
  _, nifty_5m = get_last_bar_change(session_hist)

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
  R1, S1 = (2 * PP) - pdl, (2 * PP) - pdh
  R2, S2 = PP + (pdh - pdl), PP - (pdh - pdl)

  typ = (session_hist["High"] + session_hist["Low"] + session_hist["Close"]) / 3
  cv = session_hist["Volume"].cumsum()
  session_hist["VWAP"] = np.where(
      cv > 0, (typ * session_hist["Volume"]).cumsum() / cv, np.nan
  )
  if session_hist["VWAP"].isna().all():
    session_hist["VWAP"] = session_hist["Close"]

  bn_price, bn_5m = get_last_bar_change(bn_hist)
  vix_val, vix_5m = get_last_bar_change(vix_hist)

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

  # ========== 1. TOP METRICS (SIDE-BY-SIDE MOBILE VIEW) ==========
  nd_str = f"{nifty_5m:+.2f}%" if nifty_5m is not None else "0.00%"
  bd_str = f"{bn_5m:+.2f}%" if bn_5m is not None else "0.00%"
  vd_str = f"{vix_5m:+.2f}%" if vix_5m is not None else "0.00%"
  nc_color = "#00b300" if (nifty_5m or 0) >= 0 else "#cc0000"
  bc_color = "#00b300" if (bn_5m or 0) >= 0 else "#cc0000"
  vc_color = "#cc0000" if (vix_5m or 0) >= 0 else "#00b300"
  bn_val_str = f"₹{bn_price:,.2f}" if bn_price is not None else "N/A"
  vix_val_str = f"{vix_val:.2f}" if vix_val is not None else "N/A"

  st.write(
      """
    <div style="border: 1px solid #333; border-radius: 6px; padding: 8px; margin-bottom: 12px; font-family: monospace; background: #fff;">
        <div style="display: flex; border-bottom: 1px solid #333; padding-bottom: 6px;">
            <div style="flex: 1; padding: 4px; border-right: 1px solid #333;">
                <div style="font-size: 11px; color: #555;">NIFTY 50</div>
                <div style="font-size: 16px; font-weight: bold;">₹{:,.2f}</div>
                <div style="font-size: 11px; color: {};">{}</div>
            </div>
            <div style="flex: 1; padding: 4px; padding-left: 8px;">
                <div style="font-size: 11px; color: #555;">BANK NIFTY</div>
                <div style="font-size: 16px; font-weight: bold;">{}</div>
                <div style="font-size: 11px; color: {};">{}</div>
            </div>
        </div>
        <div style="border-bottom: 1px solid #333; padding: 6px 0; text-align: center;">
            <div style="font-size: 11px; color: #555;">INDIA VIX</div>
            <div style="font-size: 16px; font-weight: bold;">{}</div>
            <div style="font-size: 11px; color: {};">{}</div>
        </div>
        <div style="display: flex; padding-top: 6px;">
            <div style="flex: 1; padding: 4px; border-right: 1px solid #333;">
                <div style="font-size: 11px; color: #555;">PDH</div>
                <div style="font-size: 15px; font-weight: bold;">₹{:,.2f}</div>
            </div>
            <div style="flex: 1; padding: 4px; padding-left: 8px;">
                <div style="font-size: 11px; color: #555;">PDL</div>
                <div style="font-size: 15px; font-weight: bold;">₹{:,.2f}</div>
            </div>
        </div>
    </div>
    """.format(
          spot_price,
          nc_color,
          nd_str,
          bn_val_str,
          bc_color,
          bd_str,
          vix_val_str,
          vc_color,
          vd_str,
          pdh,
          pdl,
      ),
      unsafe_allow_html=True,
  )

  # ========== 2. LIVE INTRADAY STRATEGY ENGINE ==========
  st.markdown("---")
  st.subheader("⚡ நேரலை டிரேடிங் ஸ்ட்ராடஜி (Strategy Signal)")

  buy_conditions = [
      spot_price > TC,
      spot_price > vwap_val,
      ema9_val > ema21_val,
      rsi_val >= 55,
  ]
  sell_conditions = [
      spot_price < BC,
      spot_price < vwap_val,
      ema9_val < ema21_val,
      rsi_val <= 45,
  ]

  if all(buy_conditions):
    target = round(min(R1, spot_price + 60), 2)
    stoploss = round(max(BC, vwap_val - 15), 2)
    st.success(
        f"🟢 **BUY SIGNAL (Call Option சாதகம்)**\n\n- **காரணம்:** விலை CPR (TC)"
        f" மற்றும் VWAP-க்கு மேல் நிலைபெற்றுள்ளது. EMA 9 > EMA 21, RSI:"
        f" {rsi_val:.1f}\n- **என்ட்ரி:** ₹{spot_price:,.2f} | **இலக்கு:**"
        f" ₹{target:,.2f} | **ஸ்டாப்லாஸ்:** ₹{stoploss:,.2f}"
    )
  elif all(sell_conditions):
    target = round(max(S1, spot_price - 60), 2)
    stoploss = round(min(TC, vwap_val + 15), 2)
    st.error(
        f"🔴 **SELL SIGNAL (Put Option சாதகம்)**\n\n- **காரணம்:** விலை CPR (BC)"
        f" மற்றும் VWAP-க்கு கீழ் உள்ளது. EMA 9 < EMA 21, RSI:"
        f" {rsi_val:.1f}\n- **என்ட்ரி:** ₹{spot_price:,.2f} | **இலக்கு:**"
        f" ₹{target:,.2f} | **ஸ்டாப்லாஸ்:** ₹{stoploss:,.2f}"
    )
  elif spot_price > pdh and (spot_price - pdh) < 20 and rsi_val > 68:
    st.warning("⚠️ PDH Trap: Overbought-ல் ஏமாற்றுப் பிரேக்அவுட் சாத்தியம்.")
  else:
    st.info("⚖️ நோ-டிரேட் மண்டலம் (Range Bound): தெளிவான சிக்னல் வரை காத்திருக்கவும்.")

  # ========== 3. LIVE ALERTS ==========
  st.markdown("---")
  st.subheader("🔔 Live Alerts")
  alerts = []
  if pd.notna(ema9_val) and pd.notna(ema21_val):
    alerts.append(
        f"🟢 **EMA Bullish** — EMA 9 ({ema9_val:,.2f}) > EMA 21"
        f" ({ema21_val:,.2f})"
        if ema9_val > ema21_val
        else f"🔴 **EMA Bearish** — EMA 9 ({ema9_val:,.2f}) < EMA 21"
        f" ({ema21_val:,.2f})"
    )
  if pd.notna(vwap_val):
    alerts.append(
        f"🟢 **Above VWAP** — Price ({spot_price:,.2f}) > VWAP ({vwap_val:,.2f})"
        if spot_price > vwap_val
        else f"🔴 **Below VWAP** — Price ({spot_price:,.2f}) < VWAP"
        f" ({vwap_val:,.2f})"
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
  for a in alerts:
    st.markdown(f"- {a}")

  # ========== 4. TOP 5 GAINERS & LOSERS ==========
  st.markdown("---")
  st.subheader("Market Breadth - Nifty 50")
  breadth_stocks, _ = get_nifty50_breadth()
  if breadth_stocks:
    adv = sum(1 for s in breadth_stocks if s["Change%"] > 0.05)
    dec = sum(1 for s in breadth_stocks if s["Change%"] < -0.05)
    b1, b2, b3 = st.columns(3)
    b1.metric("Advances", adv)
    b2.metric("Declines", dec)
    b3.metric(
        "Avg Change",
        f"{sum(s['Change%'] for s in breadth_stocks)/len(breadth_stocks):+.2f}%",
    )

    ss = sorted(breadth_stocks, key=lambda x: x["Change%"], reverse=True)
    g_inner = "".join([
        f"<div style='border-bottom:1px solid #eee;"
        f" padding:3px;'><b>{s['Symbol']}</b><br>₹{s['LTP']:,.2f} <span"
        f" style='color:#00b300;'>(+{s['Change%']}%)</span></div>"
        for s in ss[:5]
    ])
    l_inner = "".join([
        f"<div style='border-bottom:1px solid #eee;"
        f" padding:3px;'><b>{s['Symbol']}</b><br>₹{s['LTP']:,.2f} <span"
        f" style='color:#cc0000;'>({s['Change%']}%)</span></div>"
        for s in ss[-5:][::-1]
    ])

    st.write(
        f"""
        <div style="border: 1px solid #333; border-radius: 6px; padding: 8px; font-family: monospace; background: #fff; margin-top: 8px;">
            <div style="display: flex;">
                <div style="flex: 1; padding: 4px; border-right: 1px solid #333;">
                    <div style="font-weight: bold; color: #00b300; margin-bottom: 6px;">🟢 Top 5 Gainers</div>
                    {g_inner}
                </div>
                <div style="flex: 1; padding: 4px; padding-left: 8px;">
                    <div style="font-weight: bold; color: #cc0000; margin-bottom: 6px;">🔴 Top 5 Losers</div>
                    {l_inner}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

  # ========== 5. SECTOR PERFORMANCE ==========
  st.markdown("---")
  st.subheader("Sector Performance")
  sec_data = get_sector_data()
  if sec_data:
    cols = st.columns(len(sec_data))
    for i, (name, pct) in enumerate(sec_data.items()):
      with cols[i]:
        st.success(f"{name}: +{pct:.2f}%") if pct >= 0 else st.error(
            f"{name}: {pct:.2f}%"
        )

  # ========== 6. OPTION CHAIN ==========
  st.markdown("---")
  st.subheader("Strike-wise Call vs Put (Estimated Model)")
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
      "📊 PCR",
      f"{pcr:.2f}",
      (
          "🟢 Bullish"
          if pcr > 1.2
          else ("🔴 Bearish" if pcr < 0.8 else "⚖️ Neutral")
      ),
  )
  pb.metric("🎯 ATM", f"₹{atm:,}")
  pc.metric("📍 Spot", f"₹{spot_price:,.2f}")
  st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

  # ========== 7. PAPER TRADING ==========
  st.markdown("---")
  st.subheader("📝 Model-based Paper Trading")
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
      submitted = st.form_submit_button("🚀 Place Model Trade")
    if submitted:
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
            "LTP": f"₹{cur_p if t['status']=='OPEN' else t['exit']}",
            "PnL": f"₹{pnl:+,.2f}",
            "Status": t["status"],
        })
      st.dataframe(pd.DataFrame(t_rows), hide_index=True)
      open_t = [
          t for t in st.session_state.paper_trades if t["status"] == "OPEN"
      ]
      if open_t:
        with st.form("close_trade_form"):
          c_id = st.selectbox("Close Trade ID", [t["id"] for t in open_t])
          closed = st.form_submit_button("❌ Close Trade")
        if closed:
          t_obj = next(t for t in open_t if t["id"] == c_id)
          c_ext = (
              round(
                  max(5.0, 180.0 + ((spot_price - t_obj["strike"]) / 50.0 * 45)),
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

  # ========== 8. CHART WITH CPR & ANALYSIS (PLOTLY LOCKED RANGE) ==========
  st.markdown("---")
  st.subheader("📈 NIFTY Intraday Chart - Price, VWAP & CPR அனாலிசிஸ்")
  cdf = session_hist[["Close", "VWAP"]].copy().dropna(subset=["Close"])
  if not cdf.empty:
    fig = go.Figure()

    # 1. Price Line
    fig.add_trace(
        go.Scatter(
            x=cdf.index,
            y=cdf["Close"],
            mode="lines",
            name="Nifty Price",
            line=dict(color="#0052cc", width=2.5),
        )
    )

    # 2. VWAP Line
    fig.add_trace(
        go.Scatter(
            x=cdf.index,
            y=cdf["VWAP"],
            mode="lines",
            name="VWAP",
            line=dict(color="#ff9900", width=1.8, dash="dash"),
        )
    )

    # 3. CPR & Pivots Analysis Lines
    fig.add_hline(
        y=TC,
        line_dash="dot",
        line_color="#66b3ff",
        annotation_text=f"TC: ₹{TC:,.0f}",
    )
    fig.add_hline(
        y=PP,
        line_dash="dash",
        line_color="#0066cc",
        annotation_text=f"Pivot
