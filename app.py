import feedparser
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf

st.set_page_config(page_title="Nifty Smart Monitor", layout="wide")
st_autorefresh(interval=60000, key="refresh")
st.title("NIFTY 50 - Smart Money & Market Monitor")

def chg(d):
    if d is None or len(d) < 2: return None, None
    c = float(d["Close"].iloc[-1])
    p = float(d["Close"].iloc[-2])
    return c, (((c - p) / p) * 100 if p != 0 else None)

def rsi(close, w=14):
    d = close.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    ag = g.ewm(alpha=1/w, adjust=False, min_periods=w).mean()
    al = l.ewm(alpha=1/w, adjust=False, min_periods=w).mean()
    r = 100.0 - (100.0 / (1.0 + (ag/al)))
    return r.mask(al == 0, 100.0).mask((ag == 0) & (al == 0), 50.0)

@st.cache_data(ttl=60)
def gsd(sym, p, itv=None):
    t = yf.Ticker(sym)
    return t.history(period=p, interval=itv) if itv else t.history(period=p)

@st.cache_data(ttl=300)
def gbreadth():
    syms = ["ADANIENT.NS", "ASIANPAINT.NS", "AXISBANK.NS", "BAJFINANCE.NS", "BHARTIARTL.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "ITC.NS", "KOTAKBANK.NS", "LT.NS", "M&M.NS", "MARUTI.NS", "RELIANCE.NS", "SBIN.NS", "TCS.NS", "TATAMOTORS.NS", "TITAN.NS"]
    o = []
    try:
        df = yf.download(syms, period="2d", interval="1d", group_by="ticker", progress=False, threads=True)
        for s in syms:
            try:
                h = df[s].dropna()
                if len(h) >= 2:
                    c = float(h["Close"].iloc[-1])
                    p = float(h["Close"].iloc[-2])
                    if p > 0:
                        o.append({"s": s.replace(".NS", ""), "l": round(c,2), "c": round(((c-p)/p)*100, 2)})
            except: pass
    except: pass
    return o

@st.cache_data(ttl=300)
def gnews():
    feeds = [
        "https://tamil.goodreturns.in/rss/feeds/tamil-money-news-fb.xml",
        "https://tamil.oneindia.com/rss/feeds/tamil-business-fb.xml",
        "https://tamil.samayam.com/business/rssfeed.cms"
    ]
    o = []
    for u in feeds:
        try:
            r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            if r.status_code == 200:
                f = feedparser.parse(r.content)
                for e in f.entries[:3]:
                    t = e.get("title", "").strip()
                    l = e.get("link", "")
                    if t: o.append("[" + t + "](" + l + ")" if l else t)
                if len(o) >= 6: break
        except: continue
    return o[:6] if o else ["தமிழ் பங்கு வர்த்தக செய்திகள் தற்போது கிடைக்கவில்லை."]

try:
    h = gsd("^NSEI", "5d", "5m")
    d = gsd("^NSEI", "5d", "1d")
    bh = gsd("^NSEBANK", "2d", "5m")
    vh = gsd("^INDIAVIX", "2d", "5m")
except:
    st.error("Data unavailable.")
    st.stop()

if h.empty or d.empty or len(d) < 2:
    st.error("Nifty unavailable.")
    st.stop()

h.index = pd.to_datetime(h.index)
h.index = h.index.tz_convert("Asia/Kolkata") if h.index.tz is not None else h.index.tz_localize("Asia/Kolkata")
d.index = pd.to_datetime(d.index)
d.index = d.index.tz_convert("Asia/Kolkata") if d.index.tz is not None else d.index.tz_localize("Asia/Kolkata")

td = pd.Timestamp.now(tz="Asia/Kolkata").date()
sd = td if (h.index.date == td).any() else h.index[-1].date()
sh = h[h.index.date == sd].copy()
if sh.empty:
    st.error("Session unavailable.")
    st.stop()

sp = float(sh["Close"].iloc[-1])
_, n5 = chg(sh)

ps = d[pd.Index(d.index.date) < sd]
if ps.empty:
    st.error("Prev unavailable.")
    st.stop()

pd_ = ps.iloc[-1]
pdh = float(pd_["High"])
pdl = float(pd_["Low"])
pdc = float(pd_["Close"])

PP = (pdh + pdl + pdc) / 3
BC = min((pdh + pdl) / 2, (2 * PP) - ((pdh + pdl) / 2))
TC = max((pdh + pdl) / 2, (2 * PP) - ((pdh + pdl) / 2))
R1 = (2 * PP) - pdl
S1 = (2 * PP) - pdh
R2 = PP + (pdh - pdl)
S2 = PP - (pdh - pdl)

tp = (sh["High"] + sh["Low"] + sh["Close"]) / 3
cv = sh["Volume"].cumsum()
sh["VWAP"] = np.where(cv > 0, (tp * sh["Volume"]).cumsum() / cv, np.nan)
if sh["VWAP"].isna().all(): sh["VWAP"] = sh["Close"]

bp, b5 = chg(bh)
vv, v5 = chg(vh)
e9 = float(sh["Close"].ewm(span=9, adjust=False).mean().iloc[-1])
e21 = float(sh["Close"].ewm(span=21, adjust=False).mean().iloc[-1])
rs = rsi(sh["Close"], 14)
rv = float(rs.iloc[-1]) if pd.notna(rs.iloc[-1]) else 50.0
vw = float(sh["VWAP"].iloc[-1]) if pd.notna(sh["VWAP"].iloc[-1]) else sp

n5s = "{:+.2f}% (5m)".format(n5) if n5 is not None else "N/A"
b5s = "{:+.2f}% (5m)".format(b5) if b5 is not None else "N/A"
v5s = "{:+.2f}% (5m)".format(v5) if v5 is not None else "N/A"
bps = "Rs {:,.2f}".format(bp) if bp is not None else "N/A"
vvs = "{:.2f}".format(vv) if vv is not None else "N/A"
n_clr = "#00b300" if (n5 is not None and n5 >= 0) else "#cc0000"
b_clr = "#00b300" if (b5 is not None and b5 >= 0) else "#cc0000"
v_clr = "#cc0000" if (v5 is not None and v5 >= 0) else "#00b300"

st.caption("Session: " + str(sd))

st.markdown(
    '<div style="display:flex;gap:8px;margin-bottom:8px;">'
    '<div style="flex:1;padding:10px;background:#f8f9fa;border-radius:8px;border-left:4px solid #0052cc;">'
    '<div style="font-size:12px;color:#666;">NIFTY 50</div>'
    '<div style="font-size:20px;font-weight:bold;">Rs {:,.2f}</div>'.format(sp)
    + '<div style="font-size:12px;color:' + n_clr + ';">' + n5s + '</div></div>'
    '<div style="flex:1;padding:10px;background:#f8f9fa;border-radius:8px;border-left:4px solid #0052cc;">'
    '<div style="font-size:12px;color:#666;">BANK NIFTY</div>'
    '<div style="font-size:20px;font-weight:bold;">' + bps + '</div>'
    '<div style="font-size:12px;color:' + b_clr + ';">' + b5s + '</div></div></div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div style="display:flex;justify-content:center;margin-bottom:8px;">'
    '<div style="padding:10px 30px;background:#f8f9fa;border-radius:8px;border-left:4px solid #ff9900;text-align:center;">'
    '<div style="font-size:12px;color:#666;">INDIA VIX</div>'
    '<div style="font-size:20px;font-weight:bold;">' + vvs + '</div>'
    '<div style="font-size:12px;color:' + v_clr + ';">' + v5s + '</div></div></div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div style="display:flex;gap:8px;">'
    '<div style="flex:1;padding:10px;background:#f8f9fa;border-radius:8px;border-left:4px solid #cc0000;">'
    '<div style="font-size:12px;color:#666;">PDH</div>'
    '<div style="font-size:18px;font-weight:bold;">Rs {:,.2f}</div></div>'.format(pdh)
    + '<div style="flex:1;padding:10px;background:#f8f9fa;border-radius:8px;border-left:4px solid #00b300;">'
    '<div style="font-size:12px;color:#666;">PDL</div>'
    '<div style="font-size:18px;font-weight:bold;">Rs {:,.2f}</div></div></div>'.format(pdl),
    unsafe_allow_html=True,
)

st.markdown("---")
st.subheader("Classic Pivots")
pc = (pdh + pdl + pdc) / 3
r1c = 2 * pc - pdl
s1c = 2 * pc - pdh
r2c = pc + (r1c - s1c)
s2c = pc - (r1c - s1c)
r3c = pdh + 2 * (pc - pdl)
s3c = pdl - 2 * (pdh - pc)
p1, p2, p3 = st.columns(3)
p1.metric("R3", "Rs {:,.2f}".format(r3c))
p1.metric("R2", "Rs {:,.2f}".format(r2c))
p1.metric("R1", "Rs {:,.2f}".format(r1c))
p2.metric("Pivot", "Rs {:,.2f}".format(pc))
p2.metric("Spot", "Rs {:,.2f}".format(sp))
p3.metric("S1", "Rs {:,.2f}".format(s1c))
p3.metric("S2", "Rs {:,.2f}".format(s2c))
p3.metric("S3", "Rs {:,.2f}".format(s3c))

st.markdown("---")
st.subheader("Gap Up / Gap Down")
try:
    h1 = gsd("^NSEI", "5d", "1m")
    if not h1.empty:
        h1.index = pd.to_datetime(h1.index)
        h1.index = h1.index.tz_convert("Asia/Kolkata") if h1.index.tz is not None else h1.index.tz_localize("Asia/Kolkata")
        d3 = h1.resample("3min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
        d3["D"] = d3.index.date
        ad = sorted(d3["D"].unique())
        if len(ad) >= 2:
            pcd = d3[d3["D"] == ad[-2]]
            tcd = d3[d3["D"] == ad[-1]]
            if len(pcd) > 0 and len(tcd) > 0:
                x1h = float(pcd.iloc[-1]["High"])
                x2h = float(tcd.iloc[0]["High"])
                x1l = float(pcd.iloc[-1]["Low"])
                x2l = float(tcd.iloc[0]["Low"])
                x3u = x2h - x1h
                x4u = x3u / 2
                x5u = x1h - x4u
                x3d = x2l - x1l
                x4d = x3d / 2
                x5d = x2l + x4d
                pvl = float(pcd["Close"].iloc[-1])
                tvl = float(tcd["Open"].iloc[0])
                gp = tvl - pvl
                gpp = (gp / pvl * 100) if pvl != 0 else 0
                if gp > 0:
                    gt = "GAP UP"
                    gc = "#00b300"
                elif gp < 0:
                    gt = "GAP DOWN"
                    gc = "#cc0000"
                else:
                    gt = "FLAT"
                    gc = "#666666"
                st.markdown('<div style="padding:10px;background:#f8f9fa;border-radius:8px;border-left:4px solid ' + gc + ';"><b style="color:' + gc + ';">' + gt + '</b><br>Gap: <b>Rs {:,.2f} pts</b> ({:+.2f}%)<br><span style="font-size:12px;">Prev: Rs {:,.2f} | Open: Rs {:,.2f}</span></div>'.format(gp, gpp, pvl, tvl), unsafe_allow_html=True)
                gg1, gg2, gg3 = st.columns(3)
                gg1.markdown("**Gap Up**")
                gg1.write("X1H: Rs {:,.2f}".format(x1h))
                gg1.write("X2H: Rs {:,.2f}".format(x2h))
                gg1.write("X3: {:+,.2f}".format(x3u))
                gg1.write("X4: {:+,.2f}".format(x4u))
                gg1.success("X5: Rs {:,.2f}".format(x5u))
                gg2.markdown("**Gap Down**")
                gg2.write("X1L: Rs {:,.2f}".format(x1l))
                gg2.write("X2L: Rs {:,.2f}".format(x2l))
                gg2.write("X3: {:+,.2f}".format(x3d))
                gg2.write("X4: {:+,.2f}".format(x4d))
                gg2.error("X5: Rs {:,.2f}".format(x5d))
                gg3.markdown("**Insight**")
                if gp > 0: gg3.info("Reversal: Rs {:,.2f}".format(x5u))
                elif gp < 0: gg3.info("Upside: Rs {:,.2f}".format(x5d))
                else: gg3.info("No gap")
except: st.caption("3-min unavailable.")

st.markdown("---")
st.subheader("Option Chain OI (Model)")
atm = int(round(sp / 50) * 50)
sk = [atm + (i * 50) for i in range(-5, 6)]
rr = []
tcl = 0
tpt = 0
for s in sk:
    dd = abs(sp - s)
    co = int(max(800000, 4500000 - (dd * 8500)))
    po = int(max(700000, 5200000 - (dd * 8000)))
    tcl += co
    tpt += po
    if po > co * 1.08: sg = "Put Support"
    elif co > po * 1.08: sg = "Call Resist"
    else: sg = "Neutral"
    rr.append({"Strike": "Rs {:,}".format(s) + (" (ATM)" if s == atm else ""), "Call OI": "{:.1f}L".format(co/100000), "Put OI": "{:.1f}L".format(po/100000), "Signal": sg})
pcr = tpt / tcl if tcl > 0 else 0
o1, o2, o3 = st.columns(3)
o1.metric("PCR", "{:.2f}".format(pcr))
o2.metric("Call OI", "{:.1f}L".format(tcl/100000))
o3.metric("Put OI", "{:.1f}L".format(tpt/100000))
st.dataframe(pd.DataFrame(rr), hide_index=True, use_container_width=True)

st.markdown("---")
st.subheader("OI Spike")
mx_c = max([int(max(800000, 4500000 - (abs(sp - s) * 8500))) for s in sk])
mx_p = max([int(max(700000, 5200000 - (abs(sp - s) * 8000))) for s in sk])
spl = []
for s in sk:
    dd = abs(sp - s)
    co = int(max(800000, 4500000 - (dd * 8500)))
    po = int(max(700000, 5200000 - (dd * 8000)))
    if co >= mx_c: spl.append("Rs {:,} Call - Strong Resistance".format(s))
    if po >= mx_p: spl.append("Rs {:,} Put - Strong Support".format(s))
if spl:
    for x in spl: st.info(x)
else: st.caption("No spike.")

st.markdown("---")
st.subheader("Market Structure")
bc2 = [sp > TC, sp > vw, e9 > e21, rv >= 55]
sc2 = [sp < BC, sp < vw, e9 < e21, rv <= 45]
if all(bc2): st.success("Bullish.")
elif all(sc2): st.error("Bearish.")
else: st.info("Mixed.")

st.markdown("---")
st.subheader("Market Breadth")
bst = gbreadth()
if bst:
    b1, b2, b3 = st.columns(3)
    b1.metric("Adv", sum(1 for s in bst if s["c"] > 0.05))
    b2.metric("Dec", sum(1 for s in bst if s["c"] < -0.05))
    b3.metric("Avg", "{:+.2f}%".format(sum(s["c"] for s in bst)/len(bst)))
    ss = sorted(bst, key=lambda x: x["c"], reverse=True)
    gh = ""
    for s in ss[:5]:
        gh += '<div style="padding:2px;"><b>' + s["s"] + '</b> Rs {:,.2f} <span style="color:#00b300;">({:+.2f}%)</span></div>'.format(s["l"], s["c"])
    lh = ""
    for s in ss[-5:][::-1]:
        lh += '<div style="padding:2px;"><b>' + s["s"] + '</b> Rs {:,.2f} <span style="color:#cc0000;">({:+.2f}%)</span></div>'.format(s["l"], s["c"])
    st.markdown('<div style="display:flex;gap:10px;"><div style="flex:1;"><b style="color:#00b300;">Gainers</b>' + gh + '</div><div style="flex:1;"><b style="color:#cc0000;">Losers</b>' + lh + '</div></div>', unsafe_allow_html=True)

st.markdown("---")
st.subheader("NIFTY Chart & CPR")
cd = sh[["Close", "VWAP"]].copy()
cd = cd.replace([np.inf, -np.inf], np.nan).dropna(subset=["Close"])
cd = cd[cd["Close"] > 0].copy()
if not cd.empty:
    fig = go.Figure()
    fig.add_hrect(y0=BC, y1=TC, fillcolor="LightSkyBlue", opacity=0.15, line_width=0, layer="below")
    fig.add_trace(go.Scatter(x=cd.index, y=cd["Close"], mode="lines+markers", name="Price", line=dict(color="#0052cc", width=2), marker=dict(color="#0052cc", size=8)))
    fig.add_trace(go.Scatter(x=cd.index, y=cd["VWAP"], mode="lines", name="VWAP", line=dict(color="#ff9900", width=1.5, dash="dash")))
    for nm, vl, cl in [("TC", TC, "#66b3ff"), ("Pivot", PP, "#0066cc"), ("BC", BC, "#3399ff"), ("R1", R1, "#ff6666"), ("S1", S1, "#66cc66"), ("PDH", pdh, "#cc0000"), ("PDL", pdl, "#00b300")]:
        fig.add_trace(go.Scatter(x=[cd.index[0], cd.index[-1]], y=[vl, vl], mode="lines", name=nm, line=dict(color=cl, width=1, dash="dot")))
    cvl = list(cd["Close"]) + list(cd["VWAP"].dropna()) + [pdh, pdl, R1, R2, S1, S2, PP, BC, TC]
    vvl = [float(v) for v in cvl if pd.notna(v) and np.isfinite(v) and abs(float(v) - sp) <= 500]
    if len(vvl) < 3:
        ymn = sp - 150
        ymx = sp + 150
    else:
        lo = min(vvl)
        hi = max(vvl)
        pdd = max(50.0, (hi - lo) * 0.15)
        ymn = lo - pdd
        ymx = hi + pdd
        if ymx - ymn < 200:
            ymn = sp - 100
            ymx = sp + 100
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=25, b=25), xaxis=dict(tickformat="%H:%M"), yaxis=dict(range=[ymn, ymx], fixedrange=False), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)
else: st.warning("Chart unavailable.")

