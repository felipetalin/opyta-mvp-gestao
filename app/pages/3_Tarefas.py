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


TIPO_OPTIONS = ["CAMPO", "RELATORIO", "ADMINISTRATIVO"]
DATE_CONFIDENCE_OPTIONS = ["PLANEJADO", "CONFIRMADO", "CANCELADO"]

STATUS_DEFAULT = "PLANEJADA"
PLACEHOLDER_PERSON_NAME = "Profissional"


# ==========================================================
# Boot (ordem obrigatória)
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


def normalize_str(x) -> str:
    return ("" if x is None else str(x)).strip()


def safe_text_list(series: pd.Series, default: str = "") -> list[str]:
    out: list[str] = []
    for v in series.tolist():
        if v is None or (isinstance(v, float) and pd.isna(v)):
            out.append(default)
        else:
            s = str(v).strip()
            out.append("" if s in ("None", "nan", "NaT") else s)
    return out


def split_assignees(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[+,;]", str(text))
    out: list[str] = []
    for p in parts:
        n = p.strip()
        if n:
            out.append(n)
    return out


def rpc_delete_task(task_id: str) -> None:
    sb.rpc("rpc_delete_task", {"p_task_id": task_id}).execute()


def rpc_set_task_people(task_id: str, person_ids: list[str]) -> None:
    sb.rpc("rpc_set_task_people", {"p_task_id": task_id, "p_person_ids": person_ids}).execute()


# ==========================================================
# Loads
# ==========================================================
def _cache_key() -> str:
    return str(st.session_state.get("access_token") or "no-token")


@st.cache_data(ttl=30)
def load_projects(_k: str):
    res = sb.table("projects").select("id, project_code, name").order("project_code").execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return df
    df["label"] = (df["project_code"].fillna("").astype(str) + " — " + df["name"].fillna("").astype(str)).str.strip(" —")
    return df


@st.cache_data(ttl=30)
def load_people(_k: str):
    try:
        res = sb.table("people").select("id, name, active").order("name").execute()
        df = pd.DataFrame(res.data or [])
        if not df.empty and "active" in df.columns:
            df = df[df["active"] == True]  # noqa: E712
    except Exception:
        res = sb.table("people").select("id, name").order("name").execute()
        df = pd.DataFrame(res.data or [])

    if df.empty:
        return df, {}, {}

    df["name"] = df["name"].astype(str)
    name_to_id = dict(zip(df["name"], df["id"]))
    id_to_name = dict(zip(df["id"], df["name"]))
    return df, name_to_id, id_to_name


@st.cache_data(ttl=30)
def load_tasks_for_project(_k: str, project_id: str):
    # tenta puxar assignee_id (se a view tiver). se não tiver, faz fallback.
    cols_with_lead = "task_id, project_id, title, tipo_atividade, start_date, end_date, date_confidence, status, assignee_names, assignee_id, notes"
    cols_fallback = "task_id, project_id, title, tipo_atividade, start_date, end_date, date_confidence, status, assignee_names, notes"

    try:
        res = (
            sb.table("v_portfolio_tasks")
            .select(cols_with_lead)
            .eq("project_id", project_id)
            .order("start_date")
            .execute()
        )
        return pd.DataFrame(res.data or [])
    except Exception:
        res = (
            sb.table("v_portfolio_tasks")
            .select(cols_fallback)
            .eq("project_id", project_id)
            .order("start_date")
            .execute()
        )
        df = pd.DataFrame(res.data or [])
        if not df.empty and "assignee_id" not in df.columns:
            df["assignee_id"] = None
        return df


def refresh_tasks_cache():
    load_tasks_for_project.clear()


# ==========================================================
# Projeto
# ==========================================================
k = _cache_key()
df_projects = load_projects(k)
if df_projects.empty:
    st.warning("Nenhum projeto encontrado. Crie um projeto antes.")
    st.stop()

selected_label = st.selectbox("Projeto", df_projects["label"].tolist(), index=0)
project_id = df_projects.loc[df_projects["label"] == selected_label, "id"].iloc[0]

df_people, people_map, id_to_name = load_people(k)
if df_people.empty:
    st.warning("Tabela people está vazia.")
    st.stop()

if PLACEHOLDER_PERSON_NAME not in people_map:
    st.error(f"Não achei '{PLACEHOLDER_PERSON_NAME}' na tabela people. Crie esse registro antes.")
    st.stop()

placeholder_id = people_map[PLACEHOLDER_PERSON_NAME]
people_names = sorted(list(people_map.keys()))


# ==========================================================
# Nova tarefa (responsáveis por seleção)
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

    st.caption("✅ Responsáveis agora são sempre escolhidos da lista (people).")
    c7, c8 = st.columns([1.2, 2.8])
    with c7:
        lead_name = st.selectbox("Responsável principal (Lead)", people_names, index=people_names.index(PLACEHOLDER_PERSON_NAME))
    with c8:
        co_names = st.multiselect(
            "Co-responsáveis (opcional)",
            options=people_names,
            default=[],
            help="Você pode escolher mais de um. O Lead sempre será incluído.",
        )

    notes = st.text_area("Observações", value="", height=90)

    if st.button("Criar tarefa", type="primary"):
        if not title.strip():
            st.error("Informe um título.")
            st.stop()
        if end_date < start_date:
            st.error("Fim não pode ser menor que Início.")
            st.stop()

        try:
            lead_id = people_map.get(lead_name) or placeholder_id

            # ids únicos, com lead primeiro
            person_ids = [lead_id]
            for n in co_names:
                pid = people_map.get(n)
                if pid and pid not in person_ids:
                    person_ids.append(pid)

            payload = {
                "project_id": project_id,
                "title": title.strip(),
                "tipo_atividade": tipo,
                "assignee_id": lead_id,  # lead
                "status": STATUS_DEFAULT,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "date_confidence": date_conf,
                "notes": (notes or "").strip() or None,
            }

            ins = sb.table("tasks").insert(payload).execute()
            new_id = ins.data[0]["id"]

            # relação N:N
            rpc_set_task_people(new_id, person_ids)

            st.success("Tarefa criada com sucesso.")
            refresh_tasks_cache()
            st.rerun()

        except Exception as e:
            st.error("Erro ao criar tarefa:")
            st.code(_api_error_message(e))


# ==========================================================
# Lista (INLINE) + Box de edição de responsáveis
# ==========================================================
st.divider()
st.subheader("Lista de tarefas (edite direto aqui)")
st.caption("✅ Edite na tabela e clique em **Salvar alterações**. Para excluir, use o bloco vermelho abaixo.")
st.caption("👤 **Responsáveis:** no inline você edita apenas o **Lead** (dropdown). Co-responsáveis são editados no box abaixo.")

df_tasks = load_tasks_for_project(k, project_id)
if df_tasks.empty:
    st.info("Sem tarefas nesse projeto.")
    st.stop()

# garante colunas
for col, default in [
    ("assignee_names", PLACEHOLDER_PERSON_NAME),
    ("assignee_id", None),
    ("notes", ""),
]:
    if col not in df_tasks.columns:
        df_tasks[col] = default

# função para achar lead-name com fallback
def _lead_name_row(assignee_id, assignee_names_text: str) -> str:
    if assignee_id and assignee_id in id_to_name:
        return id_to_name[assignee_id]
    parts = split_assignees(assignee_names_text or "")
    if parts:
        # se o primeiro nome existir em people, usa ele
        if parts[0] in people_map:
            return parts[0]
        return parts[0]
    return PLACEHOLDER_PERSON_NAME


ids = safe_text_list(df_tasks["task_id"])

df_show = pd.DataFrame(
    {
        "Excluir?": [False] * len(df_tasks),
        "Tarefa": safe_text_list(df_tasks["title"]),
        "Tipo": safe_text_list(df_tasks["tipo_atividade"]),
        "Lead": [
            _lead_name_row(aid, an)
            for aid, an in zip(df_tasks["assignee_id"].tolist(), safe_text_list(df_tasks["assignee_names"], PLACEHOLDER_PERSON_NAME))
        ],
        "Responsável(is)": [x or PLACEHOLDER_PERSON_NAME for x in safe_text_list(df_tasks["assignee_names"], PLACEHOLDER_PERSON_NAME)],
        "Início": [to_date(x) for x in df_tasks["start_date"].tolist()],
        "Fim": [to_date(x) for x in df_tasks["end_date"].tolist()],
        "Status da data": [x or "PLANEJADO" for x in safe_text_list(df_tasks["date_confidence"])],
        "Obs": safe_text_list(df_tasks["notes"]),
    },
    index=ids,
)

edited = st.data_editor(
    df_show,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "Excluir?": st.column_config.CheckboxColumn("Excluir?", width="small", help="Marque para excluir."),
        "Tarefa": st.column_config.TextColumn(width="large"),
        "Tipo": st.column_config.SelectboxColumn(options=TIPO_OPTIONS, width="medium"),
        "Lead": st.column_config.SelectboxColumn(options=people_names, width="medium", help="Responsável principal (Lead)"),
        "Responsável(is)": st.column_config.TextColumn(
            width="large",
            disabled=True,
            help="Exibição apenas. Para editar co-responsáveis use o box abaixo.",
        ),
        "Início": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Fim": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Status da data": st.column_config.SelectboxColumn(options=DATE_CONFIDENCE_OPTIONS, width="medium"),
        "Obs": st.column_config.TextColumn(width="large"),
    },
)

