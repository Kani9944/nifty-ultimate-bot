import feedparser
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit.runtime.scriptrunner import StopException
from streamlit_autorefresh import st_autorefresh
import yfinance as yf

# App Config
st.set_page_config(page_title="Nifty Smart Monitor", layout="wide")
st_autorefresh(interval=60 * 1000, key="refresh")
st.title("🦅 NIFTY 50 - Smart Money & Market Monitor")


def get_last_bar_change(d):
  if d is None or len(d) < 2:
    return None, None
  c, p = float(d["Close"].iloc[-1]), float(d["Close"].iloc[-2])
  return c, (((c - p) / p) * 100 if p != 0 else None)


# Wilder's RSI (TradingView / Broker Standard)
def calculate_rsi(close, w=14):
  d = close.diff()
  g, l = d.clip(lower=0), -d.clip(upper=0)
  ag = g.ewm(alpha=1 / w, adjust=False, min_periods=w).mean()
  al = l.ewm(alpha=1 / w, adjust=False, min_periods=w).mean()
  rs = ag / al
  rsi = 100.0 - (100.0 / (1.0 + rs))
  return rsi.mask(al == 0, 100.0).mask((ag == 0) & (al == 0), 50.0)


@st.cache_data(ttl=60)
def get_stock_data(sym, p, itv=None):
  t = yf.Ticker(sym)
  return t.history(period=p, interval=itv) if itv else t.history(period=p)


# Batched Download for 18 Stocks (Parallel & Fast)
@st.cache_data(ttl=300)
def get_breadth():
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
  out = []
  try:
    df = yf.download(
        syms,
        period="2d",
        interval="1d",
        group_by="ticker",
        progress=False,
        threads=True,
    )
    for s in syms:
      try:
        h = df[s].dropna()
        if len(h) >= 2:
          c, p = float(h["Close"].iloc[-1]), float(h["Close"].iloc[-2])
          if p > 0:
            out.append({
                "sym": s.replace(".NS", ""),
                "ltp": round(c, 2),
                "chg": round(((c - p) / p) * 100, 2),
            })
      except Exception as e:
        print(f"Error parsing {s}: {e}")
  except Exception as e:
    print(f"Batch breadth failed: {e}")
  return out


@st.cache_data(ttl=300)
def get_news():
  feeds = [
      "https://tamil.goodreturns.in/rss/feeds/tamil-money-news-fb.xml",
      "https://www.moneycontrol.com/rss/marketreports.xml",
  ]
  out = []
  for u in feeds:
    try:
      r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
      if r.status_code == 200:
        f = feedparser.parse(r.content)
        for e in f.entries[:3]:
          t, l = e.get("title", "").strip(), e.get("link", "")
          if t:
            out.append(f"🌐 [{t}]({l})" if l else f"🌐 {t}")
        if len(out) >= 6:
          break
    except Exception as e:
      print(f"News fetch error from {u}: {e}")
  return out[:6] if out else ["🌐 வர்த்தகச் செய்திகள் தற்காலிகமாக கிடைக்கவில்லை."]


