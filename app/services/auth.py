import streamlit as st
from services.supabase_client import get_anon_client


def is_logged_in() -> bool:
    return bool(st.session_state.get("access_token"))


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

            st.session_state["access_token"] = session.access_token
            st.session_state["user_email"] = email
            st.success(f"Logado como: {email}")
            st.rerun()

        except Exception as e:
            st.error(f"Falha no login: {e}")


def require_login():
    if not is_logged_in():
        login_form()
        st.stop()


def logout():
    for k in ["access_token", "user_email"]:
        if k in st.session_state:
            del st.session_state[k]


