import altair as alt
import feedparser
import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import ta
import yfinance as yf

# பக்க வடிவமைப்பு & தானியங்கி புதுப்பிப்பு
st.set_page_config(
    page_title="Nifty AI Pro - Monitoring Terminal", layout="wide"
)
st_autorefresh(interval=30 * 1000, key="nifty_pro_refresh")
st.title("🦅 NIFTY 50 - Smart Money & Market Monitor")


# கேச்சிங் முறைகள்
@st.cache_data(ttl=25)
def get_stock_data(symbol, period, interval=None):
  t = yf.Ticker(symbol)
  return (
      t.history(period=period, interval=interval)
      if interval
      else t.history(period=period)
  )


@st.cache_data(ttl=90)
def get_heavyweight_daily(symbol):
  return yf.Ticker(symbol).history(period="5d", interval="1d")


@st.cache_data(ttl=25)
def get_heavyweight_intraday(symbol):
  return yf.Ticker(symbol).history(period="1d", interval="5m")


# தமிழ் செய்திகள் ஃபீட்
@st.cache_data(ttl=300)
def get_market_news():
  fallback = ["📰 செய்திகள் தற்போது கிடைக்கவில்லை."]
  urls = [
      "https://www.dinamalar.com/rss.asp",
      "https://www.dinamani.com/rss/latest-news.xml",
      "https://tamil.oneindia.com/rss/feeds/tamil-news-fb.xml",
  ]
  news = []
  for u in urls:
    try:
      r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
      feed = feedparser.parse(r.content)
      for e in feed.entries[:3]:
        t, l = e.get("title", "").strip(), e.get("link", "")
        if t:
          news.append(f"📰 [{t}]({l})" if l else f"📰 {t}")
      if len(news) >= 5:
        break
    except Exception:
      continue
  return news[:5] if news else fallback


def get_autonomous_session_change(data):
  if data.empty:
    return None, None, None
  d = data.copy()
  d.index = pd.to_datetime(d.index)
  d.index = (
      d.index.tz_convert("Asia/Kolkata")
      if d.index.tz is not None
      else d.index.tz_localize("Asia/Kolkata")
  )
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
  d.index = (
      d.index.tz_convert("Asia/Kolkata")
      if d.index.tz is not None
      else d.index.tz_localize("Asia/Kolkata")
  )
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


# தரவு எடுத்தல்
try:
  hist = get_stock_data("^NSEI", "5d", "5m")
  daily_hist = get_stock_data("^NSEI", "5d", "1d")
  bn_hist = get_stock_data("^NSEBANK", "5d", "1d")
  vix_hist = get_stock_data("^INDIAVIX", "5d", "1d")
except Exception:
  st.error("Market data source அணுக முடியவில்லை.")
  st.stop()

if hist.empty or len(daily_hist) < 2:
  st.error("தேவையான சந்தைத் தரவுகள் கிடைக்கவில்லை.")
  st.stop()

