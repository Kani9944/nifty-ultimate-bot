import feedparser
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf

st.set_page_config(page_title="Nifty Monitor", layout="wide")
st_autorefresh(interval=30 * 1000, key="refresh")
st.title("NIFTY 50 - Smart Money & Market Monitor")


def format_lakhs(v):
  try:
    val = float(v)
    if val >= 10000000:
      return "{:.2f} Cr".format(val / 10000000)
    if val >= 100000:
      return "{:.2f} L".format(val / 100000)
    if val >= 1000:
      return "{:.1f} K".format(val / 1000)
    return "{:,.0f}".format(val)
  except Exception:
    return str(v)


def get_last_bar_change(data):
  if data is None or len(data) < 2:
    return None, None
  c = float(data["Close"].iloc[-1])
  p = float(data["Close"].iloc[-2])
  if p == 0:
    return c, None
  return c, ((c - p) / p) * 100


def calculate_rsi(close, window=14):
  delta = close.diff()
  gains = delta.clip(lower=0)
  losses = -delta.clip(upper=0)
  ag = gains.rolling(window=window, min_periods=window).mean()
  al = losses.rolling(window=window, min_periods=window).mean()
  rs = ag / al
  rsi = 100.0 - (100.0 / (1.0 + rs))
  rsi = rsi.mask((al == 0) & (ag > 0), 100.0)
  rsi = rsi.mask((ag == 0) & (al > 0), 0.0)
  return rsi.mask((ag == 0) & (al == 0), 50.0)


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
      t["status"] = "CLOSED"
      t["pnl"] = round((float(exit_price) - t["entry"]) * t["qty"], 2)
      break


@st.cache_data(ttl=25)
def get_stock_data(symbol, period, interval=None):
  t = yf.Ticker(symbol)
  if interval:
    return t.history(period=period, interval=interval)
  return t.history(period=period)


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
  if stocks:
    return stocks, None
  return None, "Unavailable"


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
          t = e.get("title", "").strip()
          l = e.get("link", "")
          if t:
            if l:
              news.append("- [" + t + "](" + l + ")")
            else:
              news.append("- " + t)
        if len(news) >= 6:
          break
    except Exception:
      continue
  if news:
    return news[:6]
  return ["- வர்த்தக செய்திகள் தற்காலிகமாக கிடைக்கவில்லை."]


try:
  hist = get_stock_data("^NSEI", "5d", "5m")
  daily = get_stock_data("^NSEI", "5d", "1d")
  bn_hist = get_stock_data("^NSEBANK", "2d", "5m")
  vix_hist = get_stock_data("^INDIAVIX", "2d", "5m")
except Exception:
  st.error("Market data source unavailable. Try again.")
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
session_date = (
    today if (hist.index.date == today).any() else hist.index[-1].date()
)
session_hist = hist[hist.index.date == session_date].copy()

if session_hist.empty:
  st.error("Session data unavailable.")
  st.stop()

spot_price = float(session_hist["Close"].iloc[-1])
_, nifty_5m = get_last_bar_change(session_hist)

prev_sessions = daily[pd.Index(daily.index.date) < session_date]
if prev_sessions.empty:
  st.error("Previous session data unavailable.")
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
rsi_val = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50.0
vwap_val = (
    float(session_hist["VWAP"].iloc[-1])
    if pd.notna(session_hist["VWAP"].iloc[-1])
    else spot_price
)

# ===== 1. TOP METRICS =====
nd = "{:+.2f}%".format(nifty_5m) if nifty_5m is not None else ""
bd = "{:+.2f}%".format(bn_5m) if bn_5m is not None else ""
vd = "{:+.2f}%".format(vix_5m) if vix_5m is not None else ""
nc = "#00b300" if (nifty_5m or 0) >= 0 else "#cc0000"
bc = "#00b300" if (bn_5m or 0) >= 0 else "#cc0000"
vc = "#cc0000" if (vix_5m or 0) >= 0 else "#00b300"
bn_d = "Rs {:,.2f}".format(bn_price) if bn_price is not None else "N/A"
vix_d = "{:.2f}".format(vix_val) if vix_val is not None else "N/A"

