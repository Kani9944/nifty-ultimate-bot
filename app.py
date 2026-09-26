import feedparser
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf


st.set_page_config(
    page_title="Nifty Monitor",
    layout="wide",
)

st_autorefresh(
    interval=30000,
    key="nifty_refresh",
)

st.title("🦅 NIFTY 50 - Smart Money & Market Monitor")


def to_ist(data):
    output = data.copy()
    output.index = pd.to_datetime(
        output.index
    )

    if output.index.tz is not None:
        output.index = output.index.tz_convert(
            "Asia/Kolkata"
        )
    else:
        output.index = output.index.tz_localize(
            "Asia/Kolkata"
        )

    return output


def get_last_change(data):
    if data is None or len(data) < 2:
        return None, None

    current = float(
        data["Close"].iloc[-1]
    )

    previous = float(
        data["Close"].iloc[-2]
    )

    if previous == 0:
        return current, None

    change = (
        (current - previous)
        / previous
        * 100
    )

    return current, change


def get_rsi(close, period=14):
    delta = close.diff()

    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = gains.rolling(
        window=period,
        min_periods=period,
    ).mean()

    avg_loss = losses.rolling(
        window=period,
        min_periods=period,
    ).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    rsi = rsi.mask(
        (avg_loss == 0)
        & (avg_gain > 0),
        100.0,
    )

    rsi = rsi.mask(
        (avg_gain == 0)
        & (avg_loss > 0),
        0.0,
    )

    rsi = rsi.mask(
        (avg_gain == 0)
        & (avg_loss == 0),
        50.0,
    )

    return rsi


@st.cache_data(ttl=25)
def get_history(symbol, period, interval=None):
    ticker = yf.Ticker(symbol)

    if interval:
        return ticker.history(
            period=period,
            interval=interval,
        )

    return ticker.history(
        period=period,
    )


@st.cache_data(ttl=120)
def get_heavyweights():
    symbols = [
        "RELIANCE.NS",
        "TCS.NS",
        "HDFCBANK.NS",
        "INFY.NS",
        "ICICIBANK.NS",
        "HINDUNILVR.NS",
        "ITC.NS",
        "SBIN.NS",
        "BHARTIARTL.NS",
        "KOTAKBANK.NS",
        "LT.NS",
        "AXISBANK.NS",
        "BAJFINANCE.NS",
        "ASIANPAINT.NS",
        "MARUTI.NS",
        "TITAN.NS",
    ]

    results = []

    for symbol in symbols:
        try:
            data = yf.Ticker(
                symbol
            ).history(
                period="2d",
                interval="1d",
            )

            if len(data) < 2:
                continue

            current = float(
                data["Close"].iloc[-1]
            )

            previous = float(
                data["Close"].iloc[-2]
            )

            if previous <= 0:
                continue

            change = (
                (current - previous)
                / previous
                * 100
            )

            results.append({
                "Symbol": symbol.replace(
                    ".NS",
                    "",
                ),
                "LTP": round(current, 2),
                "Change%": round(change, 2),
            })

        except Exception:
            continue

    return results


@st.cache_data(ttl=300)
def get_news():
    feeds = [
        "https://tamil.goodreturns.in/rss/feeds/tamil-money-news-fb.xml",
        "https://www.moneycontrol.com/rss/marketreports.xml",
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    ]

    result = []

    for url in feeds:
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                },
                timeout=2,
            )

            if response.status_code != 200:
                continue

            feed = feedparser.parse(
                response.content
            )

            for entry in feed.entries[:3]:
                title = entry.get(
                    "title",
                    "",
                ).strip()

                link = entry.get(
                    "link",
                    "",
                )

                if not title:
                    continue

                if link:
                    result.append(
                        f"📰 [{title}]({link})"
                    )
                else:
                    result.append(
                        f"📰 {title}"
                    )

            if len(result) >= 6:
                break

        except Exception:
            continue

    if result:
        return result[:6]

    return [
        "📰 Market news தற்போது கிடைக்கவில்லை."
    ]