st.markdown("---")
st.subheader("Buy/Sell Volume (Est.)")
try:
    vd = sh[["Open", "High", "Low", "Close", "Volume"]].dropna()
    vd = vd[vd["Volume"] > 0]
    if len(vd) >= 5:
        ag = vd.resample("15min").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
        if len(ag) >= 2:
            bv = []
            sv = []
            tl = []
            for i, r in ag.iterrows():
                tv = float(r["Volume"])
                o = float(r["Open"])
                c = float(r["Close"])
                hh = float(r["High"])
                ll = float(r["Low"])
                rng = hh - ll if hh > ll else 1
                if c >= o:
                    br = (c - o) / rng if rng > 0 else 0.5
                    brt = 0.5 + (br * 0.4)
                    if brt > 0.85: brt = 0.85
                else:
                    br = (o - c) / rng if rng > 0 else 0.5
                    brt = 0.5 - (br * 0.4)
                    if brt < 0.15: brt = 0.15
                bv.append(tv * brt)
                sv.append(tv * (1 - brt))
                tl.append(i.strftime("%H:%M"))
            fv = go.Figure()
            fv.add_trace(go.Bar(x=tl, y=bv, name="Buy", marker_color="#00b300"))
            fv.add_trace(go.Bar(x=tl, y=sv, name="Sell", marker_color="#cc0000"))
            fv.update_layout(barmode="group", height=320, xaxis_title="Time", yaxis_title="Vol")
            st.plotly_chart(fv, use_container_width=True)
            tb = sum(bv)
            ts = sum(sv)
            tot = tb + ts
            if tot > 0:
                bpp = (tb / tot) * 100
                st.write("Buy%: {:.1f}% | Sell%: {:.1f}%".format(bpp, 100 - bpp))
