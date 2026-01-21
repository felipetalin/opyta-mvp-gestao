# app/pages/3_Tarefas.py
import pandas as pd
import streamlit as st
from datetime import date

from services.auth import require_login
from services.supabase_client import get_authed_client

st.set_page_config(page_title="Tarefas", layout="wide")
st.title("Tarefas")

require_login()
sb = get_authed_client()

# =========================
# Constantes (conforme constraints do seu Supabase)
# =========================
TIPOS = ["CAMPO", "RELATORIO", "ADMINISTRATIVO"]
DATE_STATUS = ["PLANEJADO", "CONFIRMADO", "CANCELADO"]  # seu check tasks_date_confidence_check
TASK_STATUS = ["PLANEJADA", "AGUARDANDO_CONFIRMACAO", "EM_ANDAMENTO", "CONCLUIDA", "CANCELADA"]

# =========================
# Helpers
# =========================
def to_date(x):
    """Converte para datetime.date (ou None)."""
    if x is None or x == "":
        return None
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return None

@st.cache_data(ttl=30)
def load_projects():
    r = sb.table("projects").select("id,project_code,name").order("project_code").execute()
    df = pd.DataFrame(r.data or [])
    if df.empty:
        return df
    df["label"] = df["project_code"].astype(str) + " — " + df["name"].astype(str)
    return df[["id", "label", "project_code", "name"]]

@st.cache_data(ttl=30)
def load_people():
    r = sb.table("people").select("id,name,active").eq("active", True).order("name").execute()
    df = pd.DataFrame(r.data or [])
    if df.empty:
        return df
    df["name"] = df["name"].astype(str)
    return df[["id", "name"]]

@st.cache_data(ttl=10)
def load_tasks(project_id: str):
    # NOTE: sua tabela tasks tem notes, não obs.
    r = (
        sb.table("tasks")
        .select("id,project_id,title,tipo_atividade,start_date,end_date,date_confidence,status,notes")
        .eq("project_id", project_id)
        .order("start_date")
        .execute()
    )
    df = pd.DataFrame(r.data or [])
    if df.empty:
        return df

    # normaliza tipos pro data_editor
    df["Início"] = df["start_date"].map(to_date)
    df["Fim"] = df["end_date"].map(to_date)
    df["Título"] = df["title"].fillna("").astype(str)
    df["Tipo"] = df["tipo_atividade"].fillna("RELATORIO").astype(str)
    df["Status da data"] = df["date_confidence"].fillna("PLANEJADO").astype(str)
    df["Status"] = df["status"].fillna("PLANEJADA").astype(str)
    df["Observações"] = df["notes"].fillna("").astype(str)
    df["ID"] = df["id"].astype(str)

    # DF para exibir/editar (ID depois de Observações, como você pediu)
    show = df[["Título", "Tipo", "Início", "Fim", "Status da data", "Status", "Observações", "ID"]].copy()
    return show

@st.cache_data(ttl=10)
def load_task_people(task_ids):
    """Retorna dict task_id -> list[{person_id,is_lead}]"""
    if not task_ids:
        return {}
    r = (
        sb.table("task_people")
        .select("task_id,person_id,is_lead")
        .in_("task_id", task_ids)
        .execute()
    )
    rows = r.data or []
    mp = {}
    for row in rows:
        mp.setdefault(row["task_id"], []).append(row)
    return mp

def update_one_task(task_id: str, payload: dict):
    sb.table("tasks").update(payload).eq("id", task_id).execute()

def delete_task(task_id: str):
    # deleta vínculos primeiro
    sb.table("task_people").delete().eq("task_id", task_id).execute()
    # depois a tarefa
    sb.table("tasks").delete().eq("id", task_id).execute()

def set_task_people(task_id: str, person_ids, lead_id: str):
    """Substitui todos os responsáveis de uma tarefa; 1 lead obrigatório."""
    # limpa
    sb.table("task_people").delete().eq("task_id", task_id).execute()
    # recria
    inserts = []
    for pid in person_ids:
        inserts.append(
            {"task_id": task_id, "person_id": pid, "is_lead": (pid == lead_id)}
        )
    if inserts:
        sb.table("task_people").insert(inserts).execute()

