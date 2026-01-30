from __future__ import annotations

import streamlit as st

# Somente essas contas podem acessar o Financeiro
ALLOWED_FINANCE_EMAILS = {
    "felipetalin@opyta.com.br",
    "yurisimoes@opyta.com.br",
}


def require_finance_access(*, silent: bool = True) -> str:
    """
    Se silent=True:
        - usuários não autorizados NÃO veem nada (página vazia)
    Retorna o email normalizado (lower) se autorizado.
    """
    user_email = (st.session_state.get("user_email") or "").strip().lower()

    allowed = {e.strip().lower() for e in ALLOWED_FINANCE_EMAILS}
    if not user_email or user_email not in allowed:
        if silent:
            st.stop()  # encerra sem mensagem
        st.info("Módulo Financeiro restrito.")
        st.stop()

    return user_email
