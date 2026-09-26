# ============================================================
# BLOCK B: Helper Functions
# ============================================================

import sqlite3
from pathlib import Path

DB_PATH = Path("/tmp/nifty_oi_history.db")


def init_oi_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS oi_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                expiry TEXT,
                strike INTEGER,
                call_oi INTEGER,
                put_oi INTEGER,
                call_chg INTEGER,
                put_chg INTEGER
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ts ON oi_history(timestamp)"
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def save_oi_snapshot(records, expiry, spot):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            "SELECT MAX(timestamp) FROM oi_history WHERE expiry = ?",
            (expiry,),
        )
        last_ts = cur.fetchone()[0]

        now = pd.Timestamp.now(tz="Asia/Kolkata")
        if last_ts:
            last_dt = pd.Timestamp(last_ts)
            if (now - last_dt).total_seconds() < 300:
                conn.close()
                return

        atm = int(round(spot / 50) * 50)
        strike_range = [atm + (i * 50) for i in range(-3, 4)]

        for item in records:
            if item.get("expiryDate") != expiry:
                continue
            strike = item.get("strikePrice")
            if strike not in strike_range:
                continue
            ce = item.get("CE") or {}
            pe = item.get("PE") or {}
            conn.execute(
                "INSERT INTO oi_history "
                "(timestamp, expiry, strike, call_oi, put_oi, call_chg, put_chg) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    now.isoformat(),
                    expiry,
                    strike,
                    ce.get("openInterest", 0),
                    pe.get("openInterest", 0),
                    ce.get("changeinOpenInterest", 0),
                    pe.get("changeinOpenInterest", 0),
                ),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


def load_oi_history(expiry, strike, hours=6):
    try:
        conn = sqlite3.connect(DB_PATH)
        since = (
            pd.Timestamp.now(tz="Asia/Kolkata")
            - pd.Timedelta(hours=hours)
        ).isoformat()

        df = pd.read_sql_query(
            "SELECT timestamp, call_oi, put_oi FROM oi_history "
            "WHERE expiry = ? AND strike = ? AND timestamp >= ? "
            "ORDER BY timestamp",
            conn,
            params=(expiry, strike, since),
        )
        conn.close()

        if df.empty:
            return None
        df["Time"] = pd.to_datetime(df["timestamp"])
        return df[["Time", "call_oi", "put_oi"]]
    except Exception:
        return None


def init_paper_trades():
    if "paper_trades" not in st.session_state:
        st.session_state.paper_trades = []


def add_paper_trade(strike, opt_type, entry_price, qty=75):
    st.session_state.paper_trades.append({
        "id": len(st.session_state.paper_trades) + 1,
        "time": pd.Timestamp.now(tz="Asia/Kolkata").strftime("%H:%M:%S"),
        "strike": strike,
        "type": opt_type,
        "entry": entry_price,
        "qty": qty,
        "exit": None,
        "status": "OPEN",
    })


def close_paper_trade(trade_id, exit_price):
    for t in st.session_state.paper_trades:
        if t["id"] == trade_id and t["status"] == "OPEN":
            t["exit"] = exit_price
            t["status"] = "CLOSED"
            t["pnl"] = (exit_price - t["entry"]) * t["qty"]
            break


def calc_paper_pnl():
    closed = [
        t for t in st.session_state.paper_trades
        if t["status"] == "CLOSED"
    ]
    if not closed:
        return 0, 0, 0
    wins = sum(1 for t in closed if t.get("pnl", 0) > 0)
    losses = sum(1 for t in closed if t.get("pnl", 0) < 0)
    total = sum(t.get("pnl", 0) for t in closed)
    return total, wins, losses


def to_csv_download(df, filename, label="Download CSV"):
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label=label,
        data=csv,
        file_name=filename,
        mime="text/csv",
    )# ============================================================
# BLOCK D: Market Breadth
# ============================================================

st.markdown("---")
st.subheader("Market Breadth - Nifty 50 Live %")
st.caption("NSE Official | Cache: 60 seconds | 50 stocks live % change.")

breadth_stocks, breadth_err = get_nifty50_breadth()

if breadth_err or not breadth_stocks:
    st.warning(f"Breadth data unavailable: {breadth_err}")
