# app/pages/3_Tarefas.py

from datetime import date

import pandas as pd
import streamlit as st

from services.auth import require_login
from services.supabase_client import get_authed_client

st.set_page_config(page_title="Tarefas", layout="wide")

require_login()
sb = get_authed_client()

st.title("Tarefas")

# -----------------------------
# Data loaders
# -----------------------------
@st.cache_data(ttl=30)
def load_projects():
    r = (
        sb.table("projects")
        .select("id, project_code, name")
        .order("project_code")
        .execute()
    )
    df = pd.DataFrame(r.data or [])
    if df.empty:
        return df
    df["label"] = df["project_code"].astype(str) + " | " + df["name"].astype(str)
    return df


@st.cache_data(ttl=30)
def load_people():
    r = sb.table("people").select("id, name").order("name").execute()
    return pd.DataFrame(r.data or [])


@st.cache_data(ttl=30)
def load_tasks_for_project(project_id: str):
    # ✅ FIX AQUI: tasks não tem "obs", tem "notes"
    # (mantemos "notes" e mais pra baixo exibimos como "Obs" na UI)
    r = (
        sb.table("tasks")
        .select("id, project_id, title, tipo_atividade, status, date_confidence, start_date, end_date, notes")
        .eq("project_id", project_id)
        .order("start_date")
        .execute()
    )
    return pd.DataFrame(r.data or [])


@st.cache_data(ttl=30)
def load_task_people(project_id: str):
    # task_people: task_id, person_id, is_lead
    r = (
        sb.table("task_people")
        .select("task_id, person_id, is_lead")
        .execute()
    )
    df = pd.DataFrame(r.data or [])
    if df.empty:
        return df
    # filtramos só tasks do projeto depois, porque o PostgREST não faz join aqui
    tasks = load_tasks_for_project(project_id)
    if tasks.empty:
        return df.iloc[0:0]
    return df[df["task_id"].isin(tasks["id"].tolist())].copy()


def invalidate_all():
    load_projects.clear()
    load_people.clear()
    load_tasks_for_project.clear()
    load_task_people.clear()


# -----------------------------
# UI: selecionar projeto
# -----------------------------
df_projects = load_projects()
if df_projects.empty:
    st.warning("Nenhum projeto cadastrado.")
    st.stop()

sel = st.selectbox("Projeto", df_projects["label"].tolist(), index=0)
project_id = df_projects.loc[df_projects["label"] == sel, "id"].iloc[0]

df_people = load_people()
people_map = {row["name"]: row["id"] for _, row in df_people.iterrows()}
people_names = sorted(list(people_map.keys()))

df_tasks = load_tasks_for_project(project_id)
if df_tasks.empty:
    st.info("Este projeto ainda não tem tarefas.")
    st.stop()

df_tp = load_task_people(project_id)

# -----------------------------
# Montar dataframe editável
# -----------------------------
# assignees por tarefa (lista de nomes)
task_assignees = {}
task_lead = {}

if not df_tp.empty and not df_people.empty:
    inv_people = {row["id"]: row["name"] for _, row in df_people.iterrows()}

    for tid, grp in df_tp.groupby("task_id"):
        names = []
        lead_name = None
        for _, r in grp.iterrows():
            nm = inv_people.get(r["person_id"])
            if nm:
                names.append(nm)
                if bool(r.get("is_lead")):
                    lead_name = nm
        task_assignees[tid] = sorted(set(names))
        task_lead[tid] = lead_name

# defaults
def safe_list(x):
    return x if isinstance(x, list) else []

df_edit = df_tasks.copy()
df_edit["Profissionais"] = df_edit["id"].map(lambda x: safe_list(task_assignees.get(x, [])))
df_edit["Lead"] = df_edit["id"].map(lambda x: task_lead.get(x, None))
df_edit["Obs"] = df_edit.get("notes", "")

# colunas (pedido seu: ID depois de Obs)
df_show = df_edit[
    [
        "title",
        "tipo_atividade",
        "date_confidence",
        "status",
        "start_date",
        "end_date",
        "Profissionais",
        "Lead",
        "Obs",
        "id",
    ]
].rename(
    columns={
        "title": "Tarefa",
        "tipo_atividade": "Tipo",
        "date_confidence": "Status da data",
        "status": "Status",
        "start_date": "Início",
        "end_date": "Fim",
        "id": "ID",
    }
)

# -----------------------------
# Editor
# -----------------------------
st.caption("Edite inline e clique em **Salvar alterações** ao final.")