st.markdown(
    '<div style="display:flex; gap:8px; margin-bottom:8px;"><div'
    ' style="flex:1; padding:10px; background:#f8f9fa; border-radius:8px;'
    ' border-left:4px solid #0052cc;"><div style="font-size:12px;'
    ' color:#666;">NIFTY 50</div><div style="font-size:20px;'
    ' font-weight:bold;">Rs {:,.2f}</div><div style="font-size:12px; color:'
    .format(spot_price)
    + nc
    + ';">'
    + nd
    + '</div></div><div style="flex:1; padding:10px; background:#f8f9fa;'
    ' border-radius:8px; border-left:4px solid #0052cc;"><div'
    ' style="font-size:12px; color:#666;">BANK NIFTY</div><div'
    ' style="font-size:20px; font-weight:bold;">'
    + bn_d
    + '</div><div style="font-size:12px; color:'
    + bc
    + ';">'
    + bd
    + '</div></div></div><div style="display:flex; justify-content:center;'
    ' margin-bottom:8px;"><div style="padding:10px 30px; background:#f8f9fa;'
    ' border-radius:8px; border-left:4px solid #ff9900; text-align:center;"><div'
    ' style="font-size:12px; color:#666;">INDIA VIX</div><div'
    ' style="font-size:20px; font-weight:bold;">'
    + vix_d
    + '</div><div style="font-size:12px; color:'
    + vc
    + ';">'
    + vd
    + '</div></div></div><div style="display:flex; gap:8px;"><div style="flex:1;'
    ' padding:10px; background:#f8f9fa; border-radius:8px; border-left:4px'
    ' solid #cc0000;"><div style="font-size:12px; color:#666;">PDH</div><div'
    ' style="font-size:18px; font-weight:bold;">Rs {:,.2f}</div></div>'.format(
        pdh
    )
    + '<div style="flex:1; padding:10px; background:#f8f9fa;'
    ' border-radius:8px; border-left:4px solid #00b300;"><div'
    ' style="font-size:12px; color:#666;">PDL</div><div style="font-size:18px;'
    ' font-weight:bold;">Rs {:,.2f}</div></div></div>'.format(pdl),
    unsafe_allow_html=True,
)

# ===== 2. RULE-BASED MARKET STRUCTURE =====
st.markdown("---")
st.subheader("Rule-based Market Structure")
st.caption("Rule-based technical alignment only; not a trading recommendation.")
buy_cond = [
    spot_price > TC,
    spot_price > vwap_val,
    ema9_val > ema21_val,
    rsi_val >= 55,
]
sell_cond = [
    spot_price < BC,
    spot_price < vwap_val,
    ema9_val < ema21_val,
    rsi_val <= 45,
]
if all(buy_cond):
  st.success("Bullish alignment: price above TC/VWAP, EMA 9 > EMA 21, RSI >= 55.")
elif all(sell_cond):
  st.error("Bearish alignment: price below BC/VWAP, EMA 9 < EMA 21, RSI <= 45.")
else:
  st.info("Mixed conditions: no clear technical alignment.")
st.caption(
    "Reference: BC Rs {:,.2f} | TC Rs {:,.2f} | R1 Rs {:,.2f} | S1 Rs"
    " {:,.2f}".format(BC, TC, R1, S1)
)

# ===== 3. LIVE ALERTS =====
st.markdown("---")
st.subheader("Live Alerts")
alerts = []
if pd.notna(ema9_val) and pd.notna(ema21_val):
  if ema9_val > ema21_val:
    alerts.append("EMA Bullish - EMA 9 > EMA 21")
  else:
    alerts.append("EMA Bearish - EMA 9 < EMA 21")
if pd.notna(vwap_val):
  if spot_price > vwap_val:
    alerts.append("Above VWAP")
  else:
    alerts.append("Below VWAP")
if pd.notna(rsi_val):
  if rsi_val >= 70:
    alerts.append("RSI Overbought ({:.1f})".format(rsi_val))
  elif rsi_val <= 30:
    alerts.append("RSI Oversold ({:.1f})".format(rsi_val))
if spot_price > pdh:
  alerts.append("PDH Breakout")
elif spot_price < pdl:
  alerts.append("PDL Breakdown")
if alerts:
  for a in alerts:
    st.markdown("- " + a)
else:
  st.caption("No active alerts.")