except: st.caption("Volume unavailable.")

st.markdown("---")
st.subheader("Pattern Visual Chart")
try:
    vdf = sh[["High", "Low", "Close"]].dropna()
    if len(vdf) >= 20:
        vhi = vdf["High"].values
        vlo = vdf["Low"].values
        vcl = vdf["Close"].values
        vt = vdf.index
        shi = []
        shv = []
        for i in range(2, len(vhi) - 2):
            if vhi[i] > vhi[i-1] and vhi[i] > vhi[i-2] and vhi[i] > vhi[i+1] and vhi[i] > vhi[i+2]:
                shi.append(i)
                shv.append(float(vhi[i]))
        sli = []
        slv = []
        for i in range(2, len(vlo) - 2):
            if vlo[i] < vlo[i-1] and vlo[i] < vlo[i-2] and vlo[i] < vlo[i+1] and vlo[i] < vlo[i+2]:
                sli.append(i)
                slv.append(float(vlo[i]))
        vf = go.Figure()
        vf.add_trace(go.Scatter(x=vt, y=vcl, mode="lines", name="Price", line=dict(color="#0052cc", width=2.5)))
        if shi:
            vf.add_trace(go.Scatter(x=[vt[i] for i in shi], y=shv, mode="markers+text", name="H", marker=dict(color="#cc0000", size=10, symbol="triangle-down"), text=["H" + str(k+1) for k in range(len(shi))], textposition="top center", textfont=dict(size=9, color="#cc0000")))
        if sli:
            vf.add_trace(go.Scatter(x=[vt[i] for i in sli], y=slv, mode="markers+text", name="L", marker=dict(color="#00b300", size=10, symbol="triangle-up"), text=["L" + str(k+1) for k in range(len(sli))], textposition="bottom center", textfont=dict(size=9, color="#00b300")))
        vf.update_layout(height=400, margin=dict(l=10, r=10, t=25, b=25), xaxis=dict(title="Time", tickformat="%H:%M"), yaxis=dict(title="Price"), hovermode="x unified")
        st.plotly_chart(vf, use_container_width=True)
        if len(sli) >= 2 and slv[-2] > 0 and abs(slv[-2] - slv[-1]) / slv[-2] < 0.006:
            st.info("Possible W / Double Bottom.")
        if len(shi) >= 2 and shv[-2] > 0 and abs(shv[-2] - shv[-1]) / shv[-2] < 0.006:
            st.info("Possible M / Double Top.")
