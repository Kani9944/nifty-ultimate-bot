# ============================================================
# BLOCK B: Helper Functions (No Telegram)
# ============================================================

# ---------- 1. Historical OI Database ----------
import sqlite3
from pathlib import Path

DB_PATH = Path("/tmp/nifty_oi_history.db")


def init_oi_db():
    """SQLite DB init (ஒருமுறை மட்டும்)."""
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
    """ATM ± 3 strikes OI-ஐ DB-ல் save (5 நிமிடத்திற்கு ஒருமுறை)."""
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
                """INSERT INTO oi_history
                (timestamp, expiry, strike, call_oi, put_oi,
                 call_chg, put_chg)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
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
    """DB-இலிருந்து OI history load."""
    try:
        conn = sqlite3.connect(DB_PATH)
        since = (
            pd.Timestamp.now(tz="Asia/Kolkata")
            - pd.Timedelta(hours=hours)
        ).isoformat()

        df = pd.read_sql_query(
            """SELECT timestamp, call_oi, put_oi
            FROM oi_history
            WHERE expiry = ? AND strike = ? AND timestamp >= ?
            ORDER BY timestamp""",
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


# ---------- 2. Paper Trading ----------
def init_paper_trades():
    if "paper_trades" not in st.session_state:
        st.session_state.paper_trades = []


def add_paper_trade(strike, opt_type, entry_price, qty=75):
    """Virtual trade add (real order போகாது)."""
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
    """Virtual trade close."""
    for t in st.session_state.paper_trades:
        if t["id"] == trade_id and t["status"] == "OPEN":
            t["exit"] = exit_price
            t["status"] = "CLOSED"
            t["pnl"] = (exit_price - t["entry"]) * t["qty"]
            break


def calc_paper_pnl():
    """மொத்த P&L கணக்கிடு."""
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


# ---------- 3. CSV Export ----------
def to_csv_download(df, filename, label="📥 Download CSV"):
    """CSV download button."""
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label=label,
        data=csv,
        file_name=filename,
        mime="text/csv",
    )# ============================================================
# BLOCK C: Paper Trading + CSV Export + Historical OI
# ============================================================
st.markdown("---")

# ---------- Paper Trading ----------
st.subheader("📝 Paper Trading (Virtual — No Real Orders)")
st.caption(
    "⚠️ இது முழுவதும் **virtual**. Real order எதுவும் போகாது. "
    "Strategy test செய்ய மட்டும்."
)

init_paper_trades()

# P&L Summary
total_pnl, wins, losses = calc_paper_pnl()
p1, p2, p3, p4 = st.columns(4)
with p1:
    st.metric("📊 Total Trades", len(st.session_state.paper_trades))
with p2:
    st.metric("✅ Wins", wins)
with p3:
    st.metric("❌ Losses", losses)
with p4:
    st.metric(
        "💰 Total P&L",
        f"₹{total_pnl:+,.2f}",
        delta_color="normal" if total_pnl >= 0 else "inverse",
    )

# Add new paper trade
with st.expander("➕ New Virtual Trade"):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        pt_strike = st.number_input(
            "Strike", value=int(round(spot_price / 50) * 50),
            step=50, key="pt_strike"
        )
    with c2:
        pt_type = st.selectbox("Type", ["CE", "PE"], key="pt_type")
    with c3:
        pt_entry = st.number_input(
            "Entry Price", value=100.0, step=5.0, key="pt_entry"
        )
    with c4:
        pt_qty = st.number_input("Qty", value=75, step=25, key="pt_qty")

    if st.button("📈 Add Virtual Trade", key="add_vt"):
        add_paper_trade(pt_strike, pt_type, pt_entry, pt_qty)
        st.success(f"✅ Virtual {pt_type} {pt_strike} @ ₹{pt_entry} added")
        st.rerun()

# Trade list
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
        st.markdown("**Close an open trade:**")
        for t in open_trades:
            cc1, cc2, cc3 = st.columns([3, 1, 1])
            with cc1:
                st.write(
                    f"#{t['id']} — {t['type']} {t['strike']} "
                    f"@ ₹{t['entry']} ({t['time']})"
                )
            with cc2:
                exit_price = st.number_input(
                    "Exit ₹", value=float(t["entry"]),
                    key=f"exit_{t['id']}", step=5.0
                )
            with cc3:
                if st.button("Close", key=f"close_{t['id']}"):
                    close_paper_trade(t["id"], exit_price)
                    st.rerun()

    if st.button("🗑️ Clear All Trades", key="clear_pt"):
        st.session_state.paper_trades = []
        st.rerun()

# ---------- Historical OI Chart ----------
st.markdown("---")
st.subheader("📈 Historical OI Trend")
st.caption(
    "📀 ஒவ்வொரு 5 நிமிடமும் OI save ஆகும். "
    "காலையில் OI எப்படி இருந்தது, இப்போது எப்படி — "
    "trend பார்க்கலாம்."
)

init_oi_db()

if nse_chain is not None and "records" in nse_chain:
    try:
        records = nse_chain["records"]["data"]
        nse_spot = nse_chain["records"]["underlyingValue"]
        exp_dates = nse_chain["records"]["expiryDates"]

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

            hist_df = load_oi_history(near_exp, hist_strike, hours=6)

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
                st.altair_chart(oi_chart, use_container_width=True)

                latest = hist_df.iloc[-1]
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric("Call OI", f"{int(latest['call_oi']):,}")
                with m2:
                    st.metric("Put OI", f"{int(latest['put_oi']):,}")
                with m3:
                    pcr_live = (
                        latest["put_oi"] / latest["call_oi"]
                        if latest["call_oi"] > 0
                        else 0
                    )
                    st.metric("PCR", f"{pcr_live:.2f}")
            else:
                st.info(
                    "⏳ இன்னும் போதுமான data இல்லை. "
                    "5-10 நிமிடம் கழித்து மீண்டும் பாருங்கள்."
                )
    except Exception as e:
        st.caption(f"Historical OI error: {e}")
else:
    st.caption("ℹ️ Historical OI-க்கு NSE option chain தேவை.")

# ---------- Export CSV ----------
st.markdown("---")
st.subheader("📥 Export Data")

e1, e2, e3 = st.columns(3)

with e1:
    if nse_chain is not None and "records" in nse_chain:
        try:
            records = nse_chain["records"]["data"]
            exp = nse_chain["records"]["expiryDates"][0]
            rows = []
            for item in records:
                if item.get("expiryDate") != exp:
                    continue
                ce = item.get("CE") or {}
                pe = item.get("PE") or {}
                rows.append({
                    "Strike": item.get("strikePrice"),
                    "Call_OI": ce.get("openInterest", 0),
                    "Call_ChgOI": ce.get("changeinOpenInterest", 0),
                    "Call_LTP": ce.get("lastPrice", 0),
                    "Call_IV": ce.get("impliedVolatility", 0),
                    "Put_IV": pe.get("impliedVolatility", 0),
                    "Put_LTP": pe.get("lastPrice", 0),
                    "Put_ChgOI": pe.get("changeinOpenInterest", 0),
                    "Put_OI": pe.get("openInterest", 0),
                })
            if rows:
                to_csv_download(
                    pd.DataFrame(rows),
                    f"nifty_option_chain_{exp}.csv",
                    "📥 Option Chain CSV",
                )
        except Exception:
            st.caption("Option chain export unavailable")

with e2:
    if st.session_state.get("paper_trades"):
        to_csv_download(
            pd.DataFrame(st.session_state.paper_trades),
            "paper_trades.csv",
            "📥 Paper Trades CSV",
        )

with e3:
    summary_df = pd.DataFrame([{
        "Time": pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d %H:%M"),
        "Session": str(session_date),
        "Spot": spot_price,
        "Change": change,
        "Change%": percent_change,
        "Open": open_price,
        "PDH": pdh,
        "PDL": pdl,
        "Pivot": PP,
        "BC": BC,
        "TC": TC,
        "R1": R1,
        "S1": S1,
        "RSI": rsi_val,
        "EMA9": ema9_val,
        "EMA21": ema21_val,
        "VWAP": vwap_val,
        "Gap_Pts": gap_points,
        "Gap%": gap_pct,
    }])
    to_csv_download(
        summary_df,
        f"nifty_snapshot_{session_date}.csv",
        "📥 Daily Snapshot CSV",
        )app.py-ல்:

1. Imports ✅
2. Existing Helpers ✅
3. ⬇️ Block B paste ⬅️ (Helpers — Telegram இல்லை)
4. Main Data Fetch ✅
5. Metrics ✅
6. Option Chain ✅
7. 7 Features ✅
8. ⬇️ Market Breadth paste ⬅️ (Block D)
9. Chart ✅
10. ⬇️ Block C paste ⬅️ (Paper + Historical OI + CSV)
