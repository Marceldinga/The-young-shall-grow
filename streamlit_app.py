# ============================================================
# streamlit_app.py  (Single Complete Script)
# - Uses Supabase API (NO SQLAlchemy)
# - Loads existing data from Supabase
# - Dashboard KPIs + charts + rotation + history log
# - Admin login (password in Streamlit Secrets)
# - Forms to add Member / Contribution / Loan / Repayment
# - "Restore" tool: rebuild member totals from existing history
#   (preview first, optional write-back to members table)
#
# REQUIRED Streamlit Secrets:
#   SUPABASE_URL = "https://xxxx.supabase.co"
#   SUPABASE_ANON_KEY = "xxxx"
#   ADMIN_PASSWORD = "your_password"
#
# requirements.txt:
#   streamlit
#   pandas
#   supabase
# ============================================================

import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import datetime

# ---------------------------
# Page config
# ---------------------------
st.set_page_config(page_title="The Young Shall Grow – Njangi Dashboard", layout="wide")
st.title("🪙 The Young Shall Grow – Njangi Dashboard")


# ---------------------------
# Supabase client
# ---------------------------
@st.cache_resource
def get_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])

supabase = get_supabase()


# ---------------------------
# Helpers
# ---------------------------
def now_iso() -> str:
    return datetime.utcnow().isoformat()

def safe_df(rows, ensure_cols=None) -> pd.DataFrame:
    df = pd.DataFrame(rows or [])
    if ensure_cols:
        for c in ensure_cols:
            if c not in df.columns:
                df[c] = None
    return df