try:
  hist = get_stock_data("^NSEI", "5d", "5m")
  daily = get_stock_data("^NSEI", "5d", "1d")
  bn_hist = get_stock_data("^NSEBANK", "2d", "5m")
  vix_hist = get_stock_data("^INDIAVIX", "2d", "5m")

  if hist.empty or daily.empty or len(daily) < 2:
    st.error("Nifty data unavailable.")
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
    st.error("Session data unavailable.")
    st.stop()

  spot_price = float(session_hist["Close"].iloc[-1])
  _, nifty_5m = get_last_bar_change(session_hist)

  previous_sessions = daily[pd.Index(daily.index.date) < session_date]
  if previous_sessions.empty:
    st.error(
        "Previous completed session data கிடைக்கவில்லை; CPR கணக்கிட முடியாது."
    )
    st.stop()

  prev_day = previous_sessions.iloc[-1]
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
  cv = session_hist["Volume"].cumsum()
  session_hist["VWAP"] = np.where(
      cv > 0, (tp * session_hist["Volume"]).cumsum() / cv, np.nan
  )
  if session_hist["VWAP"].isna().all():
    session_hist["VWAP"] = session_hist["Close"]

  bn_p, bn_5m = get_last_bar_change(bn_hist)
  vix_v, vix_5m = get_last_bar_change(vix_hist)

  # Session-Scoped Indicators (Avoid Overnight Distortion)
  ema9_val = float(
      session_hist["Close"].ewm(span=9, adjust=False).mean().iloc[-1]
  )
  ema21_val = float(
      session_hist["Close"].ewm(span=21, adjust=False).mean().iloc[-1]
  )
  rsi_series = calculate_rsi(session_hist["Close"], 14)
  rsi_val = (
      float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50.0
  )
  vwap_val = (
      float(session_hist["VWAP"].iloc[-1])
      if pd.notna(session_hist["VWAP"].iloc[-1])
      else spot_price
  )

  # Explicit Formats & Distinct Names
  nd_s = f"{nifty_5m:+.2f}%" if nifty_5m is not None else "N/A"
  bd_s = f"{bn_5m:+.2f}%" if bn_5m is not None else "N/A"
  vd_s = f"{vix_5m:+.2f}%" if vix_5m is not None else "N/A"
  nifty_col = (
      "#00b300" if (nifty_5m is not None and nifty_5m >= 0) else "#cc0000"
  )
  bn_col = "#00b300" if (bn_5m is not None and bn_5m >= 0) else "#cc0000"
  vix_col = "#cc0000" if (vix_5m is not None and vix_5m >= 0) else "#00b300"
  bn_s = f"₹{bn_p:,.2f}" if bn_p is not None else "N/A"
  vix_s = f"{vix_v:.2f}" if vix_v is not None else "N/A"

  st.caption(f"📅 Session Date: {session_date}")
  st.write(
      f"""<div style="border:1px solid #333;border-radius:6px;padding:8px;font-family:monospace;background:#fff;margin-bottom:10px;">
        <div style="display:flex;border-bottom:1px solid #333;padding-bottom:5px;">
            <div style="flex:1;border-right:1px solid #333;padding:4px;"><span style="font-size:11px;color:#555;">NIFTY 50</span><br><b style="font-size:16px;">₹{spot_price:,.2f}</b><br><span style="font-size:11px;color:{nifty_col};">{nd_s}</span></div>
            <div style="flex:1;padding:4px;padding-left:8px;"><span style="font-size:11px;color:#555;">BANK NIFTY</span><br><b style="font-size:16px;">{bn_s}</b><br><span style="font-size:11px;color:{bn_col};">{bd_s}</span></div>
        </div>
        <div style="border-bottom:1px solid #333;padding:4px 0;text-align:center;"><span style="font-size:11px;color:#555;">INDIA VIX</span><br><b style="font-size:16px;">{vix_s}</b> <span style="font-size:11px;color:{vix_col};">{vd_s}</span></div>
        <div style="display:flex;padding-top:5px;">
            <div style="flex:1;border-right:1px solid #333;padding:4px;"><span style="font-size:11px;color:#555;">PDH</span><br><b style="font-size:15px;">₹{pdh:,.2f}</b></div>
            <div style="flex:1;padding:4px;padding-left:8px;"><span style="font-size:11px;color:#555;">PDL</span><br><b style="font-size:15px;">₹{pdl:,.2f}</b></div>
        </div></div>""",
      unsafe_allow_html=True,
  )

  # Alignment Engine
  st.markdown("---")
  st.subheader("⚡ சந்தை கட்டமைப்பு பகுப்பாய்வு")
  b_cond = [
      spot_price > TC,
      spot_price > vwap_val,
      ema9_val > ema21_val,
      rsi_val >= 55,
  ]
  s_cond = [
      spot_price < BC,
      spot_price < vwap_val,
      ema9_val < ema21_val,
      rsi_val <= 45,
  ]
  if all(b_cond):
    st.success(
        "🟢 Bullish Alignment: Price > TC & VWAP; EMA 9 > 21; RSI > 55."
    )
  elif all(s_cond):
    st.error("🔴 Bearish Alignment: Price < BC & VWAP; EMA 9 < 21; RSI < 45.")
  else:
    st.info("⚖️ Mixed / Range-Bound: தெளிவான தொழில்நுட்ப திசை அமைப்பு இல்லை.")

  st.caption(
      f"Levels: BC ₹{BC:,.2f} | TC ₹{TC:,.2f} | R1 ₹{R1:,.2f} | S1 ₹{S1:,.2f}"
  )

  # Market Breadth (Batched)
  st.markdown("---")
  st.subheader("Market Breadth - 18 Watchlist")
  b_stocks = get_breadth()
  if b_stocks:
    b1, b2, b3 = st.columns(3)
    b1.metric("Advances", sum(1 for s in b_stocks if s["chg"] > 0.05))
    b2.metric("Declines", sum(1 for s in b_stocks if s["chg"] < -0.05))
    b3.metric(
        "Avg Change",
        f"{sum(s['chg'] for s in b_stocks)/len(b_stocks):+.2f}%",
    )

  # Plotly Chart with CPR Band
  st.markdown("---")
  st.subheader("📈 NIFTY Chart & CPR")
  cdf = session_hist[["Close", "VWAP"]].copy().dropna(subset=["Close"])
  if not cdf.empty:
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
            line=dict(color="#0052cc", width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=cdf.index,
            y=cdf["VWAP"],
            mode="lines",
            name="VWAP",
            line=dict(color="#ff9900", width=1.5, dash="dash"),
        )
    )
    for lvl_name, lvl_val, lvl_col, lvl_dash in [
        ("TC", TC, "#66b3ff", "dot"),
        ("Pivot", PP, "#0066cc", "dash"),
        ("BC", BC, "#3399ff", "dot"),
        ("R1", R1, "#ff6666", "dot"),
        ("S1", S1, "#66cc66", "dot"),
        ("PDH", pdh, "#cc0000", "solid"),
        ("PDL", pdl, "#00b300", "solid"),
    ]:
      fig.add_trace(
          go.Scatter(
              x=[cdf.index[0], cdf.index[-1]],
              y=[lvl_val, lvl_val],
              mode="lines",
              name=lvl_name,
              line=dict(color=lvl_col, width=1, dash=lvl_dash),
          )
      )

    chart_vals = (
        cdf["Close"].dropna().tolist()
        + cdf["VWAP"].dropna().tolist()
        + [pdh, pdl, R1, R2, S1, S2, PP, BC, TC]
    )
    valid_vals = [
        float(v)
        for v in chart_vals
        if pd.notna(v) and np.isfinite(v) and abs(float(v) - spot_price) <= 400
    ]
    if valid_vals:
      low_val, high_val = min(valid_vals), max(valid_vals)
      pad = max(25.0, (high_val - low_val) * 0.10)
      y_min, y_max = low_val - pad, high_val + pad
    else:
      y_min, y_max = spot_price - 250, spot_price + 250

    fig.update_layout(
        height=400,
        margin=dict(l=10, r=10, t=25, b=25),
        xaxis=dict(tickformat="%H:%M"),
        yaxis=dict(range=[y_min, y_max]),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
        ),
    )
    st.plotly_chart(fig, width="stretch")

  # Chart Pattern Detection
  st.markdown("---")
  st.subheader("📊 Chart Pattern Detection")
  p_data = session_hist[["High", "Low", "Close"]].copy().dropna()
  patterns = []
  if len(p_data) >= 20:
    hi, lo = p_data["High"].values, p_data["Low"].values
    if max(hi[-5:]) > max(hi[-10:-5]) and min(lo[-5:]) > min(lo[-10:-5]):
      patterns.append(
          ("UPWARD BIAS", "Recent 5-bar range is above prior range.", "green")
      )
    elif max(hi[-5:]) < max(hi[-10:-5]) and min(lo[-5:]) < min(lo[-10:-5]):
      patterns.append(
          ("DOWNWARD BIAS", "Recent 5-bar range is below prior range.", "red")
      )

    if lo[-20:].min() > 0:
      rng_p = (hi[-20:].max() - lo[-20:].min()) / lo[-20:].min() * 100
      if rng_p < 0.5:
        patterns.append(
            ("CONSOLIDATION", "Recent price range is narrow.", "orange")
        )

  if patterns:
    for name, desc, col in patterns:
      if col == "green":
        st.success(f"{name}: {desc}")
      elif col == "red":
        st.error(f"{name}: {desc}")
      else:
        st.warning(f"{name}: {desc}")
  else:
    st.caption("No clear short-term chart pattern detected.")

  # Technical Indicators
  st.markdown("---")
  st.subheader("📊 Technical Indicators (Intraday)")
  i1, i2, i3, i4 = st.columns(4)
  i1.metric(
      "EMA 9",
      f"₹{ema9_val:,.2f}",
      "Above" if spot_price > ema9_val else "Below",
  )
  i2.metric(
      "EMA 21",
      f"₹{ema21_val:,.2f}",
      "Above" if spot_price > ema21_val else "Below",
  )
  i3.metric(
      "VWAP",
      f"₹{vwap_val:,.2f}",
      "Above" if spot_price > vwap_val else "Below",
  )
  rsi_st = (
      "Overbought"
      if rsi_val >= 70
      else ("Oversold" if rsi_val <= 30 else "Neutral")
  )
  i4.metric("RSI (Wilder)", f"{rsi_val:.2f}", rsi_st)

  st.markdown("---")
  st.subheader("🌐 வர்த்தக செய்திகள்")
  for item in get_news():
    st.markdown(item)

  st.caption(
      "Data source: Yahoo Finance via yfinance. Quotes may be delayed. For"
      " analysis only; not financial advice."
  )

except StopException:
  raise
except Exception as e:
  st.exception(e)
  st.stop()
  
