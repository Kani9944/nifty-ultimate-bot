import altair as alt
import feedparser
import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import ta
import yfinance as yf

# பக்க வடிவமைப்பு
st.set_page_config(
    page_title="Nifty AI Pro - Monitoring Terminal", layout="wide"
)

# 30 விநாடிகளுக்கு ஒருமுறை தானாக புதுப்பிக்கும்
st_autorefresh(interval=30 * 1000, key="nifty_pro_refresh")

st.title("🦅 NIFTY 50 - Smart Money & Market Monitor")


# 1. முக்கிய குறியீடுகளுக்கான கேச்சிங் (TTL: 25 விநாடிகள்)
@st.cache_data(ttl=25)
def get_stock_data(symbol, period, interval=None):
  ticker = yf.Ticker(symbol)
  if interval:
    return ticker.history(period=period, interval=interval)
  return ticker.history(period=period)


# 2. ஹெவிவெயிட் பங்குகளுக்கான பிரத்யேக கேச்சிங் (Daily: 90s, Intraday: 25s)
@st.cache_data(ttl=90)
def get_heavyweight_daily(symbol):
  return yf.Ticker(symbol).history(period="5d", interval="1d")


@st.cache_data(ttl=25)
def get_heavyweight_intraday(symbol):
  return yf.Ticker(symbol).history(period="1d", interval="5m")


# 3. Moneycontrol RSS Feed (Fallback செய்தி + Exception Message)
@st.cache_data(ttl=300)
def get_market_news():
  fallback_news = [
      "📰 **Market news feed தற்போது அணுக முடியவில்லை.**",
      "📰 **Nifty மற்றும் உலகளாவிய சந்தை நிலவரங்களைத் தனியாகச் சரிபார்க்கவும்.**",
  ]
  try:
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(
        "https://www.moneycontrol.com/rss/markets.xml",
        headers=headers,
        timeout=5,
    )
    feed = feedparser.parse(r.content)
    news_list = []
    for entry in getattr(feed, "entries", [])[:4]:
      title = entry.get("title", "Market Update")
      link = entry.get("link")
      if link:
        news_list.append(f"📰 **[{title}]({link})**")
      else:
        news_list.append(f"📰 **{title}**")

    if news_list:
      return news_list, None
    return fallback_news, "Empty feed entries"
  except Exception as e:
    return fallback_news, str(e)


# 4. குறியீடுகளின் சொந்த அமர்வைக் கண்டறியும் தன்னாட்சி முறை
def get_autonomous_session_change(data):
  if data.empty:
    return None, None, None

  d = data.copy()
  d.index = pd.to_datetime(d.index)
  if d.index.tz is not None:
    d.index = d.index.tz_convert("Asia/Kolkata")
  else:
    d.index = d.index.tz_localize("Asia/Kolkata")

  unique_dates = pd.Index(d.index.date).unique().sort_values()
  if len(unique_dates) < 2:
    return None, None, None

  target_date = unique_dates[-1]
  curr_val = float(d[d.index.date == target_date]["Close"].iloc[-1])
  prev_val = float(d[d.index.date == unique_dates[-2]]["Close"].iloc[-1])

  pct = (
      ((curr_val - prev_val) / prev_val * 100)
      if prev_val != 0
      else 0.0
  )
  return curr_val, pct, target_date


# 5. Date-aware Previous Close Helper for Heavyweights
def get_previous_close_for_session(daily_data, target_date):
  if daily_data.empty:
    return None

  d = daily_data.copy()
  d.index = pd.to_datetime(d.index)
  if d.index.tz is not None:
    d.index = d.index.tz_convert("Asia/Kolkata")
  else:
    d.index = d.index.tz_localize("Asia/Kolkata")

  earlier = d[d.index.date < target_date]
  if earlier.empty:
    return None
  return float(earlier["Close"].iloc[-1])


# 6. Safe Indicator Trend Label Helper
def trend_label(price, indicator):
  if pd.isna(indicator):
    return "⚪ Insufficient data"
  return "🟢 Bullish" if price > indicator else "🩸 Bearish"


# Core Data Fetches
try:
  hist = get_stock_data("^NSEI", "5d", "5m")
  daily_hist = get_stock_data("^NSEI", "5d", "1d")
  bn_hist = get_stock_data("^NSEBANK", "5d", "1d")
  vix_hist = get_stock_data("^INDIAVIX", "5d", "1d")
