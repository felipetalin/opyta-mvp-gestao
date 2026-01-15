# app/pages/3_Tarefas.py
import streamlit as st
import pandas as pd
from datetime import date

from services.auth import require_login
from services.supabase_client import get_authed_client

st.set_page_config(page_title="Tarefas", layout="wide")
st.title("Tarefas")

# Mantém como está (sem mexer em conexão)
require_login()
sb = get_authed_client()

# -----------------------------
# Constantes (Status da data)
# -----------------------------
STATUS_DATA_OPTIONS = ["PLANEJADO", "CONFIRMADO", "CANCELADO"]

# (Mantemos status operacional interno só para satisfazer CHECK do banco, sem expor na UI)
DEFAULT_INTERNAL_STATUS = "PLANEJADA"


# -----------------------------
# Helpers de carga
# -----------------------------
@st.cache_data(ttl=15)
def load_people():
    res = sb.table("people").select("id,name,active,is_placeholder").execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return df
    df["name"] = df["name"].astype(str)
    df = df[df.get("active", True) == True].copy()
    df = df.sort_values(["is_placeholder", "name"], ascending=[True, True]).reset_index(drop=True)
    return df


@st.cache_data(ttl=15)
def load_projects():
    res = sb.table("projects").select("id,project_code,name,status").execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return df
    df["project_code"] = df["project_code"].fillna("").astype(str)
    df["name"] = df["name"].fillna("").astype(str)
    df["label"] = (df["project_code"] + " — " + df["name"]).str.strip(" —")
    df = df.sort_values(["project_code", "name"]).reset_index(drop=True)
    return df


@st.cache_data(ttl=10)
def load_tasks(project_id=None):
    q = sb.table("tasks").select(
        "id,project_id,title,tipo_atividade,assignee_id,start_date,end_date,date_confidence,notes,created_at,updated_at,status"
    )
    if project_id:
        q = q.eq("project_id", project_id)
    res = q.execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return df
    # normalizações
    df["title"] = df["title"].fillna("").astype(str)
    df["tipo_atividade"] = df["tipo_atividade"].fillna("CAMPO").astype(str)
    df["notes"] = df["notes"].fillna("").astype(str)
    df["date_confidence"] = df["date_confidence"].fillna("PLANEJADO").astype(str)
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce").dt.date
    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce").dt.date
    df["end_date"] = df["end_date"].fillna(df["start_date"])
    return df


def refresh_all():
    load_people.clear()
    load_projects.clear()
    load_tasks.clear()


def safe_date(x):
    if x is None or x == "":
        return None
    if isinstance(x, date):
        return x
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return None


# -----------------------------
# Base
# -----------------------------
people_df = load_people()
projects_df = load_projects()

if people_df.empty:
    st.error("Tabela people está vazia. Crie as pessoas (incluindo placeholders) antes.")
    st.stop()

if projects_df.empty:
    st.warning("Tabela projects está vazia. Crie/importa projetos para começar.")
    st.stop()

# Mapa de pessoas
people_id_by_name = dict(zip(people_df["name"], people_df["id"]))
people_name_by_id = dict(zip(people_df["id"], people_df["name"]))
people_names = people_df["name"].tolist()

# Seleção de projeto (escopo da página)
project_labels = projects_df["label"].tolist()
sel_project_label = st.selectbox("Projeto", project_labels, index=0)
sel_project_row = projects_df[projects_df["label"] == sel_project_label].iloc[0]
sel_project_id = sel_project_row["id"]

tasks_df = load_tasks(sel_project_id)

st.divider()


# -----------------------------
# Criar nova tarefa
# -----------------------------
with st.container(border=True):
    st.subheader("Nova tarefa")

    c1, c2, c3, c4 = st.columns([2.2, 1.2, 1.2, 1.2])

    with c1:
        title = st.text_input("Título", value="")

    with c2:
        tipo = st.selectbox("Tipo Atividade", ["CAMPO", "RELATORIO", "ADMINISTRATIVO"], index=0)

    with c3:
        assignee_name = st.selectbox("Responsável", people_names, index=0)

    with c4:
        status_data = st.selectbox("Status da data", STATUS_DATA_OPTIONS, index=0)

    c5, c6 = st.columns([1, 1])
    with c5:
        start_d = st.date_input("Início", value=date.today(), format="DD/MM/YYYY")
    with c6:
        end_d = st.date_input("Fim", value=date.today(), format="DD/MM/YYYY")

    notes = st.text_area("Obs", value="", height=80)

    col_btn1, col_btn2 = st.columns([1, 6])
    with col_btn1:
        if st.button("Salvar tarefa", type="primary"):
            if not title.strip():
                st.error("Informe o título da tarefa.")
                st.stop()

            payload = {
                "project_id": str(sel_project_id),
                "title": title.strip(),
                "tipo_atividade": tipo,
                "assignee_id": str(people_id_by_name[assignee_name]),
                # Campo único: Status da data -> gravamos em date_confidence
                "date_confidence": status_data,
                "start_date": str(start_d),
                "end_date": str(end_d),
                "notes": notes.strip() if notes else None,
                # status interno para satisfazer CHECK do banco (não mostramos na UI)
                "status": DEFAULT_INTERNAL_STATUS,
            }

            sb.table("tasks").insert(payload).execute()
            st.success("Tarefa criada.")
            refresh_all()
            st.rerun()


st.divider()


# -----------------------------
# Lista + edição inline
# -----------------------------
st.subheader("Lista de tarefas (edição inline)")

if tasks_df.empty:
    st.info("Este projeto ainda não tem tarefas.")
    st.stop()

