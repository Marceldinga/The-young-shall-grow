import streamlit as st
import pandas as pd
from supabase import create_client
from sqlalchemy import create_engine, text

# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(page_title="The Young Shall Grow – Njangi", layout="wide")
st.title("🪙 The Young Shall Grow – Njangi")

# =========================================================
# SECRETS
# =========================================================
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]
DB_URL = st.secrets["DB_URL"]

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

@st.cache_resource
def get_engine():
    return create_engine(DB_URL)

engine = get_engine()

# =========================================================
# DB HELPERS
# =========================================================
def qdf(query: str, params: dict | None = None) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params=params or {})

def qexec(query: str, params: dict | None = None):
    with engine.begin() as conn:
        conn.execute(text(query), params or {})

# =========================================================
# AUTH HELPERS
# =========================================================
def get_user_role(user_id: str):
    try:
        res = supabase.table("profiles").select("role").eq("id", user_id).execute()
        if res.data:
            return res.data[0]["role"]
        return None
    except Exception:
        return None

def do_logout():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    st.session_state.clear()
    st.rerun()

# =========================================================
# BOOTSTRAP: Ensure columns exist in members
# (safe to run repeatedly)
# =========================================================
def ensure_members_columns():
    try:
        qexec("""
            alter table public.members
            add column if not exists user_id uuid references auth.users(id),
            add column if not exists email text;
        """)
    except Exception:
        # If DB_URL is wrong or permissions issue, we will fail later anyway.
        pass

ensure_members_columns()

# =========================================================
# AUTH UI (LOGIN + SIGNUP)
# =========================================================
if "user" not in st.session_state:
    st.subheader("🔐 Login Required")

    tab1, tab2 = st.tabs(["Login", "Create Account"])

    with tab1:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_pw")

        if st.button("Login", use_container_width=True):
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                user = res.user
                role = get_user_role(user.id)

                if not role:
                    st.error("No role found in profiles. (Create profiles table + trigger, or insert role manually.)")
                    st.stop()

                st.session_state.user = user
                st.session_state.role = role
                st.rerun()
            except Exception:
                st.error("Login failed. Check email/password (or confirm email if confirmation is ON).")

    with tab2:
        new_email = st.text_input("Email", key="signup_email")
        new_pw = st.text_input("Create Password (min 6 chars)", type="password", key="signup_pw")
        new_pw2 = st.text_input("Confirm Password", type="password", key="signup_pw2")

        if st.button("Create Account", use_container_width=True):
            if not new_email:
                st.error("Email is required.")
            elif new_pw != new_pw2:
                st.error("Passwords do not match.")
            elif len(new_pw) < 6:
                st.error("Password must be at least 6 characters.")
            else:
                try:
                    supabase.auth.sign_up({"email": new_email, "password": new_pw})
                    st.success("Account created! Now go to Login and sign in.")
                    st.info("If Supabase requires email confirmation, confirm your email first.")
                except Exception:
                    st.error("Signup failed. Email may already exist or signup is blocked in Supabase Auth settings.")

    st.stop()

# =========================================================
# AUTHENTICATED AREA
# =========================================================
user = st.session_state.user
role = st.session_state.role

st.sidebar.success(f"Logged in: {user.email}")
st.sidebar.write(f"Role: **{role}**")
st.sidebar.button("Logout", on_click=do_logout)

# =========================================================
# ADMIN LINKING (connect login to an existing member row)
# =========================================================
def admin_link_panel():
    st.subheader("👑 Admin: Link a Login to a Member Record")

    try:
        members = qdf("select id, name, email, user_id from public.members order by id asc")
    except Exception as e:
        st.error("Cannot read members table. Check DB_URL permissions.")
        st.stop()

    st.caption("Select a member name, then link them to THIS logged-in user (sets members.user_id + members.email).")
    st.dataframe(members, use_container_width=True)

    name_list = members["name"].fillna("").tolist()
    chosen_name = st.selectbox("Select member to link", options=[""] + name_list)

    if st.button("Link selected member to this login", use_container_width=True):
        if not chosen_name:
            st.error("Please choose a member name first.")
        else:
            qexec(
                """
                update public.members
                set user_id = :uid,
                    email = :email
                where name = :name
                """,
                {"uid": user.id, "email": user.email, "name": chosen_name}
            )
            st.success(f"Linked '{chosen_name}' ✅")
            st.rerun()

# =========================================================
# DASHBOARDS
# =========================================================
if role == "admin":
    st.header("📌 Admin Dashboard")

    admin_link_panel()

    st.divider()
    st.subheader("All Members (Admin View)")
    all_members = qdf("select * from public.members order by id asc")
    st.dataframe(all_members, use_container_width=True)

