import streamlit as st
from services.supabase_client import get_supabase

def login(email: str, password: str):
    sb = get_supabase()
    res = sb.auth.sign_in_with_password({"email": email, "password": password})
    st.session_state["sb_session"] = res.session
    st.session_state["sb_user"] = res.user

def logout():
    sb = get_supabase()
    try:
        sb.auth.sign_out()
    except Exception:
        pass
    st.session_state["sb_session"] = None
    st.session_state["sb_user"] = None

def require_login():
    if st.session_state.get("sb_session") is None:
        st.warning("Faça login na Home.")
        st.stop()

def inject_session():
    """
    Injeta o access_token no PostgREST para as chamadas obedecerem RLS.
    """
    sb = get_supabase()
    sess = st.session_state.get("sb_session")
    if sess and getattr(sess, "access_token", None):
        sb.postgrest.auth(sess.access_token)
    return sb