else:
    advances = sum(1 for s in breadth_stocks if s["Change%"] > 0.05)
    declines = sum(1 for s in breadth_stocks if s["Change%"] < -0.05)
    unchanged = len(breadth_stocks) - advances - declines

    avg_change = (
        sum(s["Change%"] for s in breadth_stocks) / len(breadth_stocks)
    )

    total = advances + declines
    adv_pct = (advances / total * 100) if total > 0 else 50

    if adv_pct >= 75:
        breadth_label = "Strong Bullish (Broad Rally)"
    elif adv_pct >= 60:
        breadth_label = "Bullish"
    elif adv_pct >= 40:
        breadth_label = "Neutral / Mixed"
    elif adv_pct >= 25:
        breadth_label = "Bearish"
    else:
        breadth_label = "Strong Bearish (Broad Decline)"

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric(
            "Advances",
            advances,
            f"{(advances/len(breadth_stocks)*100):.0f}%",
        )
    with m2:
        st.metric(
            "Declines",
            declines,
            f"-{(declines/len(breadth_stocks)*100):.0f}%",
        )
    with m3:
        st.metric("Unchanged", unchanged)
    with m4:
        st.metric(
            "Avg Change",
            f"{avg_change:+.2f}%",
            "Above 0" if avg_change >= 0 else "Below 0",
        )

    st.markdown("Breadth Meter:")
    st.progress(adv_pct / 100)
    st.markdown(f"Overall: {breadth_label}")

    st.markdown("---")
    g_col, l_col = st.columns(2)

    sorted_stocks = sorted(
        breadth_stocks, key=lambda x: x["Change%"], reverse=True
    )

    with g_col:
        st.markdown("### Top 5 Gainers")
        for s in sorted_stocks[:5]:
            st.markdown(
                f"{s['Symbol']} - Rs {s['LTP']:,.2f} "
                f"(+{s['Change%']:.2f}%)"
            )

    with l_col:
        st.markdown("### Top 5 Losers")
        for s in sorted_stocks[-5:][::-1]:
            st.markdown(
                f"{s['Symbol']} - Rs {s['LTP']:,.2f} "
                f"({s['Change%']:.2f}%)"
            )

    st.markdown("---")
    st.markdown("### Sector-wise Breadth")

    sector_stats = {}
    for s in breadth_stocks:
        sector = get_sector_for_symbol(s["Symbol"])
        if sector not in sector_stats:
            sector_stats[sector] = {
                "count": 0, "sum_pct": 0, "stocks": []
            }
        sector_stats[sector]["count"] += 1
        sector_stats[sector]["sum_pct"] += s["Change%"]
        sector_stats[sector]["stocks"].append(s)

    sector_rows = []
    for sector, stat in sector_stats.items():
        avg = stat["sum_pct"] / stat["count"]
        adv_count = sum(1 for s in stat["stocks"] if s["Change%"] > 0)
        dec_count = stat["count"] - adv_count
        sector_rows.append({
            "Sector": sector,
            "Stocks": stat["count"],
            "Advances": adv_count,
            "Declines": dec_count,
            "Avg %": round(avg, 2),
        })

    sector_df = pd.DataFrame(sector_rows).sort_values(
        "Avg %", ascending=False
    )
    st.dataframe(sector_df, hide_index=True, use_container_width=True)

    with st.expander("View all 50 stocks"):
        breadth_df = pd.DataFrame(breadth_stocks).sort_values(
            "Change%", ascending=False
        )
        breadth_df["Sector"] = breadth_df["Symbol"].apply(
            get_sector_for_symbol
        )
        display_df = breadth_df[[
            "Symbol", "Sector", "LTP", "Change%", "Volume"
        ]].copy()
        display_df["LTP"] = display_df["LTP"].apply(
            lambda x: f"Rs {x:,.2f}"
        )
        display_df["Change%"] = display_df["Change%"].apply(
            lambda x: f"{x:+.2f}%"
        )
        display_df["Volume"] = display_df["Volume"].apply(
            lambda x: f"{x:,}"
        )
        st.dataframe(
            display_df,
            hide_index=True,
            use_container_width=True,
            height=400,
        )

    st.markdown("---")
    st.markdown("### Interpretation")

    nifty_pct = percent_change

    if nifty_pct > 0 and adv_pct > 65:
        st.success(
            "Strong Broad Rally: Nifty up, 65%+ stocks up. Healthy uptrend."
        )
    elif nifty_pct > 0 and adv_pct < 40:
        st.warning(
            "Weak Rally: Nifty up but most stocks down. Caution."
        )
    elif nifty_pct < 0 and adv_pct < 35:
        st.error(
            "Strong Broad Decline: Nifty down, stocks down. Avoid longs."
        )
    elif nifty_pct < 0 and adv_pct > 60:
        st.info(
            "Hidden Strength: Nifty down but 60%+ stocks up. Reversal possible."
        )
    else:
        st.info("Mixed Market: Direction unclear. Wait for breakout# ============================================================
# BLOCK D-1: Breadth Helpers
# ============================================================

@st.cache_data(ttl=60)
def get_nifty50_breadth():
    session, err = get_nse_session()
    if session is None:
        return None, err
    try:
        r = session.get(
            "https://www.nseindia.com/api/equity-stockIndices"
            "?index=NIFTY%2050",
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        stocks = []
        for item in data.get("data", []):
            symbol = item.get("symbol", "")
            if symbol in ("NIFTY 50", "NIFTY", ""):
                continue
            pct = item.get("pChange", 0)
            ltp = item.get("lastPrice", 0)
            if ltp > 0:
                stocks.append({
                    "Symbol": symbol,
                    "LTP": float(ltp),
                    "Change%": float(pct),
                    "Open": float(item.get("open", 0)),
                    "High": float(item.get("dayHigh", 0)),
                    "Low": float(item.get("dayLow", 0)),
                    "Volume": int(item.get("totalTradedVolume", 0)),
                })
        return stocks, None
    except Exception as e:
        return None, str(e)


NIFTY50_SECTORS = {
    "Banking": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK"],
    "IT": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM"],
    "Oil & Gas": ["RELIANCE", "ONGC", "BPCL", "IOC", "COALINDIA"],
    "Auto": ["MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "TATACONSUM"],
    "Pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP"],
    "Metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL"],
    "Financials": ["BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "ADANIENT", "ADANIPORTS"],
    "Infra": ["LT", "NTPC", "POWERGRID", "BHARTIARTL", "ULTRACEMCO", "GRASIM", "TITAN", "ASIANPAINT"],
}


def get_sector_for_symbol(symbol):
    for sector, symbols in NIFTY50_SECTORS.items():
        if symbol in symbols:
            return sector
    return "Others".")# ============================================================
# BLOCK B: Helper Functions
# ============================================================

import sqlite3
from pathlib import Path

DB_PATH = Path("/tmp/nifty_oi_history.db")


def init_oi_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS oi_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                expiry TEXT,
                strike INTEGER,
                call_oi INTEGER,
                put_oi INTEGER,
                call_chg INTEGER,
                put_chg INTEGER
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ts ON oi_history(timestamp)"
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def save_oi_snapshot(records, expiry, spot):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            "SELECT MAX(timestamp) FROM oi_history WHERE expiry = ?",
            (expiry,),
        )
        last_ts = cur.fetchone()[0]

        now = pd.Timestamp.now(tz="Asia/Kolkata")
        if last_ts:
            last_dt = pd.Timestamp(last_ts)
            if (now - last_dt).total_seconds() < 300:
                conn.close()
                return

        atm = int(round(spot / 50) * 50)
        strike_range = [atm + (i * 50) for i in range(-3, 4)]

        for item in records:
            if item.get("expiryDate") != expiry:
                continue
            strike = item.get("strikePrice")
            if strike not in strike_range:
                continue
            ce = item.get("CE") or {}
            pe = item.get("PE") or {}
            conn.execute(
                "INSERT INTO oi_history "
                "(timestamp, expiry, strike, call_oi, put_oi, call_chg, put_chg) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    now.isoformat(),
                    expiry,
                    strike,
                    ce.get("openInterest", 0),
                    pe.get("openInterest", 0),
                    ce.get("changeinOpenInterest", 0),
                    pe.get("changeinOpenInterest", 0),
                ),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


def load_oi_history(expiry, strike, hours=6):
    try:
        conn = sqlite3.connect(DB_PATH)
        since = (
            pd.Timestamp.now(tz="Asia/Kolkata")
            - pd.Timedelta(hours=hours)
        ).isoformat()

        df = pd.read_sql_query(
            "SELECT timestamp, call_oi, put_oi FROM oi_history "
            "WHERE expiry = ? AND strike = ? AND timestamp >= ? "
            "ORDER BY timestamp",
            conn,
            params=(expiry, strike, since),
        )
        conn.close()

        if df.empty:
            return None
        df["Time"] = pd.to_datetime(df["timestamp"])
        return df[["Time", "call_oi", "put_oi"]]
    except Exception:
        return None


def init_paper_trades():
    if "paper_trades" not in st.session_state:
        st.session_state.paper_trades = []


def add_paper_trade(strike, opt_type, entry_price, qty=75):
    st.session_state.paper_trades.append({
        "id": len(st.session_state.paper_trades) + 1,
        "time": pd.Timestamp.now(tz="Asia/Kolkata").strftime("%H:%M:%S"),
        "strike": strike,
        "type": opt_type,
        "entry": entry_price,
        "qty": qty,
        "exit": None,
        "status": "OPEN",
    })


def close_paper_trade(trade_id, exit_price):
    for t in st.session_state.paper_trades:
        if t["id"] == trade_id and t["status"] == "OPEN":
            t["exit"] = exit_price
            t["status"] = "CLOSED"
            t["pnl"] = (exit_price - t["entry"]) * t["qty"]
            break


def calc_paper_pnl():
    closed = [
        t for t in st.session_state.paper_trades
        if t["status"] == "CLOSED"
    ]
    if not closed:
        return 0, 0, 0
    wins = sum(1 for t in closed if t.get("pnl", 0) > 0)
    losses = sum(1 for t in closed if t.get("pnl", 0) < 0)
    total = sum(t.get("pnl", 0) for t in closed)
    return total, wins, losses


def to_csv_download(df, filename, label="Download CSV"):
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label=label,
        data=csv,
        file_name=filename,
        mime="text/csv",
    )# ============================================================
