import feedparser
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf


# =========================================================
# PAGE SETUP
# =========================================================
st.set_page_config(
    page_title="Nifty Monitor & Strategy",
    layout="wide",
)

st_autorefresh(
    interval=30 * 1000,
    key="nifty_refresh",
)

st.title("🦅 NIFTY 50 - Smart Money & Market Monitor")


# =========================================================
# HELPERS
# =========================================================
def format_lakhs(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)

    if value >= 10000000:
        return f"{value / 10000000:.2f} Cr"

    if value >= 100000:
        return f"{value / 100000:.2f} L"

    if value >= 1000:
        return f"{value / 1000:.1f} K"

    return f"{value:,.0f}"


def get_last_bar_change(data):
    if data is None or len(data) < 2:
        return None, None

    current = float(data["Close"].iloc[-1])
    previous = float(data["Close"].iloc[-2])

    if previous == 0:
        return current, None

    change = ((current - previous) / previous) * 100
    return current, change


def calculate_rsi(close, window=14):
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    average_gain = gains.rolling(
        window=window,
        min_periods=window,
    ).mean()

    average_loss = losses.rolling(
        window=window,
        min_periods=window,
    ).mean()

    rs = average_gain / average_loss
    rsi = 100 - (100 / (1 + rs))

    rsi = rsi.mask(
        (average_loss == 0) & (average_gain > 0),
        100.0,
    )

    rsi = rsi.mask(
        (average_gain == 0) & (average_loss > 0),
        0.0,
    )

    rsi = rsi.mask(
        (average_gain == 0) & (average_loss == 0),
        50.0,
    )

    return rsi


def normalize_timezone(data):
    output = data.copy()
    output.index = pd.to_datetime(output.index)

    if output.index.tz is not None:
        output.index = output.index.tz_convert(
            "Asia/Kolkata"
        )
    else:
        output.index = output.index.tz_localize(
            "Asia/Kolkata"
        )

    return output


def estimate_option_premium(spot, strike, option_type):
    distance = (spot - strike) / 50.0

    if option_type == "CE":
        premium = 180.0 + (distance * 45)
    else:
        premium = 175.0 - (distance * 45)

    return round(max(5.0, premium), 2)


# =========================================================
# PAPER TRADING STATE
# =========================================================
if "paper_trades" not in st.session_state:
    st.session_state.paper_trades = []

if "paper_trade_next_id" not in st.session_state:
    st.session_state.paper_trade_next_id = 1


def add_paper_trade(strike, option_type, entry_price, quantity):
    trade_id = st.session_state.paper_trade_next_id

    st.session_state.paper_trades.append({
        "id": trade_id,
        "strike": int(strike),
        "type": option_type,
        "entry": float(entry_price),
        "qty": int(quantity),
        "exit": None,
        "pnl": 0.0,
        "status": "OPEN",
    })

    st.session_state.paper_trade_next_id += 1


def close_paper_trade(trade_id, exit_price):
    for trade in st.session_state.paper_trades:
        if (
            trade["id"] == trade_id
            and trade["status"] == "OPEN"
        ):
            trade["exit"] = float(exit_price)
            trade["pnl"] = round(
                (
                    float(exit_price)
                    - trade["entry"]
                )
                * trade["qty"],
                2,
            )
            trade["status"] = "CLOSED"
            break


# =========================================================
# DATA FUNCTIONS
# =========================================================
@st.cache_data(ttl=25)
def get_stock_data(symbol, period, interval=None):
    ticker = yf.Ticker(symbol)

    if interval:
        return ticker.history(
            period=period,
            interval=interval,
        )

    return ticker.history(period=period)