to_delete_ids = edited.index[edited["Excluir?"] == True].astype(str).tolist()  # noqa: E712

if to_delete_ids:
    with st.container(border=True):
        st.error(f"🗑 Exclusão: você marcou **{len(to_delete_ids)}** tarefa(s).")
        titles = edited.loc[to_delete_ids, "Tarefa"].astype(str).tolist()
        st.write("**Tarefas marcadas:**")
        st.write("\n".join([f"- {t}" for t in titles if t and t != "None"]))

        confirm_delete = st.checkbox("Confirmo a exclusão definitiva das tarefas marcadas", value=False)

        colx1, colx2 = st.columns([1, 2])
        delete_now = colx1.button("Excluir marcadas agora", type="primary", disabled=not confirm_delete)
        colx2.caption("Dica: desmarque o checkbox na tabela para cancelar a exclusão.")

        if delete_now:
            try:
                for tid in to_delete_ids:
                    rpc_delete_task(tid)
                st.success(f"Excluídas: {len(to_delete_ids)}")
                refresh_tasks_cache()
                st.rerun()
            except Exception as e:
                st.error("Erro ao excluir:")
                st.code(_api_error_message(e))

st.divider()

# ==========================================================
# Box: editar responsáveis (Lead + Co) por seleção
# ==========================================================
with st.container(border=True):
    st.subheader("Editar responsáveis (por seleção)")
    st.caption("Aqui você ajusta **Lead + co-responsáveis** sem digitar nada.")

    # lista de tarefas para escolher
    task_labels = []
    task_id_by_label = {}
    for tid, title_txt in zip(ids, safe_text_list(df_tasks["title"])):
        lbl = f"{tid[:8]} — {title_txt or 'Sem título'}"
        task_labels.append(lbl)
        task_id_by_label[lbl] = tid

    pick = st.selectbox("Selecione a tarefa", task_labels, index=0)
    picked_task_id = task_id_by_label[pick]

    # estado atual (a partir da view)
    row = df_tasks.loc[df_tasks["task_id"].astype(str) == str(picked_task_id)].iloc[0]
    current_assignees_text = normalize_str(row.get("assignee_names") or PLACEHOLDER_PERSON_NAME)
    current_names = split_assignees(current_assignees_text) or [PLACEHOLDER_PERSON_NAME]
    # garante que existam em people (se algum não existir, ignora no default)
    current_names = [n for n in current_names if n in people_map] or [PLACEHOLDER_PERSON_NAME]

    default_lead = _lead_name_row(row.get("assignee_id"), current_assignees_text)
    if default_lead not in people_map:
        default_lead = PLACEHOLDER_PERSON_NAME

    cA, cB = st.columns([1.2, 2.8])
    with cA:
        edit_lead_name = st.selectbox(
            "Lead",
            options=people_names,
            index=people_names.index(default_lead),
            key="edit_lead_name",
        )
    with cB:
        # co = atuais menos lead
        default_cos = [n for n in current_names if n != default_lead]
        edit_cos = st.multiselect(
            "Co-responsáveis",
            options=people_names,
            default=default_cos,
            key="edit_cos",
        )

    if st.button("Salvar responsáveis desta tarefa", type="primary"):
        try:
            lead_id = people_map.get(edit_lead_name) or placeholder_id
            ids_unique = [lead_id]
            for n in edit_cos:
                pid = people_map.get(n)
                if pid and pid not in ids_unique:
                    ids_unique.append(pid)

            # 1) atualizar lead na task
            sb.table("tasks").update({"assignee_id": lead_id}).eq("id", str(picked_task_id)).execute()

            # 2) atualizar relação N:N
            rpc_set_task_people(str(picked_task_id), ids_unique)

            st.success("Responsáveis atualizados.")
            refresh_tasks_cache()
            st.rerun()
        except Exception as e:
            st.error("Erro ao salvar responsáveis:")
            st.code(_api_error_message(e))


