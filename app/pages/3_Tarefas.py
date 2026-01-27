# app/pages/3_Tarefas.py
import streamlit as st
import pandas as pd
from datetime import date

from services.auth import require_login
from services.supabase_client import get_authed_client
from ui.brand import apply_brand, apply_app_chrome, page_header

st.set_page_config(page_title="Tarefas", layout="wide")

apply_brand()
apply_app_chrome()

require_login()
sb = get_authed_client()

page_header("Tarefas", "Edição e controle", st.session_state.get("user_email", ""))



# ... resto do seu código continua igual






require_login()
sb = get_authed_client()

# ==========================================================
# Config (alinhado com constraints do Supabase)
# ==========================================================
TIPO_OPTIONS = ["CAMPO", "RELATORIO", "ADMINISTRATIVO"]
DATE_CONFIDENCE_OPTIONS = ["PLANEJADO", "CONFIRMADO", "CANCELADO"]
STATUS_DEFAULT = "PLANEJADA"  # coluna status ainda existe na tabela tasks

PLACEHOLDER_PERSON_NAME = "Profissional a definir"  # você padronizou isso

# ==========================================================
# Helpers
# ==========================================================
def _api_error_message(e: Exception) -> str:
    # postgrest.exceptions.APIError geralmente vem com dict em e.args[0]
    try:
        if getattr(e, "args", None) and len(e.args) > 0 and isinstance(e.args[0], dict):
            d = e.args[0]
            msg = d.get("message") or str(d)
            details = d.get("details")
            if details:
                return f"{msg}\n\nDetalhes: {details}"
            return msg
        return str(e)
    except Exception:
        return "Erro desconhecido (APIError)."

@st.cache_data(ttl=30)
def load_projects():
    res = sb.table("projects").select("id, project_code, name").order("project_code").execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return df
    df["label"] = df["project_code"].fillna("").astype(str) + " — " + df["name"].fillna("").astype(str)
    df["label"] = df["label"].str.strip(" —")
    return df

@st.cache_data(ttl=30)
def load_people():
    res = sb.table("people").select("id, name").order("name").execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return df, {}
    name_to_id = dict(zip(df["name"], df["id"]))
    return df, name_to_id

