import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf

# ============ PAGE CONFIG & REFRESH ============
st.set_page_config(page_title="Nifty Monitor", layout="wide")
st_autorefresh(interval=30 * 1000, key="refresh")
st.title("NIFTY 50 - Smart Money & Market Monitor")


# ============ DATA FETCHING FUNCTIONS ============
@st.cache_data(ttl=25)
def get_stock_data(symbol, period, interval=None):
    ticker = yf.Ticker(symbol)
    if interval:
        return ticker.history(period=period, interval=interval)
    return ticker.history(period=period)


@st.cache_data(ttl=120)
def get_nifty50_breadth():
    symbols = [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
        "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
        "LT.NS", "AXISBANK.NS", "BAJFINANCE.NS", "ASIANPAINT.NS", "MARUTI.NS",
        "HCLTECH.NS", "SUNPHARMA.NS", "TITAN.NS", "WIPRO.NS", "ULTRACEMCO.NS",
        "ONGC.NS", "NTPC.NS", "POWERGRID.NS", "M&M.NS", "TATAMOTORS.NS",
        "TATASTEEL.NS", "JSWSTEEL.NS", "ADANIENT.NS", "ADANIPORTS.NS", "COALINDIA.NS"
    ]
    stocks = []
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="2d", interval="1d")
            if len(hist) >= 2:
                curr = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                if prev > 0:
                    pct = ((curr - prev) / prev) * 100
                    stocks.append({
                        "Symbol": sym.replace(".NS", ""),
                        "LTP": round(curr, 2),
                        "Change%": round(pct, 2),
                    })
        except Exception:
            pass
    if not stocks:
        return None, "Yahoo data unavailable"
    return stocks, None


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
    for name, sym in sectors.items():
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d", interval="1d")
            if len(hist) >= 2:
                curr = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                if prev > 0:
                    pct = ((curr - prev) / prev) * 100
                    result[name] = round(pct, 2)
        except Exception:
            pass
    return result


# ============ PAPER TRADING FUNCTIONS ============
def init_paper_trades():
    if "paper_trades" not in st.session_state:
        st.session_state.paper_trades = []


def add_paper_trade(strike, opt_type, entry_price, qty=25):
    st.session_state.paper_trades.append({
        "id": len(st.session_state.paper_trades) + 1,
        "strike": strike,
        "type": opt_type,
        "entry": entry_price,
        "qty": qty,
        "exit": None,
        "pnl": 0.0,
        "status": "OPEN",
    })


def close_paper_trade(trade_id, exit_price):
    for t in st.session_state.paper_trades:
        if t["id"] == trade_id and t["status"] == "OPEN":
            t["exit"] = exit_price
            t["pnl"] = round((exit_price - t["entry"]) * t["qty"], 2)
            t["status"] = "CLOSED"
            break


def calc_paper_pnl():
    closed = [t for t in st.session_state.paper_trades if t.get("status") == "CLOSED"]
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