# ==========================================================
# Salvar alterações INLINE (lead + campos simples)
# ==========================================================
cbtn1, cbtn2 = st.columns([1, 1])
save_inline = cbtn1.button("Salvar alterações", type="primary")
reload_inline = cbtn2.button("Recarregar")

if reload_inline:
    refresh_tasks_cache()
    st.rerun()

if save_inline:
    try:
        before = df_show.copy()
        after = edited.copy()

        after_updates = after[after["Excluir?"] != True].copy()  # noqa: E712
        before_updates = before.loc[after_updates.index].copy()

        compare_cols = ["Tarefa", "Tipo", "Lead", "Início", "Fim", "Status da data", "Obs"]
        n_updates = 0
        warnings: list[str] = []

        for task_id, ra in after_updates.iterrows():
            rb = before_updates.loc[task_id]

            changed = False
            for c in compare_cols:
                if normalize_str(rb[c]) != normalize_str(ra[c]):
                    changed = True
                    break
            if not changed:
                continue

            start_v = ra["Início"]
            end_v = ra["Fim"]
            if start_v and end_v and end_v < start_v:
                warnings.append(f"Tarefa {normalize_str(ra['Tarefa'])}: 'Fim' menor que 'Início' (ignorado).")
                continue

            lead_name_new = normalize_str(ra["Lead"]) or PLACEHOLDER_PERSON_NAME
            lead_id_new = people_map.get(lead_name_new) or placeholder_id

            update_payload = {
                "title": normalize_str(ra["Tarefa"]) or "Sem título",
                "tipo_atividade": normalize_str(ra["Tipo"]) or TIPO_OPTIONS[0],
                "assignee_id": lead_id_new,  # LEAD via dropdown
                "start_date": start_v.isoformat() if start_v else None,
                "end_date": end_v.isoformat() if end_v else None,
                "date_confidence": normalize_str(ra["Status da data"]) or DATE_CONFIDENCE_OPTIONS[0],
                "notes": normalize_str(ra["Obs"]) or None,
            }

            sb.table("tasks").update(update_payload).eq("id", str(task_id)).execute()
            n_updates += 1

        if warnings:
            st.warning("\n".join(warnings))

        st.success(f"Atualizadas: {n_updates}")
        refresh_tasks_cache()
        st.rerun()

    except Exception as e:
        st.error("Erro ao salvar alterações:")
        st.code(_api_error_message(e))





