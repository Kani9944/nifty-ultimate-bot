import altair as alt
import feedparser
import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import ta
import yfinance as yf

# பக்க வடிவமைப்பு & தானியங்கி புதுப்பிப்பு (30 விநாடிகள்)
st.set_page_config(
    page_title="Nifty AI Pro - Monitoring Terminal", layout="wide"
)
st_autorefresh(interval=30 * 1000, key="nifty_pro_refresh")
st.title("🦅 நிஃப்டி 50 - ஸ்மார்ட் மணி & மார்க்கெட் மானிட்டர்")


# எண்களை லட்சங்களில் காட்டும் முறை
def format_lakhs(val):
  if val is None or pd.isna(val):
    return "0.00L"
  return f"{val / 100000:,.2f}L"


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


# தமிழ் நேரலை வணிகச் செய்திகள்
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
      r = requests.get(feed_url, headers=headers, timeout=5)
      if r.status_code == 200:
        feed = feedparser.parse(r.content)
        for entry in feed.entries[:3]:
          title = entry.get("title", "").strip()
          link = entry.get("link", "")
          if not title:
            continue
          if link:
            all_news.append(f"📰 [{title}]({link})")
          else:
            all_news.append(f"📰 {title}")
        if len(all_news) >= 6:
          break
    except Exception:
      continue

  if all_news:
    return all_news[:6]
  return fallback


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
    return "⚪ போதிய தரவு இல்லை"
  if indicator == 0:
    return "⚪ கிடைக்கவில்லை"
  if abs((price - indicator) / indicator * 100) < 0.01:
    return "⚪ சமநிலை (At Par)"
  return "🟢 ஏற்றம் (Bullish)" if price > indicator else "🩸 இறக்கம் (Bearish)"


# சந்தைத் தரவுகள் எடுத்தல்
try:
  hist = get_stock_data("^NSEI", "5d", "5m")
  daily_hist = get_stock_data("^NSEI", "5d", "1d")
  bn_hist = get_stock_data("^NSEBANK", "5d", "1d")
  vix_hist = get_stock_data("^INDIAVIX", "5d", "1d")
except Exception:
  st.error("சந்தைத் தரவு மூலத்தை அணுக முடியவில்லை.")
  st.stop()