def validate_row(row):
    # datas
    ini = row.get("Início")
    fim = row.get("Fim")
    if ini and fim and fim < ini:
        return "Fim < Início"
    # enums
    if row.get("Tipo") not in TIPOS:
        return "Tipo inválido"
    if row.get("Status da data") not in DATE_STATUS:
        return "Status da data inválido"
    if row.get("Status") not in TASK_STATUS:
        return "Status inválido"
    return None

# =========================
# UI: Seleção de projeto
# =========================
projects = load_projects()
if projects.empty:
    st.warning("Nenhum projeto cadastrado ainda.")
    st.stop()

proj_label_to_id = dict(zip(projects["label"], projects["id"]))
sel_proj_label = st.selectbox("Projeto", projects["label"].tolist(), index=0)
project_id = proj_label_to_id[sel_proj_label]

# =========================
# UI: Criar tarefa (rápido)
# =========================
with st.expander("➕ Nova tarefa", expanded=False):
    people_df = load_people()
    if people_df.empty:
        st.error("Tabela people está vazia. Cadastre pessoas antes.")
    else:
        p_name_to_id = dict(zip(people_df["name"], people_df["id"]))
        all_names = people_df["name"].tolist()

        c1, c2 = st.columns([2, 1])
        with c1:
            new_title = st.text_input("Título", value="")
        with c2:
            new_tipo = st.selectbox("Tipo", TIPOS, index=1)

        c3, c4, c5 = st.columns([1, 1, 1])
        with c3:
            new_ini = st.date_input("Início", value=date.today(), format="DD/MM/YYYY")
        with c4:
            new_fim = st.date_input("Fim", value=date.today(), format="DD/MM/YYYY")
        with c5:
            new_date_status = st.selectbox("Status da data", DATE_STATUS, index=0)

        new_status = st.selectbox("Status", TASK_STATUS, index=0)

        st.markdown("**Responsáveis (multi) + Lead obrigatório**")
        new_people = st.multiselect("Responsáveis", all_names, default=[])
        new_lead = st.selectbox("Lead", (new_people if new_people else ["(selecione responsáveis)"]), index=0)

        new_notes = st.text_area("Observações", value="", height=90)

        if st.button("Criar tarefa", type="primary"):
            if not new_title.strip():
                st.error("Informe um título.")
            elif new_fim < new_ini:
                st.error("Fim < Início.")
            elif not new_people:
                st.error("Selecione pelo menos 1 responsável.")
            elif new_lead == "(selecione responsáveis)":
                st.error("Defina um Lead.")
            else:
                payload = {
                    "project_id": project_id,
                    "title": new_title.strip(),
                    "tipo_atividade": new_tipo,
                    "start_date": new_ini.isoformat(),
                    "end_date": new_fim.isoformat(),
                    "date_confidence": new_date_status,
                    "status": new_status,
                    "notes": new_notes.strip() if new_notes else None,
                }
                ins = sb.table("tasks").insert(payload).execute()
                new_task_id = ins.data[0]["id"]
                person_ids = [p_name_to_id[n] for n in new_people]
                lead_id = p_name_to_id[new_lead]
                set_task_people(new_task_id, person_ids, lead_id)
                st.success("Tarefa criada.")
                st.cache_data.clear()
                st.rerun()

# =========================
# Carregar tarefas
# =========================
df_show = load_tasks(project_id)
if df_show.empty:
    st.info("Sem tarefas neste projeto.")
    st.stop()

# =========================
# Data editor (INLINE) — estável
# =========================
st.subheader("Lista de tarefas (edição inline)")

edited = st.data_editor(
    df_show,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "Título": st.column_config.TextColumn(width="large"),
        "Tipo": st.column_config.SelectboxColumn(options=TIPOS, width="medium"),
        "Início": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Fim": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Status da data": st.column_config.SelectboxColumn(options=DATE_STATUS, width="medium"),
        "Status": st.column_config.SelectboxColumn(options=TASK_STATUS, width="medium"),
        "Observações": st.column_config.TextColumn(width="large"),
        "ID": st.column_config.TextColumn(disabled=True, width="small"),
    },
)

