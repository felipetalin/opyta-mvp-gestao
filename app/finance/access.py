import streamlit as st
from services.finance_guard import has_finance_read_access

def finance_guard(user_email: str) -> None:
    email = (user_email or "").strip().lower()
    if not has_finance_read_access(email):
        st.info("Módulo em implantação (desativado). Em breve.")
        st.stop()


