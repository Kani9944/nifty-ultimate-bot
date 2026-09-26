import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf

st.set_page_config(page_title="Nifty Monitor", layout="wide")
st_autorefresh(interval=30 * 1000, key="refresh")
st.title("NIFTY 50 - Smart Money & Market Monitor")


@st.cache_data(ttl=25)
def get_stock_data(symbol, period, interval=None):
    ticker = yf.Ticker(symbol)
    if interval:
        return ticker.history(period=period, interval=interval)
    return ticker.history(period=period)


@st.cache_data(ttl=60)
def get_nse_session():
    try:
        session = requests.Session()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
        }
        session.headers.update(headers)
        session.get("https://www.nseindia.com/", timeout=10)
        return session, None
    except Exception as e:
        return None, str(e)


def init_paper_trades():
    if "paper_trades" not in st.session_state:
        st.session_state.paper_trades = []


# Nifty-ன் தற்போதைய லாட் அளவு 25
def add_paper_trade(strike, opt_type, entry_price, qty=25):
    st.session_state.paper_trades.append(
        {
            "id": len(st.session_state.paper_trades) + 1,
            "strike": strike,
            "type": opt_type,
            "entry": entry_price,
            "qty": qty,
            "exit": None,
            "pnl": 0.0,
            "status": "OPEN",
        }
    )


def close_paper_trade(trade_id, exit_price):
    for t in st.session_state.paper_trades:
        if t["id"] == trade_id and t["status"] == "OPEN":
            t["exit"] = exit_price
            t["pnl"] = (exit_price - t["entry"]) * t["qty"]
            t["status"] = "CLOSED"
            break


def calc_paper_pnl():
    closed = [
        t for t in st.session_state.paper_trades if t.get("status") == "CLOSED"
    ]
    if not closed:
        return 0.0, 0, 0
    wins = sum(1 for t in closed if t.get("pnl", 0) > 0)
    losses = sum(1 for t in closed if t.get("pnl", 0) < 0)
    total = sum(t.get("pnl", 0.0) for t in closed)
    return total, wins, losses


def to_csv_download(df, filename, label="Download CSV"):
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label=label,
        data=csv,
        file_name=filename,
        mime="text/csv",
    )


