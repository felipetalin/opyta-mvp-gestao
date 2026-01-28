# app/pages/3_Tarefas.py

import re
from datetime import date

import pandas as pd
import streamlit as st

from services.auth import require_login
from services.supabase_client import get_authed_client

# Branding (não pode quebrar o app se faltar algo)
try:
    from ui.brand import apply_brand, apply_app_chrome, page_header
except Exception:
    def apply_brand():  # type: ignore
        return

    def apply_app_chrome():  # type: ignore
        return

    def page_header(title, subtitle, user_email=""):  # type: ignore
        st.title(title)
        if subtitle:
            st.caption(subtitle)
        if user_email:
            st.caption(f"Logado como: {user_email}")


# ==========================================================
# Config (alinhado com constraints do Supabase)
# ==========================================================
TIPO_OPTIONS = ["CAMPO", "RELATORIO", "ADMINISTRATIVO"]
DATE_CONFIDENCE_OPTIONS = ["PLANEJADO", "CONFIRMADO", "CANCELADO"]

STATUS_DEFAULT = "PLANEJADA"  # coluna status ainda existe
PLACEHOLDER_PERSON_NAME = "Profissional"  # você padronizou para "Profissional"


# ==========================================================
# Boot
# ==========================================================
st.set_page_config(page_title="Tarefas", layout="wide")
apply_brand()
apply_app_chrome()

require_login()
sb = get_authed_client()

page_header("Tarefas", "Edição e controle", st.session_state.get("user_email", ""))


# ==========================================================
# Helpers
# ==========================================================
def _api_error_message(e: Exception) -> str:
    try:
        if getattr(e, "args", None) and len(e.args) > 0 and isinstance(e.args[0], dict):
            d = e.args[0]
            msg = d.get("message") or str(d)
            details = d.get("details")
            hint = d.get("hint")
            out = msg
            if hint:
                out += f"\nHint: {hint}"
            if details:
                out += f"\nDetalhes: {details}"
            return out
        return str(e)
    except Exception:
        return "Erro desconhecido."

def to_date(x):
    if pd.isna(x) or x is None:
        return None
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return None

def split_assignees(text: str) -> list[str]:
    """
    Aceita:
      'Ana + Felipe'
      'Ana, Felipe'
      'Ana;Felipe'
    Retorna lista limpa.
    """
    if not text:
        return []
    parts = re.split(r"[+,;]", str(text))
    names = []
    for p in parts:
        n = p.strip()
        if n:
            names.append(n)
    return names

def delete_task(task_id: str):
    # remove relacionamentos antes
    sb.table("task_people").delete().eq("task_id", task_id).execute()
    sb.table("tasks").delete().eq("id", task_id).execute()

def set_task_people(task_id: str, person_ids: list[str]):
    """
    Regrava task_people.
    Lead obrigatório: o 1º da lista vira is_lead=true
    Também mantém tasks.assignee_id = 1º.
    """
    sb.table("task_people").delete().eq("task_id", task_id).execute()

    if not person_ids:
        return

    inserts = []
    for i, pid in enumerate(person_ids):
        inserts.append({"task_id": task_id, "person_id": pid, "is_lead": True if i == 0 else False})
    sb.table("task_people").insert(inserts).execute()

    sb.table("tasks").update({"assignee_id": person_ids[0]}).eq("id", task_id).execute()


# ==========================================================
# Loads
# ==========================================================
@st.cache_data(ttl=30)
def load_projects():
    res = sb.table("projects").select("id, project_code, name").order("project_code").execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return df
    df["label"] = (df["project_code"].fillna("").astype(str) + " — " + df["name"].fillna("").astype(str)).str.strip(" —")
    return df

@st.cache_data(ttl=30)
def load_people():
    res = sb.table("people").select("id, name").order("name").execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return df, {}, {}
    name_to_id = dict(zip(df["name"], df["id"]))
    id_to_name = dict(zip(df["id"], df["name"]))
    return df, name_to_id, id_to_name

@st.cache_data(ttl=30)
def load_tasks_for_project(project_id: str):
    # tenta ler notes também; se view não tiver, a UI segue sem notes
    cols_try = "task_id, project_id, title, tipo_atividade, start_date, end_date, date_confidence, status, assignee_names, notes"
    try:
        res = (
            sb.table("v_portfolio_tasks")
            .select(cols_try)
            .eq("project_id", project_id)
            .order("start_date")
            .execute()
        )
        return pd.DataFrame(res.data or [])
    except Exception:
        cols_fallback = "task_id, project_id, title, tipo_atividade, start_date, end_date, date_confidence, status, assignee_names"
        res = (
            sb.table("v_portfolio_tasks")
            .select(cols_fallback)
            .eq("project_id", project_id)
            .order("start_date")
            .execute()
        )
        return pd.DataFrame(res.data or [])