# ===== 4. MARKET BREADTH =====
st.markdown("---")
st.subheader("Market Breadth - Nifty 50 Watchlist")
st.caption("18 Nifty heavyweight stocks.")
breadth_stocks, _ = get_nifty50_breadth()
if breadth_stocks:
  adv = sum(1 for s in breadth_stocks if s["Change%"] > 0.05)
  dec = sum(1 for s in breadth_stocks if s["Change%"] < -0.05)
  avg_c = sum(s["Change%"] for s in breadth_stocks) / len(breadth_stocks)
  b1, b2, b3 = st.columns(3)
  b1.metric("Advances", adv)
  b2.metric("Declines", dec)
  b3.metric("Avg Change", "{:+.2f}%".format(avg_c))
  ss = sorted(breadth_stocks, key=lambda x: x["Change%"], reverse=True)
  g_html = "".join([
      '<div style="border-bottom:1px solid #eee; padding:3px;"><b>'
      + s["Symbol"]
      + "</b><br>Rs {:,.2f} <span style=\"color:#00b300;\">({:+.2f}%)</span></div>"
      .format(s["LTP"], s["Change%"])
      for s in ss[:5]
  ])
  l_html = "".join([
      '<div style="border-bottom:1px solid #eee; padding:3px;"><b>'
      + s["Symbol"]
      + "</b><br>Rs {:,.2f} <span style=\"color:#cc0000;\">({:+.2f}%)</span></div>"
      .format(s["LTP"], s["Change%"])
      for s in ss[-5:][::-1]
  ])
  st.markdown(
      '<div style="display:flex; gap:10px;"><div style="flex:1;"><div'
      ' style="font-weight:bold; color:#00b300;">Top 5 Gainers</div>'
      + g_html
      + '</div><div style="flex:1;"><div style="font-weight:bold;'
      ' color:#cc0000;">Top 5 Losers</div>'
      + l_html
      + "</div></div>",
      unsafe_allow_html=True,
  )

# ===== 5. SECTOR PERFORMANCE =====
st.markdown("---")
st.subheader("Sector Performance")
sec_data = get_sector_data()
if sec_data:
  cols = st.columns(len(sec_data))
  for i, (name, pct) in enumerate(sec_data.items()):
    with cols[i]:
      if pct >= 0:
        st.success("{}: +{:.2f}%".format(name, pct))
      else:
        st.error("{}: {:.2f}%".format(name, pct))

# ===== 6. OPTION CHAIN =====
st.markdown("---")
st.subheader("Strike-wise Call vs Put (Estimated Model)")
st.caption("Illustrative model only; not real NSE OI.")
atm = int(round(spot_price / 50) * 50)
rows = []
tot_call = 0
tot_put = 0
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
    sig = "Put Support"
  elif c_oi > p_oi * 1.15:
    sig = "Call Resistance"
  else:
    sig = "Neutral"
  slbl = "Rs {:,}".format(s)
  if s == atm:
    slbl += " (ATM)"
  rows.append({
      "Strike": slbl,
      "Call OI": format_lakhs(c_oi),
      "Call LTP": "Rs {}".format(c_ltp),
      "Put LTP": "Rs {}".format(p_ltp),
      "Put OI": format_lakhs(p_oi),
      "Signal": sig,
  })
pcr = tot_put / tot_call if tot_call > 0 else 0
pa, pb, pc = st.columns(3)
if pcr > 1.2:
  pa.metric("PCR", "{:.2f}".format(pcr), "Bullish")
elif pcr < 0.8:
  pa.metric("PCR", "{:.2f}".format(pcr), "Bearish")
else:
  pa.metric("PCR", "{:.2f}".format(pcr), "Neutral")
pb.metric("ATM", "Rs {:,}".format(atm))
pc.metric("Spot", "Rs {:,.2f}".format(spot_price))
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

# ===== 7. PAPER TRADING =====
st.markdown("---")
st.subheader("Model-based Paper Trading")
st.caption("Virtual only - no real orders.")
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
    if pt_type == "CE":
      est_p = round(
          max(5.0, 180.0 + ((spot_price - pt_strike) / 50.0 * 45)), 2
      )
    else:
      est_p = round(
          max(5.0, 175.0 - ((spot_price - pt_strike) / 50.0 * 45)), 2
      )
    st.write("Model Premium: Rs {:,.2f} | Units: {}".format(est_p, pt_qty))
    submitted = st.form_submit_button("Place Model Trade")
  if submitted:
    add_paper_trade(pt_strike, pt_type, est_p, pt_qty)
    st.rerun()
