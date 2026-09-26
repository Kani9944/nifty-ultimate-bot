# ============================================================
# STEP 1: Helper Functions
# ============================================================

import sqlite3
from pathlib import Path

DB_PATH = Path("/tmp/nifty_oi_history.db")


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


def init_oi_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS oi_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp TEXT, expiry TEXT, strike INTEGER, "
            "call_oi INTEGER, put_oi INTEGER, "
            "call_chg INTEGER, put_chg INTEGER)"
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
                "(timestamp, expiry, strike, call_oi, put_oi, "
                "call_chg, put_chg) VALUES (?,?,?,?,?,?,?)",
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
        "time": pd.Timestamp.now(
            tz="Asia/Kolkata"
        ).strftime("%H:%M:%S"),
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
# STEP 2: Market Breadth
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
                    "Volume": int(item.get("totalTradedVolume", 0)),
                })
        return stocks, None
    except Exception as e:
        return None, str(e)


NIFTY50_SECTORS = {
    "Banking": [
        "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK",
        "KOTAKBANK", "INDUSINDBK",
    ],
    "IT": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM"],
    "Oil & Gas": ["RELIANCE", "ONGC", "BPCL", "IOC", "COALINDIA"],
    "Auto": [
        "MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO",
        "HEROMOTOCO", "EICHERMOT",
    ],
    "FMCG": [
        "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "TATACONSUM",
    ],
    "Pharma": [
        "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP",
    ],
    "Metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL"],
    "Financials": [
        "BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE",
        "ADANIENT", "ADANIPORTS",
    ],
    "Infra": [
        "LT", "NTPC", "POWERGRID", "BHARTIARTL",
        "ULTRACEMCO", "GRASIM", "TITAN", "ASIANPAINT",
    ],
}


def get_sector_for_symbol(symbol):
    for sector, symbols in NIFTY50_SECTORS.items():
        if symbol in symbols:
            return sector
    return "Others"