def refresh_tasks_cache():
    load_tasks_for_project.clear()

def refresh_people_cache():
    load_people.clear()

def refresh_projects_cache():
    load_projects.clear()


# ==========================================================
# Projeto
# ==========================================================
df_projects = load_projects()
if df_projects.empty:
    st.warning("Nenhum projeto encontrado. Crie um projeto antes.")
    st.stop()

selected_label = st.selectbox("Projeto", df_projects["label"].tolist(), index=0)
project_id = df_projects.loc[df_projects["label"] == selected_label, "id"].iloc[0]


# ==========================================================
# People + placeholder
# ==========================================================
df_people, people_map, id_to_name = load_people()
if df_people.empty:
    st.warning("Tabela people está vazia.")
    st.stop()

if PLACEHOLDER_PERSON_NAME not in people_map:
    st.error(f"Não achei '{PLACEHOLDER_PERSON_NAME}' na tabela people. Crie esse registro antes.")
    st.stop()

placeholder_id = people_map[PLACEHOLDER_PERSON_NAME]


# ==========================================================
# Nova tarefa
# ==========================================================
st.divider()
with st.container(border=True):
    st.subheader("Nova tarefa")

    c1, c2, c3, c4 = st.columns([2.2, 1.2, 1.2, 1.2])

    with c1:
        title = st.text_input("Título", value="")

    with c2:
        tipo = st.selectbox("Tipo", TIPO_OPTIONS, index=0)

    with c3:
        start_date = st.date_input("Início", value=date.today(), format="DD/MM/YYYY")

    with c4:
        end_date = st.date_input("Fim", value=date.today(), format="DD/MM/YYYY")

    c5, c6 = st.columns([2.2, 1.2])
    with c5:
        date_conf = st.selectbox("Status da data", DATE_CONFIDENCE_OPTIONS, index=0)
    with c6:
        st.text_input("Status (interno)", value=STATUS_DEFAULT, disabled=True)

    assignees_text = st.text_input(
        "Responsável(is) (ex: Ana + Felipe)",
        value=PLACEHOLDER_PERSON_NAME,
        help="Use '+' para múltiplos responsáveis. Também aceito ',' e ';'.",
    )

    notes = st.text_area("Observações", value="", height=90)

    create = st.button("Criar tarefa", type="primary")

    if create:
        if not title.strip():
            st.error("Informe um título.")
        elif end_date < start_date:
            st.error("Fim não pode ser menor que Início.")
        else:
            try:
                names = split_assignees(assignees_text)
                if not names:
                    names = [PLACEHOLDER_PERSON_NAME]

                person_ids = []
                unknown = []
                for n in names:
                    pid = people_map.get(n)
                    if pid:
                        person_ids.append(pid)
                    else:
                        unknown.append(n)

                # se tiver nome não cadastrado, aborta e explica
                if unknown:
                    st.error(
                        "Alguns responsáveis não existem na tabela people:\n"
                        + "\n".join([f"- {x}" for x in unknown])
                        + "\n\nCadastre no Supabase ou corrija o texto."
                    )
                else:
                    if not person_ids:
                        person_ids = [placeholder_id]

                    payload = {
                        "project_id": project_id,
                        "title": title.strip(),
                        "tipo_atividade": tipo,
                        "assignee_id": person_ids[0],
                        "status": STATUS_DEFAULT,
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "date_confidence": date_conf,
                        "notes": (notes or "").strip() or None,
                    }

                    ins = sb.table("tasks").insert(payload).execute()
                    new_id = ins.data[0]["id"]

                    set_task_people(new_id, person_ids)

                    st.success("Tarefa criada com sucesso.")
                    refresh_tasks_cache()
                    st.rerun()

            except Exception as e:
                st.error("Erro ao criar tarefa:")
                st.code(_api_error_message(e))


# ==========================================================
# Lista (edição inline + exclusão por linha)
# ==========================================================
st.divider()
st.subheader("Lista de tarefas (edite direto aqui)")

try:
    df_tasks = load_tasks_for_project(project_id)
except Exception as e:
    st.error("Erro ao carregar tarefas (view v_portfolio_tasks).")
    st.code(_api_error_message(e))
    st.stop()

if df_tasks.empty:
    st.info("Sem tarefas nesse projeto.")
    st.stop()

df_tasks = df_tasks.copy()
df_tasks.rename(columns={"task_id": "ID"}, inplace=True)

# garante colunas
if "assignee_names" not in df_tasks.columns:
    df_tasks["assignee_names"] = PLACEHOLDER_PERSON_NAME
if "notes" not in df_tasks.columns:
    df_tasks["notes"] = ""