# ============ MAIN APP ============
try:
    hist = get_stock_data("^NSEI", "5d", "5m")
    daily = get_stock_data("^NSEI", "5d", "1d")

    if hist.empty:
        st.error("Nifty data unavailable.")
        st.stop()

    # Timezone handling
    hist.index = pd.to_datetime(hist.index)
    hist.index = hist.index.tz_convert("Asia/Kolkata") if hist.index.tz is not None else hist.index.tz_localize("Asia/Kolkata")

    daily.index = pd.to_datetime(daily.index)
    daily.index = daily.index.tz_convert("Asia/Kolkata") if daily.index.tz is not None else daily.index.tz_localize("Asia/Kolkata")

    today = pd.Timestamp.now(tz="Asia/Kolkata").date()
    last_date = pd.Timestamp(hist.index[-1]).date()
    session_date = today if (hist.index.date == today).any() else last_date
    session_hist = hist[hist.index.date == session_date].copy()

    if session_hist.empty:
        session_hist = hist.copy()

    spot_price = float(session_hist["Close"].iloc[-1])

    # Previous Day Levels (CPR / Pivot)
    daily_dates = pd.Index(daily.index.date)
    prev_sessions = daily[daily_dates < session_date]

    if not prev_sessions.empty:
        prev_day = prev_sessions.iloc[-1]
        pdh = float(prev_day["High"])
        pdl = float(prev_day["Low"])
        pdc = float(prev_day["Close"])
    else:
        pdh = float(session_hist["High"].max())
        pdl = float(session_hist["Low"].min())
        pdc = float(session_hist["Close"].iloc[0])

    PP = (pdh + pdl + pdc) / 3
    bc_raw = (pdh + pdl) / 2
    tc_raw = (2 * PP) - bc_raw
    BC = min(bc_raw, tc_raw)
    TC = max(bc_raw, tc_raw)
    R1 = (2 * PP) - pdl
    S1 = (2 * PP) - pdh

    # Session VWAP
    typical = (session_hist["High"] + session_hist["Low"] + session_hist["Close"]) / 3
    cum_vol = session_hist["Volume"].cumsum()
    cum_tpv = (typical * session_hist["Volume"]).cumsum()
    session_hist["VWAP"] = np.where(cum_vol > 0, cum_tpv / cum_vol, np.nan)
    if session_hist["VWAP"].isna().all():
        session_hist["VWAP"] = typical.expanding().mean()

    # Metrics Display
    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("NIFTY 50 Spot", f"Rs {spot_price:,.2f}")
    with m2:
        st.metric("Previous Day High (PDH)", f"Rs {pdh:,.2f}")
    with m3:
        st.metric("Previous Day Low (PDL)", f"Rs {pdl:,.2f}")

    # ============ MARKET BREADTH ============
    st.markdown("---")
    st.subheader("Market Breadth - Nifty 50")
    breadth_stocks, breadth_err = get_nifty50_breadth()

    if breadth_err or not breadth_stocks:
        st.warning(f"Breadth unavailable: {breadth_err}")
    else:
        advances = sum(1 for s in breadth_stocks if s["Change%"] > 0.05)
        declines = sum(1 for s in breadth_stocks if s["Change%"] < -0.05)
        avg_chg = sum(s["Change%"] for s in breadth_stocks) / len(breadth_stocks)

        b1, b2, b3 = st.columns(3)
        with b1:
            st.metric("Advances", advances)
        with b2:
            st.metric("Declines", declines)
        with b3:
            st.metric("Avg Change", f"{avg_chg:+.2f}%")

        sorted_stocks = sorted(breadth_stocks, key=lambda x: x["Change%"], reverse=True)
        g_col, l_col = st.columns(2)
        with g_col:
            st.markdown("### Top Gainers")
            for s in sorted_stocks[:5]:
                st.write(f"**{s['Symbol']}**: Rs {s['LTP']:,.2f} (`{s['Change%']:+.2f}%`)")
        with l_col:
            st.markdown("### Top Losers")
            for s in sorted_stocks[-5:][::-1]:
                st.write(f"**{s['Symbol']}**: Rs {s['LTP']:,.2f} (`{s['Change%']:+.2f}%`)")

    # ============ SECTOR HEATMAP ============
    st.markdown("---")
    st.subheader("Sector Performance")
    sector_data = get_sector_data()
    if sector_data:
        cols = st.columns(len(sector_data))
        for i, (name, pct) in enumerate(sector_data.items()):
            with cols[i]:
                if pct >= 0:
                    st.success(f"{name}\n\n+{pct:.2f}%")
                else:
                    st.error(f"{name}\n\n{pct:.2f}%")
    else:
        st.caption("Sector data unavailable.")

    # ============ CHART ============
    st.markdown("---")
    st.subheader("NIFTY Intraday Chart - Price / VWAP / CPR")

    chart_df = session_hist[["Close", "VWAP"]].copy()
    chart_df["Time"] = chart_df.index
    chart_df = chart_df.reset_index(drop=True)

    chart_start = chart_df["Time"].min()
    chart_end = chart_df["Time"].max() + pd.Timedelta(minutes=15)

    levels_data = pd.DataFrame([
        {"Level": "PDH", "Value": float(pdh), "Color": "#cc0000", "Time": chart_start},
        {"Level": "R1", "Value": float(R1), "Color": "#ff9999", "Time": chart_start},
        {"Level": "TC", "Value": float(TC), "Color": "#66b3ff", "Time": chart_start},
        {"Level": "Pivot", "Value": float(PP), "Color": "#0066cc", "Time": chart_start},
        {"Level": "BC", "Value": float(BC), "Color": "#66b3ff", "Time": chart_start},
        {"Level": "S1", "Value": float(S1), "Color": "#85e085", "Time": chart_start},
        {"Level": "PDL", "Value": float(pdl), "Color": "#009900", "Time": chart_start},
    ])

    valid_closes = [x for x in chart_df["Close"] if pd.notna(x) and x > 0]
    valid_vwaps = [x for x in chart_df["VWAP"].dropna() if x > 0]
    valid_levels = [x for x in levels_data["Value"] if x > 0]
    all_prices = valid_closes + valid_vwaps + valid_levels

    if all_prices:
        min_val = float(min(all_prices) - 20)
        max_val = float(max(all_prices) + 20)
    else:
        min_val, max_val = 22000.0, 26000.0

    price_line = (
        alt.Chart(chart_df)
        .mark_line(color="#0052cc", strokeWidth=2.5)
        .encode(
            x=alt.X("Time:T", title="Time (IST)", axis=alt.Axis(format="%H:%M", tickCount=8), scale=alt.Scale(domain=[chart_start, chart_end])),
            y=alt.Y("Close:Q", title="Price (Rs)", scale=alt.Scale(domain=[min_val, max_val])),
            tooltip=[alt.Tooltip("Time:T", format="%d-%b %H:%M"), alt.Tooltip("Close:Q", format=",.2f")],
        )
    )

    vwap_line = (
        alt.Chart(chart_df.dropna(subset=["VWAP"]))
        .mark_line(color="#ff9900", strokeWidth=2.0, strokeDash=[3, 3])
        .encode(
            x=alt.X("Time:T"),
            y=alt.Y("VWAP:Q"),
            tooltip=[alt.Tooltip("Time:T", format="%d-%b %H:%M"), alt.Tooltip("VWAP:Q", format=",.2f")],
        )
    )

    cpr_band_data = pd.DataFrame([{"_Start": chart_start, "_End": chart_end, "_Lower": float(BC), "_Upper": float(TC)}])
    cpr_band = (
        alt.Chart(cpr_band_data)
        .mark_rect(color="#9ecae1", opacity=0.15)
        .encode(x=alt.X("_Start:T"), x2="_End:T", y=alt.Y("_Lower:Q"), y2="_Upper:Q")
    )

    level_rules = (
        alt.Chart(levels_data)
        .mark_rule(strokeDash=[4, 4], strokeWidth=1.2)
        .encode(y=alt.Y("Value:Q"), color=alt.Color("Color:N", scale=None, legend=None))
    )

    level_labels = (
        alt.Chart(levels_data)
        .mark_text(align="left", dx=8, dy=-4, fontSize=11, fontWeight="bold")
        .encode(x=alt.X("Time:T"), y=alt.Y("Value:Q"), text=alt.Text("Level:N"), color=alt.Color("Color:N", scale=None, legend=None))
    )

    latest_bar = chart_df.iloc[[-1]]
    price_dot = (
        alt.Chart(latest_bar)
        .mark_point(color="#0052cc", filled=True, size=80, shape="circle")
        .encode(x=alt.X("Time:T"), y=alt.Y("Close:Q"))
    )

    final_chart = (cpr_band + level_rules + price_line + vwap_line + price_dot + level_labels).resolve_scale(
        x="shared", y="shared"
    ).properties(height=420, title="NIFTY Intraday - Price, VWAP, CPR")

    st.altair_chart(final_chart, use_container_width=True)

    # ============ PAPER TRADING ============
    st.markdown("---")
    st.subheader("Paper Trading (Virtual)")

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
            pt_strike = st.number_input("Strike", value=int(round(spot_price / 50) * 50), step=50)
        with c2:
            pt_type = st.selectbox("Type", ["CE", "PE"])
        with c3:
            pt_entry = st.number_input("Entry Price", value=100.0, step=5.0)
        if st.button("Add Trade"):
            add_paper_trade(pt_strike, pt_type, pt_entry)
            st.success("Trade added!")
            st.rerun()

    open_trades = [t for t in st.session_state.paper_trades if t["status"] == "OPEN"]
    if open_trades:
        with st.expander("Close Open Trade"):
            tc1, tc2 = st.columns(2)
            with tc1:
                trade_opts = {f"ID {t['id']} - {t['strike']} {t['type']} @ Rs {t['entry']}": t["id"] for t in open_trades}
                selected_label = st.selectbox("Select Trade", list(trade_opts.keys()))
            with tc2:
                exit_price = st.number_input("Exit Price", value=110.0, step=5.0)
            if st.button("Close Trade"):
                close_paper_trade(trade_opts[selected_label], exit_price)
                st.success("Trade closed!")
                st.rerun()

    if st.session_state.paper_trades:
        st.dataframe(pd.DataFrame(st.session_state.paper_trades), hide_index=True, use_container_width=True)

    # ============ EXPORT ============
    st.markdown("---")
    st.subheader("Export Data")
    e1, e2, e3 = st.columns(3)
    with e1:
        if breadth_stocks:
            to_csv_download(pd.DataFrame(breadth_stocks), "breadth.csv", "Breadth CSV")
    with e2:
        if st.session_state.paper_trades:
            to_csv_download(pd.DataFrame(st.session_state.paper_trades), "paper_trades.csv", "Paper Trades CSV")
    with e3:
        to_csv_download(levels_data[["Level", "Value"]], "levels.csv", "Levels CSV")

    st.success("App loaded successfully!")

except Exception as e:
    st.error(f"Error: {e}")