try:
    st.markdown("---")
    st.subheader("Market Breadth - Nifty 50 Live %")
    st.caption("NSE Official | 50 stocks live % change.")

    breadth_stocks, breadth_err = get_nifty50_breadth()

    if breadth_err or not breadth_stocks:
        st.warning(f"Breadth data unavailable: {breadth_err}")
    else:
        advances = sum(
            1 for s in breadth_stocks if s["Change%"] > 0.05
        )
        declines = sum(
            1 for s in breadth_stocks if s["Change%"] < -0.05
        )
        unchanged = len(breadth_stocks) - advances - declines
        avg_change = (
            sum(s["Change%"] for s in breadth_stocks)
            / len(breadth_stocks)
        )

        total = advances + declines
        adv_pct = (advances / total * 100) if total > 0 else 50

        if adv_pct >= 75:
            breadth_label = "Strong Bullish"
        elif adv_pct >= 60:
            breadth_label = "Bullish"
        elif adv_pct >= 40:
            breadth_label = "Neutral"
        elif adv_pct >= 25:
            breadth_label = "Bearish"
        else:
            breadth_label = "Strong Bearish"

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Advances", advances)
        with m2:
            st.metric("Declines", declines)
        with m3:
            st.metric("Unchanged", unchanged)
        with m4:
            st.metric("Avg Change", f"{avg_change:+.2f}%")

        st.progress(adv_pct / 100)
        st.markdown(f"**Overall: {breadth_label}**")

        st.markdown("---")
        g_col, l_col = st.columns(2)
        sorted_stocks = sorted(
            breadth_stocks,
            key=lambda x: x["Change%"],
            reverse=True,
        )

        with g_col:
            st.markdown("### Top 5 Gainers")
            for s in sorted_stocks[:5]:
                st.markdown(
                    f"**{s['Symbol']}** - Rs {s['LTP']:,.2f} "
                    f"(+{s['Change%']:.2f}%)"
                )

        with l_col:
            st.markdown("### Top 5 Losers")
            for s in sorted_stocks[-5:][::-1]:
                st.markdown(
                    f"**{s['Symbol']}** - Rs {s['LTP']:,.2f} "
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
            adv_count = sum(
                1 for s in stat["stocks"] if s["Change%"] > 0
            )
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
        st.dataframe(
            sector_df,
            hide_index=True,
            use_container_width=True,
        )

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

        nifty_pct = percent_change if "percent_change" in dir() else 0

        if nifty_pct > 0 and adv_pct > 65:
            st.success("Strong Broad Rally.")
        elif nifty_pct > 0 and adv_pct < 40:
            st.warning("Weak Rally.")
        elif nifty_pct < 0 and adv_pct < 35:
            st.error("Strong Broad Decline.")
        elif nifty_pct < 0 and adv_pct > 60:
            st.info("Hidden Strength.")
        else:
            st.info("Mixed Market.")
except Exception as e:
    st.caption(f"Breadth error: {e}")# ============================================================
# STEP 3: Paper Trading
# ============================================================

try:
    st.markdown("---")
    st.subheader("Paper Trading (Virtual - No Real Orders)")
    st.caption("Virtual trades only. No real orders.")

    init_paper_trades()

    total_pnl, wins, losses = calc_paper_pnl()
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        st.metric(
            "Total Trades", len(st.session_state.paper_trades)
        )
    with p2:
        st.metric("Wins", wins)
    with p3:
        st.metric("Losses", losses)
    with p4:
        st.metric("Total P&L", f"Rs {total_pnl:+,.2f}")

    _spot = spot_price if "spot_price" in dir() else 23500

    with st.expander("New Virtual Trade"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            pt_strike = st.number_input(
                "Strike",
                value=int(round(_spot / 50) * 50),
                step=50,
                key="pt_strike",
            )
        with c2:
            pt_type = st.selectbox(
                "Type", ["CE", "PE"], key="pt_type"
            )
        with c3:
            pt_entry = st.number_input(
                "Entry Price",
                value=100.0,
                step=5.0,
                key="pt_entry",
            )
        with c4:
            pt_qty = st.number_input(
                "Qty", value=75, step=25, key="pt_qty"
            )

        if st.button("Add Virtual Trade", key="add_vt"):
            add_paper_trade(
                pt_strike, pt_type, pt_entry, pt_qty
            )
            st.success(f"Added {pt_type} {pt_strike}")
            st.rerun()

    if st.session_state.paper_trades:
        trade_df = pd.DataFrame(st.session_state.paper_trades)
        st.dataframe(
            trade_df,
            hide_index=True,
            use_container_width=True,
        )

        open_trades = [
            t for t in st.session_state.paper_trades
            if t["status"] == "OPEN"
        ]
        if open_trades:
            st.markdown("Close an open trade:")
            for t in open_trades:
                cc1, cc2, cc3 = st.columns([3, 1, 1])
                with cc1:
                    st.write(
                        f"#{t['id']} - {t['type']} "
                        f"{t['strike']} at Rs {t['entry']}"
                    )
                with cc2:
                    exit_price = st.number_input(
                        "Exit Rs",
                        value=float(t["entry"]),
                        key=f"exit_{t['id']}",
                        step=5.0,
                    )
                with cc3:
                    if st.button(
                        "Close", key=f"close_{t['id']}"
                    ):
                        close_paper_trade(t["id"], exit_price)
                        st.rerun()

        if st.button("Clear All Trades", key="clear_pt"):
            st.session_state.paper_trades = []
            st.rerun()
except Exception as e:
    st.caption(f"Paper Trading error: {e}")# ============================================================
# STEP 4: Historical OI + CSV Export
# ============================================================

try:
    st.markdown("---")
    st.subheader("Historical OI Trend")
    st.caption("OI saved every 5 minutes.")

    init_oi_db()

    _nse_chain = globals().get("nse_chain", None)

    if _nse_chain and "records" in _nse_chain:
        records = _nse_chain["records"]["data"]
        nse_spot = _nse_chain["records"]["underlyingValue"]
        exp_dates = _nse_chain["records"]["expiryDates"]

        if exp_dates:
            near_exp = exp_dates[0]
            save_oi_snapshot(records, near_exp, nse_spot)

            atm_hist = int(round(nse_spot / 50) * 50)
            strike_options = [
                atm_hist + (i * 50) for i in range(-3, 4)
            ]

            c1, c2 = st.columns([1, 3])
            with c1:
                hist_strike = st.selectbox(
                    "Strike:",
                    strike_options,
                    index=3,
                    key="hist_strike",
                )

            hist_df = load_oi_history(
                near_exp, hist_strike, hours=6
            )

            if hist_df is not None and len(hist_df) >= 2:
                chart_data = hist_df.melt(
                    id_vars=["Time"],
                    value_vars=["call_oi", "put_oi"],
                    var_name="Type",
                    value_name="OI",
                )
                chart_data["Type"] = chart_data["Type"].map({
                    "call_oi": "Call OI",
                    "put_oi": "Put OI",
                })

                oi_chart = (
                    alt.Chart(chart_data)
                    .mark_line(strokeWidth=2.5, point=True)
                    .encode(
                        x=alt.X("Time:T", title="Time"),
                        y=alt.Y("OI:Q", title="Open Interest"),
                        color=alt.Color(
                            "Type:N",
                            scale=alt.Scale(
                                domain=["Call OI", "Put OI"],
                                range=["#cc0000", "#00b300"],
                            ),
                        ),
                        tooltip=[
                            alt.Tooltip("Time:T", format="%H:%M"),
                            alt.Tooltip("Type:N"),
                            alt.Tooltip("OI:Q", format=","),
                        ],
                    )
                    .properties(
                        height=300,
                        title=f"NIFTY {hist_strike} OI Trend",
                    )
                )
                st.altair_chart(
                    oi_chart, use_container_width=True
                )

                latest = hist_df.iloc[-1]
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric(
                        "Call OI", f"{int(latest['call_oi']):,}"
                    )
                with m2:
                    st.metric(
                        "Put OI", f"{int(latest['put_oi']):,}"
                    )
                with m3:
                    pcr_live = (
                        latest["put_oi"] / latest["call_oi"]
                        if latest["call_oi"] > 0
                        else 0
                    )
                    st.metric("PCR", f"{pcr_live:.2f}")
            else:
                st.info("Not enough data yet. Wait 5-10 min.")
    else:
        st.caption("NSE option chain data not available.")

    st.markdown("---")
    st.subheader("Export Data")

    e1, e2, e3 = st.columns(3)

    with e1:
        if _nse_chain and "records" in _nse_chain:
            records = _nse_chain["records"]["data"]
            exp = _nse_chain["records"]["expiryDates"][0]
            rows = []
            for item in records:
                if item.get("expiryDate") != exp:
                    continue
                ce = item.get("CE") or {}
                pe = item.get("PE") or {}
                rows.append({
                    "Strike": item.get("strikePrice"),
                    "Call_OI": ce.get("openInterest", 0),
                    "Call_LTP": ce.get("lastPrice", 0),
                    "Put_LTP": pe.get("lastPrice", 0),
                    "Put_OI": pe.get("openInterest", 0),
                })
            if rows:
                to_csv_download(
                    pd.DataFrame(rows),
                    f"nifty_chain_{exp}.csv",
                    "Option Chain CSV",
                )

    with e2:
        if st.session_state.get("paper_trades"):
            to_csv_download(
                pd.DataFrame(st.session_state.paper_trades),
                "paper_trades.csv",
                "Paper Trades CSV",
            )

    with e3:
        _spot2 = spot_price if "spot_price" in dir() else 0
        _sd = str(session_date) if "session_date" in dir() else "N/A"
        summary_df = pd.DataFrame([{
            "Session": _sd,
            "Spot": _spot2,
            "Time": pd.Timestamp.now(
                tz="Asia/Kolkata"
            ).strftime("%Y-%m-%d %H:%M"),
        }])
        to_csv_download(
            summary_df,
            f"nifty_snapshot_{_sd}.csv",
            "Daily Snapshot CSV",
        )
except Exception as e:
    st.caption(f"OI/CSV error: {e}")
