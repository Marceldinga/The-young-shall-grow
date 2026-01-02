
import streamlit as st
import pandas as pd
from supabase import create_client

# ---------------------------
# PAGE CONFIG
# ---------------------------
st.set_page_config(page_title="The Young Shall Grow – Njangi", layout="wide")
st.title("🌱 The Young Shall Grow – Njangi")

# ---------------------------
# SECRETS (Streamlit TOML)
# SUPABASE_URL = "https://..."
# SUPABASE_ANON_KEY = "..."
# ---------------------------
SUPABASE_URL = st.secrets.get("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("❌ Missing SUPABASE_URL or SUPABASE_ANON_KEY in Streamlit Secrets.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------
# DASHBOARD LOADERS
# ---------------------------
def load_table(table_name: str) -> pd.DataFrame:
    try:
        res = supabase.table(table_name).select("*").execute()
        return pd.DataFrame(res.data or [])
    except Exception as e:
        st.error(f"❌ Could not load table '{table_name}'.")
        st.caption("Most common cause: RLS blocks SELECT for anon users.")
        st.caption(str(e))
        return pd.DataFrame()

# ---------------------------
# DASHBOARD
# ---------------------------
st.header("📊 Dashboard")

members_df = load_table("members")
payouts_df = load_table("payouts")
fines_df   = load_table("fines")

c1, c2, c3 = st.columns(3)
c1.metric("Members", 0 if members_df.empty else len(members_df))
c2.metric("Payouts", 0 if payouts_df.empty else len(payouts_df))
c3.metric("Fines",   0 if fines_df.empty else len(fines_df))

st.subheader("👥 Members")
st.dataframe(members_df, use_container_width=True) if not members_df.empty else st.info("No members found.")

st.subheader("💸 Payouts")
st.dataframe(payouts_df, use_container_width=True) if not payouts_df.empty else st.info("No payouts found.")

st.subheader("⚠️ Fines")
st.dataframe(fines_df, use_container_width=True) if not fines_df.empty else st.info("No fines found.")

st.success("✅ Dashboard loaded.")
