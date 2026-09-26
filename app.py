import feedparser
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf

st.set_page_config(
    page_title="Nifty Monitor & Strategy",
    layout="wide",
)

st_autorefresh(
    interval=30 * 1000,
    key="refresh",
)

st.title("🦅 NIFTY 50 - Smart Money & Market Monitor")


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

    avg_gain = gains.rolling(
        window=window,
        min_periods=window,
    ).mean()

    avg_loss = losses.rolling(
        window=window,
        min_periods=window,
    ).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    rsi = rsi.mask(
        (avg_loss == 0) & (avg_gain > 0),
        100.0,
    )

    rsi = rsi.mask(
        (avg_gain == 0) & (avg_loss > 0),
        0.0,
    )

    rsi = rsi.mask(
        (avg_gain == 0) & (avg_loss == 0),
        50.0,
    )

    return rsi


def normalize_timezone(data):
    data = data.copy()
    data.index = pd.to_datetime(data.index)

    if data.index.tz is not None:
        data.index = data.index.tz_convert("Asia/Kolkata")
    else:
        data.index = data.index.tz_localize("Asia/Kolkata")

    return data


def estimate_option_premium(spot, strike, option_type):
    distance = (spot - strike) / 50.0

    if option_type == "CE":
        premium = 180.0 + (distance * 45)
    else:
        premium = 175.0 - (distance * 45)

    return round(max(5.0, premium), 2)


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
                (float(exit_price) - trade["entry"])
                * trade["qty"],
                2,
            )
            trade["status"] = "CLOSED"
            break


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
def get_nifty50_breadth():
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

    stocks = []

    for symbol in symbols:
        try:
            history = yf.Ticker(symbol).history(
                period="2d",
                interval="1d",
            )

            if len(history) < 2:
                continue

            current = float(history["Close"].iloc[-1])
            previous = float(history["Close"].iloc[-2])

            if previous <= 0:
                continue

            change = ((current - previous) / previous) * 100

            stocks.append({
                "Symbol": symbol.replace(".NS", ""),
                "LTP": round(current, 2),
                "Change%": round(change, 2),
            })

        except Exception:
            continue

    if stocks:
        return stocks, None

    return None, "Breadth data unavailable"


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
            history = yf.Ticker(symbol).history(
                period="2d",
                interval="1d",
            )

            if len(history) < 2:
                continue

            current = float(history["Close"].iloc[-1])
            previous = float(history["Close"].iloc[-2])

            if previous <= 0:
                continue

            change = ((current - previous) / previous) * 100
            result[name] = round(change, 2)

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

    for url in feeds:
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=2,
            )

            if response.status_code != 200:
                continue

            parsed = feedparser.parse(response.content)

            for entry in parsed.entries[:3]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "")

                if not title:
                    continue

                if link:
                    news.append(f"🌐 [{title}]({link})")
                else:
                    news.append(f"🌐 {title}")

            if len(news) >= 6:
                break

        except Exception:
            continue

    if news:
        return news[:6]

    return ["🌐 வர்த்தகச் செய்திகள் கிடைக்கவில்லை."]