# =========================
# Aplicar alterações (somente o necessário)
# =========================
if st.button("Salvar alterações", type="primary"):
    before = df_show.copy()
    after = edited.copy()

    # validações + updates
    errors = []
    changed = 0

    for i in range(len(after)):
        row_a = after.iloc[i].to_dict()
        row_b = before.iloc[i].to_dict()
        task_id = str(row_a["ID"])

        err = validate_row(row_a)
        if err:
            errors.append(f"[{task_id}] {err}")
            continue

        payload = {}
        # compara campos editáveis
        if row_a["Título"] != row_b["Título"]:
            payload["title"] = str(row_a["Título"]).strip()
        if row_a["Tipo"] != row_b["Tipo"]:
            payload["tipo_atividade"] = str(row_a["Tipo"]).strip()
        if row_a["Status da data"] != row_b["Status da data"]:
            payload["date_confidence"] = str(row_a["Status da data"]).strip()
        if row_a["Status"] != row_b["Status"]:
            payload["status"] = str(row_a["Status"]).strip()
        if row_a["Observações"] != row_b["Observações"]:
            payload["notes"] = str(row_a["Observações"]).strip() if str(row_a["Observações"]).strip() else None

        # datas (date -> iso)
        if row_a["Início"] != row_b["Início"]:
            payload["start_date"] = row_a["Início"].isoformat() if row_a["Início"] else None
        if row_a["Fim"] != row_b["Fim"]:
            payload["end_date"] = row_a["Fim"].isoformat() if row_a["Fim"] else None

        if payload:
            update_one_task(task_id, payload)
            changed += 1

    if errors:
        st.error("Erros de validação:\n- " + "\n- ".join(errors))
    else:
        st.success(f"Salvo. Tarefas atualizadas: {changed}")
        st.cache_data.clear()
        st.rerun()

# =========================
# Responsáveis (multi) + lead obrigatório (fora do editor p/ não quebrar tipos)
# =========================
st.divider()
st.subheader("Responsáveis da tarefa (multi)")

people_df = load_people()
if people_df.empty:
    st.error("Tabela people está vazia. Cadastre pessoas antes.")
    st.stop()

names = people_df["name"].tolist()
name_to_id = dict(zip(people_df["name"], people_df["id"]))
id_to_name = dict(zip(people_df["id"], people_df["name"]))

task_ids = df_show["ID"].astype(str).tolist()
tp_map = load_task_people(task_ids)

# Escolher tarefa
task_pick = st.selectbox("Selecione a tarefa", task_ids, index=0)
cur = tp_map.get(task_pick, [])

cur_people_ids = [x["person_id"] for x in cur]
cur_people_names = [id_to_name.get(pid, pid) for pid in cur_people_ids]

cur_lead = None
for x in cur:
    if x.get("is_lead"):
        cur_lead = x["person_id"]
lead_name_default = id_to_name.get(cur_lead) if cur_lead else None

sel_people_names = st.multiselect("Responsáveis", names, default=cur_people_names)
if not sel_people_names:
    st.warning("Selecione ao menos 1 responsável (lead obrigatório).")
else:
    lead_options = sel_people_names
    lead_default_index = 0
    if lead_name_default in lead_options:
        lead_default_index = lead_options.index(lead_name_default)

    sel_lead_name = st.selectbox("Lead (obrigatório)", lead_options, index=lead_default_index)

    if st.button("Salvar responsáveis"):
        person_ids = [name_to_id[n] for n in sel_people_names]
        lead_id = name_to_id[sel_lead_name]
        set_task_people(task_pick, person_ids, lead_id)
        st.success("Responsáveis atualizados.")
        st.cache_data.clear()
        st.rerun()

# =========================
# Excluir tarefa
# =========================
st.divider()
st.subheader("Excluir tarefa")

col_a, col_b = st.columns([2, 1])
with col_a:
    del_task_id = st.selectbox("Tarefa para excluir", task_ids, index=0, key="del_task")
with col_b:
    confirm = st.checkbox("Confirmo exclusão permanente", value=False)

if st.button("Excluir definitivamente", type="secondary"):
    if not confirm:
        st.error("Marque a confirmação de exclusão.")
    else:
        delete_task(del_task_id)
        st.success("Tarefa excluída.")
        st.cache_data.clear()
        st.rerun()