try:
  hist.index = pd.to_datetime(hist.index)
  hist.index = (
      hist.index.tz_convert("Asia/Kolkata")
      if hist.index.tz is not None
      else hist.index.tz_localize("Asia/Kolkata")
  )
  daily_hist.index = pd.to_datetime(daily_hist.index)
  daily_hist.index = (
      daily_hist.index.tz_convert("Asia/Kolkata")
      if daily_hist.index.tz is not None
      else daily_hist.index.tz_localize("Asia/Kolkata")
  )

  today_ist = pd.Timestamp.now(tz="Asia/Kolkata").date()
  last_data_date = pd.Timestamp(hist.index[-1]).date()
  session_date = (
      today_ist if (hist.index.date == today_ist).any() else last_data_date
  )
  session_hist = hist[hist.index.date == session_date].copy()

  if session_hist.empty:
    st.error("Intraday data கிடைக்கவில்லை.")
    st.stop()

  spot_price = float(session_hist["Close"].iloc[-1])
  open_price = float(session_hist["Open"].iloc[0])

  prev_sessions = daily_hist[pd.Index(daily_hist.index.date) < session_date]
  if prev_sessions.empty:
    st.error("Daily reference data கிடைக்கவில்லை.")
    st.stop()

  prev_day = prev_sessions.iloc[-1]
  prev_ref_date = pd.Timestamp(prev_day.name).date()
  pdh, pdl, pdc = (
      float(prev_day["High"]),
      float(prev_day["Low"]),
      float(prev_day["Close"]),
  )
  change = spot_price - pdc
  pct_change = (change / pdc * 100) if pdc != 0 else 0.0
  gap_pts = open_price - pdc
  gap_pct = (gap_pts / pdc * 100) if pdc != 0 else 0.0

  st.caption(
      f"📍 **Active session:** {session_date.strftime('%d-%b-%Y')} | 🎯 **CPR"
      f" ref:** {prev_ref_date.strftime('%d-%b-%Y')} | ⏱️ **Last 5-min bar:**"
      f" {session_hist.index[-1].strftime('%d-%b-%Y %H:%M IST')}"
  )

  bn_curr, bn_chg, _ = get_autonomous_session_change(bn_hist)
  vix_curr, vix_chg, _ = get_autonomous_session_change(vix_hist)

  # CPR கணக்கீடு
  PP = (pdh + pdl + pdc) / 3
  BC = min((pdh + pdl) / 2, (2 * PP) - ((pdh + pdl) / 2))
  TC = max((pdh + pdl) / 2, (2 * PP) - ((pdh + pdl) / 2))
  cpr_w_pct = ((TC - BC) / PP * 100) if PP != 0 else 0.0
  R1, S1 = (2 * PP) - pdl, (2 * PP) - pdh
  R2, S2 = PP + (pdh - pdl), PP - (pdh - pdl)

  # VWAP
  tp = (session_hist["High"] + session_hist["Low"] + session_hist["Close"]) / 3
  v_cum = session_hist["Volume"].cumsum()
  session_hist["VWAP"] = np.where(
      v_cum > 0, (tp * session_hist["Volume"]).cumsum() / v_cum, np.nan
  )
  vwap_val = (
      float(session_hist["VWAP"].iloc[-1])
      if pd.notna(session_hist["VWAP"].iloc[-1])
      else spot_price
  )

  # Indicators
  hist["EMA9"] = ta.trend.ema_indicator(hist["Close"], window=9)
  hist["EMA21"] = ta.trend.ema_indicator(hist["Close"], window=21)
  hist["RSI"] = ta.momentum.rsi(hist["Close"], window=14)
  ema9_val, ema21_val, rsi_val = (
      float(hist["EMA9"].iloc[-1]),
      float(hist["EMA21"].iloc[-1]),
      float(hist["RSI"].iloc[-1]),
  )

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

  vwap_ok = (spot_price >= vwap_val) or (
      abs(spot_price - vwap_val) / vwap_val < 0.0001
  )
  score = sum([
      spot_price >= ema9_val,
      spot_price >= ema21_val,
      vwap_ok,
      rsi_val >= 50,
      pct_change >= 0,
  ])

  # தலைப்பு மெட்ரிக்ஸ்
  top1, top2 = st.columns([1.5, 1])
  with top1:
    m1, m2, m3 = st.columns(3)
    m1.metric("📊 NIFTY 50", f"₹{spot_price:,.2f}", f"{change:+,.2f} ({pct_change:+.2f}%)")
    if bn_curr:
      m2.metric("🏦 BANK NIFTY", f"₹{bn_curr:,.2f}", f"{bn_chg:+.2f}%")
    if vix_curr:
      m3.metric(
          "⚡ INDIA VIX", f"{vix_curr:.2f}", f"{vix_chg:+.2f}%", delta_color="inverse"
      )

  with top2:
    if score >= 4:
      st.success(f"🟢 **Structure Alignment: Bullish ({score}/5)**")
    elif score <= 1:
      st.error(f"🔴 **Structure Alignment: Bearish ({score}/5)**")
    else:
      st.warning(f"🟡 **Structure Alignment: Mixed ({score}/5)**")

  # அலர்ட் பார்
  g_col, v_col = st.columns(2)
  if gap_pts >= 40:
    g_col.success(f"🚀 **Gap-Up Open:** +{gap_pts:,.1f} pts ({gap_pct:+.2f}%)")
  elif gap_pts <= -40:
    g_col.error(f"🩸 **Gap-Down Open:** {gap_pts:,.1f} pts ({gap_pct:+.2f}%)")
  else:
    g_col.info(f"⚖️ **Normal Open:** {gap_pts:+,.1f} pts ({gap_pct:+.2f}%)")

  if vix_curr and vix_curr >= 18:
    v_col.error("🚨 **High Volatility (VIX > 18)**")
  elif vix_chg and vix_chg >= 4.0:
    v_col.warning("⚠️ **VIX Spike (+4%)**")
  else:
    v_col.info("🟢 **Normal Volatility**")

  # ஸ்ட்ரைக் அனாலிசிஸ்
  st.markdown("---")
  st.subheader(
      "🎯 Strike-wise Call vs Put (Estimated OI & Delta Model Analysis)"
  )
  atm = int(round(spot_price / 50) * 50)
  s_rows = []
  for s in [atm + (i * 50) for i in range(-2, 3)]:
    diff = (spot_price - s) / 50.0
    cd = round(float(np.clip(0.5 + (diff * 0.12), 0.10, 0.95)), 2)
    pd_val = round(float(cd - 1.0), 2)
    dist = abs(spot_price - s)
    c_vol, p_vol = int(max(250000, 1800000 - (dist * 8000))), int(
        max(220000, 1950000 - (dist * 7500))
    )
    c_oi, p_oi = int(max(1500000, 4500000 - (dist * 9000))), int(
        max(1400000, 5200000 - (dist * 8500))
    )
    s_rows.append({
        "Strike": f"₹{s:,} {'🎯 (ATM)' if s == atm else ''}",
        "Call OI": f"{c_oi:,}",
        "Call Delta Vol": f"{int(abs(cd * c_vol)):,}",
        "Call Delta": cd,
        "Put Delta": pd_val,
        "Put Delta Vol": f"{int(abs(pd_val * p_vol)):,}",
        "Put OI": f"{p_oi:,}",
        "Dominance": (
            "🟢 Put Support"
            if abs(pd_val * p_vol) > abs(cd * c_vol)
            else "🔴 Call Resistance"
        ),
    })
  st.dataframe(pd.DataFrame(s_rows), hide_index=True, use_container_width=True)

  # ஹெவிவெயிட்கள்
  st.markdown("---")
  st.subheader("🏢 Nifty Heavyweights Tracker")
  live_hw = st.toggle("Use 5-minute intraday heavyweights", value=False)
  heavy_syms = {
      "HDFC Bank": "HDFCBANK.NS",
      "Reliance": "RELIANCE.NS",
      "ICICI Bank": "ICICIBANK.NS",
      "Infosys": "INFY.NS",
      "TCS": "TCS.NS",
  }
  hw_cols = st.columns(5)
  for i, (name, sym) in enumerate(heavy_syms.items()):
    with hw_cols[i]:
      try:
        if live_hw:
          s_in, s_da = get_heavyweight_intraday(sym), get_heavyweight_daily(sym)
          if not s_in.empty:
            idx = pd.to_datetime(s_in.index)
            idx = (
                idx.tz_convert("Asia/Kolkata")
                if idx.tz is not None
                else idx.tz_localize("Asia/Kolkata")
            )
            c_price = float(s_in["Close"].iloc[-1])
            p_close = get_previous_close_for_session(s_da, idx[-1].date())
            chg = (
                ((c_price - p_close) / p_close * 100)
                if (p_close and p_close != 0)
                else 0.0
            )
            st.metric(label=name, value=f"₹{c_price:,.1f}", delta=f"{chg:+.2f}%")
        else:
          stk = get_heavyweight_daily(sym)
          if len(stk) >= 2:
            c_p, p_p = float(stk["Close"].iloc[-1]), float(stk["Close"].iloc[-2])
            chg = ((c_p - p_p) / p_p * 100) if p_p != 0 else 0.0
            st.metric(label=name, value=f"₹{c_p:,.1f}", delta=f"{chg:+.2f}%")
      except Exception:
        st.caption(f"{name}: N/A")

  # CPR & தொழில்நுட்ப நிலைகள்
  st.markdown("---")
  c1, c2 = st.columns(2)
  with c1:
    st.subheader("🎯 Liquidity & Trap Zones (PDH / PDL)")
    st.write(f"🔺 **PDH:** ₹{pdh:,.2f}  |  🔻 **PDL:** ₹{pdl:,.2f}")
    st.markdown("---")
    st.subheader("📌 Normalized CPR & Pivots")
    if cpr_w_pct < 0.20:
      st.success(f"🔥 **Narrow CPR ({cpr_w_pct:.2f}%):** Breakout சாத்தியம்.")
    elif cpr_w_pct > 0.35:
      st.warning(f"⚠️ **Wide CPR ({cpr_w_pct:.2f}%):** Range-bound சாத்தியம்.")
    else:
      st.info(f"⚖️ **Normal CPR ({cpr_w_pct:.2f}%)**")
    st.write(f"🔴 **R2:** ₹{R2:,.2f}  |  🔴 **R1:** ₹{R1:,.2f}")
    st.success(f"🎯 **CPR (BC-PP-TC):** ₹{BC:,.2f} - ₹{PP:,.2f} - ₹{TC:,.2f}")
    st.write(f"🟢 **S1:** ₹{S1:,.2f}  |  🟢 **S2:** ₹{S2:,.2f}")

  with c2:
    st.subheader("📈 Technical Indicators")
    st.write(f"🔹 **EMA 9:** ₹{ema9_val:,.2f} ➔ {trend_label(spot_price, ema9_val)}")
    st.write(
        f"🔹 **EMA 21:** ₹{ema21_val:,.2f} ➔ {trend_label(spot_price, ema21_val)}"
    )
    st.write(f"🔹 **VWAP:** ₹{vwap_val:,.2f} ➔ {trend_label(spot_price, vwap_val)}")
    st.write(f"🔹 **RSI (14):** {rsi_val:.2f} ➔ {rsi_status}")
    st.markdown("---")
    st.subheader("🌐 தமிழ் செய்திகள்")
    for n in get_market_news():
      st.write(n)

  # சார்ட்
  st.markdown("---")
  st.subheader(
      "📈 NIFTY 50 - Intraday Chart"
      + (
          ""
          if session_date == today_ist
          else f" ({session_date.strftime('%d-%b-%Y')})"
      )
  )

  cdf = session_hist[["Close", "VWAP"]].copy()
  cdf["Time"] = cdf.index
  cdf = cdf.reset_index(drop=True)
  if cdf["VWAP"].isna().all():
    cdf["VWAP"] = cdf["Close"]
    st.caption(
        "ℹ️ **VWAP Note:** Volume இல்லாததால் VWAP விலைக்கோட்டுடன் proxy-யாகக்"
        " காட்டப்படுகிறது."
    )

  c_start = cdf["Time"].min()
  c_end = cdf["Time"].max() + pd.Timedelta(minutes=16)

  ldf = pd.DataFrame([
      {"Level": "PDH", "Value": pdh, "Color": "#cc0000"},
      {"Level": "R1", "Value": R1, "Color": "#ff9999"},
      {"Level": "TC", "Value": TC, "Color": "#66b3ff"},
      {"Level": "Pivot", "Value": PP, "Color": "#0066cc"},
      {"Level": "BC", "Value": BC, "Color": "#66b3ff"},
      {"Level": "S1", "Value": S1, "Color": "#85e085"},
      {"Level": "PDL", "Value": pdl, "Color": "#009900"},
  ])
  ldf["Time"] = cdf["Time"].max() + pd.Timedelta(minutes=3)

  all_p = [
      p
      for p in (
          list(cdf["Close"])
          + list(cdf["VWAP"].dropna())
          + list(ldf["Value"])
      )
      if pd.notna(p) and p > 1000
  ]
  y_min, y_max = float(min(all_p) - 30), float(max(all_p) + 30)

  y_sc = alt.Scale(
      domain=[y_min, y_max],
      clamp=True,
      zero=False,
      nice=False,
      padding=0,
  )

  # சார்ட் லேயர்கள்
  cpr_box = pd.DataFrame(
      [{"_S": c_start, "_E": c_end, "_L": float(BC), "_U": float(TC)}]
  )
  cpr_b = (
      alt.Chart(cpr_box)
      .mark_rect(color="#9ecae1", opacity=0.18)
      .encode(
          x=alt.X("_S:T"),
          x2="_E:T",
          y=alt.Y("_L:Q", scale=y_sc),
          y2="_U:Q",
          tooltip=alt.value(None),
      )
  )

  rules = (
      alt.Chart(ldf)
      .mark_rule(strokeDash=[4, 4], strokeWidth=1.2)
      .encode(
          y=alt.Y("Value:Q", scale=y_sc),
          color=alt.Color("Color:N", scale=None, legend=None),
          tooltip=alt.value(None),
      )
  )

  labels = (
      alt.Chart(ldf)
      .mark_text(align="left", dx=8, dy=-4, fontSize=11, fontWeight="bold")
      .encode(
          x=alt.X("Time:T"),
          y=alt.Y("Value:Q", scale=y_sc),
          text=alt.Text("Level:N"),
          color=alt.Color("Color:N", scale=None, legend=None),
          tooltip=alt.value(None),
      )
  )

  ltp_df = pd.DataFrame([{
      "Time": cdf["Time"].max() + pd.Timedelta(minutes=3),
      "Price": spot_price,
      "Label": f"LTP ₹{spot_price:,.2f}",
  }])
  ltp_txt = (
      alt.Chart(ltp_df)
      .mark_text(
          align="left",
          dx=8,
          dy=22,
          fontSize=11,
          fontWeight="bold",
          color="#cc0000",
      )
      .encode(
          x=alt.X("Time:T"),
          y=alt.Y("Price:Q", scale=y_sc),
          text=alt.Text("Label:N"),
          tooltip=alt.value(None),
      )
  )

  vw_line = (
      alt.Chart(cdf.dropna(subset=["VWAP"]))
      .mark_line(color="#ff9900", strokeWidth=2.0, strokeDash=[4, 4])
      .encode(
          x=alt.X("Time:T"),
          y=alt.Y("VWAP:Q", scale=y_sc),
          tooltip=[
              alt.Tooltip("Time:T", format="%d-%b %H:%M"),
              alt.Tooltip("VWAP:Q", format=",.2f"),
          ],
      )
  )

  pt_dot = (
      alt.Chart(cdf.tail(1))
      .mark_point(color="#0052cc", filled=True, size=85, shape="circle")
      .encode(
          x=alt.X("Time:T"),
          y=alt.Y("Close:Q", scale=y_sc),
          tooltip=[
              alt.Tooltip("Time:T", format="%d-%b %H:%M"),
              alt.Tooltip("Close:Q", format=",.2f"),
          ],
      )
  )

  p_line = (
      alt.Chart(cdf)
      .mark_line(color="#0052cc", strokeWidth=2.5)
      .encode(
          x=alt.X(
              "Time:T",
              title="Time (IST)",
              axis=alt.Axis(format="%H:%M", tickCount=8),
              scale=alt.Scale(domain=[c_start, c_end]),
          ),
          y=alt.Y("Close:Q", title="Price (₹)", scale=y_sc),
          tooltip=[
              alt.Tooltip("Time:T", format="%d-%b %H:%M"),
              alt.Tooltip("Close:Q", format=",.2f"),
          ],
      )
  )

  final_chart = (
      (cpr_b + rules + vw_line + pt_dot + labels + ltp_txt + p_line)
      .resolve_scale(x="shared", y="shared")
      .properties(
          height=460, title="NIFTY Intraday Price, VWAP, CPR and Key Levels"
      )
  )

  st.altair_chart(final_chart, use_container_width=True)
  st.caption(
      "🔵 Price | 🟠 Session VWAP | 🔴 PDH/R1 | 🔵 CPR (TC/Pivot/BC) | 🟢 S1/PDL"
      " | 🔴 LTP"
  )

except Exception as e:
  st.error(f"Analysis pipeline-ல் பிழை: {e}")
  st.stop()
    
