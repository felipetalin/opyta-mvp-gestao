from __future__ import annotations

import streamlit as st

ALLOWED_FINANCE_EMAILS = {
    "felipetalin@opyta.com.br",
    "yurisimoes@opyta.com.br",
}


def require_finance_access(silent: bool = True) -> str | None:
    """
    Se silent=True:
      - usuários não autorizados NÃO veem nada (página vazia)
    Retorna email se autorizado, senão None.
    """
    user_email = (st.session_state.get("user_email") or "").strip().lower()

    if not user_email or user_email not in {e.lower() for e in ALLOWED_FINANCE_EMAILS}:
        if silent:
            st.stop()  # mata a página sem mensagem
        else:
            st.info("Módulo Financeiro restrito.")
            st.stop()

    return user_email
