# app/pages/2_Projetos.py
import streamlit as st
import pandas as pd
from datetime import date

from services.auth import require_login
from services.supabase_client import get_authed_client
from ui.brand import apply_brand

st.set_page_config(page_title="Projetos", layout="wide")
from ui.layout import apply_app_chrome, page_header

apply_brand()
apply_app_chrome()
page_header("Projetos", "Cadastro e edição", st.session_state.get("user_email", ""))


require_login()
sb = get_authed_client()


# ... (resto do seu código continua igual)



@st.cache_data(ttl=20)
def fetch_projects():
    res = sb.table("projects").select(
        "id,project_code,name,client,status,start_date,end_date_planned,notes,created_at"
    ).order("created_at", desc=True).execute()
    return pd.DataFrame(res.data or [])

def upsert_project(project_id, payload):
    if project_id:
        return sb.table("projects").update(payload).eq("id", project_id).execute()
    return sb.table("projects").insert(payload).execute()

df = fetch_projects()

st.subheader("Criar / Editar")

mode = st.radio("Modo", ["Criar", "Editar"], horizontal=True)

edit_row = None
if mode == "Editar":
    if df.empty:
        st.info("Sem projetos para editar.")
    else:
        options = (df["project_code"].fillna("") + " — " + df["name"].fillna("")).tolist()
        chosen = st.selectbox("Escolha um projeto", options)
        idx = options.index(chosen)
        edit_row = df.iloc[idx].to_dict()

c1, c2, c3 = st.columns(3)
with c1:
    project_code = st.text_input("Código", value=(edit_row.get("project_code") if edit_row else ""))
with c2:
    name = st.text_input("Nome", value=(edit_row.get("name") if edit_row else ""))
with c3:
    client = st.text_input("Cliente", value=(edit_row.get("client") if edit_row else ""))

c4, c5, c6 = st.columns(3)
with c4:
    status = st.selectbox("Status", ["ATIVO", "PAUSADO", "CONCLUIDO"], index=0)
    if edit_row and edit_row.get("status") in ["ATIVO", "PAUSADO", "CONCLUIDO"]:
        status = edit_row.get("status")
with c5:
    start_date = st.date_input("Início", value=(pd.to_datetime(edit_row["start_date"]).date() if edit_row and edit_row.get("start_date") else date.today()))
with c6:
    end_date_planned = st.date_input("Fim previsto", value=(pd.to_datetime(edit_row["end_date_planned"]).date() if edit_row and edit_row.get("end_date_planned") else date.today()))

notes = st.text_area("Observações", value=(edit_row.get("notes") if edit_row else ""))

if st.button("Salvar projeto", type="primary"):
    payload = {
        "project_code": project_code.strip() or None,
        "name": name.strip() or None,
        "client": client.strip() or None,
        "status": status,
        "start_date": start_date.isoformat(),
        "end_date_planned": end_date_planned.isoformat(),
        "notes": notes.strip() or None,
    }
    project_id = edit_row.get("id") if edit_row else None

    try:
        upsert_project(project_id, payload)
        st.success("Projeto salvo.")
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao salvar projeto: {e}")

st.divider()
st.subheader("Lista de Projetos")

df = fetch_projects()
if df.empty:
    st.info("Nenhum projeto cadastrado.")
else:
    st.dataframe(
        df[["project_code", "name", "client", "status", "start_date", "end_date_planned"]],
        use_container_width=True,
        hide_index=True
    )

