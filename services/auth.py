# services/auth.py
import streamlit as st
from services.supabase_client import get_public_client


def login(email: str, password: str):
    sb = get_public_client()

    # supabase-py v2
    res = sb.auth.sign_in_with_password({"email": email, "password": password})

    session = res.session
    user = res.user

    if not session or not session.access_token:
        raise RuntimeError("Login falhou: sessão inválida retornada pelo Supabase.")

    st.session_state["user"] = {"id": user.id, "email": user.email}
    st.session_state["access_token"] = session.access_token
    st.session_state["refresh_token"] = session.refresh_token
    st.session_state["logged_in"] = True


def logout():
    try:
        sb = get_public_client()
        sb.auth.sign_out()
    except Exception:
        pass

    for k in ["user", "access_token", "refresh_token", "logged_in"]:
        if k in st.session_state:
            del st.session_state[k]