# BLOCK D-1: Breadth Helpers
# ============================================================

@st.cache_data(ttl=60)
def get_nifty50_breadth():
    session, err = get_nse_session()
    if session is None:
        return None, err
    try:
        r = session.get(
            "https://www.nseindia.com/api/equity-stockIndices"
            "?index=NIFTY%2050",
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        stocks = []
        for item in data.get("data", []):
            symbol = item.get("symbol", "")
            if symbol in ("NIFTY 50", "NIFTY", ""):
                continue
            pct = item.get("pChange", 0)
            ltp = item.get("lastPrice", 0)
            if ltp > 0:
                stocks.append({
                    "Symbol": symbol,
                    "LTP": float(ltp),
                    "Change%": float(pct),
                    "Open": float(item.get("open", 0)),
                    "High": float(item.get("dayHigh", 0)),
                    "Low": float(item.get("dayLow", 0)),
                    "Volume": int(item.get("totalTradedVolume", 0)),
                })
        return stocks, None
    except Exception as e:
        return None, str(e)


NIFTY50_SECTORS = {
    "Banking": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK"],
    "IT": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM"],
    "Oil & Gas": ["RELIANCE", "ONGC", "BPCL", "IOC", "COALINDIA"],
    "Auto": ["MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "TATACONSUM"],
    "Pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP"],
    "Metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL"],
    "Financials": ["BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "ADANIENT", "ADANIPORTS"],
    "Infra": ["LT", "NTPC", "POWERGRID", "BHARTIARTL", "ULTRACEMCO", "GRASIM", "TITAN", "ASIANPAINT"],
}


def get_sector_for_symbol(symbol):
    for sector, symbols in NIFTY50_SECTORS.items():
        if symbol in symbols:
            return sector
    return "Others"# ============================================================
# BLOCK D-2: Market Breadth UI
# ============================================================

st.markdown("---")
st.subheader("Market Breadth - Nifty 50 Live %")
st.caption("NSE Official | Cache: 60 seconds | 50 stocks live % change.")

breadth_stocks, breadth_err = get_nifty50_breadth()

if breadth_err or not breadth_stocks:
    st.warning(f"Breadth data unavailable: {breadth_err}")
else:
    advances = sum(1 for s in breadth_stocks if s["Change%"] > 0.05)
    declines = sum(1 for s in breadth_stocks if s["Change%"] < -0.05)
    unchanged = len(breadth_stocks) - advances - declines

    avg_change = (
        sum(s["Change%"] for s in breadth_stocks) / len(breadth_stocks)
    )

    total = advances + declines
    adv_pct = (advances / total * 100) if total > 0 else 50

    if adv_pct >= 75:
        breadth_label = "Strong Bullish (Broad Rally)"
    elif adv_pct >= 60:
        breadth_label = "Bullish"
    elif adv_pct >= 40:
        breadth_label = "Neutral / Mixed"
    elif adv_pct >= 25:
        breadth_label = "Bearish"
    else:
        breadth_label = "Strong Bearish (Broad Decline)"

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric(
            "Advances",
            advances,
            f"{(advances/len(breadth_stocks)*100):.0f}%",
        )
    with m2:
        st.metric(
            "Declines",
            declines,
            f"-{(declines/len(breadth_stocks)*100):.0f}%",
        )
    with m3:
        st.metric("Unchanged", unchanged)
    with m4:
        st.metric(
            "Avg Change",
            f"{avg_change:+.2f}%",
            "Above 0" if avg_change >= 0 else "Below 0",
        )

    st.markdown("**Breadth Meter:**")
    st.progress(adv_pct / 100)
    st.markdown(f"**Overall: {breadth_label}**")

    st.markdown("---")
    g_col, l_col = st.columns(2)

    sorted_stocks = sorted(
        breadth_stocks, key=lambda x: x["Change%"], reverse=True
    )

    with g_col:
        st.markdown("### Top 5 Gainers")
        for s in sorted_stocks[:5]:
            st.markdown(
                f"**{s['Symbol']}** - Rs {s['LTP']:,.2f} "
                f"(**+{s['Change%']:.2f}%**)"
            )

    with l_col:
        st.markdown("### Top 5 Losers")
        for s in sorted_stocks[-5:][::-1]:
            st.markdown(
                f"**{s['Symbol']}** - Rs {s['LTP']:,.2f} "
                f"(**{s['Change%']:.2f}%**)"
            )

    st.markdown("---")
    st.markdown("### Sector-wise Breadth")

    sector_stats = {}
    for s in breadth_stocks:
        sector = get_sector_for_symbol(s["Symbol"])
        if sector not in sector_stats:
            sector_stats[sector] = {
                "count": 0, "sum_pct": 0, "stocks": []
            }
        sector_stats[sector]["count"] += 1
        sector_stats[sector]["sum_pct"] += s["Change%"]
        sector_stats[sector]["stocks"].append(s)

    sector_rows = []
    for sector, stat in sector_stats.items():
        avg = stat["sum_pct"] / stat["count"]
        adv_count = sum(1 for s in stat["stocks"] if s["Change%"] > 0)
        dec_count = stat["count"] - adv_count
        sector_rows.append({
            "Sector": sector,
            "Stocks": stat["count"],
            "Advances": adv_count,
            "Declines": dec_count,
            "Avg %": round(avg, 2),
        })

    sector_df = pd.DataFrame(sector_rows).sort_values(
        "Avg %", ascending=False
    )
    st.dataframe(sector_df, hide_index=True, use_container_width=True)

    with st.expander("View all 50 stocks"):
        breadth_df = pd.DataFrame(breadth_stocks).sort_values(
            "Change%", ascending=False
        )
        breadth_df["Sector"] = breadth_df["Symbol"].apply(
            get_sector_for_symbol
        )
        display_df = breadth_df[[
            "Symbol", "Sector", "LTP", "Change%", "Volume"
        ]].copy()
        display_df["LTP"] = display_df["LTP"].apply(
            lambda x: f"Rs {x:,.2f}"
        )
        display_df["Change%"] = display_df["Change%"].apply(
            lambda x: f"{x:+.2f}%"
        )
        display_df["Volume"] = display_df["Volume"].apply(
            lambda x: f"{x:,}"
        )
        st.dataframe(
            display_df,
            hide_index=True,
            use_container_width=True,
            height=400,
        )

    st.markdown("---")
    st.markdown("### Interpretation")

    nifty_pct = percent_change

    if nifty_pct > 0 and adv_pct > 65:
        st.success("Strong Broad Rally: Nifty up, 65%+ stocks up.")
    elif nifty_pct > 0 and adv_pct < 40:
        st.warning("Weak Rally: Nifty up but most stocks down.")
    elif nifty_pct < 0 and adv_pct < 35:
        st.error("Strong Broad Decline: Avoid longs.")
    elif nifty_pct < 0 and adv_pct > 60:
        st.info("Hidden Strength: Reversal possible.")
    else:
        st.info("Mixed Market: Wait for breakout.")