try:
    nifty = get_history(
        "^NSEI",
        "5d",
        "5m",
    )

    daily = get_history(
        "^NSEI",
        "5d",
        "1d",
    )

    bank_nifty = get_history(
        "^NSEBANK",
        "2d",
        "5m",
    )

    india_vix = get_history(
        "^INDIAVIX",
        "2d",
        "5m",
    )

    if nifty.empty or daily.empty:
        st.error(
            "Nifty data கிடைக்கவில்லை. "
            "சில நிமிடங்கள் கழித்து முயற்சிக்கவும்."
        )
        st.stop()

    if len(daily) < 2:
        st.error(
            "CPR கணக்கிட போதுமான daily data கிடைக்கவில்லை."
        )
        st.stop()

    nifty = to_ist(nifty)
    daily = to_ist(daily)

    today = pd.Timestamp.now(
        tz="Asia/Kolkata"
    ).date()

    if (
        nifty.index.date == today
    ).any():
        active_date = today
    else:
        active_date = nifty.index[-1].date()

    session = nifty[
        nifty.index.date == active_date
    ].copy()

    if session.empty:
        st.error("Session data கிடைக்கவில்லை.")
        st.stop()

    spot = float(
        session["Close"].iloc[-1]
    )

    _, nifty_change = get_last_change(
        session
    )

    old_sessions = daily[
        daily.index.date < active_date
    ]

    if old_sessions.empty:
        st.error(
            "Previous session data கிடைக்கவில்லை."
        )
        st.stop()

    previous_day = old_sessions.iloc[-1]

    pdh = float(
        previous_day["High"]
    )

    pdl = float(
        previous_day["Low"]
    )

    pdc = float(
        previous_day["Close"]
    )

    pivot = (
        pdh + pdl + pdc
    ) / 3

    bc_raw = (
        pdh + pdl
    ) / 2

    tc_raw = (
        2 * pivot
    ) - bc_raw

    BC = min(
        bc_raw,
        tc_raw,
    )

    TC = max(
        bc_raw,
        tc_raw,
    )

    R1 = (
        2 * pivot
    ) - pdl

    S1 = (
        2 * pivot
    ) - pdh

    R2 = pivot + (
        pdh - pdl
    )

    S2 = pivot - (
        pdh - pdl
    )

    typical = (
        session["High"]
        + session["Low"]
        + session["Close"]
    ) / 3

    cumulative_volume = session[
        "Volume"
    ].cumsum()

    cumulative_value = (
        typical * session["Volume"]
    ).cumsum()

    session["VWAP"] = np.where(
        cumulative_volume > 0,
        cumulative_value
        / cumulative_volume,
        np.nan,
    )

    if session["VWAP"].isna().all():
        session["VWAP"] = session["Close"]

    vwap = float(
        session["VWAP"].iloc[-1]
    )

    bank_price, bank_change = get_last_change(
        bank_nifty
    )

    vix_price, vix_change = get_last_change(
        india_vix
    )

    ema9 = float(
        nifty["Close"].ewm(
            span=9,
            adjust=False,
        ).mean().iloc[-1]
    )

    ema21 = float(
        nifty["Close"].ewm(
            span=21,
            adjust=False,
        ).mean().iloc[-1]
    )

    rsi_series = get_rsi(
        nifty["Close"],
        14,
    )

    if pd.notna(rsi_series.iloc[-1]):
        rsi = float(
            rsi_series.iloc[-1]
        )
    else:
        rsi = 50.0

    st.caption(
        f"Session: "
        f"{active_date.strftime('%d-%b-%Y')} | "
        f"Last Nifty bar: "
        f"{session.index[-1].strftime('%H:%M IST')} | "
        "Yahoo Finance feed may be delayed."
    )

    top_1, top_2, top_3 = st.columns(3)

    with top_1:
        st.metric(
            "NIFTY 50",
            f"₹{spot:,.2f}",
            (
                f"{nifty_change:+.2f}% (5m)"
                if nifty_change is not None
                else "N/A"
            ),
        )

    with top_2:
        st.metric(
            "BANK NIFTY",
            (
                f"₹{bank_price:,.2f}"
                if bank_price is not None
                else "N/A"
            ),
            (
                f"{bank_change:+.2f}% (5m)"
                if bank_change is not None
                else "N/A"
            ),
        )

    with top_3:
        st.metric(
            "INDIA VIX",
            (
                f"{vix_price:.2f}"
                if vix_price is not None
                else "N/A"
            ),
            (
                f"{vix_change:+.2f}% (5m)"
                if vix_change is not None
                else "N/A"
            ),
            delta_color="inverse",
        )

    st.markdown("---")
    st.subheader("Rule-based Market Structure")

    bullish = [
        spot > TC,
        spot > vwap,
        ema9 > ema21,
        rsi >= 55,
    ]

    bearish = [
        spot < BC,
        spot < vwap,
        ema9 < ema21,
        rsi <= 45,
    ]

    if all(bullish):
        st.success(
            "🟢 Bullish technical alignment."
        )

    elif all(bearish):
        st.error(
            "🔴 Bearish technical alignment."
        )

    else:
        st.info(
            "🟡 Mixed conditions: "
            "no clear technical alignment."
        )

    st.caption(
        "Technical analysis only; "
        "not a trading recommendation."
    )

    st.markdown("---")
    st.subheader("Live Alerts")

    if ema9 > ema21:
        st.write(
            "🟢 EMA 9 is above EMA 21."
        )
    else:
        st.write(
            "🔴 EMA 9 is below EMA 21."
        )

    if spot > vwap:
        st.write(
            "🟢 Price is above session VWAP."
        )
    else:
        st.write(
            "🔴 Price is below session VWAP."
        )

    if rsi >= 70:
        st.write(
            f"⚠️ RSI overbought: {rsi:.1f}"
        )

    elif rsi <= 30:
        st.write(
            f"🟢 RSI oversold: {rsi:.1f}"
        )

    if spot > pdh:
        st.write(
            f"🚀 PDH breakout above ₹{pdh:,.2f}"
        )

    elif spot < pdl:
        st.write(
            f"🩸 PDL breakdown below ₹{pdl:,.2f}"
        )

    st.markdown("---")
    st.subheader("CPR & Pivot Levels")

    level_1, level_2, level_3 = st.columns(3)

    with level_1:
        st.metric(
            "PDH",
            f"₹{pdh:,.2f}",
        )

        st.metric(
            "R2",
            f"₹{R2:,.2f}",
        )

        st.metric(
            "R1",
            f"₹{R1:,.2f}",
        )

    with level_2:
        st.metric(
            "TC",
            f"₹{TC:,.2f}",
        )

        st.metric(
            "Pivot",
            f"₹{pivot:,.2f}",
        )

        st.metric(
            "BC",
            f"₹{BC:,.2f}",
        )

    with level_3:
        st.metric(
            "S1",
            f"₹{S1:,.2f}",
        )

        st.metric(
            "S2",
            f"₹{S2:,.2f}",
        )

        st.metric(
            "PDL",
            f"₹{pdl:,.2f}",
        )

    st.markdown("---")
    st.subheader(
        "🏢 Nifty Heavyweights "
        "- Top Gainers & Losers"
    )

    heavyweight_data = get_heavyweights()

    if heavyweight_data:
        sorted_heavyweights = sorted(
            heavyweight_data,
            key=lambda item: item["Change%"],
            reverse=True,
        )

        gainers, losers = st.columns(2)

        with gainers:
            st.markdown("### 🟢 Top Gainers")

            for stock in sorted_heavyweights[:5]:
                st.write(
                    f"**{stock['Symbol']}** — "
                    f"₹{stock['LTP']:,.2f} "
                    f"({stock['Change%']:+.2f}%)"
                )

        with losers:
            st.markdown("### 🔴 Top Losers")

            for stock in sorted_heavyweights[-5:][::-1]:
                st.write(
                    f"**{stock['Symbol']}** — "
                    f"₹{stock['LTP']:,.2f} "
                    f"({stock['Change%']:+.2f}%)"
                )

    else:
        st.warning(
            "Heavyweight data unavailable."
        )

    st.markdown("---")
    st.subheader(
        "📈 NIFTY Intraday Chart - "
        "Price, VWAP & CPR"
    )

    chart_data = session[
        ["Close", "VWAP"]
    ].copy()

    chart_data = chart_data.replace(
        [np.inf, -np.inf],
        np.nan,
    )

    chart_data = chart_data.dropna(
        subset=["Close"]
    )

    chart_data = chart_data[
        chart_data["Close"] > 0
    ].copy()

    if chart_data.empty:
        st.warning(
            "Chart data unavailable."
        )

    else:
        values = (
            chart_data["Close"]
            .dropna()
            .tolist()
            + chart_data["VWAP"]
            .dropna()
            .tolist()
            + [
                pdh,
                pdl,
                R1,
                S1,
                BC,
                TC,
                pivot,
            ]
        )

        valid_values = [
            float(value)
            for value in values
            if pd.notna(value)
            and np.isfinite(value)
            and abs(
                float(value) - spot
            ) <= 400
        ]

        if valid_values:
            low = min(valid_values)
            high = max(valid_values)

            padding = max(
                25.0,
                (high - low) * 0.10,
            )

            y_range = [
                low - padding,
                high + padding,
            ]

        else:
            y_range = [
                spot - 250,
                spot + 250,
            ]

        chart = go.Figure()

        chart.add_hrect(
            y0=BC,
            y1=TC,
            fillcolor="LightSkyBlue",
            opacity=0.15,
            line_width=0,
            layer="below",
        )

        chart.add_trace(
            go.Scatter(
                x=chart_data.index,
                y=chart_data["Close"],
                mode="lines",
                name="Price",
                line=dict(
                    color="#0052cc",
                    width=2.5,
                ),
            )
        )

        chart.add_trace(
            go.Scatter(
                x=chart_data.index,
                y=chart_data["VWAP"],
                mode="lines",
                name="VWAP",
                line=dict(
                    color="#ff9900",
                    width=1.8,
                    dash="dash",
                ),
            )
        )

        levels = [
            (
                "PDH",
                pdh,
                "#cc0000",
                "solid",
            ),
            (
                "R1",
                R1,
                "#ff6666",
                "dot",
            ),
            (
                "TC",
                TC,
                "#66b3ff",
                "dot",
            ),
            (
                "Pivot",
                pivot,
                "#0066cc",
                "dash",
            ),
            (
                "BC",
                BC,
                "#3399ff",
                "dot",
            ),
            (
                "S1",
                S1,
                "#66cc66",
                "dot",
            ),
            (
                "PDL",
                pdl,
                "#00b300",
                "solid",
            ),
        ]

        start_time = chart_data.index[0]
        end_time = chart_data.index[-1]

        for name, price, color, dash in levels:
            chart.add_trace(
                go.Scatter(
                    x=[
                        start_time,
                        end_time,
                    ],
                    y=[
                        price,
                        price,
                    ],
                    mode="lines",
                    name=name,
                    line=dict(
                        color=color,
                        width=1,
                        dash=dash,
                    ),
                )
            )

        chart.update_layout(
            height=450,
            margin=dict(
                l=10,
                r=10,
                t=35,
                b=35,
            ),
            xaxis=dict(
                title="Time (IST)",
                tickformat="%H:%M",
            ),
            yaxis=dict(
                title="Price (₹)",
                range=y_range,
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
            hovermode="x unified",
        )

        st.plotly_chart(
            chart,
            use_container_width=True,
        )

    st.markdown("---")
    st.subheader("Technical Indicators")

    i1, i2, i3, i4 = st.columns(4)

    with i1:
        st.metric(
            "EMA 9",
            f"₹{ema9:,.2f}",
        )

    with i2:
        st.metric(
            "EMA 21",
            f"₹{ema21:,.2f}",
        )

    with i3:
        st.metric(
            "Session VWAP",
            f"₹{vwap:,.2f}",
        )

    with i4:
        st.metric(
            "RSI (14)",
            f"{rsi:.2f}",
        )

    st.markdown("---")
    st.subheader("🌐 Market News")

    for item in get_news():
        st.markdown(item)

    st.caption(
        "Data source: Yahoo Finance via yfinance. "
        "Quotes may be delayed or unavailable. "
        "This dashboard is for educational "
        "and analysis use only."
    )

except Exception:
    st.error(
        "டேஷ்போர்டை புதுப்பிப்பதில் தற்காலிகச் சிக்கல். "
        "சில நிமிடங்கள் கழித்து மீண்டும் முயற்சிக்கவும்."
    )
    st.stop()
