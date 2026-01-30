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


def join_assignees(names: list[str]) -> str:
    names = [normalize_str(n) for n in names if normalize_str(n)]
    return " + ".join(names) if names else ""


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

    # normaliza nomes (strip) para mapear
    df["name"] = df["name"].astype(str).str.strip()

    name_to_id = dict(zip(df["name"], df["id"]))
    id_to_name = dict(zip(df["id"], df["name"]))
    return df, name_to_id, id_to_name


@st.cache_data(ttl=30)
def load_tasks_for_project(_k: str, project_id: str):
    cols_try = "task_id, project_id, title, tipo_atividade, start_date, end_date, date_confidence, status, assignee_names, notes"
    res = (
        sb.table("v_portfolio_tasks")
        .select(cols_try)
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

df_people, people_map, id_to_people = load_people(k)
if df_people.empty:
    st.warning("Tabela people está vazia.")
    st.stop()

people_names_all = df_people["name"].astype(str).tolist()

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

    # ✅ troca: texto livre -> multiselect
    assignees_selected = st.multiselect(
        "Responsável(is)",
        options=people_names_all,
        default=[PLACEHOLDER_PERSON_NAME] if PLACEHOLDER_PERSON_NAME in people_names_all else [],
        help="Selecione 1 ou mais responsáveis (sem digitação).",
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
            names = [n.strip() for n in assignees_selected if n and n.strip()]
            if not names:
                names = [PLACEHOLDER_PERSON_NAME]

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
                "assignee_id": person_ids[0],  # lead
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

# garante colunas
for col, default in [
    ("assignee_names", PLACEHOLDER_PERSON_NAME),
    ("notes", ""),
]:
    if col not in df_tasks.columns:
        df_tasks[col] = default

# monta DF por LISTAS (sem alinhamento por índice)
ids = safe_text_list(df_tasks["task_id"])
df_show = pd.DataFrame(
    {
        "Excluir?": [False] * len(df_tasks),
        "Tarefa": safe_text_list(df_tasks["title"]),
        "Tipo": safe_text_list(df_tasks["tipo_atividade"]),
        # ⚠️ agora é somente exibição (edição via painel abaixo)
        "Responsável(is)": [x or PLACEHOLDER_PERSON_NAME for x in safe_text_list(df_tasks["assignee_names"])],
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
    disabled=["Responsável(is)"],  # ✅ evita digitação e erro
    column_config={
        "Excluir?": st.column_config.CheckboxColumn("Excluir?", width="small", help="Marque para excluir."),
        "Tarefa": st.column_config.TextColumn(width="large"),
        "Tipo": st.column_config.SelectboxColumn(options=TIPO_OPTIONS, width="medium"),
        "Responsável(is)": st.column_config.TextColumn(width="large", help="Edite no painel abaixo (seleção)."),
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
# Painel: edição de responsáveis por seleção (SEM digitação)
# ==========================================================
with st.container(border=True):
    st.subheader("Editar responsáveis (seleção)")

    st.caption("Selecione uma tarefa na lista abaixo e ajuste os responsáveis sem digitar.")

    # Seleciona uma tarefa (por label)
    task_options = [
        f"{tid} — {normalize_str(edited.loc[tid, 'Tarefa'])}" for tid in edited.index.astype(str).tolist()
    ]
    chosen_task = st.selectbox("Escolha a tarefa", task_options, index=0)
    chosen_task_id = chosen_task.split(" — ")[0].strip()

    # Default: tenta parsear string "A + B"
    current_text = normalize_str(edited.loc[chosen_task_id, "Responsável(is)"])
    current_names = split_assignees(current_text)
    # filtra para existentes (evita default com nome antigo errado)
    current_names = [n for n in current_names if n in people_map]
    if not current_names and PLACEHOLDER_PERSON_NAME in people_map:
        current_names = [PLACEHOLDER_PERSON_NAME]

    new_names = st.multiselect(
        "Responsáveis",
        options=people_names_all,
        default=current_names,
    )

    colp1, colp2 = st.columns([1, 3])
    save_people = colp1.button("Salvar responsáveis", type="primary")
    colp2.caption("A lista de responsáveis da tarefa será atualizada via RPC (task_people).")

    if save_people:
        try:
            names = [n.strip() for n in new_names if n and n.strip()]
            if not names:
                names = [PLACEHOLDER_PERSON_NAME]

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

            # ✅ Atualiza lead (assignee_id) e pessoas
            sb.table("tasks").update({"assignee_id": person_ids[0]}).eq("id", chosen_task_id).execute()
            rpc_set_task_people(chosen_task_id, person_ids)

            st.success("Responsáveis atualizados.")
            refresh_tasks_cache()
            st.rerun()
        except Exception as e:
            st.error("Erro ao salvar responsáveis:")
            st.code(_api_error_message(e))


# ==========================================================
# Botões salvar / recarregar (inline)
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

        compare_cols = ["Tarefa", "Tipo", "Início", "Fim", "Status da data", "Obs"]
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

            update_payload = {
                "title": normalize_str(ra["Tarefa"]) or "Sem título",
                "tipo_atividade": normalize_str(ra["Tipo"]) or TIPO_OPTIONS[0],
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





