import streamlit as st
import pandas as pd
from supabase import create_client

# ===========================
# PAGE CONFIG
# ===========================
st.set_page_config(
    page_title="The Young Shall Grow – Njangi Dashboard",
    layout="wide"
)

st.title("🪙 The Young Shall Grow – Njangi Dashboard")


# ===========================
# SUPABASE CONNECTION
# ===========================
@st.cache_resource
def get_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)

supabase = get_supabase()


# ===========================
# DATA LOADERS
# ===========================
def _fetch_table(table_name: str, limit: int = 2000):
    """
    Fetch rows from a Supabase table using the REST API.
    """
    res = supabase.table(table_name).select("*").limit(limit).execute()
    return res.data

@st.cache_data(ttl=60)
def load_data():
    """
    Load all main tables from Supabase:
    - members
    - app_state
    - history
    """
    members_data = _fetch_table("members", limit=5000)
    app_state_data = _fetch_table("app_state", limit=10)

    # history with ordering (newest first)
    history_res = (
        supabase.table("history")
        .select("*")
        .order("created_at", desc=True)
        .limit(5000)
        .execute()
    )
    history_data = history_res.data

    members = pd.DataFrame(members_data)
    app_state = pd.DataFrame(app_state_data)
    history = pd.DataFrame(history_data)

    # Ensure expected columns exist even if empty
    if members.empty:
        members = pd.DataFrame(columns=["id", "name", "position", "contributed", "foundation_contrib", "loan_due", "created_at"])
    if app_state.empty:
        app_state = pd.DataFrame(columns=["id", "foundation", "next_payout_index", "updated_at"])
    if history.empty:
        history = pd.DataFrame(columns=["created_at", "type", "member", "amount", "interest_percent", "total_due"])

    # Datetime conversions
    for df, col in [(members, "created_at"), (app_state, "updated_at"), (history, "created_at")]:
        if col in df.columns and not df.empty:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Numeric safety (avoid crashes if nulls)
    for col in ["contributed", "foundation_contrib", "loan_due"]:
        if col in members.columns:
            members[col] = pd.to_numeric(members[col], errors="coerce").fillna(0)

    for col in ["amount", "interest_percent", "total_due"]:
        if col in history.columns:
            history[col] = pd.to_numeric(history[col], errors="coerce").fillna(0)

    if "foundation" in app_state.columns:
        app_state["foundation"] = pd.to_numeric(app_state["foundation"], errors="coerce").fillna(0)

    if "next_payout_index" in app_state.columns:
        app_state["next_payout_index"] = pd.to_numeric(app_state["next_payout_index"], errors="coerce").fillna(0).astype(int)

    return members, app_state, history


# ===========================
# LOAD DATA (WITH ERROR HANDLING)
# ===========================
try:
    members, app_state, history = load_data()
except Exception as e:
    st.error("❌ Could not connect to Supabase or load tables.")
    st.caption("Most common cause: Supabase RLS is blocking reads for the anon key.")
    st.exception(e)
    st.stop()


# ===========================
# SIDEBAR FILTERS
# ===========================
st.sidebar.header("Filters")

# Member filter (by name)
member_names = ["All members"] + sorted(members["name"].dropna().astype(str).tolist())
selected_member = st.sidebar.selectbox("Member", member_names)

# History date range filter
if not history.empty and "created_at" in history.columns and history["created_at"].notna().any():
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
if not history.empty and "type" in history.columns:
    history_types = ["All types"] + sorted(history["type"].dropna().astype(str).unique().tolist())
else:
    history_types = ["All types"]
selected_type = st.sidebar.selectbox("Transaction type", history_types)


# Apply filters to history
history_filtered = history.copy()

if start_date and end_date and "created_at" in history_filtered.columns:
    history_filtered = history_filtered[
        (history_filtered["created_at"].dt.date >= start_date)
        & (history_filtered["created_at"].dt.date <= end_date)
    ]