# Join nomes (assignee)
tasks_view = tasks_df.copy()
tasks_view["Responsável"] = tasks_view["assignee_id"].map(people_name_by_id).fillna("Gestao de Projetos")
tasks_view["Tipo"] = tasks_view["tipo_atividade"]
tasks_view["Status da data"] = tasks_view["date_confidence"].str.upper()

# Ordenação cronológica
tasks_view = tasks_view.sort_values(["start_date", "end_date", "title"], na_position="last").reset_index(drop=True)

# Colunas (ID depois de Obs)
tasks_view["Obs"] = tasks_view["notes"]

# Mostramos ID no final (depois de Obs), como você pediu
display_cols = [
    "title",
    "Tipo",
    "Responsável",
    "start_date",
    "end_date",
    "Status da data",
    "Obs",
    "id",
]

# dataframe para edição
edit_df = tasks_view[display_cols].copy()
edit_df.rename(columns={"title": "Tarefa", "start_date": "Início", "end_date": "Fim"}, inplace=True)

# Config editor (selects)
column_config = {
    "Tarefa": st.column_config.TextColumn("Tarefa", width="large"),
    "Tipo": st.column_config.SelectboxColumn("Tipo", options=["CAMPO", "RELATORIO", "ADMINISTRATIVO"], width="medium"),
    "Responsável": st.column_config.SelectboxColumn("Responsável", options=people_names, width="medium"),
    "Início": st.column_config.DateColumn("Início", format="DD/MM/YYYY", width="small"),
    "Fim": st.column_config.DateColumn("Fim", format="DD/MM/YYYY", width="small"),
    "Status da data": st.column_config.SelectboxColumn("Status da data", options=STATUS_DATA_OPTIONS, width="small"),
    "Obs": st.column_config.TextColumn("Obs", width="large"),
    "id": st.column_config.TextColumn("ID", width="medium", disabled=True),
}

edited = st.data_editor(
    edit_df,
    use_container_width=True,
    hide_index=True,
    column_config=column_config,
    key="tasks_editor",
)

# Botões de ação
b1, b2, b3 = st.columns([1, 1, 6])

with b1:
    save_changes = st.button("Salvar alterações", type="primary")

with b2:
    reload_btn = st.button("Recarregar")

if reload_btn:
    refresh_all()
    st.rerun()


def apply_updates(before_df: pd.DataFrame, after_df: pd.DataFrame):
    """Compara linhas e atualiza apenas o que mudou."""
    # Indexa por id
    b = before_df.set_index("id")
    a = after_df.rename(columns={"Tarefa": "title", "Início": "start_date", "Fim": "end_date"}).set_index("id")

    changed = []
    for task_id in a.index:
        row_a = a.loc[task_id]
        row_b = b.loc[task_id]

        # campos relevantes
        fields = {
            "title": (str(row_a["title"]).strip(), str(row_b["title"]).strip()),
            "tipo_atividade": (str(row_a["Tipo"]).strip(), str(row_b["Tipo"]).strip()),
            "assignee_id": (
                str(people_id_by_name.get(str(row_a["Responsável"]), "")),
                str(row_b.get("assignee_id", "")),
            ),
            "start_date": (safe_date(row_a["start_date"]), safe_date(row_b["start_date"])),
            "end_date": (safe_date(row_a["end_date"]), safe_date(row_b["end_date"])),
            "date_confidence": (str(row_a["Status da data"]).upper(), str(row_b["date_confidence"]).upper()),
            "notes": (str(row_a.get("Obs", "")).strip(), str(row_b.get("notes", "")).strip()),
        }

        payload = {}
        for k, (newv, oldv) in fields.items():
            if newv != oldv and newv is not None and newv != "":
                if k in ("start_date", "end_date"):
                    payload[k] = str(newv)
                else:
                    payload[k] = newv

        if payload:
            # mantém status interno válido
            payload["status"] = DEFAULT_INTERNAL_STATUS
            changed.append((task_id, payload))

    # Aplica
    for task_id, payload in changed:
        sb.table("tasks").update(payload).eq("id", task_id).execute()

    return len(changed)


if save_changes:
    # before_df precisa ter os campos reais (inclui assignee_id etc.)
    before = tasks_df.copy()
    # after_df vem do editor, mas precisa do id + colunas visíveis
    after = edited.copy()
    # Reconstruímos colunas para o comparador
    after["id"] = edited["id"].astype(str)

    n = apply_updates(before_df=before, after_df=after)
    st.success(f"Alterações salvas. Linhas atualizadas: {n}")
    refresh_all()
    st.rerun()


st.divider()


# -----------------------------
# Ações: Cancelar e Excluir
# -----------------------------
st.subheader("Ações (Cancelar / Excluir)")

# Caixa para buscar tarefa existente
search_options = (tasks_view["title"].fillna("").astype(str) + "  —  " + tasks_view["id"].astype(str)).tolist()
sel_task = st.selectbox("Selecione uma tarefa", search_options, index=0)

sel_task_id = sel_task.split("—")[-1].strip()

a1, a2, _ = st.columns([1, 1, 6])

with a1:
    if st.button("Cancelar tarefa"):
        sb.table("tasks").update({"date_confidence": "CANCELADO", "status": DEFAULT_INTERNAL_STATUS}).eq("id", sel_task_id).execute()
        st.success("Tarefa cancelada (mantida no histórico).")
        refresh_all()
        st.rerun()

with a2:
    # DELETE com confirmação simples
    confirm = st.checkbox("Confirmo exclusão definitiva desta tarefa", value=False)
    if st.button("Excluir tarefa", type="secondary", disabled=not confirm):
        sb.table("tasks").delete().eq("id", sel_task_id).execute()
        st.success("Tarefa excluída definitivamente.")
        refresh_all()
        st.rerun()


