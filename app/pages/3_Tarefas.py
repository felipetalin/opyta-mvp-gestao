# app/pages/3_Tarefas.py

import streamlit as st
import pandas as pd
from datetime import date

from services.auth import require_login
from services.supabase_client import get_authed_client

st.set_page_config(page_title="Tarefas", layout="wide")
st.title("Tarefas")

require_login()
sb = get_authed_client()

# -----------------------------
# Config (valores aceitos pelos CHECKs)
# -----------------------------
DATE_CONF_OPTIONS = ["PLANEJADO", "CONFIRMADO", "CANCELADO"]  # tasks_date_confidence_check
STATUS_OPTIONS = ["PLANEJADA", "EM_ANDAMENTO", "CONCLUIDA", "CANCELADA"]  # tasks_status_check
# Se você quiser deixar simples no formulário, a gente usa STATUS="PLANEJADA" sempre,
# e o usuário controla "Status da data" (date_confidence) como você decidiu.

# Tabela de vínculo (ajuste aqui se o nome for outro)
TASK_PEOPLE_TABLE = "task_people"  # troque para "task_assignees" se for esse o nome
TASK_PEOPLE_PERSON_COL = "person_id"  # se sua coluna chamar "person_id" ok; se chamar "person_id" ok; se chamar "person_id" mantenha
TASK_PEOPLE_IS_LEAD_COL = "is_lead"

# -----------------------------
# Helpers
# -----------------------------
@st.cache_data(ttl=30)
def load_projects():
    res = sb.table("projects").select("id, project_code, name").order("project_code").execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return df
    df["label"] = df["project_code"].fillna("") + " — " + df["name"].fillna("")
    return df

@st.cache_data(ttl=30)
def load_people_active():
    # ajuste o select conforme sua tabela people
    res = sb.table("people").select("id, name, active").execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return df
    df = df[df["active"] == True].copy() if "active" in df.columns else df
    df["name"] = df["name"].astype(str)
    return df.sort_values("name")

@st.cache_data(ttl=15)
def load_tasks_for_project(project_id: str):
    # puxa tasks
    t = sb.table("tasks").select("id, project_id, title, tipo_atividade, start_date, end_date, date_confidence, obs").eq("project_id", project_id).order("start_date").execute()
    df = pd.DataFrame(t.data or [])
    if df.empty:
        return df

    # puxa vínculos
    rel = sb.table(TASK_PEOPLE_TABLE).select("task_id, person_id, is_lead").execute()
    rel_df = pd.DataFrame(rel.data or [])
    if rel_df.empty:
        df["Responsáveis"] = ""
        df["Lead"] = ""
        return df

    people = load_people_active()
    if people.empty:
        df["Responsáveis"] = ""
        df["Lead"] = ""
        return df

    rel_df = rel_df.merge(people[["id", "name"]], left_on="person_id", right_on="id", how="left")
    rel_df["name"] = rel_df["name"].fillna("")

    # monta strings por task
    agg = (
        rel_df.groupby("task_id")
        .apply(lambda g: pd.Series({
            "Responsáveis": " + ".join(
                g.sort_values(["is_lead", "name"], ascending=[False, True])["name"].astype(str).tolist()
            ),
            "Lead": (g[g["is_lead"] == True]["name"].astype(str).iloc[0] if (g["is_lead"] == True).any() else "")
        }))
        .reset_index()
        .rename(columns={"task_id": "id"})
    )

    df = df.merge(agg, on="id", how="left")
    df["Responsáveis"] = df["Responsáveis"].fillna("")
    df["Lead"] = df["Lead"].fillna("")
    return df

def insert_task_people(task_id: str, person_ids: list[str], lead_id: str):
    rows = []
    for pid in person_ids:
        rows.append({
            "task_id": task_id,
            "person_id": pid,
            "is_lead": (pid == lead_id),
        })
    if rows:
        sb.table(TASK_PEOPLE_TABLE).insert(rows).execute()

