# app/pages/1_Portfolio_Gantt.py
import streamlit as st
import pandas as pd

from app.services.auth import require_login
from app.services.supabase_client import get_authed_client

st.set_page_config(page_title="Portfólio Gantt", layout="wide")
require_login()
sb = get_authed_client()

st.title("Portfólio – Gantt (MVP)")

@st.cache_data(ttl=20)
def fetch_portfolio():
    # se você tiver a view public.v_portfolio_tasks use ela:
    try:
        res = sb.table("v_portfolio_tasks").select("*").execute()
        return pd.DataFrame(res.data or [])
    except Exception:
        # fallback: tasks + projects
        res = sb.table("tasks").select("id,project_id,title,tipo_atividade,assignee_id,status,start_date,end_date,date_confidence").execute()
        return pd.DataFrame(res.data or [])

df = fetch_portfolio()

if df.empty:
    st.info("Sem dados para exibir (verifique tasks/view).")
    st.stop()

st.dataframe(df, use_container_width=True, hide_index=True)
st.caption("Esta é uma versão mínima só para estabilizar o app. Depois reativamos o Gantt bonito.")





