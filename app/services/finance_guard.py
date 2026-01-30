from __future__ import annotations

import streamlit as st

# Somente essas contas podem acessar o Financeiro
ALLOWED_FINANCE_EMAILS = {
    "felipetalin@opyta.com.br",
    "yurisimoes@opyta.com.br",
}


def require_finance_access() -> str:
    """
    Bloqueia acesso ao Financeiro para qualquer usuário que não esteja na whitelist.
    Retorna o email normalizado (lower).
    """
    user_email = (st.session_state.get("user_email") or "").strip().lower()

    # se por algum motivo não tiver email, bloqueia
    if not user_email:
        st.info("Módulo Financeiro restrito.")
        st.stop()

    if user_email not in {e.lower() for e in ALLOWED_FINANCE_EMAILS}:
        st.info("Módulo Financeiro restrito.")
        st.stop()

    return user_email