if hist.empty or len(daily_hist) < 2:
  st.error("தேவையான நிஃப்டி சந்தைத் தரவுகள் கிடைக்கவில்லை.")
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
    st.error("இன்ட்ராடே தரவுகள் கிடைக்கவில்லை.")
    st.stop()

  spot_price = float(session_hist["Close"].iloc[-1])
  open_price = float(session_hist["Open"].iloc[0])

  prev_sessions = daily_hist[pd.Index(daily_hist.index.date) < session_date]
  if prev_sessions.empty:
    st.error("முந்தைய நாள் ஒப்பீட்டுத் தரவுகள் கிடைக்கவில்லை.")
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
      f"📍 **செயலில் உள்ள அமர்வு:** {session_date.strftime('%d-%b-%Y')} | 🎯"
      f" **CPR ஒப்பீட்டு நாள்:** {prev_ref_date.strftime('%d-%b-%Y')} | ⏱️"
      " **கடைசி 5-நிமிட பார்:**"
      f" {session_hist.index[-1].strftime('%d-%b-%Y %H:%M IST')} | Yahoo Finance"
      " delayed feed."
  )

  bn_curr, bn_chg, _ = get_autonomous_session_change(bn_hist)
  vix_curr, vix_chg, _ = get_autonomous_session_change(vix_hist)
  vix_val = vix_curr

  # CPR கணக்கீடுகள்
  PP = (pdh + pdl + pdc) / 3
  bc_raw = (pdh + pdl) / 2
  tc_raw = (2 * PP) - bc_raw
  BC, TC = min(bc_raw, tc_raw), max(bc_raw, tc_raw)
  cpr_w_pct = ((TC - BC) / PP * 100) if PP != 0 else 0.0
  R1, S1 = (2 * PP) - pdl, (2 * PP) - pdh
  R2, S2 = PP + (pdh - pdl), PP - (pdh - pdl)

  # Session VWAP
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

  # தொழில்நுட்ப குறிகாட்டிகள்
  hist["EMA9"] = ta.trend.ema_indicator(hist["Close"], window=9)
  hist["EMA21"] = ta.trend.ema_indicator(hist["Close"], window=21)
  hist["RSI"] = ta.momentum.rsi(hist["Close"], window=14)
  ema9_val, ema21_val, rsi_val = (
      float(hist["EMA9"].iloc[-1]),
      float(hist["EMA21"].iloc[-1]),
      float(hist["RSI"].iloc[-1]),
  )

  if pd.isna(rsi_val):
    rsi_status = "⚪ போதிய தரவு இல்லை"
  elif rsi_val >= 70:
    rsi_status = "🚨 அதிக வாங்குதல் (>70 Overbought)"
  elif rsi_val >= 60:
    rsi_status = "🟢 ஏற்றச் சாய்வு (60-70 Bullish)"
  elif rsi_val <= 30:
    rsi_status = "🟢 அதிக விற்பனை (<30 Oversold)"
  elif rsi_val <= 40:
    rsi_status = "🩸 இறக்கச் சாய்வு (30-40 Bearish)"
  else:
    rsi_status = "⚖️ நடுநிலை மண்டலம் (40-60 Neutral)"

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
    m1.metric("📊 நிஃப்டி 50", f"₹{spot_price:,.2f}", f"{change:+,.2f} ({pct_change:+.2f}%)")
    if bn_curr:
      m2.metric("🏦 பேங்க் நிஃப்டி", f"₹{bn_curr:,.2f}", f"{bn_chg:+.2f}%")
    if vix_curr:
      m3.metric(
          "⚡ இந்தியா VIX", f"{vix_curr:.2f}", f"{vix_chg:+.2f}%", delta_color="inverse"
      )

  with top2:
    if score >= 4:
      st.success(
          f"🟢 **சந்தை கட்டமைப்பு: ஏற்றப் போக்கு (Bullish {score}/5)**\nதொழில்நுட்ப"
          " நிலைகள் மேல்நோக்கிய நகர்வுக்குச் சாதகமாக உள்ளன."
      )
    elif score <= 1:
      st.error(
          f"🔴 **சந்தை கட்டமைப்பு: இறக்கப் போக்கு (Bearish {score}/5)**\nவிற்பனை"
          " அழுத்தம் அதிகமாக உள்ளது."
      )
    else:
      st.warning(
          f"🟡 **சந்தை கட்டமைப்பு: சமநிலை (Mixed {score}/5)**\nதெளிவான"
          " பிரேக்அவுட் வரை காத்திருக்கவும்."
      )

  # கேப் & வாலட்டிலிட்டி பார்
  g_col, v_col = st.columns(2)
  if gap_pts >= 40:
    g_col.success(f"🚀 **கேப்-அப் துவக்கம்:** +{gap_pts:,.1f} புள்ளிகள் ({gap_pct:+.2f}%)")
  elif gap_pts <= -40:
    g_col.error(f"🩸 **கேப்-டவுன் துவக்கம்:** {gap_pts:,.1f} புள்ளிகள் ({gap_pct:+.2f}%)")
  else:
    g_col.info(f"⚖️ **சாதாரண துவக்கம்:** {gap_pts:+,.1f} புள்ளிகள் ({gap_pct:+.2f}%)")

  if vix_curr and vix_curr >= 18:
    v_col.error("🚨 **அதிக ஏற்ற இறக்கம் (VIX > 18):** Trailing Stoploss அவசியம்.")
  elif vix_chg and vix_chg >= 4.0:
    v_col.warning("⚠️ **VIX ஸ்பைக் (+4%):** ஹெட்ஜிங் வேகம் அதிகரித்துள்ளது.")
  else:
    v_col.info("🟢 **இயல்பான ஏற்ற இறக்கம்:** VIX அமைதியான வரம்பில் உள்ளது.")

  # ஸ்ட்ரைக் வாரியான பகுப்பாய்வு
  st.markdown("---")
  st.subheader("🎯 ஸ்ட்ரைக் வாரியான கால் vs புட் பகுப்பாய்வு (மாதிரி மதிப்பீடு)")
  atm = int(round(spot_price / 50) * 50)
  Rows = []
  tot_call = 0
  tot_put = 0

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

    ce = {
        "lastPrice": max(15.0, 180.0 + (diff * 45)),
        "changeinOpenInterest": int(call_oi * 0.08),
    }
    pe = {
        "lastPrice": max(15.0, 175.0 - (diff * 45)),
        "changeinOpenInterest": int(put_oi * 0.09),
    }
    signal = (
        "🟢 புட் ஆதரவு (Support)"
        if (put_oi * abs(pd_val)) > (call_oi * cd)
        else "🔴 கால் தடை (Resistance)"
    )

    Rows.append({
        "ஸ்ட்ரைக்": f"₹{strike:,}" + (" 🎯 ATM" if strike == atm else ""),
        "Call OI": format_lakhs(call_oi),
        "Call மாற்றம்": format_lakhs(ce.get("changeinOpenInterest", 0)),
        "Call LTP": f"₹{ce.get('lastPrice', 0):.2f}",
        "Put LTP": f"₹{pe.get('lastPrice', 0):.2f}",
        "Put மாற்றம்": format_lakhs(pe.get("changeinOpenInterest", 0)),
        "Put OI": format_lakhs(put_oi),
        "சிக்னல்": signal,
    })

  st.dataframe(pd.DataFrame(Rows), hide_index=True, use_container_width=True)

  # PCR மற்றும் Max Pain பகுப்பாய்வு
  pcr_val = tot_put / tot_call if tot_call > 0 else 0
  max_pain_strike = atm

  pa, pb, pc = st.columns(3)
  with pa:
    if pcr_val > 1.2:
      st.metric("PCR (OI)", f"{pcr_val:.2f}", "ஏற்றப் போக்கு (Bullish)")
    elif pcr_val < 0.8:
      st.metric("PCR (OI)", f"{pcr_val:.2f}", "இறக்கப் போக்கு (Bearish)")
    else:
      st.metric("PCR (OI)", f"{pcr_val:.2f}", "சமநிலை (Neutral)")
  with pb:
    st.metric("மேக்ஸ் பெயின் (Max Pain)", f"₹{max_pain_strike:,}")
  with pc:
    st.metric("ஸ்பாட் விலை (Spot)", f"₹{spot_price:,.2f}")

  # ஹெவிவெயிட்கள் கண்காணிப்பு
  st.markdown("---")
  st.subheader("🏢 நிஃப்டி முக்கிய பங்குகள் (Heavyweights Tracker)")
  live_hw = st.toggle("5-நிமிட இன்ட்ராடே விலையைப் பயன்படுத்து", value=False)
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
        st.caption(f"{name}: விவரமில்லை")

  # CPR & தொழில்நுட்ப நிலைகள்
  st.markdown("---")
  c1, c2 = st.columns(2)
  with c1:
    st.subheader("🎯 முக்கிய லிக்விடிட்டி நிலைகள் (PDH / PDL)")
    st.write(
        f"🔺 **நேற்றைய உச்சம் (PDH):** ₹{pdh:,.2f}  |  🔻 **நேற்றைய வீழ்ச்சி"
        f" (PDL):** ₹{pdl:,.2f}"
    )
    st.markdown("---")
    st.subheader("📌 CPR & Pivot நிலைகள்")
    if cpr_w_pct < 0.20:
      st.success(
          f"🔥 **குறுகிய CPR ({cpr_w_pct:.2f}% Narrow):** பெரிய பிரேக்அவுட்"
          " சாத்தியம்."
      )
    elif cpr_w_pct > 0.35:
      st.warning(
          f"⚠️ **அகன்ற CPR ({cpr_w_pct:.2f}% Wide):** குறிப்பிட்ட வரம்பிற்குள்"
          " (Range-bound) வர்த்தகம்."
      )
    else:
      st.info(f"⚖️ **சாதாரண CPR ({cpr_w_pct:.2f}% Normal):** சமநிலையான சந்தை.")
    st.write(f"🔴 **ரெசிஸ்டன்ஸ் 2 (R2):** ₹{R2:,.2f}")
    st.write(f"🔴 **ரெசிஸ்டன்ஸ் 1 (R1):** ₹{R1:,.2f}")
    st.success(
        f"🎯 **CPR மண்டலம் (BC-PP-TC):** ₹{BC:,.2f} - ₹{PP:,.2f} - ₹{TC:,.2f}"
    )
    st.write(f"🟢 **சப்போர்ட் 1 (S1):** ₹{S1:,.2f}")
    st.write(f"🟢 **சப்போர்ட் 2 (S2):** ₹{S2:,.2f}")

  with c2:
    st.subheader("📈 தொழில்நுட்ப குறிகாட்டிகள் (Indicators)")
    st.write(f"🔹 **EMA 9:** ₹{ema9_val:,.2f} ➔ {trend_label(spot_price, ema9_val)}")
    st.write(
        f"🔹 **EMA 21:**"
        f" {f'₹{ema21_val:,.2f}'} ➔ {trend_label(spot_price, ema21_val)}"
    )
    st.write(
        f"🔹 **Session VWAP:**"
        f" {f'₹{vwap_val:,.2f}'} ➔ {trend_label(spot_price, vwap_val)}"
    )
    st.write(f"🔹 **RSI (14):** {rsi_val:.2f} ➔ {rsi_status}")
    st.markdown("---")
    st.subheader("🌐 தமிழ் வணிகச் செய்திகள் (Tamil News)")
    for n in get_market_news():
      st.write(n)

  # நேரலை எச்சரிக்கைகள் (Live Alerts)
  st.markdown("---")
  st.subheader("🔔 நேரலை சந்தை எச்சரிக்கைகள்")
  alerts = []
  if pd.notna(ema9_val) and pd.notna(ema21_val):
    if ema9_val > ema21_val:
      alerts.append(
          f"🟢 **EMA ஏற்றப் போக்கு** — EMA 9 ({ema9_val:,.2f}) > EMA 21"
          f" ({ema21_val:,.2f})"
      )
    else:
      alerts.append(
          f"🔴 **EMA இறக்கப் போக்கு** — EMA 9 ({ema9_val:,.2f}) < EMA 21"
          f" ({ema21_val:,.2f})"
      )

  if pd.notna(vwap_val):
    if spot_price > vwap_val:
      alerts.append(
          f"🟢 **VWAP-க்கு மேல் வர்த்தகம்** — விலை ₹{spot_price:,.2f} > VWAP"
          f" ₹{vwap_val:,.2f} (வாங்குவோர் ஆதிக்கம்)"
      )
    else:
      alerts.append(
          f"🔴 **VWAP-க்கு கீழ் வர்த்தகம்** — விலை ₹{spot_price:,.2f} < VWAP"
          f" ₹{vwap_val:,.2f} (விற்போர் அழுத்தம்)"
      )

  if pd.notna(rsi_val):
    if rsi_val >= 70:
      alerts.append(
          f"⚠️ **RSI அதிக வாங்குதல் (Overbought)** ({rsi_val:.1f}) — இறக்கம் வரலாம்"
      )
    elif rsi_val <= 30:
      alerts.append(
          f"🟢 **RSI அதிக விற்பனை (Oversold)** ({rsi_val:.1f}) — மீண்டெழ வாய்ப்பு"
      )
    elif rsi_val >= 60:
      alerts.append(f"🟢 **RSI ஏற்றச் சாய்வு (Bullish Bias)** ({rsi_val:.1f})")
    elif rsi_val <= 40:
      alerts.append(f"🩸 **RSI இறக்கச் சாய்வு (Bearish Bias)** ({rsi_val:.1f})")

  if spot_price > pdh:
    alerts.append(
        "🚀 **நேற்றைய உச்சம் உடைப்பு (PDH Breakout)** —"
        f" ₹{pdh:,.2f}-க்கு மேல் நிலை கொண்டுள்ளது"
    )
  elif spot_price < pdl:
    alerts.append(
        "🩸 **நேற்றைய வீழ்ச்சி உடைப்பு (PDL Breakdown)** —"
        f" ₹{pdl:,.2f}-க்கு கீழ் இறங்கியுள்ளது"
    )

  if vix_val is not None and vix_val >= 18:
    alerts.append(
        f"🚨 **அதிக VIX ஏற்ற இறக்கம்** — {vix_val:.2f} (ஹெட்ஜிங் பாதுகாப்பு"
        " அவசியம்)"
    )

  if alerts:
    for a in alerts:
      st.markdown(f"- {a}")
  else:
    st.caption("தற்போது நேரலை எச்சரிக்கைகள் ஏதுமில்லை.")

  # சார்ட் பகுதி (பாதுகாப்பான ஒற்றை வரிசை Tooltip வடிவம்)
  st.markdown("---")
  st.subheader("📈 நிஃப்டி இன்ட்ராடே சார்ட் - விலை / VWAP / CPR")

  chart_df = session_hist[["Close", "VWAP"]].copy()
  chart_df["Time"] = chart_df.index
  chart_df = chart_df.reset_index(drop=True)

  if chart_df["VWAP"].isna().all():
    chart_df["VWAP"] = chart_df["Close"]
    st.caption(
        "ℹ️ **VWAP Note:** வால்யூம் கிடைக்காததால், VWAP விலைக்கோட்டுடன்"
        " proxy-யாகக் காட்டப்படுகிறது."
    )

  chart_start = chart_df["Time"].min()
  chart_end = chart_df["Time"].max() + pd.Timedelta(minutes=25)
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

  vwap_df = chart_df.dropna(subset=["VWAP"]).copy()

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
    y_min = float(min(valid_vals) - 20)
    y_max = float(max(valid_vals) + 20)
  else:
    y_min = float(spot_price - 250)
    y_max = float(spot_price + 250)

  x_scale = alt.Scale(domain=[chart_start, chart_end])
  y_scale = alt.Scale(
      domain=[y_min, y_max], clamp=True, zero=False, nice=False, padding=0
  )

  # 1. Price Line (பாதுகாப்பான Tooltip)
  price_line = (
      alt.Chart(chart_df)
      .mark_line(color="#0052cc", strokeWidth=2.5)
      .encode(
          x=alt.X(
              "Time:T",
              title="நேரம் (IST)",
              axis=alt.Axis(
                  format="%H:%M",
                  tickMinStep=300000,
                  labelAngle=-45,
                  labelFontSize=8,
              ),
              scale=x_scale,
          ),
          y=alt.Y("Close:Q", title="விலை (₹)", scale=y_scale),
          tooltip="Close:Q",
      )
  )

  # 2. VWAP Line
  vwap_line = (
      alt.Chart(vwap_df)
      .mark_line(color="#ff9900", strokeWidth=2.0, strokeDash=[3, 3])
      .encode(
          x=alt.X("Time:T", scale=x_scale),
          y=alt.Y("VWAP:Q", scale=y_scale),
          tooltip="VWAP:Q",
      )
  )

  # 3. CPR Band
  cpr_band_data = pd.DataFrame([{
      "_Start": chart_start,
      "_End": chart_end,
      "_Lower": float(BC),
      "_Upper": float(TC),
  }])
  cpr_band = (
      alt.Chart(cpr_band_data)
      .mark_re