if selected_member != "All members" and "member" in history_filtered.columns:
    history_filtered = history_filtered[history_filtered["member"].astype(str) == str(selected_member)]

if selected_type != "All types" and "type" in history_filtered.columns:
    history_filtered = history_filtered[history_filtered["type"].astype(str) == str(selected_type)]


# ===========================
# KPIs (TOP CARDS)
# ===========================
num_members = len(members)

total_contributed = members["contributed"].sum() if "contributed" in members.columns else 0
total_foundation_contrib = members["foundation_contrib"].sum() if "foundation_contrib" in members.columns else 0
total_loan_due = members["loan_due"].sum() if "loan_due" in members.columns else 0

# Foundation balance from app_state if available, else fallback
if not app_state.empty and "foundation" in app_state.columns:
    current_foundation = float(app_state["foundation"].iloc[0] or 0)
    next_payout_index = int(app_state["next_payout_index"].iloc[0] or 0) if "next_payout_index" in app_state.columns else 0
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

members_chart = members.copy()
if selected_member != "All members":
    members_chart = members_chart[members_chart["name"].astype(str) == str(selected_member)]

if not members_chart.empty and "name" in members_chart.columns:
    if "contributed" in members_chart.columns:
        contrib_chart = (
            members_chart[["name", "contributed"]]
            .set_index("name")
            .sort_values("contributed", ascending=False)
        )
    else:
        contrib_chart = pd.DataFrame()

    if "loan_due" in members_chart.columns:
        loan_chart = (
            members_chart[["name", "loan_due"]]
            .set_index("name")
            .sort_values("loan_due", ascending=False)
        )
    else:
        loan_chart = pd.DataFrame()

    c_left, c_right = st.columns(2)
    with c_left:
        st.caption("Total contributed per member")
        if not contrib_chart.empty:
            st.bar_chart(contrib_chart, use_container_width=True)
        else:
            st.info("No contributed column found.")

    with c_right:
        st.caption("Loan due per member")
        if not loan_chart.empty:
            st.bar_chart(loan_chart, use_container_width=True)
        else:
            st.info("No loan_due column found.")
else:
    st.info("No member data available for the current filter.")

st.markdown("---")


# ===========================
# PAYOUT ROTATION VIEW
# ===========================
st.subheader("Payout Rotation Order")

rotation_cols = [c for c in ["id", "name", "position", "contributed", "loan_due"] if c in members.columns]
if rotation_cols:
    rotation_df = (
        members[rotation_cols]
        .sort_values("position" if "position" in members.columns else "name")
        .reset_index(drop=True)
    )
else:
    rotation_df = pd.DataFrame()

if not rotation_df.empty:
    rotation_df["is_next"] = False
    if 0 <= next_payout_index < len(rotation_df):
        rotation_df.loc[next_payout_index, "is_next"] = True

    def highlight_next(row):
        return ["background-color: #d1fade"] * len(row) if row.get("is_next") else [""] * len(row)

    show_cols = [c for c in ["position", "name", "contributed", "loan_due", "is_next"] if c in rotation_df.columns]
    st.dataframe(
        rotation_df[show_cols].style.apply(highlight_next, axis=1),
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

    total_hist_amount = history_filtered["amount"].fillna(0).sum() if "amount" in history_filtered.columns else 0
    total_hist_due = history_filtered["total_due"].fillna(0).sum() if "total_due" in history_filtered.columns else 0

    h1, h2 = st.columns(2)
    h1.metric("Filtered transaction amount", f"${total_hist_amount:,.2f}")
    h2.metric("Filtered total due (if applicable)", f"${total_hist_due:,.2f}")

    display_cols = [c for c in ["created_at", "type", "member", "amount", "interest_percent", "total_due"] if c in history_filtered.columns]
    st.dataframe(
        history_filtered[display_cols],
        use_container_width=True,
        hide_index=True
    )
