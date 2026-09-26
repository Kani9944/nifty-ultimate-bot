# 3. Current Price Dot Marker
latest_bar = chart_df.iloc[[-1]]
price_dot = (
    alt.Chart(latest_bar)
    .mark_point(
        color="#0052cc",
        filled=True,
        size=85,
        shape="circle",
    )
    .encode(
        x=alt.X("Time:T"),
        y=alt.Y("Close:Q"),
        tooltip=[
            alt.Tooltip("Time:T", title="Latest bar", format="%d-%b %H:%M"),
            alt.Tooltip("Close:Q", title="Current price", format=",.2f"),
        ],
    )
)

# 4. CPR Band: BC முதல் TC வரை மெல்லிய highlighted zone
cpr_band_data = pd.DataFrame([
    {
        "Start": chart_start,
        "End": chart_end,
        "Lower": float(BC),
        "Upper": float(TC),
    }
])

cpr_band = (
    alt.Chart(cpr_band_data)
    .mark_rect(color="#9ecae1", opacity=0.14)
    .encode(
        x=alt.X("Start:T"),
        x2="End:T",
        y=alt.Y("Lower:Q"),
        y2="Upper:Q",
    )
)

# 5. PDH / R1 / TC / Pivot / BC / S1 / PDL horizontal dashed levels
level_rules = (
    alt.Chart(levels_data)
    .mark_rule(strokeDash=[4, 4], strokeWidth=1.2)
    .encode(
        y=alt.Y("Value:Q"),
        color=alt.Color("Color:N", scale=None, legend=None),
        tooltip=[
            alt.Tooltip("Level:N", title="Level"),
            alt.Tooltip("Value:Q", title="Price", format=",.2f"),
        ],
    )
)

# 6. வலதுபுறம் key-level labels
level_labels = (
    alt.Chart(levels_data)
    .mark_text(
        align="left",
        dx=5,
        dy=-4,
        fontSize=11,
        fontWeight="bold",
    )
    .encode(
        x=alt.X("Time:T"),
        y=alt.Y("Value:Q"),
        text=alt.Text("Level:N"),
        color=alt.Color("Color:N", scale=None, legend=None),
    )
)

# 7. Current LTP label
current_price_label_data = pd.DataFrame([
    {
        "Time": chart_df["Time"].max() + pd.Timedelta(minutes=3),
        "Price": spot_price,
        "Label": f"LTP ₹{spot_price:,.2f}",
    }
])

current_price_label = (
    alt.Chart(current_price_label_data)
    .mark_text(
        align="left",
        dx=5,
        dy=10,
        fontSize=11,
        fontWeight="bold",
        color="#0052cc",
    )
    .encode(
        x=alt.X("Time:T"),
        y=alt.Y("Price:Q"),
        text=alt.Text("Label:N"),
    )
)

# 8. அனைத்து layers-ஐயும் ஒரே chart-ஆக இணைத்தல்
final_chart = (
    cpr_band
    + level_rules
    + price_line
    + vwap_line
    + price_dot
    + level_labels
    + current_price_label
).resolve_scale(
    x="shared",
    y="shared",
).properties(
    height=440,
    title="NIFTY Intraday Price, VWAP, CPR and Key Levels",
)

st.altair_chart(
    final_chart,
    use_container_width=True,
    theme=None,
)
