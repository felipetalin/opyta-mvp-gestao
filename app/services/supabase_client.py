import os
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client


def _load_env():
    try:
        load_dotenv(override=True)
    except Exception:
        pass


def _get(key: str) -> str | None:
    if hasattr(st, "secrets") and key in st.secrets:
        v = st.secrets.get(key)
        return str(v) if v is not None else None
    return os.getenv(key)


def get_anon_client():
    _load_env()
    url = _get("SUPABASE_URL")
    anon = _get("SUPABASE_ANON_KEY")
    if not url or not anon:
        raise RuntimeError("Faltando SUPABASE_URL / SUPABASE_ANON_KEY (.env ou Streamlit Secrets).")
    return create_client(url, anon)


def get_authed_client():
    sb = get_anon_client()
    token = st.session_state.get("access_token")
    if not token:
        raise RuntimeError("Sem access_token na sessão. Faça login novamente.")
    sb.postgrest.auth(token)
    return sb





