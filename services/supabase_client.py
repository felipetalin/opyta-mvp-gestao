# services/supabase_client.py
import os
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client


def _load_env():
    # Local: lê .env; Cloud: usa Secrets/vars do Streamlit
    load_dotenv(override=True)


def get_public_client():
    """
    Cliente ANÔNIMO (sem usuário logado).
    Serve para coisas públicas (se houver), mas NÃO para telas com RLS por usuário.
    """
    _load_env()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")

    if not url or not key:
        raise RuntimeError("Faltam SUPABASE_URL / SUPABASE_ANON_KEY no ambiente (.env ou Secrets).")

    return create_client(url, key)


def get_authed_client():
    """
    Cliente autenticado com o usuário logado (RLS funcionando).
    Requer st.session_state['access_token'] preenchido no login.
    """
    sb = get_public_client()

    access_token = st.session_state.get("access_token")
    if not access_token:
        # Não derruba o app — mas você vai enxergar 0 linhas em tabelas com RLS.
        raise RuntimeError("Sessão sem access_token. Faça login novamente.")

    # PostgREST com JWT do usuário (RLS OK)
    sb.postgrest.auth(access_token)

    # (Opcional) storage/realtime também, se usar
    try:
        sb.storage.auth(access_token)
    except Exception:
        pass

    return sb


def get_service_client():
    """
    Cliente ADMIN (bypass RLS) - use só em scripts de import/migração.
    Precisa SUPABASE_SERVICE_ROLE_KEY no .env (NUNCA no Streamlit Cloud público).
    """
    _load_env()
    url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not service_key:
        raise RuntimeError("Faltam SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY para client ADMIN.")

    return create_client(url, service_key)


