# app/pages/3_Tarefas.py

import re
from datetime import date, timedelta
from io import BytesIO

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

try:
    from ui.layout import filter_bar_start
except Exception:

    def filter_bar_start():  # type: ignore
        return st.container(border=True)


TIPO_OPTIONS = ["CAMPO", "RELATORIO", "ADMINISTRATIVO"]
DATE_CONFIDENCE_OPTIONS = ["PLANEJADO", "CONFIRMADO", "CANCELADO"]
SITUACAO_OPTIONS = ["Atrasada", "Hoje", "Em andamento", "Próxima", "Confirmada", "Planejada", "Cancelada", "Sem data"]
SITUACAO_PRIORITY = {s: i for i, s in enumerate(SITUACAO_OPTIONS)}
PROXIMO_DIAS = 7

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


def month_range(d: date) -> tuple[date, date]:
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1, day=1)
    else:
        nxt = first.replace(month=first.month + 1, day=1)
    return first, nxt - timedelta(days=1)


def shift_month_first(d: date, delta: int) -> date:
    y = d.year
    m = d.month + delta
    while m > 12:
        y += 1
        m -= 12
    while m < 1:
        y -= 1
        m += 12
    return date(y, m, 1)


def month_label(d: date) -> str:
    meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    return f"{meses[d.month - 1]}/{d.year}"


def normalize_option(value: str, options: list[str], default: str) -> str:
    value_norm = normalize_str(value).upper()
    return value_norm if value_norm in options else default


def period_presets(today: date) -> list[tuple[str, date | None, date | None]]:
    cur_first = shift_month_first(today, 0)
    prev_first = shift_month_first(today, -1)
    cur_start, cur_end = month_range(cur_first)
    prev_start, _ = month_range(prev_first)
    return [
        ("Tudo", None, None),
        (f"Mês atual ({month_label(cur_first)})", cur_start, cur_end),
        ("Próximos 30 dias", today, today + timedelta(days=30)),
        (f"Mês anterior + atual ({month_label(prev_first)} + {month_label(cur_first)})", prev_start, cur_end),
    ]


def task_situation(start_v: date | None, end_v: date | None, date_confidence: str, status: str, today: date) -> str:
    conf = normalize_str(date_confidence).upper()
    task_status = normalize_str(status).upper()
    if conf == "CANCELADO" or task_status in {"CANCELADA", "CANCELADO", "CANCELLED"}:
        return "Cancelada"
    if not start_v and not end_v:
        return "Sem data"

    ref_start = start_v or end_v
    ref_end = end_v or start_v
    if ref_start is None or ref_end is None:
        return "Sem data"

    if ref_end < today:
        return "Atrasada"
    if ref_start <= today <= ref_end:
        return "Hoje" if ref_start == ref_end == today else "Em andamento"
    if 0 <= (ref_start - today).days <= PROXIMO_DIAS:
        return "Próxima"
    if conf == "CONFIRMADO":
        return "Confirmada"
    return "Planejada"


def format_days(end_v: date | None, situation: str, today: date) -> str:
    if not end_v or situation in {"Cancelada", "Sem data"}:
        return ""
    delta = (end_v - today).days
    if delta < 0:
        return f"{abs(delta)}d atraso"
    if delta == 0:
        return "Hoje"
    return f"+{delta}d"


def task_overlaps_window(start_v: date | None, end_v: date | None, p_start: date, p_end: date) -> bool:
    if not start_v and not end_v:
        return False
    ref_start = start_v or end_v
    ref_end = end_v or start_v
    if ref_start is None or ref_end is None:
        return False
    return ref_start <= p_end and ref_end >= p_start


def update_task(task_id: str, payload: dict) -> None:
    patch = dict(payload)
    patch["updated_at"] = pd.Timestamp.utcnow().isoformat()
    try:
        sb.table("tasks").update(patch).eq("id", str(task_id)).execute()
    except Exception as e:
        msg = _api_error_message(e).lower()
        if "updated_at" not in msg:
            raise
        patch.pop("updated_at", None)
        sb.table("tasks").update(patch).eq("id", str(task_id)).execute()


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
with st.spinner("Carregando dados..."):
    df_projects = load_projects(k)
    df_people, people_map, id_to_name = load_people(k)