except Exception:
  st.error(
      "Market data source-ஐ தற்போது அணுக முடியவில்லை. சிறிது நேரம் கழித்து"
      " மீண்டும் முயற்சிக்கவும்."
  )
  st.stop()

# Core Data Validation
if hist.empty or len(daily_hist) < 2:
  st.error(
      "தேவையான Nifty Market Data கிடைக்கவில்லை. சந்தை விடுமுறை அல்லது Yahoo"
      " Finance தற்காலிக இணைப்புச் சிக்கலாக இருக்கலாம்."
  )
  st.stop()

try:
  # Timezone Conversion to Asia/Kolkata
  hist.index = pd.to_datetime(hist.index)
  if hist.index.tz is not None:
    hist.index = hist.index.tz_convert("Asia/Kolkata")
  else:
    hist.index = hist.index.tz_localize("Asia/Kolkata")

  daily_hist.index = pd.to_datetime(daily_hist.index)
  if daily_hist.index.tz is not None:
    daily_hist.index = daily_hist.index.tz_convert("Asia/Kolkata")
  else:
    daily_hist.index = daily_hist.index.tz_localize("Asia/Kolkata")

  today_ist = pd.Timestamp.now(tz="Asia/Kolkata").date()
  last_data_date = pd.Timestamp(hist.index[-1]).date()

  # Dynamic Session Identification
  session_date = (
      today_ist if (hist.index.date == today_ist).any() else last_data_date
  )
  session_hist = hist[hist.index.date == session_date].copy()

  if session_hist.empty:
    st.error("தேர்ந்தெடுக்கப்பட்ட session-க்கான intraday data கிடைக்கவில்லை.")
    st.stop()

  spot_price = float(session_hist["Close"].iloc[-1])
  open_price = float(session_hist["Open"].iloc[0])

  # Explicit Session Date-based Daily Reference Selection
  daily_dates = pd.Index(daily_hist.index.date)
  previous_sessions = daily_hist[daily_dates < session_date]

  if previous_sessions.empty:
    st.error("Previous-session daily data கிடைக்கவில்லை; CPR கணக்கிட முடியாது.")
    st.stop()

  prev_day = previous_sessions.iloc[-1]
  prev_reference_date = pd.Timestamp(prev_day.name).date()

  pdh = float(prev_day["High"])
  pdl = float(prev_day["Low"])
  pdc = float(prev_day["Close"])

  prev_close = pdc
  change = spot_price - prev_close
  percent_change = (
      (change / prev_close * 100) if prev_close != 0 else 0.0
  )

  # Gap-Up / Gap-Down Calculation
  gap_points = open_price - prev_close
  gap_pct = (gap_points / prev_close * 100) if prev_close != 0 else 0.0

  # Header Caption
  last_bar_time = session_hist.index[-1].strftime("%d-%b-%Y %H:%M IST")
  st.caption(
      f"📍 **Active session:** {session_date.strftime('%d-%b-%Y')} | "
      f"🎯 **CPR reference:** {prev_reference_date.strftime('%d-%b-%Y')} | "
      f"⏱️ **Last 5-min bar:** {last_bar_time} | "
      "Yahoo Finance delayed feed (கல்வி மற்றும் அனாலிசிஸ் பயன்பாட்டிற்கு"
      " மட்டுமே)."
  )

  # Bank Nifty & India VIX Autonomous Calculations
  bn_curr, bn_change_pct, bn_session_date = get_autonomous_session_change(
      bn_hist
  )
  vix_curr, vix_change_pct, vix_session_date = get_autonomous_session_change(
      vix_hist
  )

  bn_available = bn_curr is not None and bn_change_pct is not None
  vix_available = vix_curr is not None and vix_change_pct is not None

  # Normalized CPR கணக்கீடுகள்
  PP = (pdh + pdl + pdc) / 3
  bc_raw = (pdh + pdl) / 2
  tc_raw = (2 * PP) - bc_raw
  BC = min(bc_raw, tc_raw)
  TC = max(bc_raw, tc_raw)
  cpr_width = TC - BC
  cpr_width_pct = (cpr_width / PP * 100) if PP != 0 else 0.0

  R1 = (2 * PP) - pdl
  S1 = (2 * PP) - pdh
  R2 = PP + (pdh - pdl)
  S2 = PP - (pdh - pdl)

  # Safe Intraday Session VWAP
  typical_price = (
      session_hist["High"] + session_hist["Low"] + session_hist["Close"]
  ) / 3
  cum_volume = session_hist["Volume"].cumsum()
  cum_tpv = (typical_price * session_hist["Volume"]).cumsum()

  session_hist["VWAP"] = np.where(cum_volume > 0, cum_tpv / cum_volume, np.nan)
  last_vwap = session_hist["VWAP"].iloc[-1]
  vwap_val = float(last_vwap) if pd.notna(last_vwap) else spot_price

  # Rolling 5-day Indicators
  hist["EMA9"] = ta.trend.ema_indicator(hist["Close"], window=9)
  hist["EMA21"] = ta.trend.ema_indicator(hist["Close"], window=21)
  hist["RSI"] = ta.momentum.rsi(hist["Close"], window=14)

  ema9_val = float(hist["EMA9"].iloc[-1])
  ema21_val = float(hist["EMA21"].iloc[-1])
  rsi_val = float(hist["RSI"].iloc[-1])

  # RSI Status Logic
  if pd.isna(rsi_val):
    rsi_status = "⚪ Insufficient data"
  elif rsi_val >= 70:
    rsi_status = "🚨 Overbought (>70)"
  elif rsi_val <= 30:
    rsi_status = "🟢 Oversold (<30)"
  else:
    rsi_status = "⚖️ Neutral Zone (30-70)"

  # Market Structure / Signal Strength Logic
  indicator_ready = all(
      pd.notna(value) for value in [ema9_val, ema21_val, rsi_val, vwap_val]
  )

  if indicator_ready:
    bullish_score = sum([
        spot_price > ema9_val,
        spot_price > ema21_val,
        spot_price > vwap_val,
        rsi_val > 50,
        percent_change > 0,
    ])
  else:
    bullish_score = None

  # மேல் பகுதி - Nifty, Bank Nifty, VIX
  top_m1, top_m2 = st.columns([1.5, 1])

  with top_m1:
    m1, m2, m3 = st.columns(3)
    with m1:
      st.metric(
          "📊 NIFTY 50",
          f"₹{spot_price:,.2f}",
          f"{change:+,.2f} ({percent_change:+.2f}%)",
      )
    with m2:
      if bn_available:
        st.metric(
            "🏦 BANK NIFTY", f"₹{bn_curr:,.2f}", f"{bn_change_pct:+.2f}%"
        )
      else:
        st.info("🏦 **BANK NIFTY:** Session data unavailable")
    with m3:
      if vix_available:
        st.metric(
            "⚡ INDIA VIX",
            f"{vix_curr:.2f}",
            f"{vix_change_pct:+.2f}%",
            delta_color="inverse",
        )
      else:
        st.info("⚡ **INDIA VIX:** Session data unavailable")

  with top_m2:
    if bullish_score is None:
      st.info(
          "ℹ️ Signal Score உருவாக்க போதுமான Indicator Data இன்னும்"
          " கிடைக்கவில்லை."
      )
    elif bullish_score >= 4:
      st.success(
          f"🟢 **Structure Alignment: Bullish ({bullish_score}/5)**\nதற்போதைய"
          " technical conditions மேல்நோக்கி சாதகமாக சாய்ந்துள்ளன."
      )
    elif bullish_score <= 1:
      st.error(
          f"🔴 **Structure Alignment: Bearish ({bullish_score}/5)**\nதற்போதைய"
          " technical conditions விற்பனை அழுத்தத்தில் கீழ்நோக்கி சாய்ந்துள்ளன."
      )
    else:
      st.warning(
          f"🟡 **Structure Alignment: Mixed ({bullish_score}/5)**\nடிரெண்ட்"
          " சமநிலையாக உள்ளது; பிரேக்அவுட் ஆகும் வரை காத்திருக்கவும்."
      )

  # Gap-Up/Down & Volatility Alert Bar
  gap_col, vix_col = st.columns(2)
  with gap_col:
    if gap_points >= 40:
      st.success(
          f"🚀 **Gap-Up Open:** +{gap_points:,.1f} pts ({gap_pct:+.2f}%) | Gap"
          " Fill ஆதரவைக் கவனிக்கவும்."
      )
    elif gap_points <= -40:
      st.error(
          f"🩸 **Gap-Down Open:** {gap_points:,.1f} pts ({gap_pct:+.2f}%) | Gap"
          " Resistance அழுத்தத்தைக் கவனிக்கவும்."
      )
    else:
      st.info(
          f"⚖️ **Flat / Normal Open:** {gap_points:+,.1f} pts ({gap_pct:+.2f}%)"
      )

  with vix_col:
    if not vix_available:
      st.caption("ℹ️ VIX சூழல் அறியப்படவில்லை.")
    elif vix_curr >= 18:
      st.error(
          "🚨 **Elevated Volatility (VIX > 18):** பெரிய ஏற்ற இறக்கம் இருக்கும்;"
          " trailing SL அவசியம்."
      )
    elif vix_change_pct >= 4.0:
      st.warning(
          "⚠️ **VIX Spike (+4%):** ஹெஜிங் வேகம் அதிகரித்துள்ளது; கவனமாக"
          " வர்த்தகிக்கவும்."
      )
    else:
      st.info("🟢 **Normal Volatility:** VIX அமைதியான வரம்பில் உள்ளது.")

  # ஸ்ட்ரைக் வாரியான மாதிரி பகுப்பாய்வு
  st.markdown("---")
  st.subheader(
      "🎯 Strike-wise Call vs Put (Estimated OI & Delta Model Analysis)"
  )
  st.caption(
      "⚠️ **குறிப்பு:** இப்பகுதி தற்போதைய ஸ்பாட் விலையைக் கொண்டு உருவாக்கப்பட்ட"
      " மாதிரி அனாலிசிஸ் (Illustrative Model) மட்டுமே; என்.எஸ்.இ-யின் நேரடி"
      " ஆப்ஷன் செயின் டேட்டா அல்ல."
  )

  atm_strike = int(round(spot_price / 50) * 50)
  strikes = [atm_strike + (i * 50) for i in range(-2, 3)]

  strike_records = []
  for s in strikes:
    diff = (spot_price - s) / 50.0
    call_delta = round(float(np.clip(0.5 + (diff * 0.12), 0.10, 0.95)), 2)
    put_delta = round(float(call_delta - 1.0), 2)

    base_dist = abs(spot_price - s)
    call_vol = int(max(250000, 1800000 - (base_dist * 8000)))
    put_vol = int(max(220000, 1950000 - (base_dist * 7500)))

    call_oi_strike = int(max(1500000, 4500000 - (base_dist * 9000)))
    put_oi_strike = int(max(1400000, 5200000 - (base_dist * 8500)))

    call_delta_vol = int(abs(call_delta * call_vol))
    put_delta_vol = int(abs(put_delta * put_vol))

    strike_records.append({
        "Strike": f"₹{s:,} {'🎯 (ATM)' if s == atm_strike else ''}",
        "Call OI": f"{call_oi_strike:,}",
        "Call Delta Vol": f"{call_delta_vol:,}",
        "Call Delta": call_delta,
        "Put Delta": put_delta,
        "Put Delta Vol": f"{put_delta_vol:,}",
        "Put OI": f"{put_oi_strike:,}",
        "Dominance": (
            "🟢 Put Support"
            if put_delta_vol > call_delta_vol
            else "🔴 Call Resistance"
        ),
    })

  st.dataframe(
      pd.DataFrame(strike_records), hide_index=True, use_container_width=True
  )

  # ஹெவிவெயிட்கள் (பிரித்தெடுக்கப்பட்ட TTL கேச் முறை)
  st.markdown("---")
  st.subheader("🏢 Nifty Heavyweights Tracker")
  live_heavyweights = st.toggle(
      "Use 5-minute intraday heavyweights",
      value=False,
      key="live_heavyweights_toggle",
  )
  st.caption(
      "Intraday mode: latest 5-minute price vs prior completed trading-session"
      " close."
      if live_heavyweights
      else (
          "Daily-bar mode: latest two daily bars are compared; market hours-ல்"
          " latest daily bar இன்னும் மாறக்கூடும்."
      )
  )

  heavy_tickers = {
      "HDFC Bank": "HDFCBANK.NS",
      "Reliance": "RELIANCE.NS",
      "ICICI Bank": "ICICIBANK.NS",
      "Infosys": "INFY.NS",
      "TCS": "TCS.NS",
  }

  hw_cols = st.columns(5)
  for i, (name, sym) in enumerate(heavy_tickers.items()):
    with hw_cols[i]:
      try:
        if live_heavyweights:
          stk_intra = get_heavyweight_intraday(sym)
          stk_daily = get_heavyweight_daily(sym)
          if not stk_intra.empty:
            intra_idx = pd.to_datetime(stk_intra.index)
            if intra_idx.tz is not None:
              intra_idx = intra_idx.tz_convert("Asia/Kolkata")
            else:
              intra_idx = intra_idx.tz_localize("Asia/Kolkata")
            heavy_session_date = intra_idx[-1].date()
            stk_curr = float(stk_intra["Close"].iloc[-1])

            prev_day_close = get_previous_close_for_session(
                stk_daily, heavy_session_date
            )
            if prev_day_close is not None and prev_day_close != 0:
              stk_chg = ((stk_curr - prev_day_close) / prev_day_close) * 100
              st.metric(
                  label=name,
                  value=f"₹{stk_curr:,.1f}",
                  delta=f"{stk_chg:+.2f}%",
              )
            else:
              st.caption(f"{name}: Prev Close N/A")
          else:
            st.caption(f"{name}: Data Pending")
        else:
          stk = get_heavyweight_daily(sym)
          if len(stk) >= 2:
            stk_curr = float(stk["Close"].iloc[-1])
            stk_prev = float(stk["Close"].iloc[-2])
            stk_chg = (
                ((stk_curr - stk_prev) / stk_prev * 100)
                if stk_prev != 0
                else 0.0
            )
            st.metric(
                label=name,
                value=f"₹{stk_curr:,.1f}",
                delta=f"{stk_chg:+.2f}%",
            )
          else:
            st.caption(f"{name}: Data Pending")
      except Exception:
        st.caption(f"{name}: Unavailable")

  # லிக்விடிட்டி & CPR விவரங்கள்
  st.markdown("---")
  c1, c2 = st.columns(2)

  with c1:
    st.subheader("🎯 Liquidity & Trap Zones (PDH / PDL)")
    st.caption(
        f"PDH / PDL / CPR reference: {prev_reference_date.strftime('%d-%b-%Y')}"
    )
    st.write(f"🔺 **Previous Day High (PDH):** ₹{pdh:,.2f}")
    st.write(f"🔻 **Previous Day Low (PDL):** ₹{pdl:,.2f}")

    st.markdown("---")
    st.subheader("📌 Normalized CPR & Pivots")
    if cpr_width_pct < 0.15:
      st.success(
          f"🔥 **Narrow CPR ({cpr_width_pct:.2f}%):** ஒருபக்க movement-ஐ"
          " கவனிக்க வேண்டிய சூழல்."
      )
    else:
      st.info(
          f"⚠️ **Wide CPR ({cpr_width_pct:.2f}%):** range-bound அல்லது mixed"
          " movement சாத்தியம் இருக்கலாம்."
      )

    st.write(f"🔴 **Resistance 2 (R2):** ₹{R2:,.2f}")
    st.write(f"🔴 **Resistance 1 (R1):** ₹{R1:,.2f}")
    st.success(
        f"🎯 **CPR Range (BC-PP-TC):** ₹{BC:,.2f} - ₹{PP:,.2f} - ₹{TC:,.2f}"
    )
    st.write(f"🟢 **Support 1 (S1):** ₹{S1:,.2f}")
    st.write(f"🟢 **Support 2 (S2):** ₹{S2:,.2f}")

  with c2:
    st.subheader("📈 Technical Indicators (Multi-Timeframe)")
    st.caption(
        "EMA 9 (~45-min) & EMA 21 (~105-min) are 5-min rolling; VWAP is"
        " Session-Reset."
    )
    st.write(
        f"🔹 **EMA 9:** {f'₹{ema9_val:,.2f}' if pd.notna(ema9_val) else '--'}"
        f" ➔ {trend_label(spot_price, ema9_val)}"
    )
    st.write(
        f"🔹 **EMA 21:**"
        f" {f'₹{ema21_val:,.2f}' if pd.notna(ema21_val) else '--'} ➔"
        f" {trend_label(spot_price, ema21_val)}"
    )
    st.write(
        f"🔹 **Session VWAP:** ₹{vwap_val:,.2f} ➔"
        f" {trend_label(spot_price, vwap_val)}"
    )
    st.write(
        f"🔹 **RSI (14):** {f'{rsi_val:.2f}' if pd.notna(rsi_val) else '--'}"
        f" ➔ {rsi_status}"
    )

    st.markdown("---")
    st.subheader("🌐 Global Web Market News")
    news_items, news_err = get_market_news()
    if news_err:
      st.toast(f"News Feed Notice: {news_err}")
    for n in news_items:
      st.write(n)

  # சார்ட் (VWAP, CPR Band, Current Price Marker & Labels)
  st.markdown("---")
  if session_date == today_ist:
    st.subheader("📈 NIFTY 50 - Today's Intraday Levels Chart")
  else:
    st.subheader(
        "📈 NIFTY 50 - Last Available Intraday Session "
        f"({session_date.strftime('%d-%b-%Y')})"
    )
  st.caption(
      "Chart displays Price, Session VWAP (Orange), CPR Band (BC/Pivot/TC),"
      " PDH, and PDL."
  )

  chart_df = session_hist[["Close", "VWAP"]].copy()
  chart_df["Time"] = chart_df.index
  chart_df = chart_df.reset_index(drop=True)

  # வலதுபுறத்தில் லேபிள்களுக்கு 15 நிமிடங்கள் Padding
  chart_start = chart_df["Time"].min()
  chart_end = chart_df["Time"].max() + pd.Timedelta(minutes=15)

  levels_data = pd.DataFrame([
      {"Level": "PDH", "Value": float(pdh), "Color": "#cc0000"},
      {"Level": "R1", "Value": float(R1), "Color": "#ff9999"},
      {"Level": "TC", "Value": float(TC), "Color": "#66b3ff"},
      {"Level": "Pivot", "Value": float(PP), "Color": "#0066cc"},
      {"Level": "BC", "Value": float(BC), "Color": "#66b3ff"},
      {"Level": "S1", "Value": float(S1), "Color": "#85e085"},
      {"Level": "PDL", "Value": float(pdl), "Color": "#009900"},
  ])
  levels_data["Time"] = chart_df["Time"].max() + pd.Timedelta(minutes=3)

  # Auto-Zoom: 0-விலிருந்து போகாமல் வர்த்தக வரம்பை மட்டும் ஜூம் செய்ய
  all_valid_prices = [
      p
      for p in (
          list(chart_df["Close"])
          + list(chart_df["VWAP"].dropna())
          + list(levels_data["Value"])
      )
      if pd.notna(p) and p > 1000
  ]
  min_val = float(min(all_valid_prices) - 30)
  max_val = float(max(all_valid_prices) + 30)

  # 1. Price Line Chart
  price_line = (
      alt.Chart(chart_df)
      .mark_line(color="#0052cc", strokeWidth=2.5)
      .encode(
          x=alt.X(
              "Time:T",
              title="Time (IST)",
              axis=alt.Axis(format="%H:%M", tickCount=8),
              scale=alt.Scale(domain=[chart_start, chart_end]),
          ),
          y=alt.Y(
              "Close:Q",
              title="Price (₹)",
              scale=alt.Scale(domain=[min_val, max_val], zero=False),
          ),
      )
  )

  # 2. VWAP Line (Orange)
  vwap_line = (
      alt.Chart(chart_df.dropna(subset=["VWAP"]))
      .mark_line(color="#ff9900", strokeWidth=2.0, strokeDash=[3, 3])
      .encode(
          x=alt.X("Time:T"),
          y=alt.Y(
              "VWAP:Q", scale=alt.Scale(domain=[min_val, max_val], zero=False)
          ),
      )
  )

  # 3. Current Price Dot Marker
  latest_bar = chart_df.iloc[[-1]]
  price_dot = (
      alt.Chart(latest_bar)
      .mark_point(color="#0052cc", filled=True, size=85, shape="circle")
      .encode(
          x=alt.X("Time:T"),
          y=alt.
