import streamlit as st
import pandas as pd
from sqlalchemy import create_engine

# ===========================
# PAGE CONFIG
# ===========================

st.set_page_config(
    page_title="The Young Shall Grow – Njangi Dashboard",
    layout="wide"
)

st.title("🪙 The Young Shall Grow – Njangi Dashboard")


# ===========================
# DB CONNECTION HELPERS
# ===========================

@st.cache_resource
def get_engine():
    """
    Create a SQLAlchemy engine using the db_url
    defined in Streamlit Cloud secrets.
    """
    return create_engine(st.secrets["db_url"])


@st.cache_data
def load_data():
    """
    Load all main tables from Supabase:
    - members
    - app_state
    - history
    """
    engine = get_engine()

    members = pd.read_sql("SELECT * FROM public.members", engine)
    app_state = pd.read_sql("SELECT * FROM public.app_state", engine)
    history = pd.read_sql("SELECT * FROM public.history ORDER BY created_at DESC", engine)

    # Ensure datetime types
    if "created_at" in members.columns:
        members["created_at"] = pd.to_datetime(members["created_at"])

    if "updated_at" in app_state.columns:
        app_state["updated_at"] = pd.to_datetime(app_state["updated_at"])

    if "created_at" in history.columns:
        history["created_at"] = pd.to_datetime(history["created_at"])

    return members, app_state, history


# ===========================
# LOAD DATA (WITH ERROR HANDLING)
# ===========================

try:
    members, app_state, history = load_data()
except Exception as e:
    st.error("❌ Could not connect to Supabase or load tables.")
    st.exception(e)
    st.stop()


# ===========================
# SIDEBAR FILTERS
# ===========================

st.sidebar.header("Filters")

# Member filter (by name)
member_names = ["All members"] + sorted(members["name"].tolist())
selected_member = st.sidebar.selectbox("Member", member_names)

# History date range filter
if not history.empty:
    min_date = history["created_at"].min().date()
    max_date = history["created_at"].max().date()
    date_range = st.sidebar.date_input(
        "History date range",
        value=(min_date, max_date),
    )
    if isinstance(date_range, tuple):
        start_date, end_date = date_range
    else:
        start_date, end_date = min_date, max_date
else:
    start_date = end_date = None

# History type filter
history_types = ["All types"] + sorted(history["type"].unique().tolist())
selected_type = st.sidebar.selectbox("Transaction type", history_types)


# Apply filters to history
history_filtered = history.copy()

if start_date and end_date:
    history_filtered = history_filtered[
        (history_filtered["created_at"].dt.date >= start_date)
        & (history_filtered["created_at"].dt.date <= end_date)
    ]

if selected_member != "All members":
    history_filtered = history_filtered[history_filtered["member"] == selected_member]

if selected_type != "All types":
    history_filtered = history_filtered[history_filtered["type"] == selected_type]


# ===========================
# KPIs (TOP CARDS)
# ===========================

num_members = len(members)

total_contributed = members["contributed"].sum()
total_foundation_contrib = members["foundation_contrib"].sum()
total_loan_due = members["loan_due"].sum()

# Foundation balance from app_state if available, else fallback
if not app_state.empty:
    current_foundation = float(app_state["foundation"].iloc[0] or 0)
    next_payout_index = int(app_state["next_payout_index"].iloc[0] or 0)
else:
    current_foundation = float(total_foundation_contrib)
    next_payout_index = 0

col1, col2, col3, col4 = st.columns(4)

col1.metric("👥 Active Members", f"{num_members}")
col2.metric("💰 Total Contributed", f"${total_contributed:,.2f}")
col3.metric("🏦 Foundation Balance", f"${current_foundation:,.2f}")
col4.metric("📉 Total Loan Due", f"${total_loan_due:,.2f}")

st.markdown("---")


# ===========================
# CONTRIBUTIONS & LOANS BY MEMBER
# ===========================

st.subheader("Member Contributions & Loan Exposure")

# Optionally filter members for charts
members_chart = members.copy()
if selected_member != "All members":
    members_chart = members_chart[members_chart["name"] == selected_member]

if not members_chart.empty:
    # Bar chart of contributions
    contrib_chart = (
        members_chart[["name", "contributed"]]
        .set_index("name")
        .sort_values("contributed", ascending=False)
    )
    loan_chart = (
        members_chart[["name", "loan_due"]]
        .set_index("name")
        .sort_values("loan_due", ascending=False)
    )

    c_left, c_right = st.columns(2)
    with c_left:
        st.caption("Total contributed per member")
        st.bar_chart(contrib_chart, use_container_width=True)

    with c_right:
        st.caption("Loan due per member")
        st.bar_chart(loan_chart, use_container_width=True)
else:
    st.info("No member data available for the current filter.")


st.markdown("---")


# ===========================
# PAYOUT ROTATION VIEW
# ===========================

st.subheader("Payout Rotation Order")

# Sort members by position
rotation_df = (
    members[["id", "name", "position", "contributed", "loan_due"]]
    .sort_values("position")
    .reset_index(drop=True)
)

# Add helper column: is_next
if not rotation_df.empty:
    # next_payout_index is assumed 0-based index into this sorted list
    rotation_df["is_next"] = False
    if 0 <= next_payout_index < len(rotation_df):
        rotation_df.loc[next_payout_index, "is_next"] = True
else:
    rotation_df["is_next"] = False

def highlight_next(row):
    if row.get("is_next"):
        return ["background-color: #d1fade"] * len(row)
    return [""] * len(row)

if not rotation_df.empty:
    display_rotation = rotation_df[["position", "name", "contributed", "loan_due", "is_next"]]
    st.dataframe(
        display_rotation.style.apply(highlight_next, axis=1),
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("No rotation data available.")


st.markdown("---")


# ===========================
# TRANSACTION HISTORY
# ===========================

st.subheader("Transaction History (Log)")

if history_filtered.empty:
    st.info("No transactions found for the selected filters.")
else:
    st.caption("Latest transactions (Contributions, Loans, Repayments, etc.)")

    # Small summary metrics from filtered history
    total_hist_amount = history_filtered["amount"].fillna(0).sum()
    total_hist_due = history_filtered["total_due"].fillna(0).sum()

    h1, h2 = st.columns(2)
    h1.metric("Filtered transaction amount", f"${total_hist_amount:,.2f}")
    h2.metric("Filtered total due (if applicable)", f"${total_hist_due:,.2f}")

    st.dataframe(
        history_filtered[
            ["created_at", "type", "member", "amount", "interest_percent", "total_due"]
        ],
        use_container_width=True,
        hide_index=True
    )