@st.cache_data(ttl=60)
def get_nifty50_breadth():
    session, err = get_nse_session()
    if session is None:
        return None, err
    try:
        r = session.get(
            "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050",
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        stocks = []
        for item in data.get("data", []):
            symbol = item.get("symbol", "")
            if symbol in ("NIFTY 50", "NIFTY", ""):
                continue
            ltp = item.get("lastPrice", 0)
            if ltp > 0:
                stocks.append(
                    {
                        "Symbol": symbol,
                        "LTP": float(ltp),
                        "Change%": float(item.get("pChange", 0)),
                    }
                )
        return stocks, None
    except Exception as e:
        return None, str(e)


# ============ MAIN APP ============
try:
    hist = get_stock_data("^NSEI", "5d", "5m")
    daily = get_stock_data("^NSEI", "5d", "1d")

    if hist.empty:
        st.error("Nifty data unavailable.")
        st.stop()

    hist.index = pd.to_datetime(hist.index)
    if hist.index.tz is not None:
        hist.index = hist.index.tz_convert("Asia/Kolkata")
    else:
        hist.index = hist.index.tz_localize("Asia/Kolkata")

    today = pd.Timestamp.now(tz="Asia/Kolkata").date()
    last_date = pd.Timestamp(hist.index[-1]).date()
    session_date = today if (hist.index.date == today).any() else last_date
    session_hist = hist[hist.index.date == session_date].copy()

    if session_hist.empty:
        st.error("No session data.")
        st.stop()

    spot_price = float(session_hist["Close"].iloc[-1])
    st.metric("NIFTY 50", f"Rs {spot_price:,.2f}")

    st.markdown("---")
    st.subheader("Market Breadth - Nifty 50 Live %")

    breadth_stocks, breadth_err = get_nifty50_breadth()

    if breadth_err or not breadth_stocks:
        st.warning(f"Breadth unavailable: {breadth_err}")
    else:
        advances = sum(1 for s in breadth_stocks if s["Change%"] > 0.05)
        declines = sum(1 for s in breadth_stocks if s["Change%"] < -0.05)
        avg_chg = sum(s["Change%"] for s in breadth_stocks) / len(
            breadth_stocks
        )

        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Advances", advances)
        with m2:
            st.metric("Declines", declines)
        with m3:
            st.metric("Avg Change", f"{avg_chg:+.2f}%")

        sorted_stocks = sorted(
            breadth_stocks, key=lambda x: x["Change%"], reverse=True
        )

        g_col, l_col = st.columns(2)
        with g_col:
            st.markdown("### Top 5 Gainers")
            for s in sorted_stocks[:5]:
                st.write(
                    f"{s['Symbol']}: Rs {s['LTP']:,.2f} ({s['Change%']:+.2f}%)"
                )
        with l_col:
            st.markdown("### Top 5 Losers")
            for s in sorted_stocks[-5:][::-1]:
                st.write(
                    f"{s['Symbol']}: Rs {s['LTP']:,.2f} ({s['Change%']:+.2f}%)"
                )

    st.markdown("---")
    st.subheader("Paper Trading (Virtual - No Real Orders)")
    st.caption("Virtual trades only. No real orders.")

    init_paper_trades()
    total_pnl, wins, losses = calc_paper_pnl()

    p1, p2, p3, p4 = st.columns(4)
    with p1:
        st.metric("Total Trades", len(st.session_state.paper_trades))
    with p2:
        st.metric("Wins", wins)
    with p3:
        st.metric("Losses", losses)
    with p4:
        st.metric("Realized P&L", f"Rs {total_pnl:+,.2f}")

    with st.expander("New Virtual Trade"):
        c1, c2, c3 = st.columns(3)
        with c1:
            pt_strike = st.number_input("Strike", value=24000, step=50)
        with c2:
            pt_type = st.selectbox("Type", ["CE", "PE"])
        with c3:
            pt_entry = st.number_input("Entry Price", value=100.0, step=5.0)

        if st.button("Add Trade"):
            add_paper_trade(pt_strike, pt_type, pt_entry)
            st.success("Trade added")
            st.rerun()

    open_trades = [
        t for t in st.session_state.paper_trades if t["status"] == "OPEN"
    ]
    if open_trades:
        with st.expander("Close Open Trade"):
            tc1, tc2 = st.columns(2)
            with tc1:
                trade_opts = {
                    f"ID {t['id']} - {t['strike']} {t['type']} @ {t['entry']}": t[
                        "id"
                    ]
                    for t in open_trades
                }
                selected_label = st.selectbox(
                    "Select Trade", list(trade_opts.keys())
                )
            with tc2:
                exit_price = st.number_input("Exit Price", value=110.0, step=5.0)

            if st.button("Close Trade"):
                close_paper_trade(trade_opts[selected_label], exit_price)
                st.success("Trade closed!")
                st.rerun()

    if st.session_state.paper_trades:
        st.dataframe(
            pd.DataFrame(st.session_state.paper_trades),
            hide_index=True,
            use_container_width=True,
        )

    st.markdown("---")
    st.subheader("Export Data")

    e1, e2 = st.columns(2)
    with e1:
        if breadth_stocks:
            to_csv_download(
                pd.DataFrame(breadth_stocks), "breadth.csv", "Breadth CSV"
            )
    with e2:
        if st.session_state.paper_trades:
            to_csv_download(
                pd.DataFrame(st.session_state.paper_trades),
                "paper_trades.csv",
                "Paper Trades CSV",
            )

    st.success("App loaded successfully!")

except Exception as e:
    st.error(f"Error: {e}")
    