try:
    hist = get_stock_data("^NSEI", "5d", "5m")
    daily = get_stock_data("^NSEI", "5d", "1d")
    bank_history = get_stock_data("^NSEBANK", "2d", "5m")
    vix_history = get_stock_data("^INDIAVIX", "2d", "5m")

    if hist.empty or daily.empty or len(daily) < 2:
        st.error("Nifty data கிடைக்கவில்லை.")
        st.stop()

    hist = normalize_timezone(hist)
    daily = normalize_timezone(daily)

    today = pd.Timestamp.now(
        tz="Asia/Kolkata"
    ).date()

    hist_dates = pd.Index(hist.index.date)

    if (hist_dates == today).any():
        session_date = today
    else:
        session_date = hist.index[-1].date()

    session_hist = hist[
        hist.index.date == session_date
    ].copy()

    if session_hist.empty:
        st.error("Session data கிடைக்கவில்லை.")
        st.stop()

    spot_price = float(session_hist["Close"].iloc[-1])
    _, nifty_change = get_last_bar_change(session_hist)

    daily_dates = pd.Index(daily.index.date)
    previous_sessions = daily[
        daily_dates < session_date
    ]

    if previous_sessions.empty:
        st.error("Previous session data கிடைக்கவில்லை.")
        st.stop()

    previous_day = previous_sessions.iloc[-1]

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
        session_hist["High"]
        + session_hist["Low"]
        + session_hist["Close"]
    ) / 3

    cumulative_volume = session_hist["Volume"].cumsum()
    cumulative_tpv = (
        typical_price * session_hist["Volume"]
    ).cumsum()

    session_hist["VWAP"] = np.where(
        cumulative_volume > 0,
        cumulative_tpv / cumulative_volume,
        np.nan,
    )

    if session_hist["VWAP"].isna().all():
        session_hist["VWAP"] = session_hist["Close"]

    bank_price, bank_change = get_last_bar_change(bank_history)
    vix_price, vix_change = get_last_bar_change(vix_history)

    ema9 = hist["Close"].ewm(
        span=9,
        adjust=False,
    ).mean().iloc[-1]

    ema21 = hist["Close"].ewm(
        span=21,
        adjust=False,
    ).mean().iloc[-1]

    rsi_series = calculate_rsi(hist["Close"], window=14)

    if pd.notna(rsi_series.iloc[-1]):
        rsi = float(rsi_series.iloc[-1])
    else:
        rsi = 50.0

    vwap = float(session_hist["VWAP"].iloc[-1])

    # Top metrics
    metric_col1, metric_col2, metric_col3 = st.columns(3)

    with metric_col1:
        st.metric(
            "NIFTY 50",
            f"₹{spot_price:,.2f}",
            f"{nifty_change:+.2f}% (5m)"
            if nifty_change is not None
            else "N/A",
        )

    with metric_col2:
        st.metric(
            "BANK NIFTY",
            f"₹{bank_price:,.2f}"
            if bank_price is not None
            else "N/A",
            f"{bank_change:+.2f}% (5m)"
            if bank_change is not None
            else "N/A",
        )

    with metric_col3:
        st.metric(
            "INDIA VIX",
            f"{vix_price:.2f}"
            if vix_price is not None
            else "N/A",
            f"{vix_change:+.2f}% (5m)"
            if vix_change is not None
            else "N/A",
            delta_color="inverse",
        )

    # Strategy
    st.markdown("---")
    st.subheader("Rule-based Market Structure")
    st.caption(
        "Technical alignment only; not a trading recommendation."
    )

    buy_conditions = [
        spot_price > TC,
        spot_price > vwap,
        ema9 > ema21,
        rsi >= 55,
    ]

    sell_conditions = [
        spot_price < BC,
        spot_price < vwap,
        ema9 < ema21,
        rsi <= 45,
    ]

    if all(buy_conditions):
        st.success(
            "Bullish technical alignment detected."
        )
    elif all(sell_conditions):
        st.error(
            "Bearish technical alignment detected."
        )
    else:
        st.info(
            "Mixed conditions: no clear technical alignment."
        )

    # Alerts
    st.markdown("---")
    st.subheader("Live Alerts")

    alert_messages = []

    if ema9 > ema21:
        alert_messages.append(
            "🟢 EMA 9 is above EMA 21."
        )
    else:
        alert_messages.append(
            "🔴 EMA 9 is below EMA 21."
        )

    if spot_price > vwap:
        alert_messages.append(
            "🟢 Price is above session VWAP."
        )
    else:
        alert_messages.append(
            "🔴 Price is below session VWAP."
        )

    if rsi >= 70:
        alert_messages.append(
            f"⚠️ RSI is overbought ({rsi:.1f})."
        )
    elif rsi <= 30:
        alert_messages.append(
            f"🟢 RSI is oversold ({rsi:.1f})."
        )

    if spot_price > pdh:
        alert_messages.append(
            "🚀 Price is above PDH."
        )
    elif spot_price < pdl:
        alert_messages.append(
            "🩸 Price is below PDL."
        )

    for message in alert_messages:
        st.write(message)

    # Breadth
    st.markdown("---")
    st.subheader("Market Breadth - 18-Stock Watchlist")

    breadth_stocks, breadth_error = get_nifty50_breadth()

    if breadth_error or not breadth_stocks:
        st.warning("Breadth data unavailable.")
    else:
        advances = sum(
            1 for stock in breadth_stocks
            if stock["Change%"] > 0.05
        )

        declines = sum(
            1 for stock in breadth_stocks
            if stock["Change%"] < -0.05
        )

        average_change = sum(
            stock["Change%"] for stock in breadth_stocks
        ) / len(breadth_stocks)

        b1, b2, b3 = st.columns(3)
        b1.metric("Advances", advances)
        b2.metric("Declines", declines)
        b3.metric(
            "Average Change",
            f"{average_change:+.2f}%",
        )

        sorted_stocks = sorted(
            breadth_stocks,
            key=lambda x: x["Change%"],
            reverse=True,
        )

        winners, losers = st.columns(2)

        with winners:
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

    # Sectors
    st.markdown("---")
    st.subheader("Sector Performance")

    sector_data = get_sector_data()

    if sector_data:
        sector_cols = st.columns(len(sector_data))

        for index, (sector, change) in enumerate(
            sector_data.items()
        ):
            with sector_cols[index]:
                if change >= 0:
                    st.success(
                        f"{sector}: +{change:.2f}%"
                    )
                else:
                    st.error(
                        f"{sector}: {change:.2f}%"
                    )
    else:
        st.info("Sector data unavailable.")

    # Estimated option model
    st.markdown("---")
    st.subheader(
        "Strike-wise Call vs Put (Estimated Model)"
    )

    st.caption(
        "Illustrative model only; not live NSE option-chain data."
    )

    atm = int(round(spot_price / 50) * 50)
    option_rows = []
    total_call_oi = 0
    total_put_oi = 0

    for strike in [
        atm + (i * 50)
        for i in range(-2, 3)
    ]:
        distance = abs(spot_price - strike)

        call_oi = int(
            max(
                1500000,
                4500000 - (distance * 9000),
            )
        )

        put_oi = int(
            max(
                1400000,
                5200000 - (distance * 8500),
            )
        )

        difference = (spot_price - strike) / 50.0

        call_ltp = round(
            max(5.0, 180.0 + (difference * 45)),
            2,
        )

        put_ltp = round(
            max(5.0, 175.0 - (difference * 45)),
            2,
        )

        total_call_oi += call_oi
        total_put_oi += put_oi

        if put_oi > call_oi * 1.15:
            signal = "🟢 Put Support"
        elif call_oi > put_oi * 1.15:
            signal = "🔴 Call Resistance"
        else:
            signal = "⚖️ Neutral"

        option_rows.append({
            "Strike": f"₹{strike:,}"
            + (" 🎯 ATM" if strike == atm else ""),
            "Call OI": format_lakhs(call_oi),
            "Call LTP": f"₹{call_ltp}",
            "Put LTP": f"₹{put_ltp}",
            "Put OI": format_lakhs(put_oi),
            "Signal": signal,
        })

    model_pcr = (
        total_put_oi / total_call_oi
        if total_call_oi > 0
        else 0
    )

    option_cols = st.columns(3)

    with option_cols[0]:
        st.metric(
            "Model PCR",
            f"{model_pcr:.2f}",
        )

    with option_cols[1]:
        st.metric(
            "Model ATM",
            f"₹{atm:,}",
        )

    with option_cols[2]:
        st.metric(
            "Nifty Spot",
            f"₹{spot_price:,.2f}",
        )

    st.dataframe(
        pd.DataFrame(option_rows),
        hide_index=True,
        use_container_width=True,
    )

    # Paper trading
    st.markdown("---")
    st.subheader("Model-based Paper Trading")

    st.caption(
        "Virtual only. Premium and P&L are illustrative model values."
    )

    paper_left, paper_right = st.columns([1, 2])

    with paper_left:
        with st.form("open_trade_form"):
            selected_strike = st.selectbox(
                "Strike",
                [
                    atm + (i * 50)
                    for i in range(-2, 3)
                ],
                index=2,
            )

            selected_type = st.radio(
                "Type",
                ["CE", "PE"],
                horizontal=True,
            )

            lot_size = st.number_input(
                "Lot size",
                min_value=1,
                value=25,
                step=1,
            )

            lots = st.number_input(
                "Lots",
                min_value=1,
                value=1,
                step=1,
            )

            quantity = int(lot_size * lots)

            entry_price = estimate_option_premium(
                spot_price,
                selected_strike,
                selected_type,
            )

            st.write(
                f"Model premium: ₹{entry_price:,.2f} | "
                f"Units: {quantity}"
            )

            place_trade = st.form_submit_button(
                "Place model trade"
            )

        if place_trade:
            add_paper_trade(
                selected_strike,
                selected_type,
                entry_price,
                quantity,
            )
            st.rerun()

    with paper_right:
        if not st.session_state.paper_trades:
            st.info("No active virtual trades.")
        else:
            rows = []

            for trade in st.session_state.paper_trades:
                current_premium = estimate_option_premium(
                    spot_price,
                    trade["strike"],
                    trade["type"],
                )

                if trade["status"] == "OPEN":
                    pnl = round(
                        (
                            current_premium - trade["entry"]
                        ) * trade["qty"],
                        2,
                    )
                    display_price = current_premium
                else:
                    pnl = trade["pnl"]
                    display_price = trade["exit"]

                rows.append({
                    "ID": trade["id"],
                    "Trade": f"{trade['strike']} {trade['type']}",
                    "Entry": f"₹{trade['entry']:.2f}",
                    "Qty": trade["qty"],
                    "LTP / Exit": f"₹{display_price:.2f}",
                    "P&L": f"₹{pnl:+,.2f}",
                    "Status": trade["status"],
                })

            st.dataframe(
                pd.DataFrame(rows),
                hide_index=True,
                use_container_width=True,
            )

            open_trades = [
                trade
                for trade in st.session_state.paper_trades
                if trade["status"] == "OPEN"
            ]

            if open_trades:
                with st.form("close_trade_form"):
                    trade_id = st.selectbox(
                        "Select trade",
                        [trade["id"] for trade in open_trades],
                    )

                    close_trade = st.form_submit_button(
                        "Close trade"
                    )

       
