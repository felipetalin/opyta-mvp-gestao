import os, sys
import streamlit as st
import pandas as pd
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from services.auth import require_login, inject_session  # noqa: E402

load_dotenv()
st.set_page_config(page_title="Projetos", layout="wide")
st.title("Projetos")

require_login()
sb = inject_session()

@st.cache_data(ttl=30)
def load_people():
    res = sb.table("people").select("id,name,active,is_placeholder,role").order("name").execute()
    df = pd.DataFrame(res.data or [])
    if not df.empty and "active" in df.columns:
        df = df[df["active"] == True]  # noqa: E712
    return df

@st.cache_data(ttl=30)
def load_projects():
    res = sb.table("projects").select("*").order("project_code").execute()
    return pd.DataFrame(res.data or [])

people_df = load_people()
projects_df = load_projects()

# -------------------- Editor (Create / Edit) FIRST --------------------
st.subheader("Criar / Editar")

edit_mode = st.checkbox("Editar projeto existente", value=False)

selected_row = None
if edit_mode and not projects_df.empty:
    options = (projects_df["project_code"].astype(str) + " | " + projects_df["name"].astype(str)).tolist()
    pick = st.selectbox("Selecione um projeto", options)
    code = pick.split("|")[0].strip()
    selected_row = projects_df[projects_df["project_code"] == code].iloc[0].to_dict()

defv = lambda k, d=None: (selected_row.get(k) if selected_row else d)

pm_options = ["(vazio)"]
pm_map = {}
if not people_df.empty:
    for _, r in people_df.iterrows():
        label = r["name"]
        pm_options.append(label)
        pm_map[label] = r["id"]

pm_default_idx = 0
current_pm_id = defv("project_manager_id", None)
if current_pm_id and pm_map:
    for i, label in enumerate(pm_options):
        if label != "(vazio)" and str(pm_map[label]) == str(current_pm_id):
            pm_default_idx = i
            break

with st.form("proj_form", clear_on_submit=not edit_mode):
    c1, c2, c3 = st.columns([1.2, 2.6, 2.0])
    with c1:
        project_code = st.text_input("Código (project_code)", value=defv("project_code",""), placeholder="BRSAJT02")
    with c2:
        name = st.text_input("Nome do Projeto", value=defv("name",""), placeholder="Monitoramento da Ictiofauna")
    with c3:
        client = st.text_input("Cliente", value=defv("client",""), placeholder="Cliente X")

    c4, c5, c6, c7 = st.columns([1.2, 1.2, 1.2, 1.8])
    with c4:
        status = st.selectbox("Status", ["ATIVO","PAUSADO","CONCLUIDO"],
                              index=["ATIVO","PAUSADO","CONCLUIDO"].index(defv("status","ATIVO")))
    with c5:
        start_date = st.date_input("Início", value=pd.to_datetime(defv("start_date", None)) if defv("start_date", None) else None, format="DD/MM/YYYY")
    with c6:
        end_date_planned = st.date_input("Fim previsto", value=pd.to_datetime(defv("end_date_planned", None)) if defv("end_date_planned", None) else None, format="DD/MM/YYYY")
    with c7:
        pm_label = st.selectbox("Gerente do Projeto", pm_options, index=pm_default_idx)

    notes = st.text_area("Observações", value=defv("notes","") or "", height=90)
    submitted = st.form_submit_button("Salvar")

if submitted:
    project_code = (project_code or "").strip()
    name = (name or "").strip()
    if not project_code or not name:
        st.error("Código e nome são obrigatórios.")
        st.stop()

    pm_id = None if pm_label == "(vazio)" else pm_map.get(pm_label)

    payload = {
        "project_code": project_code,
        "name": name,
        "client": (client or "").strip() or None,
        "status": status,
        "start_date": str(start_date) if start_date else None,
        "end_date_planned": str(end_date_planned) if end_date_planned else None,
        "project_manager_id": str(pm_id) if pm_id else None,
        "notes": (notes or "").strip() or None,
    }

    sb.table("projects").upsert(payload, on_conflict="project_code").execute()
    st.success("Projeto salvo.")
    st.cache_data.clear()
    st.rerun()

# delete opcional
if edit_mode and selected_row is not None:
    with st.expander("Excluir projeto (cuidado)"):
        st.warning("Excluir remove o projeto e tarefas relacionadas (FK).")
        if st.button("Excluir este projeto"):
            sb.table("projects").delete().eq("project_code", selected_row["project_code"]).execute()
            st.success("Projeto excluído.")
            st.cache_data.clear()
            st.rerun()

st.divider()

# -------------------- List AFTER --------------------
st.subheader("Lista de projetos")
projects_df = load_projects()

if projects_df.empty:
    st.info("Sem projetos ainda.")
else:
    show_cols = ["project_code","name","client","status","start_date","end_date_planned","notes","updated_at"]
    cols = [c for c in show_cols if c in projects_df.columns]
    st.dataframe(projects_df[cols], use_container_width=True, hide_index=True)