except: st.caption("Pattern unavailable.")

st.markdown("---")
st.subheader("Technical Indicators")
i1, i2, i3, i4 = st.columns(4)
i1.metric("EMA 9", "Rs {:,.2f}".format(e9))
i2.metric("EMA 21", "Rs {:,.2f}".format(e21))
i3.metric("VWAP", "Rs {:,.2f}".format(vw))
if rv >= 70: rl = "Overbought"
elif rv <= 30: rl = "Oversold"
else: rl = "Neutral"
i4.metric("RSI", "{:.2f}".format(rv), rl)

st.markdown("---")
st.subheader("தமிழ் பங்கு வர்த்தக செய்திகள்")
for it in gnews():
    st.markdown(it)

st.caption("Yahoo Finance may be delayed. Not financial advice.")

# ===== Big Player panel (paste at the very end of app.py) =====

# ^NSEI (index) has no volume in yfinance, so scan NIFTY 50 heavyweights instead
BIG_STOCKS = [
    "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS",
    "ITC.NS", "LT.NS", "BHARTIARTL.NS", "SBIN.NS", "AXISBANK.NS",
    "KOTAKBANK.NS", "HINDUNILVR.NS", "BAJFINANCE.NS", "M&M.NS", "MARUTI.NS",
]

VOL_MULT = 2.5    # candle volume must be >= 2.5x recent average
BODY_MULT = 1.5   # candle body must be >= 1.5x recent average body
LOOKBACK = 20     # candles used for the averages


