# services/auth.py
import streamlit as st
from services.supabase_client import get_anon_client


SESSION_TOKEN_KEY = "sb_access_token"
SESSION_EMAIL_KEY = "user_email"


def is_logged_in() -> bool:
    return bool(st.session_state.get(SESSION_TOKEN_KEY))


def login():
    st.subheader("Login")

    email = st.text_input("Email", key="login_email")
    password = st.text_input("Senha", type="password", key="login_password")

    if st.button("Entrar"):
        try:
            sb = get_anon_client()
            res = sb.auth.sign_in_with_password({"email": email, "password": password})
            token = res.session.access_token if res and res.session else None
            if not token:
                st.error("Falha no login: token não retornou.")
                return

            st.session_state[SESSION_TOKEN_KEY] = token
            st.session_state[SESSION_EMAIL_KEY] = email
            st.success(f"Logado como: {email}")
            st.rerun()
        except Exception as e:
            st.error(f"Falha no login: {e}")


def logout():
    for k in [SESSION_TOKEN_KEY, SESSION_EMAIL_KEY]:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()


def require_login():
    if not is_logged_in():
        login()
        st.stop()