with p_col2:
  if st.session_state.paper_trades:
    t_rows = []
    for t in st.session_state.paper_trades:
      if t["type"] == "CE":
        cur_p = round(
            max(5.0, 180.0 + ((spot_price - t["strike"]) / 50.0 * 45)), 2
        )
      else:
        cur_p = round(
            max(5.0, 175.0 - ((spot_price - t["strike"]) / 50.0 * 45)), 2
        )
      if t["status"] == "OPEN":
        pnl = round((cur_p - t["entry"]) * t["qty"], 2)
        ltp_disp = "Rs {}".format(cur_p)
      else:
        pnl = t["pnl"]
        ltp_disp = "Rs {}".format(t["exit"])
      t_rows.append({
          "ID": t["id"],
          "Trade": "{} {}".format(t["strike"], t["type"]),
          "Entry": "Rs {}".format(t["entry"]),
          "Qty": t["qty"],
          "LTP": ltp_disp,
          "PnL": "Rs {:+,.2f}".format(pnl),
          "Status": t["status"],
      })
    st.dataframe(pd.DataFrame(t_rows), hide_index=True)
    open_t = [t for t in st.session_state.paper_trades if t["status"] == "OPEN"]
    if open_t:
      with st.form("close_trade_form"):
        c_id = st.selectbox("Close Trade ID", [t["id"] for t in open_t])
        closed = st.form_submit_button("Close Trade")
      if closed:
        t_obj = next(t for t in open_t if t["id"] == c_id)
        if t_obj["type"] == "CE":
          c_ext = round(
              max(5.0, 180.0 + ((spot_price - t_obj["strike"]) / 50.0 * 45)),
              2,
          )
        else:
          c_ext = round(
              max(5.0, 175.0 - ((spot_price - t_obj["strike"]) / 50.0 * 45)),
              2,
          )
        close_paper_trade(c_id, c_ext)
        st.rerun()
  else:
    st.info("No active trades.")

# ===== 8. CHART =====
st.markdown("---")
st.subheader("NIFTY Intraday Chart - Price & VWAP")
cdf = session_hist[["Close", "VWAP"]].copy().dropna(subset=["Close"])

if not cdf.empty:
  cv_vals = (
      list(cdf["Close"].dropna())
      + list(cdf["VWAP"].dropna())
      + [pdh, pdl, R1, S1, TC, BC, PP]
  )
  valid = [
      float(v)
      for v in cv_vals
      if pd.notna(v)
      and np.isfinite(v)
      and (spot_price - 400) <= float(v) <= (spot_price + 400)
  ]
  if valid:
    lo = min(valid)
    hi = max(valid)
    pad = max(25.0, (hi - lo) * 0.10)
    y_range = [lo - pad, hi + pad]
  else:
    y_range = [spot_price - 250, spot_price + 250]

  t0 = cdf.index[0]
  t1 = cdf.index[-1]

  fig = go.Figure()
  fig.add_hrect(
      y0=BC,
      y1=TC,
      fillcolor="LightSkyBlue",
      opacity=0.15,
      line_width=0,
      layer="below",
  )
  fig.add_trace(
      go.Scatter(
          x=cdf.index,
          y=cdf["Close"],
          mode="lines",
          name="Price",
          line=dict(color="#0052cc", width=2.5),
      )
  )
  fig.add_trace(
      go.Scatter(
          x=cdf.index,
          y=cdf["VWAP"],
          mode="lines",
          name="VWAP",
          line=dict(color="#ff9900", width=1.8, dash="dash"),
      )
  )
  fig.add_trace(
      go.Scatter(
          x=[t0, t1],
          y=[TC, TC],
          mode="lines",
          name="TC",
          line=dict(color="#66b3ff", width=1, dash="dot"),
      )
  )
  fig.add_trace(
      go.Scatter(
          x=[t0, t1],
          y=[BC, BC],
          mode="lines",
          name="BC",
          line=dict(color="#3399ff", width=1, dash="dot"),
      )
  )
  fig.add_trace(
      go.Scatter(
          x=[t0, t1],
          y=[PP, PP],
          mode="lines",
          name="Pivot",
          line=dict(color="#0066cc", width=1, dash="dash"),
      )
  )
  fig.add_trace(
      go.Scatter(
          x=[t0, t1],
          y=[pdh, pdh],
          mode="lines",
          name="PDH",
          line=dict(color="#cc0000", width=1),
      )
  )
  fig.add_trace(
      go.Scatter(
          x=[t0, t1],
          y=[pdl, pdl],
          mode="lines",
          name="PDL",
          line=dict(color="#00b300", width=1),
      )
  )
  fig.update_layout(
      height=450,
      margin=dict(l=10, r=10, t=35, b=45),
      legend=dict(orientation="h", y=-0.18),
      xaxis_title="Time (IST)",
      yaxis=dict(title="Price (Rs)", range=y_range, fixedrange=False),
      hovermode="x unified",
  )
  st.plotly_chart(fig, use_container_width=True)

  st.markdown("### Key Pivots & Levels")
  lvl_tbl = pd.DataFrame([
      {"Level": "PDH", "Price": "Rs {:,.2f}".format(pdh), "Zone": "Resistance"},
      {
          "Level": "R2",
          "Price": "Rs {:,.2f}".format(R2),
          "Zone": "Major Resistance",
      },
      {
          "Level": "R1",
          "Price": "Rs {:,.2f}".format(R1),
          "Zone": "Immediate Resistance"
