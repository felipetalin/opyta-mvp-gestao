import time

import streamlit as st
from services.supabase_client import get_anon_client


def _clear_auth_state() -> None:
    for key in ["access_token", "refresh_token", "expires_at", "user_email"]:
        if key in st.session_state:
            del st.session_state[key]


def is_logged_in() -> bool:
    token = st.session_state.get("access_token")
    expires_at = st.session_state.get("expires_at")

    if not token:
        return False

    if expires_at is not None:
        try:
            if int(expires_at) <= int(time.time()):
                _clear_auth_state()
                return False
        except Exception:
            _clear_auth_state()
            return False

    return True


def login_form():
    st.subheader("Login")

    email = st.text_input("Email", key="login_email")
    password = st.text_input("Senha", type="password", key="login_password")

    if st.button("Entrar", type="primary"):
        try:
            sb = get_anon_client()
            res = sb.auth.sign_in_with_password({"email": email, "password": password})

            session = res.session
            if not session or not session.access_token:
                st.error("Falha no login: sessão inválida.")
                return

            user = getattr(res, "user", None) or getattr(session, "user", None)
            user_email = getattr(user, "email", None) or email

            st.session_state["access_token"] = session.access_token
            st.session_state["refresh_token"] = getattr(session, "refresh_token", None)
            st.session_state["expires_at"] = getattr(session, "expires_at", None)
            st.session_state["user_email"] = str(user_email).strip().lower()
            st.success(f"Logado como: {st.session_state['user_email']}")
            st.rerun()

        except Exception as e:
            st.error(f"Falha no login: {e}")


def require_login():
    if not is_logged_in():
        login_form()
        st.stop()


def logout():
    _clear_auth_state()