@st.cache_data(ttl=120)
def get_breadth_data():
    symbols = [
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

    result = []

    for symbol in symbols:
        try:
            stock_data = yf.Ticker(symbol).history(
                period="2d",
                interval="1d",
            )

            if len(stock_data) < 2:
                continue

            current = float(
                stock_data["Close"].iloc[-1]
            )

            previous = float(
                stock_data["Close"].iloc[-2]
            )

            if previous <= 0:
                continue

            percent_change = (
                (current - previous)
                / previous
                * 100
            )

            result.append({
                "Symbol": symbol.replace(".NS", ""),
                "LTP": round(current, 2),
                "Change%": round(percent_change, 2),
            })

        except Exception:
            continue

    if result:
        return result

    return []


@st.cache_data(ttl=120)
def get_sector_data():
    sectors = {
        "Bank": "^NSEBANK",
        "IT": "^CNXIT",
        "Auto": "^CNXAUTO",
        "Pharma": "^CNXPHARMA",
        "FMCG": "^CNXFMCG",
        "Metal": "^CNXMETAL",
    }

    result = {}

    for name, symbol in sectors.items():
        try:
            sector_history = yf.Ticker(
                symbol
            ).history(
                period="2d",
                interval="1d",
            )

            if len(sector_history) < 2:
                continue

            current = float(
                sector_history["Close"].iloc[-1]
            )

            previous = float(
                sector_history["Close"].iloc[-2]
            )

            if previous <= 0:
                continue

            result[name] = round(
                (
                    (current - previous)
                    / previous
                    * 100
                ),
                2,
            )

        except Exception:
            continue

    return result


@st.cache_data(ttl=300)
def get_market_news():
    feeds = [
        "https://tamil.goodreturns.in/rss/feeds/tamil-money-news-fb.xml",
        "https://www.moneycontrol.com/rss/marketreports.xml",
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    ]

    news = []

    for feed_url in feeds:
        try:
            response = requests.get(
                feed_url,
                headers={
                    "User-Agent": "Mozilla/5.0"
                },
                timeout=2,
            )

            if response.status_code != 200:
                continue

            parsed_feed = feedparser.parse(
                response.content
            )

            for entry in parsed_feed.entries[:3]:
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
                    news.append(
                        f"🌐 [{title}]({link})"
                    )
                else:
                    news.append(
                        f"🌐 {title}"
                    )

            if len(news) >= 6:
                break

        except Exception:
            continue

    if news:
        return news[:6]

    return [
        "🌐 வர்த்தகச் செய்திகள் தற்போது கிடைக்கவில்லை."
    ]


# =========================================================
# MAIN DASHBOARD
# =========================================================
try:
    nifty_history = get_stock_data(
        "^NSEI",
        "5d",
        "5m",
    )

    nifty_daily = get_stock_data(
        "^NSEI",
        "5d",
        "1d",
    )

    bank_nifty_history = get_stock_data(
        "^NSEBANK",
        "2d",
        "5m",
    )

    india_vix_history = get_stock_data(
        "^INDIAVIX",
        "2d",
        "5m",
    )

    if (
        nifty_history.empty
        or nifty_daily.empty
        or len(nifty_daily) < 2
    ):
        st.error(
            "Nifty market data தற்போது கிடைக்கவில்லை. "
            "சில நிமிடங்கள் கழித்து மீண்டும் முயற்சிக்கவும்."
        )
        st.stop()

    nifty_history = normalize_timezone(
        nifty_history
    )

    nifty_daily = normalize_timezone(
        nifty_daily
    )

    now_ist = pd.Timestamp.now(
        tz="Asia/Kolkata"
    )

    today_ist = now_ist.date()

    if (nifty_history.index.date == today_ist).any():
        active_session_date = today_ist
    else:
        active_session_date = nifty_history.index[
            -1
        ].date()

    session_history = nifty_history[
        nifty_history.index.date
        == active_session_date
    ].copy()

    if session_history.empty:
        st.error(
            "தேர்ந்தெடுக்கப்பட்ட session data கிடைக்கவில்லை."
        )
        st.stop()

    spot_price = float(
        session_history["Close"].iloc[-1]
    )

    _, nifty_change_5m = get_last_bar_change(
        session_history
    )

    prior_sessions = nifty_daily[
        nifty_daily.index.date
        < active_session_date
    ]

    if prior_sessions.empty:
        st.error(
            "Previous completed session data கிடைக்கவில்லை."
        )
        st.stop()

    previous_day = prior_sessions.iloc[-1]

    pdh = float(previous_day["High"])
    pdl = float(previous_day["Low"])
    pdc = float(previous_day["Close"])

    pivot = (pdh + pdl + pdc) / 3

    bc_raw = (pdh + pdl) / 2
    tc_raw = (2 * pivot) - bc_raw

    BC = min(bc_raw, tc_raw)
    TC = max(bc_raw, tc_raw)

    R1 = (2 * pivot) - pdl
    S1 = (2 * pivot) - pdh

    R2 = pivot + (pdh - pdl)
    S2 = pivot - (pdh - pdl)

    typical_price = (
        session_history["High"]
        + session_history["Low"]
        + session_history["Close"]
    ) / 3

    cumulative_volume = session_history[
        "Volume"
    ].cumsum()

    cumulative_tpv = (
        typical_price
        * session_history["Volume"]
    ).cumsum()

    session_history["VWAP"] = np.where(
        cumulative_volume > 0,
        cumulative_tpv / cumulative_volume,
        np.nan,
    )

    if session_history["VWAP"].isna().all():
        session_history["VWAP"] = session_history[
            "Close"
        ]

    vwap = float(
        session_history["VWAP"].iloc[-1]
    )

    bank_nifty_price, bank_nifty_change = (
        get_last_bar_change(
            bank_nifty_history
        )
    )

    india_vix_price, india_vix_change = (
        get_last_bar_change(
            india_vix_history
        )
    )

    ema9 = float(
        nifty_history["Close"].ewm(
            span=9,
            adjust=False,
        ).mean().iloc[-1]
    )

    ema21 = float(
        nifty_history["Close"].ewm(
            span=21,
            adjust=False,
        ).mean().iloc[-1]
    )

    rsi_series = calculate_rsi(
        nifty_history["Close"],
        window=14,
    )

    rsi = float(
        rsi_series.iloc[-1]
    ) if pd.notna(
        rsi_series.iloc[-1]
    ) else 50.0

    # -----------------------------------------------------
    # TOP METRICS
    # -----------------------------------------------------
    st.caption(
        f"Active session: {active_session_date.strftime('%d-%b-%Y')} | "
        f"Last Nifty bar: "
        f"{session_history.index[-1].strftime('%H:%M IST')} | "
        "Yahoo Finance data may be delayed."
    )

    metric_1, metric_2, metric_3 = st.columns(3)

    with metric_1:
        st.metric(
            "NIFTY 50",
            f"₹{spot_price:,.2f}",
            (
                f"{nifty_change_5m:+.2f}% (5m)"
                if nifty_change_5m is not None
                else "N/A"
            ),
        )

    with metric_2:
        st.metric(
            "BANK NIFTY",
            (
                f"₹{bank_nifty_price:,.2f}"
                if bank_nifty_price is not None
                else "N/A"
            ),
            (
                f"{bank_nifty_change:+.2f}% (5m)"
                if bank_nifty_change is not None
                else "N/A"
            ),
        )

    with metric_3:
        st.metric(
            "INDIA VIX",
            (
                f"{india_vix_price:.2f}"
                if india_vix_price is not None
                else "N/A"
            ),
            (
                f"{india_vix_change:+.2f}% (5m)"
                if india_vix_change is not None
                else "N/A"
            ),
            delta_color="inverse",
        )

    # -----------------------------------------------------
    # RULE-BASED MARKET STRUCTURE
    # -----------------------------------------------------
    st.markdown("---")
    st.subheader("Rule-based Market Structure")

    st.caption(
        "Technical alignment only; not a trading recommendation."
    )

    bullish_conditions = [
        spot_price > TC,
        spot_price > vwap,
        ema9 > ema21,
        rsi >= 55,
    ]

    bearish_conditions = [
        spot_price < BC,
        spot_price < vwap,
        ema9 < ema21,
        rsi <= 45,
    ]

    if all(bullish_conditions):
        st.success(
            "🟢 Bullish technical alignment: "
            "price is above TC and VWAP, "
            "EMA 9 is above EMA 21, "
            "and RSI is at or above 55."
        )

    elif all(bearish_conditions):
        st.error(
            "🔴 Bearish technical alignment: "
            "price is below BC and VWAP, "
            "EMA 9 is below EMA 21, "
            "and RSI is at or below 45."
        )

    else:
        st.info(
            "🟡 Mixed technical conditions: "
            "no clear alignment currently."
        )

    st.caption(
        f"Reference levels — BC: ₹{BC:,.2f} | "
        f"TC: ₹{TC:,.2f} | "
        f"R1: ₹{R1:,.2f} | "
        f"S1: ₹{S1:,.2f}"
    )

    # -----------------------------------------------------
    # LIVE ALERTS
    # -----------------------------------------------------
    st.markdown("---")
    st.subheader("🔔 Live Alerts")

    alerts = []

    if ema9 > ema21:
        alerts.append(
            "🟢 EMA 9 is above EMA 21."
        )
    else:
        alerts.append(
            "🔴 EMA 9 is below EMA 21."
        )

    if spot_price > vwap:
        alerts.append(
            "🟢 Price is above session VWAP."
        )
    else:
        alerts.append(
            "🔴 Price is below session VWAP."
        )

    if rsi >= 70:
        alerts.append(
            f"⚠️ RSI is overbought ({rsi:.1f})."
        )

    elif rsi <= 30:
        alerts.append(
            f"🟢 RSI is oversold ({rsi:.1f})."
        )

    if spot_price > pdh:
        alerts.append(
            f"🚀 Price is above PDH ₹{pdh:,.2f}."
        )

    elif spot_price < pdl:
        alerts.append(
            f"🩸 Price is below PDL ₹{pdl:,.2f}."
        )

    if (
        india_vix_price is not None
        and india_vix_price >= 18
    ):
        alerts.append(
            f"🚨 Elevated VIX: "
            f"{india_vix_price:.2f}. "
            "Intraday volatility may be higher."
        )

    if alerts:
        for alert in alerts:
            st.write(alert)
    else:
        st.caption(
            "No active technical alerts."
        )

    # -----------------------------------------------------
    # MARKET BREADTH
    # -----------------------------------------------------
    st.markdown("---")
    st.subheader("Market Breadth - 18-Stock Watchlist")

    st.caption(
        "This is a selected Nifty heavyweight watchlist, "
        "not the complete Nifty 50 constituent list."
    )

    breadth_stocks = get_breadth_data()

    if not breadth_stocks:
        st.warning(
            "Market breadth data unavailable."
        )

    else:
        advances = sum(
            1
            for stock in breadth_stocks
            if stock["Change%"] > 0.05
        )

        declines = sum(
            1
            for stock in breadth_stocks
            if stock["Change%"] < -0.05
        )

        average_change = sum(
            stock["Change%"]
            for stock in breadth_stocks
        ) / len(breadth_stocks)

        breadth_col_1, breadth_col_2, breadth_col_3 = (
            st.columns(3)
        )

        with breadth_col_1:
            st.metric(
                "Advances",
                advances,
            )

        with breadth_col_2:
            st.metric(
                "Declines",
                declines,
            )

        with breadth_col_3:
            st.metric(
                "Average Change",
                f"{average_change:+.2f}%",
            )

        sorted_stocks = sorted(
            breadth_stocks,
            key=lambda item: item["Change%"],
            reverse=True,
        )

        gainers, losers = st.columns(2)

        with gainers:
            st.markdown("### Top Gainers")

            for stock in sorted_stocks[:5]:
                st.write(
                    f"**{stock['Symbol']}** — "
                    f"₹{stock['LTP']:,.2f} "
                    f"({stock['Change%']:+.2f}%)"
                )

        with losers:
            st.markdown("### Top Losers")

            for stock in sorted_stocks[-5:][::-1]:
                st.write(
                    f"**{stock['Symbol']}** — "
                    f"₹{stock['LTP']:,.2f} "
                    f"({stock['Change%']:+.2f}%)"
                )

    # -----------------------------------------------------
    # SECTOR PERFORMANCE
    # -----------------------------------------------------
    st.markdown("---")
    st.subheader("Sector Performance")

    sector_data = get_sector_data()

    if sector_data:
        sector_columns = st.columns(
            len(sector_data)
        )

        for index, (sector, change) in enumerate(
            sector_data.items()
        ):
            with sector_columns[index]:
                if change >= 0:
                    st.success(
                        f"{sector}: +{change:.2f}%"
                    )
                else:
                    st.error(
                        f"{sector}: {change:.2f}%"
                    )

    else:
        st.warning(
            "Sector data unavailable."
        )

    # -----------------------------------------------------
    # ESTIMATED OPTION MODEL
    # -----------------------------------------------------
    st.markdown("---")
    st.subheader(
        "Strike-wise Call vs Put (Estimated Model)"
    )

    st.caption(
        "⚠️ Illustrative model only. "
        "This is not live NSE option-chain data. "
        "Model OI, PCR, and option premiums are not actual "
        "market values."
    )

    atm_strike = int(
        round(spot_price / 50) * 50
    )

    option_rows = []
    total_call_oi = 0
    total_put_oi = 0

    strikes = [
        atm_strike + (offset * 50)
        for offset in range(-2, 3)
    ]

    for strike in strikes:
        distance = abs(
            spot_price - strike
        )

        call_oi = int(
            max(
                1500000,
                4500000 - (distance * 9000),
            )
        )

        put_oi = int(
            max(
                1400000,
                5200000 - (distance
