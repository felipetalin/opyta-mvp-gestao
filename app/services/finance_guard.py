import json
import os

import streamlit as st

_ALLOWED = {
    "felipetalin@opyta.com.br": {"read": True, "write": True},
    "yurisimoes@opyta.com.br": {"read": True, "write": False},
}


def _normalize_finance_policy(configured: object) -> dict[str, dict[str, bool]]:
    if not isinstance(configured, dict):
        return {}

    policy: dict[str, dict[str, bool]] = {}
    for raw_email, rights in configured.items():
        email = str(raw_email or "").strip().lower()
        if not email:
            continue

        if isinstance(rights, dict):
            read_ok = bool(rights.get("read", False))
            write_ok = bool(rights.get("write", False))
        else:
            # Compatibilidade: valor booleano significa acesso de leitura.
            read_ok = bool(rights)
            write_ok = False

        policy[email] = {"read": read_ok, "write": write_ok}

    return policy


def _load_policy_from_env() -> dict[str, dict[str, bool]]:
    raw = (os.getenv("FINANCE_ACCESS_POLICY_JSON") or "").strip()
    if not raw:
        return {}

    try:
        return _normalize_finance_policy(json.loads(raw))
    except Exception:
        return {}


def get_finance_access_policy() -> dict[str, dict[str, bool]]:
    """
    Retorna a política de acesso ao Financeiro.
    Permite override opcional por st.secrets["FINANCE_ACCESS_POLICY"].
    """
    try:
        configured_policy = st.secrets.get("FINANCE_ACCESS_POLICY")
    except Exception:
        configured_policy = None

    secrets_policy = _normalize_finance_policy(configured_policy)
    if secrets_policy:
        return secrets_policy

    env_policy = _load_policy_from_env()
    if env_policy:
        return env_policy

    return _ALLOWED


def has_finance_read_access(user_email: str) -> bool:
    email = (user_email or "").strip().lower()
    return bool(get_finance_access_policy().get(email, {}).get("read", False))

def require_finance_access(silent: bool = True) -> str:
    """
    Permite acesso ao Financeiro só para usuários autorizados.
    Retorna o email do usuário.
    Se silent=True, não mostra erro constrangedor: só interrompe.
    """
    email = (st.session_state.get("user_email") or "").strip().lower()

    if has_finance_read_access(email):
        return email

    # Não autorizado
    if silent:
        # não mostra nada: interrompe a página
        st.stop()

    st.error("Acesso restrito ao Financeiro.")
    st.stop()

def can_finance_write(user_email: str) -> bool:
    email = (user_email or "").strip().lower()
    return bool(get_finance_access_policy().get(email, {}).get("write", False))