def to_num(df: pd.DataFrame, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df

def to_dt(df: pd.DataFrame, cols):
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df

def fetch_all_rows(table: str, page_size: int = 1000, order_col: str | None = None, desc: bool = False):
    """
    Fetch all rows from a table in pages using range().
    """
    out = []
    start = 0
    while True:
        q = supabase.table(table).select("*")
        if order_col:
            q = q.order(order_col, desc=desc)
        res = q.range(start, start + page_size - 1).execute()
        batch = res.data or []
        out.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return out

def table_exists_quick(name: str) -> bool:
    """
    Quick check: attempt a lightweight select; returns False if table not accessible.
    """
    try:
        supabase.table(name).select("*").limit(1).execute()
        return True
    except Exception:
        return False

def admin_gate() -> bool:
    """
    Simple admin login using ADMIN_PASSWORD from secrets.
    """
    admin_pw = st.secrets.get("ADMIN_PASSWORD", "")
    if not admin_pw:
        st.warning("ADMIN_PASSWORD not set in Secrets. Admin features are disabled.")
        return False

    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False

    if st.session_state.is_admin:
        return True

    with st.container(border=True):
        st.subheader("🔐 Admin Login")
        pw = st.text_input("Password", type="password")
        if st.button("Login", use_container_width=True):
            if pw == admin_pw:
                st.session_state.is_admin = True
                st.success("Logged in.")
                st.rerun()
            else:
                st.error("Wrong password.")
    return False

def history_column_guess(history_df: pd.DataFrame):
    """
    Guess history column names across different schemas.
    """
    # type column
    type_col = "type" if "type" in history_df.columns else ("event_type" if "event_type" in history_df.columns else None)
    # member name column
    member_col = "member" if "member" in history_df.columns else ("member_name" if "member_name" in history_df.columns else None)
    # amount column
    amount_col = "amount" if "amount" in history_df.columns else ("value" if "value" in history_df.columns else None)
    # total_due column
    total_due_col = "total_due" if "total_due" in history_df.columns else ("due_total" if "due_total" in history_df.columns else None)
    # interest column
    interest_col = "interest_percent" if "interest_percent" in history_df.columns else ("interest" if "interest" in history_df.columns else None)
    # created at
    created_col = "created_at" if "created_at" in history_df.columns else ("timestamp" if "timestamp" in history_df.columns else None)
    return type_col, member_col, amount_col, total_due_col, interest_col, created_col

def log_history(history_table: str, tx_type: str, member_name: str, amount: float = 0, interest_percent: float = 0, total_due: float = 0):
    """
    Insert into history table if it exists and is writable.
    Uses common column names; if your history schema is different, it still won't break the app.
    """
    if not history_table:
        return
    payload = {}
    # Try to match common schemas
    payload["type"] = tx_type
    payload["member"] = member_name
    payload["amount"] = float(amount or 0)
    payload["interest_percent"] = float(interest_percent or 0)
    payload["total_due"] = float(total_due or 0)
    payload["created_at"] = now_iso()

    try:
        supabase.table(history_table).insert(payload).execute()
    except Exception:
        # Fallback schema: event_type/details/member_id/member_name etc.
        try:
            payload2 = {
                "event_type": tx_type,
                "details": f"{tx_type} | amount={float(amount or 0)} | due={float(total_due or 0)} | interest={float(interest_percent or 0)}",
                "member_name": member_name,
                "created_at": now_iso(),
            }
            supabase.table(history_table).insert(payload2).execute()
        except Exception:
            pass  # Do not crash app if history insert fails


# ---------------------------
# Detect available tables
# ---------------------------
HAS_MEMBERS  = table_exists_quick("members")
HAS_APPSTATE = table_exists_quick("app_state")
HAS_HISTORY  = table_exists_quick("history")

history_table_name = "history" if HAS_HISTORY else None

if not HAS_MEMBERS:
    st.error("❌ I cannot read the `members` table (missing table or blocked by RLS).")
    st.caption("If the table exists, you need Supabase policies that allow SELECT for your anon key.")
    st.stop()


# ---------------------------
# Load data (cached)
# ---------------------------
@st.cache_data(ttl=30)
def load_data():
    members_rows = fetch_all_rows("members", order_col="position" if True else None, desc=False)
    app_state_rows = fetch_all_rows("app_state") if HAS_APPSTATE else []
    history_rows = fetch_all_rows("history", order_col="created_at", desc=True) if HAS_HISTORY else []

    members_df = safe_df(members_rows, ensure_cols=["id", "name", "position", "contributed", "foundation_contrib", "loan_due", "created_at"])
    app_state_df = safe_df(app_state_rows, ensure_cols=["id", "foundation", "next_payout_index", "updated_at", "total_interest_generated", "next_payout_date"])
    history_df = safe_df(history_rows)

    members_df = to_num(members_df, ["contributed", "foundation_contrib", "loan_due", "position"])
    members_df = to_dt(members_df, ["created_at"])

    app_state_df = to_num(app_state_df, ["foundation", "next_payout_index", "total_interest_generated"])
    app_state_df = to_dt(app_state_df, ["updated_at", "next_payout_date"])

    if not history_df.empty:
        type_col, member_col, amount_col, total_due_col, interest_col, created_col = history_column_guess(history_df)
        # normalize known numeric columns if present
        for c in [amount_col, total_due_col, interest_col]:
            if c and c in history_df.columns:
                history_df[c] = pd.to_numeric(history_df[c], errors="coerce").fillna(0)
        if created_col and created_col in history_df.columns:
            history_df[created_col] = pd.to_datetime(history_df[created_col], errors="coerce")

    return members_df, app_state_df, history_df

try:
    members, app_state, history = load_data()
except Exception as e:
    st.error("❌ Could not load data from Supabase.")
    st.caption("Most common cause: Supabase RLS is blocking reads for the anon key.")
    st.exception(e)
    st.stop()


# ---------------------------
# Sidebar filters
# ---------------------------
st.sidebar.header("Filters")

member_names = ["All members"] + sorted(members["name"].dropna().astype(str).tolist())
selected_member = st.sidebar.selectbox("Member", member_names)

history_filtered = history.copy()
if not history_filtered.empty:
    type_col, member_col, amount_col, total_due_col, interest_col, created_col = history_column_guess(history_filtered)

    if selected_member != "All members" and member_col and member_col in history_filtered.columns:
        history_filtered = history_filtered[history_filtered[member_col].astype(str) == str(selected_member)]

    # Transaction type filter
    if type_col and type_col in history_filtered.columns:
        history_types = ["All types"] + sorted(history_filtered[type_col].dropna().astype(str).unique().tolist())
    else:
        history_types = ["All types"]
    selected_type = st.sidebar.selectbox("Transaction type", history_types)

    if selected_type != "All types" and type_col and type_col in history_filtered.columns:
        history_filtered = history_filtered[history_filtered[type_col].astype(str) == str(selected_type)]
else:
    selected_type = "All types"
    type_col = member_col = amount_col = total_due_col = interest_col = created_col = None


# ---------------------------
# KPIs
# ---------------------------
num_members = len(members)

total_contributed = float(members["contributed"].sum()) if "contributed" in members.columns else 0.0
total_foundation_contrib = float(members["foundation_contrib"].sum()) if "foundation_contrib" in members.columns else 0.0
total_loan_due = float(members["loan_due"].sum()) if "loan_due" in members.columns else 0.0

# Foundation from app_state if exists; else fallback to foundation_contrib
if not app_state.empty and "foundation" in app_state.columns:
    current_foundation = float(app_state["foundation"].iloc[0] or 0)
    next_payout_index = int(app_state["next_payout_index"].iloc[0] or 0) if "next_payout_index" in app_state.columns else 0
    next_payout_date = app_state["next_payout_date"].iloc[0] if "next_payout_date" in app_state.columns else None
    total_interest_generated = float(app_state["total_interest_generated"].iloc[0] or 0) if "total_interest_generated" in app_state.columns else 0.0
else:
    current_foundation = float(total_foundation_contrib)
    next_payout_index = 0
    next_payout_date = None
    total_interest_generated = 0.0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("👥 Members", f"{num_members}")
c2.metric("💰 Total Contributed", f"${total_contributed:,.2f}")
c3.metric("🏦 Foundation", f"${current_foundation:,.2f}")
c4.metric("📉 Total Loan Due", f"${total_loan_due:,.2f}")
c5.metric("📈 Total Interest", f"${total_interest_generated:,.2f}")


st.markdown("---")

# ---------------------------
# Charts
# ---------------------------
st.subheader("Member Contributions & Loan Exposure")
members_chart = members.copy()
if selected_member != "All members":
    members_chart = members_chart[members_chart["name"].astype(str) == str(selected_member)]

if not members_chart.empty and "name" in members_chart.columns:
    left, right = st.columns(2)
    with left:
        st.caption("Total contributed per member")
        if "contributed" in members_chart.columns:
            st.bar_chart(members_chart.set_index("name")[["contributed"]], use_container_width=True)
        else:
            st.info("Column `contributed` not found.")
    with right:
        st.caption("Loan due per member")
        if "loan_due" in members_chart.columns:
            st.bar_chart(members_chart.set_index("name")[["loan_due"]], use_container_width=True)
        else:
            st.info("Column `loan_due` not found.")
else:
    st.info("No members found yet.")

st.markdown("---")

# ---------------------------
# Rotation view
# ---------------------------
st.subheader("Payout Rotation Order")
if not members.empty and "position" in members.columns:
    rotation_df = members[["id", "name", "position", "contributed", "loan_due"]].copy()
    rotation_df["position"] = pd.to_numeric(rotation_df["position"], errors="coerce").fillna(0).astype(int)
    rotation_df = rotation_df.sort_values("position").reset_index(drop=True)

    rotation_df["is_next"] = False
    if 0 <= next_payout_index < len(rotation_df):
        rotation_df.loc[next_payout_index, "is_next"] = True

    st.dataframe(rotation_df[["position", "name", "contributed", "loan_due", "is_next"]], use_container_width=True, hide_index=True)
else:
    st.info("No rotation data (missing `position` column or no members).")

st.markdown("---")

# ---------------------------
# History log
# ---------------------------
st.subheader("Transaction History (Log)")

if history_filtered.empty:
    st.info("No transactions yet (or history table not available).")
else:
    # display best-known columns
    display_cols = []
    for c in [created_col, type_col, member_col, amount_col, interest_col, total_due_col]:
        if c and c in history_filtered.columns and c not in display_cols:
            display_cols.append(c)

    # fallback: show all if we couldn't guess
    if not display_cols:
        display_cols = list(history_filtered.columns)

    st.dataframe(history_filtered[display_cols], use_container_width=True, hide_index=True)

# =====================================================================
# ADMIN + RESTORE (below)
# =====================================================================
st.markdown("---")
st.header("🛠️ Admin & Restore")

is_admin = admin_gate()

# ---------------------------
# Restore: rebuild member totals from history
# ---------------------------
st.subheader("🧩 Restore totals from existing history")

st.caption(
    "This tool reads your existing `history` rows and rebuilds each member’s totals "
    "(contributed, foundation_contrib, loan_due). Preview first, then optionally write back."
)

def rebuild_members_from_history(members_df: pd.DataFrame, history_df: pd.DataFrame) -> pd.DataFrame:
    members_df = members_df.copy()

    # Ensure base columns exist
    for c in ["contributed", "foundation_contrib", "loan_due"]:
        if c not in members_df.columns:
            members_df[c] = 0.0
        members_df[c] = pd.to_numeric(members_df[c], errors="coerce").fillna(0)

    if history_df.empty:
        return members_df

    tcol, mcol, acol, dcol, icol, ccol = history_column_guess(history_df)
    if not (tcol and mcol and acol):
        # Can't rebuild without at least type/member/amount
        return members_df

    h = history_df.copy()
    h[tcol] = h[tcol].astype(str).str.lower()
    h[mcol] = h[mcol].astype(str)

    if acol in h.columns:
        h[acol] = pd.to_numeric(h[acol], errors="coerce").fillna(0)

    if dcol and dcol in h.columns:
        h[dcol] = pd.to_numeric(h[dcol], errors="coerce").fillna(0)

    # reset totals
    members_df["contributed"] = 0.0
    members_df["foundation_contrib"] = 0.0
    members_df["loan_due"] = 0.0

    # Contributions
    contrib = h[h[tcol].eq("contribution")]
    if not contrib.empty:
        contrib_sum = contrib.groupby(mcol)[acol].sum()
        members_df["contributed"] = members_df["name"].astype(str).map(contrib_sum).fillna(0).astype(float)
        # If you track foundation separately in history, you can change this.
        members_df["foundation_contrib"] = members_df["contributed"]

    # Loans: use total_due if present else amount
    loan = h[h[tcol].eq("loan")]
    if not loan.empty:
        if dcol and dcol in loan.columns:
            loan_due_sum = loan.groupby(mcol)[dcol].sum()
        else:
            loan_due_sum = loan.groupby(mcol)[acol].sum()
        members_df["loan_due"] = members_df["name"].astype(str).map(loan_due_sum).fillna(0).astype(float)

    # Repayments subtract from loan_due
    repay = h[h[tcol].eq("repayment")]
    if not repay.empty:
        repay_sum = repay.groupby(mcol)[acol].sum()
        members_df["loan_due"] = (members_df["loan_due"] - members_df["name"].astype(str).map(repay_sum).fillna(0)).clip(lower=0)

    return members_df

colR1, colR2 = st.columns(2)

with colR1:
    if st.button("🔄 Rebuild totals (preview)", use_container_width=True):
        try:
            members_rows = fetch_all_rows("members")
            history_rows = fetch_all_rows("history", order_col="created_at", desc=True) if HAS_HISTORY else []

            mdf = safe_df(members_rows, ensure_cols=["id","name","contributed","foundation_contrib","loan_due"])
            hdf = safe_df(history_rows)

            rebuilt = rebuild_members_from_history(mdf, hdf)

            st.session_state["rebuilt_members_df"] = rebuilt
            st.success("✅ Preview rebuild complete.")
            st.dataframe(rebuilt[["id","name","contributed","foundation_contrib","loan_due"]], use_container_width=True, hide_index=True)
        except Exception as e:
            st.error("Rebuild failed (missing columns, missing table, or RLS).")
            st.exception(e)

with colR2:
    if st.button("✅ Write back to Supabase (update members)", use_container_width=True, disabled=(not is_admin)):
        rebuilt = st.session_state.get("rebuilt_members_df")
        if rebuilt is None or rebuilt.empty:
            st.warning("Run 'Rebuild totals (preview)' first.")
        else:
            try:
                for _, r in rebuilt.iterrows():
                    supabase.table("members").update({
                        "contributed": float(r.get("contributed", 0) or 0),
                        "foundation_contrib": float(r.get("foundation_contrib", 0) or 0),
                        "loan_due": float(r.get("loan_due", 0) or 0),
                    }).eq("id", int(r["id"])).execute()

                st.success("✅ Members updated from restored totals.")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error("Write-back failed (usually RLS update policy).")
                st.exception(e)

st.markdown("---")

# ---------------------------
# Admin Forms (Create/Update Data)
# ---------------------------
st.subheader("➕ Create / Update Data")

if not is_admin:
    st.info("Login as admin to add members and transactions.")
    st.stop()

# Live members list for forms
try:
    members_live = supabase.table("members").select("*").order("position").range(0, 4999).execute().data
    mdf_live = safe_df(members_live, ensure_cols=["id","name","position","contributed","foundation_contrib","loan_due"])
    mdf_live = to_num(mdf_live, ["contributed","foundation_contrib","loan_due","position"])
except Exception as e:
    st.error("Cannot load members for admin forms (RLS/select issue).")
    st.exception(e)
    st.stop()

with st.expander("➕ Add Member", expanded=True):
    with st.form("add_member_form", clear_on_submit=True):
        name = st.text_input("Member name")
        position = st.number_input("Rotation position", min_value=1, step=1, value=int(mdf_live["position"].max()+1) if not mdf_live.empty else 1)
        submit = st.form_submit_button("Add Member")

        if submit:
            if not name.strip():
                st.error("Name is required.")
            else:
                payload = {
                    "name": name.strip(),
                    "position": int(position),
                    "contributed": 0,
                    "foundation_contrib": 0,
                    "loan_due": 0,
                    "created_at": now_iso()
                }
                supabase.table("members").insert(payload).execute()
                log_history(history_table_name, "member_added", name.strip(), 0, 0, 0)

                st.success("✅ Member added.")
                st.cache_data.clear()
                st.rerun()

if mdf_live.empty:
    st.info("Add at least one member to record transactions.")
    st.stop()

selected_name = st.selectbox("Select member", mdf_live["name"].astype(str).tolist())
row = mdf_live[mdf_live["name"].astype(str) == str(selected_name)].iloc[0]
member_id = int(row["id"])

colF1, colF2 = st.columns(2)

with colF1:
    with st.expander("💰 Add Contribution", expanded=False):
        with st.form("contrib_form", clear_on_submit=True):
            amount = st.number_input("Contribution amount", min_value=0.0, step=50.0, value=500.0)
            foundation_part = st.number_input("Foundation part (optional)", min_value=0.0, step=50.0, value=500.0)
            submit = st.form_submit_button("Save Contribution")

            if submit:
                new_contrib = float(row.get("contributed", 0) or 0) + float(amount)
                new_found = float(row.get("foundation_contrib", 0) or 0) + float(foundation_part)

                supabase.table("members").update({
                    "contributed": new_contrib,
                    "foundation_contrib": new_found
                }).eq("id", member_id).execute()

                log_history(history_table_name, "contribution", selected_name, amount=float(amount), interest_percent=0, total_due=0)

                st.success("✅ Contribution saved.")
                st.cache_data.clear()
                st.rerun()

with colF2:
    with st.expander("🏦 Record Loan (default 5%)", expanded=False):
        with st.form("loan_form", clear_on_submit=True):
            amount = st.number_input("Loan amount", min_value=0.0, step=100.0, value=500.0)
            interest_percent = st.number_input("Interest %", min_value=0.0, step=1.0, value=5.0)
            submit = st.form_submit_button("Save Loan")

            if submit:
                total_due = float(amount) * (1 + float(interest_percent) / 100.0)
                new_due = float(row.get("loan_due", 0) or 0) + float(total_due)

                supabase.table("members").update({"loan_due": new_due}).eq("id", member_id).execute()

                # Optionally update app_state total_interest_generated if table/column exists
                if HAS_APPSTATE and not app_state.empty and "total_interest_generated" in app_state.columns:
                    interest_value = float(total_due) - float(amount)
                    try:
                        current_interest = float(app_state["total_interest_generated"].iloc[0] or 0)
                        supabase.table("app_state").update({
                            "total_interest_generated": current_interest + interest_value,
                            "updated_at": now_iso()
                        }).eq("id", int(app_state["id"].iloc[0])).execute()
                    except Exception:
                        pass

                log_history(history_table_name, "loan", selected_name, amount=float(amount), interest_percent=float(interest_percent), total_due=float(total_due))

                st.success("✅ Loan recorded.")
                st.cache_data.clear()
                st.rerun()

with st.expander("✅ Record Repayment", expanded=False):
    with st.form("repay_form", clear_on_submit=True):
        amount = st.number_input("Repayment amount", min_value=0.0, step=50.0, value=100.0)
        submit = st.form_submit_button("Save Repayment")

        if submit:
            current_due = float(row.get("loan_due", 0) or 0)
            new_due = max(0.0, current_due - float(amount))

            supabase.table("members").update({"loan_due": new_due}).eq("id", member_id).execute()
            log_history(history_table_name, "repayment", selected_name, amount=float(amount), interest_percent=0, total_due=float(new_due))

            st.success("✅ Repayment saved.")
            st.cache_data.clear()
            st.rerun()

st.caption("Tip: If inserts/updates fail, you need Supabase RLS policies that allow anon (or authenticated) write access.")