@st.cache_data(ttl=30)
def load_tasks_for_project(project_id: str):
    # IMPORTANTE: agora a lista vem da VIEW (tem assignee_names)
    # E usamos notes (não obs)
    res = (
        sb.table("v_portfolio_tasks")
        .select(
            "task_id, project_id, title, tipo_atividade, start_date, end_date, date_confidence, status, assignee_names"
        )
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

def to_date(x):
    # Streamlit DateColumn prefere date
    if pd.isna(x) or x is None:
        return None
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return None

def build_task_label(title: str, task_id: str) -> str:
    short = str(task_id)[:8]
    return f"{title} — {short}"

def set_task_people(task_id: str, person_ids: list[str]):
    """
    Define responsáveis (multi) em task_people.
    Para evitar confusão na UI: não mostramos lead.
    Mas, se a coluna is_lead existir e você quiser coerência, marcamos o 1º como lead=True.
    """
    # apaga vínculos antigos
    sb.table("task_people").delete().eq("task_id", task_id).execute()

    if not person_ids:
        return

    inserts = []
    for i, pid in enumerate(person_ids):
        inserts.append(
            {
                "task_id": task_id,
                "person_id": pid,
                "is_lead": True if i == 0 else False,
            }
        )
    sb.table("task_people").insert(inserts).execute()

    # mantém compatibilidade com tasks.assignee_id (usa o 1º como principal)
    sb.table("tasks").update({"assignee_id": person_ids[0]}).eq("id", task_id).execute()

def delete_task(task_id: str):
    # remove relacionamentos antes
    sb.table("task_people").delete().eq("task_id", task_id).execute()
    sb.table("tasks").delete().eq("id", task_id).execute()

# ==========================================================
# Header: Projeto
# ==========================================================
df_projects = load_projects()
if df_projects.empty:
    st.warning("Nenhum projeto encontrado. Crie um projeto antes.")
    st.stop()

project_labels = df_projects["label"].tolist()
selected_label = st.selectbox("Projeto", project_labels, index=0)

project_id = df_projects.loc[df_projects["label"] == selected_label, "id"].iloc[0]

# ==========================================================
# People
# ==========================================================
df_people, people_map = load_people()
if df_people.empty:
    st.warning("Nenhum profissional encontrado na tabela people.")
    st.stop()

# garante placeholder existir
if PLACEHOLDER_PERSON_NAME not in people_map:
    st.error(
        f"Não achei '{PLACEHOLDER_PERSON_NAME}' na tabela people. "
        f"Crie esse registro no Supabase para seguir."
    )
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
        # mantém no banco, mas não precisa expor tudo: default PLANEJADA
        st.text_input("Status (interno)", value=STATUS_DEFAULT, disabled=True)

    assignees_names = st.multiselect(
        "Responsáveis (multi)",
        options=df_people["name"].tolist(),
        default=[PLACEHOLDER_PERSON_NAME],
        help="Selecione 1 ou mais profissionais. Se não souber, deixe 'Profissional a definir'.",
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
                chosen_ids = [people_map.get(n) for n in assignees_names]
                chosen_ids = [pid for pid in chosen_ids if pid] or [placeholder_id]

                payload = {
                    "project_id": project_id,
                    "title": title.strip(),
                    "tipo_atividade": tipo,
                    "assignee_id": chosen_ids[0],  # compat
                    "status": STATUS_DEFAULT,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "date_confidence": date_conf,
                    "notes": (notes or "").strip() or None,
                }

                ins = sb.table("tasks").insert(payload).execute()
                new_id = ins.data[0]["id"]

                # salva responsáveis multi (sem UI de lead)
                set_task_people(new_id, chosen_ids)

                st.success("Tarefa criada com sucesso.")
                refresh_tasks_cache()
                st.rerun()

            except Exception as e:
                st.error("Erro ao criar tarefa:")
                st.code(_api_error_message(e))

# ==========================================================
# Lista (edição inline)
# ==========================================================
st.divider()
st.subheader("Lista de tarefas (edição inline)")

try:
    df_tasks = load_tasks_for_project(project_id)
except Exception as e:
    st.error("Erro ao carregar tarefas (view v_portfolio_tasks).")
    st.code(_api_error_message(e))
    st.stop()

if df_tasks.empty:
    st.info("Sem tarefas nesse projeto.")
else:
    # Normaliza tipos para o data_editor não quebrar
    df_tasks = df_tasks.copy()
    df_tasks.rename(columns={"task_id": "ID"}, inplace=True)

    df_show = pd.DataFrame(
        {
            "Tarefa": df_tasks["title"].astype(str),
            "Tipo": df_tasks["tipo_atividade"].astype(str),
            "Responsáveis": df_tasks["assignee_names"].fillna(PLACEHOLDER_PERSON_NAME).astype(str),
            "Início": df_tasks["start_date"].apply(to_date),
            "Fim": df_tasks["end_date"].apply(to_date),
            "Status da data": df_tasks["date_confidence"].fillna("PLANEJADO").astype(str),
            "Status (interno)": df_tasks["status"].fillna(STATUS_DEFAULT).astype(str),
            "Obs": "",  # notes não está na view atual — deixo vazio aqui para não quebrar
            "ID": df_tasks["ID"].astype(str),
        }
    )

    # Se você tiver notes na VIEW no futuro, basta trocar:
    # "Obs": df_tasks["notes"].fillna("").astype(str)

    # Ordem pedida: ID após Obs
    df_show = df_show[
        ["Tarefa", "Tipo", "Responsáveis", "Início", "Fim", "Status da data", "Status (interno)", "Obs", "ID"]
    ]

    # Editor
    edited = st.data_editor(
        df_show,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Tarefa": st.column_config.TextColumn(width="large"),
            "Tipo": st.column_config.SelectboxColumn(options=TIPO_OPTIONS, width="medium"),
            "Responsáveis": st.column_config.TextColumn(disabled=True, width="large"),
            "Início": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Fim": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Status da data": st.column_config.SelectboxColumn(options=DATE_CONFIDENCE_OPTIONS, width="medium"),
            "Status (interno)": st.column_config.SelectboxColumn(
                options=["PLANEJADA", "AGUARDANDO_CONFIRMACAO", "EM_ANDAMENTO", "CONCLUIDA", "CANCELADA"],
                width="medium",
            ),
            "Obs": st.column_config.TextColumn(width="large"),
            "ID": st.column_config.TextColumn(disabled=True, width="medium"),
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
            # Detecta linhas alteradas comparando df_show vs edited
            before = df_show.copy()
            after = edited.copy()

            changed = after.ne(before)
            rows_changed = changed.any(axis=1)

            n_updates = 0
            for idx in after.index[rows_changed]:
                row_b = before.loc[idx]
                row_a = after.loc[idx]

                task_id = str(row_a["ID"]).strip()

                update_payload = {
                    "title": str(row_a["Tarefa"]).strip(),
                    "tipo_atividade": str(row_a["Tipo"]).strip(),
                    "start_date": row_a["Início"].isoformat() if pd.notna(row_a["Início"]) and row_a["Início"] else None,
                    "end_date": row_a["Fim"].isoformat() if pd.notna(row_a["Fim"]) and row_a["Fim"] else None,
                    "date_confidence": str(row_a["Status da data"]).strip(),
                    "status": str(row_a["Status (interno)"]).strip(),
                    # notes/obs: como a view atual não traz notes, só atualizo se você digitou algo
                }

                obs_text = str(row_a["Obs"]).strip()
                if obs_text != str(row_b["Obs"]).strip():
                    update_payload["notes"] = obs_text or None

                # Valida datas simples
                if update_payload["start_date"] and update_payload["end_date"]:
                    if pd.to_datetime(update_payload["end_date"]) < pd.to_datetime(update_payload["start_date"]):
                        st.warning(f"Linha {idx+1}: 'Fim' menor que 'Início' (ignorando atualização).")
                        continue

                sb.table("tasks").update(update_payload).eq("id", task_id).execute()
                n_updates += 1

            st.success(f"Alterações salvas. Linhas atualizadas: {n_updates}")
            refresh_tasks_cache()
            st.rerun()

        except Exception as e:
            st.error("Erro ao salvar alterações:")
            st.code(_api_error_message(e))

# ==========================================================
# Ações: Responsáveis (multi) e Excluir
# ==========================================================
st.divider()
st.subheader("Ações (Responsáveis / Excluir)")

# Recarrega tasks (para dropdowns)
df_tasks2 = load_tasks_for_project(project_id)
if df_tasks2.empty:
    st.info("Sem tarefas para gerenciar.")
    st.stop()

task_options = []
task_label_to_id = {}
for _, r in df_tasks2.iterrows():
    tid = str(r["task_id"])
    ttl = str(r["title"])
    lbl = build_task_label(ttl, tid)
    task_options.append(lbl)
    task_label_to_id[lbl] = tid

colA, colB = st.columns([1, 1])

with colA:
    with st.container(border=True):
        st.markdown("### Responsáveis da tarefa (multi)")
        sel_task_lbl = st.selectbox("Selecione a tarefa", task_options, index=0, key="sel_task_people")
        sel_task_id = task_label_to_id[sel_task_lbl]

        # tenta pré-selecionar atuais (lendo task_people)
        current_people = []
        try:
            res_tp = sb.table("task_people").select("person_id, is_lead").eq("task_id", sel_task_id).execute()
            ids = [x["person_id"] for x in (res_tp.data or [])]
            id_to_name = {v: k for k, v in people_map.items()}
            current_people = [id_to_name.get(pid) for pid in ids if id_to_name.get(pid)]
        except Exception:
            current_people = []

        new_people = st.multiselect(
            "Responsáveis",
            options=df_people["name"].tolist(),
            default=current_people if current_people else [PLACEHOLDER_PERSON_NAME],
            key="multi_people",
        )

        btn_save_people = st.button("Salvar responsáveis", key="btn_save_people")

        if btn_save_people:
            try:
                new_ids = [people_map.get(n) for n in new_people]
                new_ids = [pid for pid in new_ids if pid] or [placeholder_id]
                set_task_people(sel_task_id, new_ids)
                st.success("Responsáveis atualizados.")
                refresh_tasks_cache()
                st.rerun()
            except Exception as e:
                st.error("Erro ao salvar responsáveis:")
                st.code(_api_error_message(e))

with colB:
    with st.container(border=True):
        st.markdown("### Excluir tarefa")
        del_task_lbl = st.selectbox("Tarefa para excluir", task_options, index=0, key="sel_task_delete")
        del_task_id = task_label_to_id[del_task_lbl]

        confirm = st.checkbox("Confirmo exclusão definitiva desta tarefa", value=False)
        btn_delete = st.button("Excluir definitivamente", disabled=not confirm, key="btn_delete_task")

        if btn_delete:
            try:
                delete_task(del_task_id)
                st.success("Tarefa excluída.")
                refresh_tasks_cache()
                st.rerun()
            except Exception as e:
                st.error("Erro ao excluir tarefa:")
                st.code(_api_error_message(e))




