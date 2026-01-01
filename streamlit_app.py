
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
# SESSION RESTORE (keeps login after refresh)
# ---------------------------
if "access_token" in st.session_state and "refresh_token" in st.session_state:
    try:
        supabase.auth.set_session(
            st.session_state["access_token"],
            st.session_state["refresh_token"]
        )
    except Exception:
        # wipe if invalid
        for k in ["logged_in", "email", "access_token", "refresh_token"]:
            st.session_state.pop(k, None)

def get_current_user():
    try:
        resp = supabase.auth.get_user()
        return getattr(resp, "user", None)
    except Exception:
        return None

user = get_current_user()
st.session_state["logged_in"] = user is not None
if user:
    st.session_state["email"] = user.email

# ---------------------------
# AUTH UI (SIGN UP + LOGIN)
# ---------------------------
if not st.session_state.get("logged_in"):
    st.subheader("🔐 Authentication")

    tab_login, tab_signup = st.tabs(["Login", "Sign Up"])

    with tab_login:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")

        if st.button("Login"):
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state["access_token"] = res.session.access_token
                st.session_state["refresh_token"] = res.session.refresh_token
                st.session_state["logged_in"] = True
                st.session_state["email"] = email
                st.success("✅ Login successful. Reloading...")
                st.rerun()
            except Exception as e:
                st.error("❌ Login failed. Check email/password.")
                st.caption(str(e))

    with tab_signup:
        new_email = st.text_input("New Email", key="signup_email")
        new_password = st.text_input("New Password", type="password", key="signup_password")

        if st.button("Create Account"):
            try:
                supabase.auth.sign_up({"email": new_email, "password": new_password})
                st.success("✅ Account created! Now go to Login tab and sign in.")
            except Exception as e:
                st.error("❌ Sign up failed.")
                st.caption(str(e))

    st.stop()

# ---------------------------
# LOGOUT BAR
# ---------------------------
col1, col2 = st.columns([3, 1])
with col1:
    st.success(f"✅ Logged in as: {st.session_state.get('email', 'User')}")
with col2:
    if st.button("Logout"):
        try:
            supabase.auth.sign_out()
        except Exception:
            pass
        for k in ["logged_in", "email", "access_token", "refresh_token"]:
            st.session_state.pop(k, None)
        st.rerun()

st.divider()

# ---------------------------
# DASHBOARD LOADERS
# ---------------------------
def load_table(table_name: str) -> pd.DataFrame:
    try:
        res = supabase.table(table_name).select("*").execute()
        return pd.DataFrame(res.data or [])
    except Exception as e:
        st.error(f"❌ Could not load table '{table_name}'.")
        st.caption("Most common cause: RLS blocks SELECT for authenticated users.")
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