if df_projects.empty:
    st.warning("Nenhum projeto encontrado. Crie um projeto antes.")
    st.stop()

selected_label = st.selectbox("Projeto", df_projects["label"].tolist(), index=0)
project_id = df_projects.loc[df_projects["label"] == selected_label, "id"].iloc[0]

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
st.caption("Edite na tabela e clique em **Salvar alterações**. Para excluir, use o bloco vermelho abaixo.")
st.caption("Responsáveis: no inline você edita o **Lead**. O app preserva os co-responsáveis e sincroniza a relação N:N.")

df_tasks = load_tasks_for_project(k, project_id)
if df_tasks.empty:
    st.info("Sem tarefas nesse projeto.")
    st.stop()

# garante colunas
for col, default in [
    ("title", ""),
    ("tipo_atividade", TIPO_OPTIONS[0]),
    ("start_date", None),
    ("end_date", None),
    ("date_confidence", DATE_CONFIDENCE_OPTIONS[0]),
    ("status", STATUS_DEFAULT),
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


today = date.today()
df_tasks["__lead_name"] = [
    _lead_name_row(aid, an)
    for aid, an in zip(df_tasks["assignee_id"].tolist(), safe_text_list(df_tasks["assignee_names"], PLACEHOLDER_PERSON_NAME))
]
df_tasks["__start"] = [to_date(x) for x in df_tasks["start_date"].tolist()]
df_tasks["__end"] = [to_date(x) for x in df_tasks["end_date"].tolist()]
df_tasks["__date_confidence"] = [
    normalize_option(x, DATE_CONFIDENCE_OPTIONS, DATE_CONFIDENCE_OPTIONS[0])
    for x in safe_text_list(df_tasks["date_confidence"], DATE_CONFIDENCE_OPTIONS[0])
]
df_tasks["__situacao"] = [
    task_situation(start_v, end_v, conf, status, today)
    for start_v, end_v, conf, status in zip(
        df_tasks["__start"].tolist(),
        df_tasks["__end"].tolist(),
        df_tasks["__date_confidence"].tolist(),
        safe_text_list(df_tasks["status"], STATUS_DEFAULT),
    )
]
df_tasks["__days"] = [
    format_days(end_v, sit, today)
    for end_v, sit in zip(df_tasks["__end"].tolist(), df_tasks["__situacao"].tolist())
]
df_tasks["__sit_priority"] = df_tasks["__situacao"].map(SITUACAO_PRIORITY).fillna(99).astype(int)

types_all = sorted({t for t in safe_text_list(df_tasks["tipo_atividade"]) if t})
people_all = sorted(
    {
        name
        for names in safe_text_list(df_tasks["assignee_names"], PLACEHOLDER_PERSON_NAME)
        for name in split_assignees(names)
        if name
    }
)
conf_all = [x for x in DATE_CONFIDENCE_OPTIONS if x in set(df_tasks["__date_confidence"].tolist())]
sit_all = [x for x in SITUACAO_OPTIONS if x in set(df_tasks["__situacao"].tolist())]

SORT_OPTIONS = {
    "Situação": ("__sit_priority", True),
    "Início (mais próximo)": ("__start", True),
    "Fim (mais próximo)": ("__end", True),
    "Tarefa (A-Z)": ("title", True),
    "Lead (A-Z)": ("__lead_name", True),
    "Tipo": ("tipo_atividade", True),
}

with filter_bar_start():
    fc1, fc2, fc3 = st.columns([2.4, 1.4, 1.6])
    with fc1:
        search = st.text_input(
            "Buscar",
            value="",
            placeholder="Tarefa, responsável, tipo ou observação...",
        )
    with fc2:
        sort_label = st.selectbox("Ordenar por", list(SORT_OPTIONS.keys()), index=0)
    with fc3:
        presets = period_presets(today)
        period_label = st.selectbox("Período", [p[0] for p in presets], index=0)

    ff1, ff2, ff3, ff4 = st.columns([1.2, 1.6, 1.4, 1.4])
    with ff1:
        f_types = st.multiselect("Tipo", types_all, default=[])
    with ff2:
        f_people = st.multiselect("Responsável", people_all, default=[])
    with ff3:
        f_conf = st.multiselect("Status da data", conf_all, default=[])
    with ff4:
        f_sit = st.multiselect("Situação", sit_all, default=[])

    fx1, fx2, _ = st.columns([1.2, 1.2, 3])
    with fx1:
        hide_cancelled = st.checkbox("Ocultar canceladas", value=True)
    with fx2:
        include_undated = st.checkbox("Incluir sem data", value=True)

mask = pd.Series(True, index=df_tasks.index)
if f_types:
    mask &= df_tasks["tipo_atividade"].isin(f_types)
if f_people:
    mask &= df_tasks["assignee_names"].apply(lambda names: any(p in split_assignees(names) for p in f_people))
if f_conf:
    mask &= df_tasks["__date_confidence"].isin(f_conf)
if f_sit:
    mask &= df_tasks["__situacao"].isin(f_sit)
if hide_cancelled:
    mask &= df_tasks["__situacao"] != "Cancelada"

p_start, p_end = next((p[1], p[2]) for p in presets if p[0] == period_label)
if p_start is not None and p_end is not None:
    in_window = df_tasks.apply(lambda r: task_overlaps_window(r["__start"], r["__end"], p_start, p_end), axis=1)
    if include_undated:
        in_window = in_window | df_tasks["__situacao"].eq("Sem data")
    mask &= in_window
elif not include_undated:
    mask &= df_tasks["__situacao"] != "Sem data"

if search.strip():
    q = search.strip().lower()
    haystack = (
        df_tasks["title"].fillna("").astype(str).str.lower() + " | "
        + df_tasks["tipo_atividade"].fillna("").astype(str).str.lower() + " | "
        + df_tasks["assignee_names"].fillna("").astype(str).str.lower() + " | "
        + df_tasks["notes"].fillna("").astype(str).str.lower()
    )
    mask &= haystack.str.contains(q, na=False, regex=False)

df_view = df_tasks.loc[mask].copy()
sort_col, sort_asc = SORT_OPTIONS[sort_label]
if sort_col in df_view.columns and not df_view.empty:
    df_view = df_view.sort_values(by=sort_col, ascending=sort_asc, na_position="last").copy()

n_atrasadas = int((df_view["__situacao"] == "Atrasada").sum())
n_hoje = int((df_view["__situacao"].isin(["Hoje", "Em andamento"])).sum())
n_proximas = int((df_view["__situacao"] == "Próxima").sum())
n_confirmadas = int((df_view["__date_confidence"] == "CONFIRMADO").sum())
n_canceladas = int((df_view["__situacao"] == "Cancelada").sum())

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Total exibido", len(df_view))
m2.metric("Atrasadas", n_atrasadas)
m3.metric("Hoje / andamento", n_hoje)
m4.metric("Próximas", n_proximas)
m5.metric("Confirmadas", n_confirmadas)
m6.metric("Canceladas", n_canceladas)

if df_view.empty:
    st.info(
        f"Nenhuma tarefa corresponde aos filtros/busca atuais. Existem **{len(df_tasks)}** tarefa(s) nesse projeto."
    )
    st.stop()


def _build_export_df(_df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Tarefa": safe_text_list(_df["title"]),
            "Tipo": safe_text_list(_df["tipo_atividade"]),
            "Situação": safe_text_list(_df["__situacao"]),
            "Lead": safe_text_list(_df["__lead_name"]),
            "Responsável(is)": [x or PLACEHOLDER_PERSON_NAME for x in safe_text_list(_df["assignee_names"], PLACEHOLDER_PERSON_NAME)],
            "Início": _df["__start"].tolist(),
            "Fim": _df["__end"].tolist(),
            "Dias": safe_text_list(_df["__days"]),
            "Status da data": safe_text_list(_df["__date_confidence"]),
            "Obs": safe_text_list(_df["notes"]),
        }
    )


