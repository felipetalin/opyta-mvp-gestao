import streamlit as st

ALLOWED_FINANCE_EMAILS = {
    "felipetalin@opyta.com.br",
    "yurisimoes@opyta.com.br",
}

def finance_guard(user_email: str) -> None:
    email = (user_email or "").strip().lower()
    if email not in {e.lower() for e in ALLOWED_FINANCE_EMAILS}:
        st.info("Módulo em implantação (desativado). Em breve.")
        st.stop()


