import streamlit as st

_ALLOWED = {
    "felipetalin@opyta.com.br": {"read": True, "write": True},
    "yurisimoes@opyta.com.br": {"read": True, "write": False},
}

def require_finance_access(silent: bool = True) -> str:
    """
    Permite acesso ao Financeiro só para usuários autorizados.
    Retorna o email do usuário.
    Se silent=True, não mostra erro constrangedor: só interrompe.
    """
    email = (st.session_state.get("user_email") or "").strip().lower()

    if email in _ALLOWED and _ALLOWED[email].get("read"):
        return email

    # Não autorizado
    if silent:
        # não mostra nada: interrompe a página
        st.stop()

    st.error("Acesso restrito ao Financeiro.")
    st.stop()

def can_finance_write(user_email: str) -> bool:
    email = (user_email or "").strip().lower()
    return bool(_ALLOWED.get(email, {}).get("write", False))