df_show = pd.DataFrame(
    {
        "Tarefa": df_tasks["title"].astype(str),
        "Tipo": df_tasks["tipo_atividade"].astype(str),
        "Responsável(is)": df_tasks["assignee_names"].fillna(PLACEHOLDER_PERSON_NAME).astype(str),
        "Início": df_tasks["start_date"].apply(to_date),
        "Fim": df_tasks["end_date"].apply(to_date),
        "Status da data": df_tasks["date_confidence"].fillna("PLANEJADO").astype(str),
        "Obs": df_tasks["notes"].fillna("").astype(str),
        "🗑 Excluir": False,
        "ID": df_tasks["ID"].astype(str),
    }
)

# Ordem solicitada: ID após Obs
df_show = df_show[["Tarefa", "Tipo", "Responsável(is)", "Início", "Fim", "Status da data", "Obs", "ID", "🗑 Excluir"]]

edited = st.data_editor(
    df_show,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "Tarefa": st.column_config.TextColumn(width="large"),
        "Tipo": st.column_config.SelectboxColumn(options=TIPO_OPTIONS, width="medium"),
        "Responsável(is)": st.column_config.TextColumn(width="large", help="Use ' + ' para múltiplos."),
        "Início": st.column_config.DateColumn(format="DD/MM/YYYY"),
        "Fim": st.column_config.DateColumn(format="DD/MM/YYYY"),
        "Status da data": st.column_config.SelectboxColumn(options=DATE_CONFIDENCE_OPTIONS, width="medium"),
        "Obs": st.column_config.TextColumn(width="large"),
        "ID": st.column_config.TextColumn(disabled=True, width="medium"),
        "🗑 Excluir": st.column_config.CheckboxColumn(width="small"),
    },
)

cbtn1, cbtn2 = st.columns([1, 1])
with cbtn1:
    save_inline = st.button("Salvar alterações", type="primary")
with cbtn2:
    reload_inline = st.button("Recarregar")

if reload_inline:
    refresh_tasks_cache()
    st.rerun()

if save_inline:
    try:
        before = df_show.copy()
        after = edited.copy()

        # 1) Exclusões
        to_delete = after[after["🗑 Excluir"] == True]  # noqa: E712
        deleted_count = 0
        for _, row in to_delete.iterrows():
            task_id = str(row["ID"]).strip()
            delete_task(task_id)
            deleted_count += 1

        # remove as deletadas da comparação de updates
        after_updates = after[after["🗑 Excluir"] != True].copy()  # noqa: E712
        before_updates = before.loc[after_updates.index].copy()

        # 2) Updates
        changed = after_updates.ne(before_updates)
        rows_changed = changed.any(axis=1)

        n_updates = 0
        for idx in after_updates.index[rows_changed]:
            row_b = before_updates.loc[idx]
            row_a = after_updates.loc[idx]

            task_id = str(row_a["ID"]).strip()

            # valida datas
            start_v = row_a["Início"]
            end_v = row_a["Fim"]
            if start_v and end_v and end_v < start_v:
                st.warning(f"Linha {idx+1}: 'Fim' menor que 'Início' (ignorado).")
                continue

            # responsáveis -> ids
            names = split_assignees(str(row_a["Responsável(is)"]))
            if not names:
                names = [PLACEHOLDER_PERSON_NAME]

            person_ids = []
            unknown = []
            for n in names:
                pid = people_map.get(n)
                if pid:
                    person_ids.append(pid)
                else:
                    unknown.append(n)

            if unknown:
                st.warning(
                    f"Linha {idx+1}: responsáveis não cadastrados (ignorado update de responsáveis): "
                    + ", ".join(unknown)
                )
                person_ids = None  # não atualiza responsáveis
            elif not person_ids:
                person_ids = [placeholder_id]

            update_payload = {
                "title": str(row_a["Tarefa"]).strip(),
                "tipo_atividade": str(row_a["Tipo"]).strip(),
                "start_date": start_v.isoformat() if start_v else None,
                "end_date": end_v.isoformat() if end_v else None,
                "date_confidence": str(row_a["Status da data"]).strip(),
                "notes": str(row_a["Obs"]).strip() or None,
            }

            sb.table("tasks").update(update_payload).eq("id", task_id).execute()

            # atualiza responsáveis multi (se ok)
            if person_ids is not None:
                set_task_people(task_id, person_ids)

            n_updates += 1

        msg = []
        if deleted_count:
            msg.append(f"Excluídas: {deleted_count}")
        msg.append(f"Atualizadas: {n_updates}")
        st.success(" | ".join(msg))

        refresh_tasks_cache()
        st.rerun()

    except Exception as e:
        st.error("Erro ao salvar alterações:")
        st.code(_api_error_message(e))
