# app/pages/3_Tarefas.py
import streamlit as st
import pandas as pd
from datetime import date

from services.auth import require_login
from services.supabase_client import get_authed_client


st.set_page_config(page_title="Tarefas", layout="wide")
require_login()
sb = get_authed_client()

st.title("Tarefas")

TIPO_VALUES = ["CAMPO", "RELATORIO", "ADMINISTRATIVO"]
CONF_VALUES = ["ESTIMADO", "CONFIRMADO"]  # (como você pediu)
STATUS_VALUES = ["ESTIMADO", "PLANEJADA", "CONFIRMADA", "CANCELADA", "CONCLUIDA"]

@st.cache_data(ttl=20)
def fetch_people():
    res = sb.table("people").select("id,name,active").order("name").execute()
    df = pd.DataFrame(res.data or [])
    if not df.empty and "active" in df.columns:
        df = df[df["active"] == True]
    return df

@st.cache_data(ttl=20)
def fetch_projects():
    res = sb.table("projects").select("id,project_code,name").order("project_code").execute()
    df = pd.DataFrame(res.data or [])
    if not df.empty:
        df["label"] = df["project_code"].fillna("") + " — " + df["name"].fillna("")
    return df

@st.cache_data(ttl=20)
def fetch_tasks(project_id: str):
    res = sb.table("tasks").select(
        "id,project_id,title,tipo_atividade,assignee_id,status,start_date,end_date,date_confidence,notes,updated_at"
    ).eq("project_id", project_id).execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return df
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    df = df.sort_values(["start_date", "end_date", "title"], na_position="last").reset_index(drop=True)
    return df

people_df = fetch_people()
projects_df = fetch_projects()

if projects_df.empty:
    st.warning("Nenhum projeto cadastrado.")
    st.stop()

proj_label = st.selectbox("Projeto", projects_df["label"].tolist(), index=0)
project_id = projects_df.loc[projects_df["label"] == proj_label, "id"].iloc[0]

st.subheader("Nova tarefa")

c1, c2, c3, c4 = st.columns(4)
with c1:
    title = st.text_input("Título")
with c2:
    tipo = st.selectbox("Tipo", TIPO_VALUES)
with c3:
    conf = st.selectbox("Confiança da data", CONF_VALUES)
with c4:
    status = st.selectbox("Status", STATUS_VALUES, index=1)

c5, c6, c7 = st.columns(3)
with c5:
    if people_df.empty:
        st.error("Tabela people está vazia ou sem permissão (RLS).")
        assignee_name = None
    else:
        assignee_name = st.selectbox("Responsável", people_df["name"].tolist())
with c6:
    start = st.date_input("Início", value=date.today())
with c7:
    end = st.date_input("Fim", value=date.today())

notes = st.text_area("Observações", height=80)

if st.button("➕ Criar tarefa", type="primary"):
    if not title.strip():
        st.error("Informe o título.")
    elif people_df.empty:
        st.error("Não dá pra criar tarefa sem people (assignee).")
    else:
        assignee_id = people_df.loc[people_df["name"] == assignee_name, "id"].iloc[0]
        payload = {
            "project_id": project_id,
            "title": title.strip(),
            "tipo_atividade": tipo,
            "assignee_id": assignee_id,
            "status": status,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "date_confidence": conf,
            "notes": notes.strip() or None,
        }
        try:
            sb.table("tasks").insert(payload).execute()
            st.success("Tarefa criada.")
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Erro ao criar tarefa: {e}")

st.divider()
st.subheader("Lista de tarefas (editar inline)")

tasks_df = fetch_tasks(project_id)
if tasks_df.empty:
    st.info("Sem tarefas nesse projeto.")
    st.stop()

# join nomes
if not people_df.empty:
    id_to_name = dict(zip(people_df["id"], people_df["name"]))
    tasks_df["Responsável"] = tasks_df["assignee_id"].map(id_to_name).fillna("—")
else:
    tasks_df["Responsável"] = "—"

tasks_df["Início"] = tasks_df["start_date"].dt.date
tasks_df["Fim"] = tasks_df["end_date"].dt.date
tasks_df["Tarefa"] = tasks_df["title"]
tasks_df["Tipo"] = tasks_df["tipo_atividade"]
tasks_df["Confiança"] = tasks_df["date_confidence"].fillna("ESTIMADO")
tasks_df["Status"] = tasks_df["status"].fillna("")
tasks_df["Obs."] = tasks_df["notes"].fillna("")

editable = tasks_df[["id", "Tarefa", "Tipo", "Responsável", "Início", "Fim", "Confiança", "Status", "Obs."]].copy()
editable = editable.rename(columns={"id": "task_id"})

col_config = {
    "task_id": st.column_config.TextColumn("id", disabled=True),
    "Tarefa": st.column_config.TextColumn("Tarefa", disabled=True),
    "Tipo": st.column_config.SelectboxColumn("Tipo", options=TIPO_VALUES),
    "Início": st.column_config.DateColumn("Início"),
    "Fim": st.column_config.DateColumn("Fim"),
    "Confiança": st.column_config.SelectboxColumn("Confiança", options=CONF_VALUES),
    "Status": st.column_config.SelectboxColumn("Status", options=STATUS_VALUES),
    "Obs.": st.column_config.TextColumn("Obs."),
}

if not people_df.empty:
    col_config["Responsável"] = st.column_config.SelectboxColumn("Responsável", options=people_df["name"].tolist())
else:
    col_config["Responsável"] = st.column_config.TextColumn("Responsável", disabled=True)

edited = st.data_editor(
    editable,
    use_container_width=True,
    hide_index=True,
    column_config=col_config,
)

if st.button("Salvar alterações"):
    name_to_id = dict(zip(people_df["name"], people_df["id"])) if not people_df.empty else {}

    changes = 0
    for i in range(len(edited)):
        new = edited.iloc[i]
        old = editable.iloc[i]
        if new.equals(old):
            continue

        patch = {
            "tipo_atividade": new["Tipo"],
            "start_date": str(new["Início"]),
            "end_date": str(new["Fim"]),
            "date_confidence": new["Confiança"],
            "status": new["Status"],
            "notes": (new["Obs."] or None),
        }

        if name_to_id:
            patch["assignee_id"] = name_to_id.get(new["Responsável"])

        try:
            sb.table("tasks").update(patch).eq("id", new["task_id"]).execute()
            changes += 1
        except Exception as e:
            st.error(f"Erro ao salvar {new['task_id']}: {e}")

    st.success(f"Salvo! {changes} tarefa(s) atualizada(s).")
    st.cache_data.clear()
    st.rerun()

