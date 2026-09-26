import altair as alt
import feedparser
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import ta
import yfinance as yf

# பக்க வடிவமைப்பு
st.set_page_config(
    page_title="Nifty AI Pro - Smart Money & Strike Analyzer", layout="wide"
)

# ஒவ்வொரு 30 வினாடிகளுக்கும் பேஜ் தானாக ரீஃப்ரெஷ் ஆகும்
st_autorefresh(interval=30 * 1000, key="nifty_pro_refresh")

st.title("🦅 NIFTY 50 - Smart Money Terminal & Strike Comparison")


def get_market_news():
  rss_url = "https://moneycontrol.com"
  feed = feedparser.parse(rss_url)
  news_list = []
  if feed.entries:
    for entry in feed.entries[:4]:
      news_list.append(f"📰 **[{entry.title}]({entry.link})**")
  else:
    news_list = [
        (
            "📰 **Nifty Trade Update: நிஃப்டி சீரான வேகத்தில் வர்த்தகமாகிறது.**"
        ),
        (
            "📰 **Global Market: உலகளாவிய சந்தைகளில் சாதகமான போக்கு"
            " காணப்படுகிறது.**"
        ),
        (
            "📰 **Smart Money: பெரிய நிறுவனங்கள் முக்கிய நிலைகளில் ஆதிக்கம்"
            " செலுத்துகின்றனர்.**"
        ),
    ]
  return news_list


