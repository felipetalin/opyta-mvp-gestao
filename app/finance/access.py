import streamlit as st

ALLOWED_FINANCE_EMAILS = {
    "felipetalin@opyta.com.br",
    "yurisimoes@opyta.com.br",
}

def finance_guard(user_email: str) -> None:
    """Bloqueia acesso ao módulo financeiro (UX + segurança em camada app)."""
    email = (user_email or "").strip().lower()
    allowed = {e.lower() for e in ALLOWED_FINANCE_EMAILS}
    if email not in allowed:
        st.info("Módulo em implantação (desativado). Em breve.")
        st.stop()