export_df = _build_export_df(df_view)
csv_bytes = export_df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
xc1, xc2, _ = st.columns([1.2, 1.2, 4])
xc1.download_button(
    "Exportar CSV",
    data=csv_bytes,
    file_name=f"tarefas_{today.isoformat()}.csv",
    mime="text/csv",
)
try:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Tarefas")
    xc2.download_button(
        "Exportar Excel",
        data=buf.getvalue(),
        file_name=f"tarefas_{today.isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
except Exception:
    pass

ids = safe_text_list(df_view["task_id"])

df_show = pd.DataFrame(
    {
        "Excluir?": [False] * len(df_view),
        "Situação": safe_text_list(df_view["__situacao"]),
        "Tarefa": safe_text_list(df_view["title"]),
        "Tipo": safe_text_list(df_view["tipo_atividade"]),
        "Lead": safe_text_list(df_view["__lead_name"], PLACEHOLDER_PERSON_NAME),
        "Responsável(is)": [x or PLACEHOLDER_PERSON_NAME for x in safe_text_list(df_view["assignee_names"], PLACEHOLDER_PERSON_NAME)],
        "Início": df_view["__start"].tolist(),
        "Fim": df_view["__end"].tolist(),
        "Dias": safe_text_list(df_view["__days"]),
        "Status da data": safe_text_list(df_view["__date_confidence"], DATE_CONFIDENCE_OPTIONS[0]),
        "Obs": safe_text_list(df_view["notes"]),
    },
    index=ids,
)

_editor_signature = abs(
    hash(
        (
            selected_label,
            tuple(ids),
            search.strip(),
            sort_label,
            period_label,
            tuple(f_types),
            tuple(f_people),
            tuple(f_conf),
            tuple(f_sit),
            hide_cancelled,
            include_undated,
        )
    )
)

edited = st.data_editor(
    df_show,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    key=f"tasks_editor_{_editor_signature}",
    column_config={
        "Excluir?": st.column_config.CheckboxColumn("Excluir?", width="small", help="Marque para excluir."),
        "Situação": st.column_config.TextColumn(disabled=True, width="medium"),
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
        "Dias": st.column_config.TextColumn(disabled=True, width="small"),
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
    for tid, title_txt in zip(ids, safe_text_list(df_view["title"])):
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
            update_task(str(picked_task_id), {"assignee_id": lead_id})

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
            lead_changed = normalize_str(rb["Lead"]) != lead_name_new

            update_payload = {
                "title": normalize_str(ra["Tarefa"]) or "Sem título",
                "tipo_atividade": normalize_option(ra["Tipo"], TIPO_OPTIONS, TIPO_OPTIONS[0]),
                "assignee_id": lead_id_new,  # LEAD via dropdown
                "start_date": start_v.isoformat() if start_v else None,
                "end_date": end_v.isoformat() if end_v else None,
                "date_confidence": normalize_option(ra["Status da data"], DATE_CONFIDENCE_OPTIONS, DATE_CONFIDENCE_OPTIONS[0]),
                "notes": normalize_str(ra["Obs"]) or None,
            }

            update_task(str(task_id), update_payload)
            if lead_changed:
                old_lead_name = normalize_str(rb["Lead"])
                current_names = [
                    n
                    for n in split_assignees(normalize_str(rb["Responsável(is)"]))
                    if n in people_map and n != PLACEHOLDER_PERSON_NAME
                ]
                keep_cos = [n for n in current_names if n not in {old_lead_name, lead_name_new}]
                person_ids = [lead_id_new]
                for n in keep_cos:
                    pid = people_map.get(n)
                    if pid and pid not in person_ids:
                        person_ids.append(pid)
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