def replace_task_people(task_id: str, person_ids: list[str], lead_id: str):
    # apaga vínculos e recria
    sb.table(TASK_PEOPLE_TABLE).delete().eq("task_id", task_id).execute()
    insert_task_people(task_id, person_ids, lead_id)

def delete_task(task_id: str):
    # apaga vínculos primeiro (FK)
    sb.table(TASK_PEOPLE_TABLE).delete().eq("task_id", task_id).execute()
    sb.table("tasks").delete().eq("id", task_id).execute()

def cancel_task(task_id: str):
    sb.table("tasks").update({"status": "CANCELADA"}).eq("id", task_id).execute()

# -----------------------------
# UI - Projeto
# -----------------------------
projects = load_projects()
if projects.empty:
    st.warning("Nenhum projeto cadastrado ainda.")
    st.stop()

proj_label_to_id = dict(zip(projects["label"], projects["id"]))
sel_proj_label = st.selectbox("Projeto", projects["label"].tolist(), index=0)
project_id = proj_label_to_id[sel_proj_label]

people_df = load_people_active()
if people_df.empty:
    st.warning("Tabela PEOPLE vazia/sem ativos. Cadastre pessoas primeiro.")
    st.stop()

name_to_id = dict(zip(people_df["name"], people_df["id"]))
all_names = people_df["name"].tolist()

st.divider()

# -----------------------------
# Nova tarefa
# -----------------------------
with st.container(border=True):
    st.subheader("Nova tarefa")

    c1, c2, c3, c4 = st.columns([2.2, 1.2, 1.4, 1.2])

    with c1:
        title = st.text_input("Título", value="", placeholder="Ex.: Campanha 03 - Jan/26")

    with c2:
        tipo = st.selectbox("Tipo Atividade", ["CAMPO", "RELATORIO", "ADMINISTRATIVO"], index=0)

    with c3:
        # multiselect de responsáveis (SEM placeholder)
        sel_people = st.multiselect("Responsáveis", all_names, default=[])

    with c4:
        date_conf = st.selectbox("Status da data", DATE_CONF_OPTIONS, index=0)

    c5, c6 = st.columns([1, 1])

    with c5:
        start = st.date_input("Início", value=date.today(), format="DD/MM/YYYY")

    with c6:
        end = st.date_input("Fim", value=date.today(), format="DD/MM/YYYY")

    obs = st.text_area("Obs", value="", height=80)

    # Lead obrigatório (somente aparece quando tem selecionados)
    lead_name = None
    if sel_people:
        lead_name = st.selectbox("Lead (obrigatório)", sel_people, index=0)
    else:
        st.info("Selecione pelo menos 1 responsável para habilitar o Lead.")

    if st.button("Salvar tarefa", type="primary"):
        if not title.strip():
            st.error("Título é obrigatório.")
            st.stop()

        if not sel_people:
            st.error("Selecione pelo menos 1 responsável.")
            st.stop()

        if not lead_name:
            st.error("Selecione o Lead.")
            st.stop()

        if end < start:
            st.error("Fim não pode ser antes do Início.")
            st.stop()

        payload = {
            "project_id": project_id,
            "title": title.strip(),
            "tipo_atividade": tipo,
            "status": "PLANEJADA",         # mantém simples aqui
            "date_confidence": date_conf,  # sua decisão de manter só “status da data”
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "obs": obs.strip() if obs else None,
        }

        ins = sb.table("tasks").insert(payload).execute()
        new_id = (ins.data or [{}])[0].get("id")

        if not new_id:
            st.error("Falha ao criar task (não retornou ID).")
            st.stop()

        person_ids = [name_to_id[n] for n in sel_people]
        lead_id = name_to_id[lead_name]

        replace_task_people(task_id=new_id, person_ids=person_ids, lead_id=lead_id)

        st.success("Tarefa criada com responsáveis e lead.")
        st.cache_data.clear()
        st.rerun()

st.divider()

# -----------------------------
# Lista (edição inline)
# -----------------------------
st.subheader("Lista de tarefas (edição inline)")

df_tasks = load_tasks_for_project(project_id)

if df_tasks.empty:
    st.info("Sem tarefas nesse projeto.")