@st.cache_data(ttl=60)
def _download(sym):
    df = yf.download(sym, period="5d", interval="5m", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def detect_big_player(df):
    """Check the last COMPLETED 5m candle for a volume + body spike."""
    if df is None or len(df) < LOOKBACK + 3:
        return None
    df = df.copy()
    df["vol_avg"] = df["Volume"].rolling(LOOKBACK).mean().shift(1)
    df["body"] = (df["Close"] - df["Open"]).abs()
    df["body_avg"] = df["body"].rolling(LOOKBACK).mean().shift(1)

    last = df.iloc[-2]
    if pd.isna(last["vol_avg"]) or last["vol_avg"] <= 0 or pd.isna(last["body_avg"]):
        return None

    vol_ratio = float(last["Volume"] / last["vol_avg"])
    strong_body = float(last["body"]) > BODY_MULT * float(last["body_avg"])

    if vol_ratio >= VOL_MULT and strong_body:
        return {
            "Side": "BUY" if last["Close"] > last["Open"] else "SELL",
            "Volume x": round(vol_ratio, 1),
            "Time": df.index[-2].strftime("%H:%M"),
            "Price": round(float(last["Close"]), 2),
        }
    return None


def render_big_player_panel():
    st.subheader("பிக் பிளேயர் என்ட்ரி (Big Player Alert)")
    rows = []
    for sym in BIG_STOCKS:
        try:
            hit = detect_big_player(_download(sym))
        except Exception:
            hit = None
        if hit:
            hit["Stock"] = sym.replace(".NS", "")
            rows.append(hit)

    if not rows:
        st.caption("இப்போது பெரிய வால்யூம் என்ட்ரி எதுவும் இல்லை (last 5m candle).")
        return

    out = pd.DataFrame(rows)[["Stock", "Side", "Volume x", "Price", "Time"]]
    out = out.sort_values("Volume x", ascending=False)
    st.dataframe(out, use_container_width=True, hide_index=True)

    buys = int((out["Side"] == "BUY").sum())
    sells = int((out["Side"] == "SELL").sum())
    if buys > sells:
        st.success(f"பெரிய வாங்குதல் அதிகம்: BUY {buys} / SELL {sells}")
    elif sells > buys:
        st.error(f"பெரிய விற்பனை அதிகம்: SELL {sells} / BUY {buys}")
    else:
        st.info(f"கலவையான நிலை: BUY {buys} / SELL {sells}")

st.markdown("---")
render_big_player_panel()
