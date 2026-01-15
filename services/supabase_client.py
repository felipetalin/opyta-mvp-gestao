import os
import streamlit as st
from supabase import create_client


def _must_env(name: str) -> str:
    v = os.getenv(name) or st.secrets.get(name)
    if not v:
        raise RuntimeError(f"Missing env/secret: {name}")
    return v


def get_public_client():
    """Cliente ANON (sem JWT). Serve só para login."""
    url = _must_env("SUPABASE_URL")
    key = _must_env("SUPABASE_ANON_KEY")
    return create_client(url, key)


def get_authed_client():
    """
    Cliente com JWT do usuário logado (RLS vai liberar conforme policies).
    Retorna None se não estiver logado.
    """
    token = st.session_state.get("sb_access_token")
    if not token:
        return None

    url = _must_env("SUPABASE_URL")
    key = _must_env("SUPABASE_ANON_KEY")

    # cria cliente normal
    sb = create_client(url, key)

    # força PostgREST usar o JWT
    try:
        sb.postgrest.auth(token)
    except Exception:
        # fallback compatibilidade
        sb.postgrest.session.headers.update({"Authorization": f"Bearer {token}"})

    return sb