else:
    # Renomeia colunas pra UI
    view = df_tasks.copy()

    # organiza ordem: Obs -> ID no fim (como você pediu)
    ui_cols = []
    col_map = {
        "title": "Tarefa",
        "tipo_atividade": "Tipo",
        "Responsáveis": "Responsáveis",
        "Lead": "Lead",
        "start_date": "Início",
        "end_date": "Fim",
        "date_confidence": "Status da data",
        "obs": "Obs",
        "id": "ID",
    }
    for k in ["title", "tipo_atividade", "Responsáveis", "Lead", "start_date", "end_date", "date_confidence", "obs", "id"]:
        if k in view.columns:
            ui_cols.append(k)

    view = view[ui_cols].rename(columns=col_map)

    # editáveis: Tarefa/Tipo/Inicio/Fim/Status da data/Obs
    # Responsáveis/Lead a gente não edita inline aqui (porque precisa regravar task_people com lead obrigatório)
    disabled_cols = ["Responsáveis", "Lead", "ID"]

    edited = st.data_editor(
        view,
        use_container_width=True,
        hide_index=True,
        disabled=disabled_cols,
        key="tasks_editor",
    )

    cbtn1, cbtn2 = st.columns([1, 1])
    with cbtn1:
        if st.button("Salvar alterações", type="primary"):
            before = view.copy()
            after = edited.copy()

            # detecta mudanças linha a linha
            changes = []
            for i in range(len(after)):
                row_a = before.iloc[i]
                row_b = after.iloc[i]
                task_id = str(row_b["ID"])

                upd = {}
                # Tarefa
                if str(row_a["Tarefa"]) != str(row_b["Tarefa"]):
                    upd["title"] = str(row_b["Tarefa"]).strip()

                # Tipo
                if str(row_a["Tipo"]) != str(row_b["Tipo"]):
                    upd["tipo_atividade"] = str(row_b["Tipo"]).strip()

                # Datas
                if str(row_a["Início"]) != str(row_b["Início"]):
                    upd["start_date"] = str(row_b["Início"])

                if str(row_a["Fim"]) != str(row_b["Fim"]):
                    upd["end_date"] = str(row_b["Fim"])

                # Status da data
                if str(row_a["Status da data"]) != str(row_b["Status da data"]):
                    upd["date_confidence"] = str(row_b["Status da data"]).strip()

                # Obs
                if str(row_a.get("Obs", "")) != str(row_b.get("Obs", "")):
                    upd["obs"] = (str(row_b.get("Obs", "")).strip() or None)

                if upd:
                    changes.append((task_id, upd))

            # aplica
            for task_id, upd in changes:
                sb.table("tasks").update(upd).eq("id", task_id).execute()

            st.success(f"Alterações salvas: {len(changes)} tarefa(s).")
            st.cache_data.clear()
            st.rerun()

    with cbtn2:
        if st.button("Recarregar"):
            st.cache_data.clear()
            st.rerun()

st.divider()

# -----------------------------
# Ações: Cancelar / Excluir
# -----------------------------
st.subheader("Ações (Cancelar / Excluir)")

df_tasks2 = load_tasks_for_project(project_id)
if df_tasks2.empty:
    st.info("Sem tarefas para ações.")
else:
    # monta label com ID
    df_tasks2["label"] = df_tasks2["title"].astype(str) + " — " + df_tasks2["id"].astype(str)
    pick = st.selectbox("Selecione uma tarefa", df_tasks2["label"].tolist(), index=0)
    picked_id = pick.split(" — ")[-1].strip()

    c1, c2 = st.columns([1, 2])

    with c1:
        if st.button("Cancelar tarefa"):
            cancel_task(picked_id)
            st.success("Tarefa cancelada (status=CANCELADA).")
            st.cache_data.clear()
            st.rerun()

    with c2:
        confirm = st.checkbox("Confirmo exclusão definitiva desta tarefa")
        if st.button("Excluir tarefa", type="secondary", disabled=not confirm):
            delete_task(picked_id)
            st.success("Tarefa excluída.")
            st.cache_data.clear()
            st.rerun()