col_config = {
    "Tarefa": st.column_config.TextColumn(width="large"),
    "Tipo": st.column_config.SelectboxColumn(
        options=["CAMPO", "RELATORIO", "ADMINISTRATIVO"],
        required=True,
        width="small",
    ),
    "Status da data": st.column_config.SelectboxColumn(
        options=["PLANEJADO", "CONFIRMADO", "CANCELADO"],
        required=False,
        width="small",
    ),
    "Status": st.column_config.SelectboxColumn(
        options=["PLANEJADA", "AGUARDANDO_CONFIRMACAO", "EM_ANDAMENTO", "CONCLUIDA", "CANCELADA"],
        required=True,
        width="small",
    ),
    "Início": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
    "Fim": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
    "Profissionais": st.column_config.ListColumn(help="Selecione 1+ pessoas", width="large"),
    "Lead": st.column_config.SelectboxColumn(options=people_names, required=True, width="medium"),
    "Obs": st.column_config.TextColumn(width="large"),
    "ID": st.column_config.TextColumn(disabled=True, width="medium"),
}

edited = st.data_editor(
    df_show,
    use_container_width=True,
    hide_index=True,
    column_config=col_config,
    num_rows="fixed",
)

# -----------------------------
# Validar e salvar
# -----------------------------
def normalize_str(x):
    if x is None:
        return None
    s = str(x).strip()
    return s if s else None


def to_date(x):
    if x is None or x == "":
        return None
    return pd.to_datetime(x).date()


def save_changes(before_df: pd.DataFrame, after_df: pd.DataFrame) -> int:
    # merge por ID
    b = before_df.copy()
    a = after_df.copy()

    # garantir colunas
    for c in ["ID", "Tarefa", "Tipo", "Status da data", "Status", "Início", "Fim", "Profissionais", "Lead", "Obs"]:
        if c not in a.columns:
            raise KeyError(f"Coluna esperada ausente no editor: {c}")

    b = b.set_index("ID")
    a = a.set_index("ID")

    updated = 0

    for tid in a.index:
        row_a = a.loc[tid]
        row_b = b.loc[tid]

        # valida lead obrigatório
        lead = normalize_str(row_a["Lead"])
        profs = row_a["Profissionais"] if isinstance(row_a["Profissionais"], list) else []
        profs = [normalize_str(p) for p in profs if normalize_str(p)]
        profs = sorted(set(profs))

        if not lead:
            st.error(f"Tarefa {tid}: Lead é obrigatório.")
            return 0
        if lead not in profs:
            # garante lead dentro da lista
            profs = sorted(set(profs + [lead]))

        # datas
        d_ini = to_date(row_a["Início"])
        d_fim = to_date(row_a["Fim"])
        if d_ini and d_fim and d_fim < d_ini:
            st.error(f"Tarefa '{row_a['Tarefa']}': Fim < Início.")
            return 0

        payload_tasks = {
            "title": normalize_str(row_a["Tarefa"]),
            "tipo_atividade": normalize_str(row_a["Tipo"]),
            "date_confidence": normalize_str(row_a["Status da data"]),
            "status": normalize_str(row_a["Status"]),
            "start_date": d_ini.isoformat() if d_ini else None,
            "end_date": d_fim.isoformat() if d_fim else None,
            "notes": normalize_str(row_a["Obs"]),
        }

        # detecta mudança em tasks
        changed_tasks = False
        for k in ["title", "tipo_atividade", "date_confidence", "status", "start_date", "end_date", "notes"]:
            # compara com before (que tem nomes diferentes)
            pass

        # atualiza tasks sempre (mais simples e seguro)
        sb.table("tasks").update(payload_tasks).eq("id", tid).execute()

        # atualizar task_people: remove tudo e insere novamente (simples e robusto)
        sb.table("task_people").delete().eq("task_id", tid).execute()

        inserts_tp = []
        for name in profs:
            pid = people_map.get(name)
            if not pid:
                st.error(f"Pessoa não encontrada na tabela people: {name}")
                return 0
            inserts_tp.append({"task_id": tid, "person_id": pid, "is_lead": (name == lead)})

        if inserts_tp:
            sb.table("task_people").insert(inserts_tp).execute()

        updated += 1

    return updated


# df_before para comparação/validação (do jeito que mostramos)
before = df_show.copy()

# botão salvar
c1, c2 = st.columns([1, 3])
with c1:
    if st.button("💾 Salvar alterações", type="primary"):
        try:
            n = save_changes(before_df=before, after_df=edited)
            if n > 0:
                st.success(f"Salvo! {n} tarefas atualizadas.")
                invalidate_all()
                st.rerun()
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")

with c2:
    st.caption("Dica: se o app estiver cacheado, use Salvar (ele já limpa cache e recarrega).")


