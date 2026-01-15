import streamlit as st
from services.supabase_client import get_public_client


def login(email: str, password: str):
    sb = get_public_client()
    res = sb.auth.sign_in_with_password({"email": email, "password": password})

    # salva sessão pro resto do app
    st.session_state["sb_access_token"] = res.session.access_token
    st.session_state["sb_refresh_token"] = res.session.refresh_token
    st.session_state["sb_user_id"] = res.user.id
    st.session_state["sb_email"] = res.user.email


def logout():
    # limpa sessão
    for k in ["sb_access_token", "sb_refresh_token", "sb_user_id", "sb_email"]:
        st.session_state.pop(k, None)
