# services/supabase_client.py
import os
import streamlit as st
from supabase import create_client, Client


def _get_setting(key: str, default: str | None = None) -> str | None:
    # Prioridade: Streamlit Secrets > env
    if hasattr(st, "secrets") and key in st.secrets:
        val = st.secrets.get(key)
        return str(val) if val is not None else default
    return os.environ.get(key, default)


@st.cache_resource(show_spinner=False)
def get_anon_client() -> Client:
    url = _get_setting("SUPABASE_URL")
    anon = _get_setting("SUPABASE_ANON_KEY")
    if not url or not anon:
        raise RuntimeError("Faltando SUPABASE_URL / SUPABASE_ANON_KEY (env ou Streamlit Secrets).")
    return create_client(url, anon)


@st.cache_resource(show_spinner=False)
def get_service_client() -> Client | None:
    """
    Se SUPABASE_SERVICE_ROLE_KEY existir (Streamlit Secrets recomendado),
    retorna um client com permissão total (ignora RLS).
    """
    url = _get_setting("SUPABASE_URL")
    service = _get_setting("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not service:
        return None
    return create_client(url, service)


def get_authed_client(access_token: str | None) -> Client:
    """
    Client que usa o access_token do usuário (RLS).
    """
    sb = get_anon_client()
    if access_token:
        # Injeta o JWT no header Authorization
        sb.postgrest.auth(access_token)
    return sb