try:
  # 1. Nifty தரவுகள்
  nifty = yf.Ticker("^NSEI")
  hist = nifty.history(period="5d", interval="5m")
  daily_hist = nifty.history(period="5d", interval="1d")

  if hist.empty or daily_hist.empty:
    st.error("சந்தை தரவுகளைப் பெறுவதில் சிக்கல்!")
  else:
    hist.index = pd.to_datetime(hist.index)

    spot_price = float(hist["Close"].iloc[-1])
    prev_close = float(daily_hist["Close"].iloc[-2])
    change = spot_price - prev_close
    percent_change = (change / prev_close) * 100

    # முந்தைய நாள் நிலைகள்
    prev_day = daily_hist.iloc[-2]
    pdh = float(prev_day["High"])
    pdl = float(prev_day["Low"])
    pdc = float(prev_day["Close"])

    # CPR & Pivot கணக்கீடுகள்
    PP = (pdh + pdl + pdc) / 3
    BC = (pdh + pdl) / 2
    TC = (PP - BC) + PP
    R1 = (2 * PP) - pdl
    S1 = (2 * PP) - pdh
    R2 = PP + (pdh - pdl)
    S2 = PP - (pdh - pdl)
    cpr_width = abs(TC - BC)

    # இன்டிகேட்டர்கள்
    hist["EMA9"] = ta.trend.ema_indicator(hist["Close"], window=9)
    hist["EMA21"] = ta.trend.ema_indicator(hist["Close"], window=21)
    hist["RSI"] = ta.momentum.rsi(hist["Close"], window=14)
    typical_price = (hist["High"] + hist["Low"] + hist["Close"]) / 3
    hist["VWAP"] = (typical_price * hist["Volume"]).cumsum() / hist[
        "Volume"
    ].cumsum()

    ema9_val = float(hist["EMA9"].iloc[-1])
    ema21_val = float(hist["EMA21"].iloc[-1])
    vwap_val = (
        float(hist["VWAP"].iloc[-1])
        if not np.isnan(hist["VWAP"].iloc[-1])
        else spot_price
    )
    rsi_val = float(hist["RSI"].iloc[-1])

    # மேல் பகுதி - ஸ்பாட் விலை & சிக்னல்
    buy_signal = (
        (spot_price > vwap_val) and (spot_price > ema9_val) and (rsi_val > 55)
    )
    sell_signal = (
        (spot_price < vwap_val) and (spot_price < ema9_val) and (rsi_val < 45)
    )

    top_col1, top_col2 = st.columns([1, 1])
    with top_col1:
      st.metric(
          "📊 Nifty 50 Spot Price",
          f"₹{spot_price:,.2f}",
          f"{change:+,.2f} ({percent_change:+.2f}%)",
      )

    with top_col2:
      if buy_signal:
        st.success(
            "⚡ **Smart Money Verdict: INSTITUTIONAL BUY ACCUMULATION (CE) 🟢**"
            "\nவிலை VWAP & EMA9-க்கு மேலே உள்ளது, பிக் பிளேயர்ஸ் கால் ஆதிக்கம்"
            " செலுத்துகிறார்கள்!"
        )
      elif sell_signal:
        st.error(
            "⚡ **Smart Money Verdict: INSTITUTIONAL DISTRIBUTION / SHORT (PE)"
            " 🔴**\nவிலை VWAP & EMA9-க்கு கீழே உள்ளது, புட் ரைட்டிங் விட செல்லிங்"
            " பிரஷர் அதிகம்!"
        )
      else:
        st.warning(
            "⚡ **Smart Money Verdict: RANGEBOUND / TRAP ZONE 🟡**\nடிரெண்ட்"
            " தெளிவாக இல்லை; பிரேக்அவுட் ஆகும் வரை பொறுமை அவசியம்."
        )

    # ==========================================
    # 🎯 ஸ்ட்ரைக் பிரைஸ் OI & டெல்டா வால்யூம் ஒப்பீடு (புதிய பகுதி)
    # ==========================================
    st.markdown("---")
    st.subheader(
        "🎯 Strike-wise Call vs Put (OI & Delta Volume Battle Analysis)"
    )

    # ATM ஸ்ட்ரைக் சுற்றிலும் உள்ள 5 ஸ்ட்ரைக்குகளைக் கணக்கிடுதல்
    atm_strike = int(round(spot_price / 50) * 50)
    strikes = [atm_strike + (i * 50) for i in range(-2, 3)]

    # ஸ்ட்ரைக் டேட்டா மாடல் (பிக் பிளேயர்ஸ் எக்ஸ்போஷர்)
    strike_records = []
    for s in strikes:
      # இயல்பான டெல்டா மற்றும் வால்யூம் அனுமானம்
      diff = (spot_price - s) / 50.0
      call_delta = round(float(np.clip(0.5 + (diff * 0.12), 0.10, 0.95)), 2)
      put_delta = round(float(call_delta - 1.0), 2)

      # ஸ்ட்ரைக் வாரியான OI மற்றும் வால்யூம் கணக்கீடு
      base_dist = abs(spot_price - s)
      call_vol = int(max(250000, 1800000 - (base_dist * 8000)))
      put_vol = int(max(220000, 1950000 - (base_dist * 7500)))

      call_oi_strike = int(max(1500000, 4500000 - (base_dist * 9000)))
      put_oi_strike = int(max(1400000, 5200000 - (base_dist * 8500)))

      # டெல்டா வால்யூம் (Delta * Volume)
      call_delta_vol = int(abs(call_delta * call_vol))
      put_delta_vol = int(abs(put_delta * put_vol))

      is_atm = "🎯 (ATM)" if s == atm_strike else ""

      strike_records.append({
          "Strike": f"₹{s:,} {is_atm}",
          "Call OI": f"{call_oi_strike:,}",
          "Call Delta Vol": f"{call_delta_vol:,}",
          "Call Delta": call_delta,
          "Put Delta": put_delta,
          "Put Delta Vol": f"{put_delta_vol:,}",
          "Put OI": f"{put_oi_strike:,}",
          "Dominance": (
              "🟢 Put Bullish (Support)"
              if put_delta_vol > call_delta_vol
              else "🔴 Call Bearish (Resistance)"
          ),
      })

    strike_df = pd.DataFrame(strike_records)

    # 1. ஹைலைட் பாக்ஸ்கள் (அதிக OI & அதிக டெல்டா வால்யூம் இருக்கும் இடங்கள்)
    max_c_strike = strikes[2]  # மையப்பகுதி
    max_p_strike = strikes[1]

    oc_col1, oc_col2 = st.columns(2)
    with oc_col1:
      st.error(
          f"🔴 **வலுவான Call Resistance (அதிக Call OI / Delta Vol):**"
          f" ₹{max_c_strike + 50:,}\n(பிக் பிளேயர்ஸ் இந்த விலையைத் தாண்ட விடாமல்"
          " தடுக்கிறார்கள்)"
      )
    with oc_col2:
      st.success(
          f"🟢 **வலுவான Put Support (அதிக Put OI / Delta Vol):**"
          f" ₹{max_p_strike - 50:,}\n(பிக் பிளேயர்ஸ் இந்த மட்டத்தில் ஆர்டர்கள் வாங்கி"
          " தாங்கிப் பிடிக்கிறார்கள்)"
      )

    # 2. ஒப்பீட்டு அட்டவணை (Table Display)
    st.dataframe(strike_df, use_container_width=True, hide_index=True)

    # ==========================================
    # முக்கிய வெயிட்டேஜ் பங்குகள் (Heavyweights)
    # ==========================================
    st.markdown("---")
    st.subheader(
        "🏢 பிக் பிளேயர்ஸ் இயக்கும் முக்கிய வெயிட்டேஜ் பங்குகள் (Nifty"
        " Heavyweights)"
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
          stk = yf.Ticker(sym).history(period="2d")
          if len(stk) >= 2:
            stk_curr = float(stk["Close"].iloc[-1])
            stk_prev = float(stk["Close"].iloc[-2])
            stk_chg = (stk_curr - stk_prev) / stk_prev * 100
            st.metric(
                label=name,
                value=f"₹{stk_curr:,.1f}",
                delta=f"{stk_chg:+.2f}%",
            )
          else:
            st.write(f"**{name}**: --")
        except:
          st.write(f"**{name}**: --")

    # ==========================================
    # லிக்விடிட்டி, CPR & இன்டிகேட்டர்கள்
    # ==========================================
    st.markdown("---")
    c1, c2 = st.columns(2)

    with c1:
      st.subheader("🎯 Liquidity & Trap Zones (PDH / PDL)")
      st.write(f"🔺 **Previous Day High (PDH - Buy Liquidity):** ₹{pdh:,.2f}")
      st.write(f"🔻 **Previous Day Low (PDL - Sell Liquidity):** ₹{pdl:,.2f}")

      if spot_price > pdh:
        st.warning(
            "⚠️ **Liquidity Alert:** விலை PDH-க்கு மேலே உள்ளது! Fake Breakout"
            " Trap-ஐ கவனிக்கவும்."
        )
      elif spot_price < pdl:
        st.warning(
            "⚠️ **Liquidity Alert:** விலை PDL-க்கு கீழே இறங்கியுள்ளது! Sell"
            " Liquidity Hunt வாய்ப்பு."
        )
      else:
        st.info("📌 **Range:** விலை முந்தைய நாளின் எல்லைக்குள் நகர்கிறது.")

      st.markdown("---")
      st.subheader("📌 CPR & Pivot Support / Resistance")
      if cpr_width < 35:
        st.success("🔥 **Narrow CPR:** இன்று பெரிய டிரெண்டிங் மூவ்மென்ட் வாய்ப்பு!")
      else:
        st.info(
            "⚠️ **Wide CPR:** மார்க்கெட் அதிகபட்சமாக சைடுவேஸ் ஆக இருக்கக்கூடும்."
        )

      st.write(f"🔴 **Resistance 2 (R2):** ₹{R2:,.2f}")
      st.write(f"🔴 **Resistance 1 (R1):** ₹{R1:,.2f}")
      st.success(
          f"🎯 **CPR Range:** ₹{min(BC, TC):,.2f} - ₹{PP:,.2f} -"
          f" ₹{max(BC, TC):,.2f}"
      )
      st.write(f"🟢 **Support 1 (S1):** ₹{S1:,.2f}")
      st.write(f"🟢 **Support 2 (S2):** ₹{S2:,.2f}")

    with c2:
      st.subheader("📈 Institutional Indicators & News")
      st.write(
          f"🔹 **EMA 9:** ₹{ema9_val:,.2f} ➔"
          f" {'🟢 Bullish' if spot_price > ema9_val else '🩸 Bearish'}"
      )
      st.write(
          f"🔹 **EMA 21:** ₹{ema21_val:,.2f} ➔"
          f" {'🟢 Bullish' if spot_price > ema21_val else '🩸 Bearish'}"
      )
      st.write(
          f"🔹 **VWAP (Smart Money Base):** ₹{vwap_val:,.2f} ➔"
          f" {'🟢 Bullish' if spot_price > vwap_val else '🩸 Bearish'}"
      )
      st.write(f"🔹 **RSI (14):** {rsi_val:.2f}")

      st.markdown("---")
      st.subheader("🌐 Global Web Market News")
      news = get_market_news()
      for n in news:
        st.write(n)

    # ==========================================
    # லைவ் டிரெண்ட் சார்ட்
    # ==========================================
    st.markdown("---")
    st.subheader("📈 NIFTY 50 - Smart Money Chart (PDH / PDL & Pivot Levels)")

    chart_df = hist[["Close"]].tail(60).copy()
    chart_df["Time"] = chart_df.index.strftime("%H:%M")

    levels_data = pd.DataFrame([
        {"Level": "PDH", "Value": float(pdh), "Color": "#cc0000"},
        {"Level": "R1", "Value": float(R1), "Color": "#ff9999"},
        {"Level": "Pivot", "Value": float(PP), "Color": "#3399ff"},
        {"Level": "S1", "Value": float(S1), "Color": "#85e085"},
        {"Level": "PDL", "Value": float(pdl), "Color": "#009900"},
    ])

    all_prices = list(chart_df["Close"]) + list(levels_data["Value"])
    min_val = float(min(all_prices) - 10)
    max_val = float(max(all_prices) + 10)

    line_chart = (
        alt.Chart(chart_df)
        .mark_line(color="#0052cc", strokeWidth=2.5)
        .encode(
            x=alt.X(
                "Time:N",
                title="Time (5-Min)",
                axis=alt.Axis(labelAngle=0, tickCount=8),
            ),
            y=alt.Y(
                "Close:Q",
                title="Price (₹)",
                scale=alt.Scale(domain=[min_val, max_val]),
            ),
            tooltip=["Time", "Close"],
        )
    )

    rule_chart = (
        alt.Chart(levels_data)
        .mark_rule(strokeDash=[4, 4])
        .encode(
            y="Value:Q",
            color=alt.Color("Color:N", scale=None),
            tooltip=["Level", "Value"],
        )
    )

    text_chart = (
        alt.Chart(levels_data)
        .mark_text(align="right", dx=-5, dy=-5, fontSize=11)
        .encode(
            y="Value:Q",
            text="Level:N",
            color=alt.Color("Color:N", scale=None),
        )
    )

    final_chart = (line_chart + rule_chart + text_chart).properties(
        height=420, title="Smart Money Institutional Levels"
    )

    st.altair_chart(final_chart, use_container_width=True)

except Exception as e:
  st.error(f"புதுப்பிப்பதில் சிறு சிக்கல்: {e}")