elif role == "member":
    st.header("👤 Member Dashboard")

    # Member record is identified by user_id (most reliable)
    my_member = qdf(
        "select * from public.members where user_id = :uid limit 1",
        {"uid": user.id}
    )

    if my_member.empty:
        st.warning("Your login is NOT linked to any member record yet.")
        st.info("Ask the admin to link your account to your name in the members table.")
        st.stop()

    st.subheader("My Member Record")
    st.dataframe(my_member, use_container_width=True)

    st.divider()
    st.subheader("My Payouts / Fines (if tables exist)")

    member_id = int(my_member.iloc[0]["id"])

    def try_table(sql, params):
        try:
            return qdf(sql, params)
        except Exception:
            return pd.DataFrame()

    payouts = try_table(
        "select * from public.payouts where member_id = :mid order by id desc",
        {"mid": member_id}
    )
    fines = try_table(
        "select * from public.fines where member_id = :mid order by id desc",
        {"mid": member_id}
    )

    c1, c2 = st.columns(2)
    with c1:
        st.write("**My Payouts**")
        st.dataframe(payouts, use_container_width=True)
    with c2:
        st.write("**My Fines**")
        st.dataframe(fines, use_container_width=True)

else:
    st.error("Unauthorized role. Contact admin.")
ensure_members_columns()

# =========================================================
# AUTH UI (LOGIN + SIGNUP)
# =========================================================
if "user" not in st.session_state:
    st.subheader("🔐 Login Required")

    tab1, tab2 = st.tabs(["Login", "Create Account"])

    with tab1:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_pw")

        if st.button("Login", use_container_width=True):
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                user = res.user
                role = get_user_role(user.id)

                if not role:
                    st.error("No role found in profiles. (Create profiles table + trigger, or insert role manually.)")
                    st.stop()

                st.session_state.user = user
                st.session_state.role = role
                st.rerun()
            except Exception:
                st.error("Login failed. Check email/password (or confirm email if confirmation is ON).")

    with tab2:
        new_email = st.text_input("Email", key="signup_email")
        new_pw = st.text_input("Create Password (min 6 chars)", type="password", key="signup_pw")
        new_pw2 = st.text_input("Confirm Password", type="password", key="signup_pw2")

        if st.button("Create Account", use_container_width=True):
            if not new_email:
                st.error("Email is required.")
            elif new_pw != new_pw2:
                st.error("Passwords do not match.")
            elif len(new_pw) < 6:
                st.error("Password must be at least 6 characters.")
            else:
                try:
                    supabase.auth.sign_up({"email": new_email, "password": new_pw})
                    st.success("Account created! Now go to Login and sign in.")
                    st.info("If Supabase requires email confirmation, confirm your email first.")
                except Exception:
                    st.error("Signup failed. Email may already exist or signup is blocked in Supabase Auth settings.")

    st.stop()

# =========================================================
# AUTHENTICATED AREA
# =========================================================
user = st.session_state.user
role = st.session_state.role

st.sidebar.success(f"Logged in: {user.email}")
st.sidebar.write(f"Role: **{role}**")
st.sidebar.button("Logout", on_click=do_logout)

# =========================================================
# ADMIN LINKING (connect login to an existing member row)
# =========================================================
def admin_link_panel():
    st.subheader("👑 Admin: Link a Login to a Member Record")

    try:
        members = qdf("select id, name, email, user_id from public.members order by id asc")
    except Exception as e:
        st.error("Cannot read members table. Check DB_URL permissions.")
        st.stop()

    st.caption("Select a member name, then link them to THIS logged-in user (sets members.user_id + members.email).")
    st.dataframe(members, use_container_width=True)

    name_list = members["name"].fillna("").tolist()
    chosen_name = st.selectbox("Select member to link", options=[""] + name_list)

    if st.button("Link selected member to this login", use_container_width=True):
        if not chosen_name:
            st.error("Please choose a member name first.")
        else:
            qexec(
                """
                update public.members
                set user_id = :uid,
                    email = :email
                where name = :name
                """,
                {"uid": user.id, "email": user.email, "name": chosen_name}
            )
            st.success(f"Linked '{chosen_name}' ✅")
            st.rerun()

# =========================================================
# DASHBOARDS
# =========================================================
if role == "admin":
    st.header("📌 Admin Dashboard")

    admin_link_panel()

    st.divider()
    st.subheader("All Members (Admin View)")
    all_members = qdf("select * from public.members order by id asc")
    st.dataframe(all_members, use_container_width=True)

elif role == "member":
    st.header("👤 Member Dashboard")

    # Member record is identified by user_id (most reliable)
    my_member = qdf(
        "select * from public.members where user_id = :uid limit 1",
        {"uid": user.id}
    )

    if my_member.empty:
        st.warning("Your login is NOT linked to any member record yet.")
        st.info("Ask the admin to link your account to your name in the members table.")
        st.stop()

    st.subheader("My Member Record")
    st.dataframe(my_member, use_container_width=True)

    st.divider()
    st.subheader("My Payouts / Fines (if tables exist)")

    member_id = int(my_member.iloc[0]["id"])

    def try_table(sql, params):
        try:
            return qdf(sql, params)
        except Exception:
            return pd.DataFrame()

    payouts = try_table(
        "select * from public.payouts where member_id = :mid order by id desc",
        {"mid": member_id}
    )
    fines = try_table(
        "select * from public.fines where member_id = :mid order by id desc",
        {"mid": member_id}
    )

    c1, c2 = st.columns(2)
    with c1:
        st.write("**My Payouts**")
        st.dataframe(payouts, use_container_width=True)
    with c2:
        st.write("**My Fines**")
        st.dataframe(fines, use_container_width=True)

else:
    st.error("Unauthorized role. Contact admin.")
