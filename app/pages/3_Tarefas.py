import streamlit as st
import pandas as pd
from datetime import date
from dotenv import load_dotenv

from services.supabase_client import get_supabase

st.set_page_config(page_title="Tarefas", layout="wide")
load_dotenv()

sb = get_supabase()

CONF_VALUES = ["ESTIMADO", "CONFIRMADO"]
TIPO_VALUES = ["CAMPO", "RELATORIO", "ADMINISTRATIVO"]
STATUS_VALUES = ["ESTIMADO", "PLANEJADA", "CONFIRMADA", "CANCELADA"]


# =========================
# Helpers
# =========================
def to_date(v):
    if v is None or v == "":
        return None
    try:
        return pd.to_datetime(v).date()
    except Exception:
        return None


@st.cache_data(ttl=30)
def fetch_people_safe():
    """
    NÃO assume tabela vazia.
    Se der erro (RLS / secrets), mostra erro real.
    """
    try:
        res = sb.table("people").select(
            "id,name,role,activity_type,is_placeholder,active"
        ).order("name").execute()
        return pd.DataFrame(res.data or []), None
    except Exception as e:
        return pd.DataFrame(), str(e)


@st.cache_data(ttl=30)
def fetch_projects():
    res = sb.table("projects").select(
        "id,project_code,name"
    ).order("project_code").execute()
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def fetch_tasks():
    res = sb.table("tasks").select(
        "id,project_id,title,tipo_atividade,assignee_id,status,"
        "start_date,end_date,date_confidence,notes"
    ).execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return df

    df = df.rename(columns={"id": "task_id"})
    df["start_date"] = df["start_date"].apply(to_date)
    df["end_date"] = df["end_date"].apply(to_date)
    df["date_confidence"] = df["date_confidence"].fillna("ESTIMADO").str.upper()
    return df


# =========================
# Carregamento seguro
# =========================
st.title("Tarefas")

df_people, people_error = fetch_people_safe()

if people_error:
    st.error("Erro ao acessar tabela PEOPLE (RLS / Secrets / Permissão)")
    st.code(people_error)
    st.stop()

if df_people.empty:
    st.warning(
        "A tabela PEOPLE existe, mas está vazia para este usuário.\n\n"
        "➡️ Isso é RLS ou Secrets no Streamlit Cloud.\n"
        "➡️ O app NÃO vai quebrar, mas você não poderá editar responsáveis."
    )

df_projects = fetch_projects()
df_tasks = fetch_tasks()

if df_projects.empty:
    st.info("Nenhum projeto cadastrado ainda.")
    st.stop()


# =========================
# Mapas auxiliares
# =========================
people_id_to_name = dict(zip(df_people["id"], df_people["name"]))
people_name_to_id = dict(zip(df_people["name"], df_people["id"]))
people_options = df_people["name"].tolist()

project_label = {
    r["id"]: f"{r.get('project_code','')} - {r.get('name','')}"
    for _, r in df_projects.iterrows()
}
project_options = ["(Todos)"] + list(project_label.values())
project_label_to_id = {v: k for k, v in project_label.items()}


# =========================
# Nova tarefa
# =========================
st.subheader("Nova tarefa")

c1, c2, c3, c4 = st.columns(4)

with c1:
    proj_sel = st.selectbox("Projeto", project_options)
with c2:
    tipo_new = st.selectbox("Tipo", TIPO_VALUES)
with c3:
    conf_new = st.selectbox("Confiança da data", CONF_VALUES)
with c4:
    status_new = st.selectbox("Status", STATUS_VALUES, index=1)

title_new = st.text_input("Título da tarefa")

c5, c6, c7 = st.columns(3)
with c5:
    assignee_new = st.selectbox(
        "Responsável",
        people_options if people_options else ["(sem people disponível)"]
    )
with c6:
    start_new = st.date_input("Início", value=date.today())
with c7:
    end_new = st.date_input("Fim", value=date.today())

notes_new = st.text_area("Observações")

if st.button("➕ Criar tarefa", type="primary"):
    if proj_sel == "(Todos)":
        st.error("Selecione um projeto.")
    elif not title_new.strip():
        st.error("Informe o título.")
    else:
        payload = {
            "project_id": project_label_to_id[proj_sel],
            "title": title_new.strip(),
            "tipo_atividade": tipo_new,
            "status": status_new,
            "date_confidence": conf_new,
            "start_date": start_new.isoformat(),
            "end_date": end_new.isoformat(),
            "notes": notes_new or None,
        }

        if assignee_new in people_name_to_id:
            payload["assignee_id"] = people_name_to_id[assignee_new]

        try:
            sb.table("tasks").insert(payload).execute()
            st.success("Tarefa criada.")
            st.cache_data.clear()
            st.rerun()
        except Exception as e:
            st.error("Erro ao criar tarefa")
            st.code(str(e))


# =========================
# Lista
# =========================
st.divider()
st.subheader("Lista de tarefas")

df = df_tasks.copy()
if df.empty:
    st.info("Nenhuma tarefa cadastrada.")
    st.stop()

df["responsavel"] = df["assignee_id"].map(people_id_to_name).fillna("—")
df["projeto"] = df["project_id"].map(project_label)

df = df.sort_values(["start_date", "end_date", "title"])

st.dataframe(
    df[
        [
            "projeto",
            "title",
            "tipo_atividade",
            "responsavel",
            "status",
            "date_confidence",
            "start_date",
            "end_date",
        ]
    ],
    use_container_width=True,
)

