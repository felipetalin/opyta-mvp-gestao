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


def safe_text_series(s: pd.Series) -> pd.Series:
    # evita "None" e "nan" virarem texto
    return s.fillna("").astype(str).replace({"None": "", "nan": "", "NaT": ""})


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
    df["label"] = (df["project_code"].fillna("").astype(str) + " — " + df["name"].fillna("").astype(str)).str.strip(
        " —"
    )
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

    name_to_id = dict(zip(df["name"], df["id"]))
    return df, name_to_id, dict(zip(df["id"], df["name"]))


@st.cache_data(ttl=30)
def load_tasks_for_project(_k: str, project_id: str):
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

df_people, people_map, _ = load_people(k)
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

    if st.button("Criar tarefa", type="primary"):
        if not title.strip():
            st.error("Informe um título.")
            st.stop()
        if end_date < start_date:
            st.error("Fim não pode ser menor que Início.")
            st.stop()

        try:
            names = split_assignees(assignees_text) or [PLACEHOLDER_PERSON_NAME]

            person_ids: list[str] = []
            unknown: list[str] = []
            for n in names:
                pid = people_map.get(n)
                if pid:
                    person_ids.append(pid)
                else:
                    unknown.append(n)

            if unknown:
                st.error("Responsáveis não cadastrados:\n" + "\n".join([f"- {x}" for x in unknown]))
                st.stop()

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

            rpc_set_task_people(new_id, person_ids)

            st.success("Tarefa criada com sucesso.")
            refresh_tasks_cache()
            st.rerun()

        except Exception as e:
            st.error("Erro ao criar tarefa:")
            st.code(_api_error_message(e))


# ==========================================================
# Lista (A2)
# ==========================================================
st.divider()
st.subheader("Lista de tarefas (edite direto aqui)")
st.caption("✅ Edite na tabela e clique em **Salvar alterações**. Para excluir, use o bloco vermelho abaixo.")

df_tasks = load_tasks_for_project(k, project_id)
if df_tasks.empty:
    st.info("Sem tarefas nesse projeto.")
    st.stop()

df_tasks = df_tasks.copy()
df_tasks.rename(columns={"task_id": "ID"}, inplace=True)

if "assignee_names" not in df_tasks.columns:
    df_tasks["assignee_names"] = PLACEHOLDER_PERSON_NAME
if "notes" not in df_tasks.columns:
    df_tasks["notes"] = ""

df_show = pd.DataFrame(
    {
        "Excluir?": False,
        "Tarefa": safe_text_series(df_tasks.get("title", pd.Series([], dtype=object))),
        "Tipo": safe_text_series(df_tasks.get("tipo_atividade", pd.Series([], dtype=object))),
        "Responsável(is)": safe_text_series(df_tasks.get("assignee_names", pd.Series([], dtype=object))).replace(
            {"": PLACEHOLDER_PERSON_NAME}
        ),
        "Início": df_tasks["start_date"].apply(to_date) if "start_date" in df_tasks.columns else None,
        "Fim": df_tasks["end_date"].apply(to_date) if "end_date" in df_tasks.columns else None,
        "Status da data": safe_text_series(df_tasks.get("date_confidence", pd.Series([], dtype=object))).replace(
            {"": "PLANEJADO"}
        ),
        "Obs": safe_text_series(df_tasks.get("notes", pd.Series([], dtype=object))),
    },
    index=safe_text_series(df_tasks["ID"]).replace({"": "SEM_ID"}) if "ID" in df_tasks.columns else None,
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
        "Responsável(is)": st.column_config.TextColumn(width="large", help="Use ' + ' para múltiplos."),
        "Início": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Fim": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Status da data": st.column_config.SelectboxColumn(options=DATE_CONFIDENCE_OPTIONS, width="medium"),
        "Obs": st.column_config.TextColumn(width="large"),
    },
)

to_delete_ids = edited.index[edited["Excluir?"] == True].astype(str).tolist()  # noqa: E712
to_delete_ids = [x for x in to_delete_ids if x and x != "SEM_ID"]

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

        compare_cols = ["Tarefa", "Tipo", "Responsável(is)", "Início", "Fim", "Status da data", "Obs"]
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

            names = split_assignees(normalize_str(ra["Responsável(is)"])) or [PLACEHOLDER_PERSON_NAME]

            unknown: list[str] = []
            person_ids: list[str] = []
            for n in names:
                pid = people_map.get(n)
                if pid:
                    person_ids.append(pid)
                else:
                    unknown.append(n)

            if unknown:
                warnings.append(
                    f"Tarefa {normalize_str(ra['Tarefa'])}: responsáveis não cadastrados (responsáveis NÃO foram salvos): "
                    + ", ".join(unknown)
                )
            else:
                if not person_ids:
                    person_ids = [placeholder_id]

            update_payload = {
                "title": normalize_str(ra["Tarefa"]) or "Sem título",
                "tipo_atividade": normalize_str(ra["Tipo"]) or TIPO_OPTIONS[0],
                "start_date": start_v.isoformat() if start_v else None,
                "end_date": end_v.isoformat() if end_v else None,
                "date_confidence": normalize_str(ra["Status da data"]) or DATE_CONFIDENCE_OPTIONS[0],
                "notes": normalize_str(ra["Obs"]) or None,
            }

            sb.table("tasks").update(update_payload).eq("id", str(task_id)).execute()

            if not unknown:
                rpc_set_task_people(str(task_id), person_ids)

            n_updates += 1

        if warnings:
            st.warning("\n".join(warnings))

        st.success(f"Atualizadas: {n_updates}")
        refresh_tasks_cache()
        st.rerun()

    except Exception as e:
        st.error("Erro ao salvar alterações:")
        st.code(_api_error_message(e))




