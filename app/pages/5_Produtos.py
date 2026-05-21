# app/pages/5_Produtos.py
"""
Acompanhamento operacional de Produtos / Entregas.

Reaproveita tarefas com tipo_atividade='RELATORIO' (cadastradas na aba Tarefas)
e adiciona uma camada de controle via task_delivery_tracking + timeline em
task_delivery_events. Nenhum cadastro novo de produto é feito aqui.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from services.auth import require_login
from services.supabase_client import get_authed_client

# Branding
try:
    from ui.brand import apply_brand, apply_app_chrome, page_header
except Exception:  # pragma: no cover
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
# Boot
# ==========================================================
st.set_page_config(page_title="Produtos", layout="wide")
apply_brand()
apply_app_chrome()

require_login()
sb = get_authed_client()
cache_key = str(st.session_state.get("access_token") or "no-token")

page_header(
    "Produtos & Entregas",
    "Acompanhamento operacional dos relatórios cadastrados em Tarefas",
    st.session_state.get("user_email", ""),
)


DELIVERY_STATUS_OPTIONS = [
    "NAO_INICIADO",
    "EM_ELABORACAO",
    "EM_REVISAO",
    "ENTREGUE",
    "FATURADO",
]
STATUS_LABEL = {
    "NAO_INICIADO":  "⚪ Não iniciado",
    "EM_ELABORACAO": "🟡 Em elaboração",
    "EM_REVISAO":    "🟠 Em revisão",
    "ENTREGUE":      "🟢 Entregue",
    "FATURADO":      "💰 Faturado",
}
LABEL_TO_STATUS = {v: k for k, v in STATUS_LABEL.items()}


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
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return None


def norm_text(x) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    if s in ("", "None", "nan", "NaT"):
        return None
    return s


def safe_text_list(series: pd.Series, default: str = "") -> list[str]:
    out: list[str] = []
    for v in series.tolist():
        if v is None or (isinstance(v, float) and pd.isna(v)):
            out.append(default)
        else:
            s = str(v).strip()
            out.append(default if s in ("None", "nan", "NaT") else s)
    return out


# ----- Helpers de período (espelho do Gantt) -----
def month_range(d: date) -> tuple[date, date]:
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1, day=1)
    else:
        nxt = first.replace(month=first.month + 1, day=1)
    return first, nxt - timedelta(days=1)


def shift_month_first(d: date, delta: int) -> date:
    y, m = d.year, d.month + delta
    while m > 12:
        y += 1; m -= 12
    while m < 1:
        y -= 1; m += 12
    return date(y, m, 1)


def month_label(d: date) -> str:
    meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    return f"{meses[d.month - 1]}/{d.year}"


# ==========================================================
# Loads
# ==========================================================
@st.cache_data(ttl=30)
def load_deliverables(_k: str) -> pd.DataFrame:
    res = (
        sb.table("v_deliverables")
        .select("*")
        .order("project_code")
        .order("end_date")
        .execute()
    )
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def load_events(_k: str, task_id: str) -> pd.DataFrame:
    res = (
        sb.table("task_delivery_events")
        .select("event_type,from_value,to_value,notes,changed_at")
        .eq("task_id", task_id)
        .order("changed_at", desc=True)
        .limit(50)
        .execute()
    )
    return pd.DataFrame(res.data or [])


def refresh():
    load_deliverables.clear()
    load_events.clear()


with st.spinner("Carregando produtos..."):
    df = load_deliverables(cache_key)

if df.empty:
    st.info(
        "Nenhum produto encontrado. Cadastre tarefas com tipo "
        "**RELATORIO** na aba Tarefas para que apareçam aqui."
    )
    st.stop()


# ==========================================================
# Filtros
# ==========================================================
projects_all = sorted({p for p in safe_text_list(df["project_code"]) if p})

# --- Atalhos de período (mesma lógica do Gantt) ---
today = date.today()
cur_first = shift_month_first(today, 0)
next_first = shift_month_first(today, 1)
prev_first = shift_month_first(today, -1)
next2_first = shift_month_first(today, 2)

cur_start, cur_end = month_range(cur_first)
next_start, next_end = month_range(next_first)
prev_start, _ = month_range(prev_first)
_, next2_end = month_range(next2_first)

period_presets: list[tuple[str, date | None, date | None]] = [
    (f"Mês atual ({month_label(cur_first)})", cur_start, cur_end),
    (f"Próximo mês ({month_label(next_first)})", next_start, next_end),
    (f"2 meses ({month_label(cur_first)} + {month_label(next_first)})", cur_start, next_end),
    (f"3 meses ({month_label(cur_first)} + {month_label(next2_first)})", cur_start, next2_end),
    (f"Mês anterior + atual ({month_label(prev_first)} + {month_label(cur_first)})", prev_start, cur_end),
    ("(manual)", None, None),
    ("Tudo", None, None),
]
period_labels = [p[0] for p in period_presets]
default_period_idx = 0  # Mês atual

fc1, fc2, fc3 = st.columns([1.6, 1.6, 1.2])
with fc1:
    f_projects = st.multiselect("Projeto", projects_all, default=[])
with fc2:
    f_status = st.multiselect(
        "Status",
        DELIVERY_STATUS_OPTIONS,
        default=[],
        format_func=lambda s: STATUS_LABEL.get(s, s),
    )
with fc3:
    only_pending = st.toggle("Apenas pendentes", value=False, help="Oculta ENTREGUE e FATURADO")

fc4, fc5, fc6 = st.columns([2.0, 1.2, 1.2])
with fc4:
    sel_period = st.selectbox(
        "Atalho (período pelo Prazo)",
        period_labels,
        index=default_period_idx,
        help="Filtra produtos cuja data de Prazo cai dentro do período.",
    )
with fc5:
    include_overdue = st.toggle(
        "Incluir atrasados",
        value=False,
        help="Mostra também produtos com Prazo vencido (não entregues/faturados), mesmo fora do período.",
    )
with fc6:
    include_undated = st.toggle(
        "Incluir sem prazo",
        value=False,
        help="Mostra produtos sem data de Prazo cadastrada.",
    )

# Resolução do período
chosen = next(p for p in period_presets if p[0] == sel_period)
if chosen[0] == "(manual)":
    period = st.date_input(
        "Período manual (Prazo)",
        value=(cur_start, cur_end),
        format="DD/MM/YYYY",
    )
    if isinstance(period, tuple) and len(period) == 2:
        p_start, p_end = period
    else:
        p_start, p_end = cur_start, cur_end
elif chosen[0] == "Tudo":
    p_start, p_end = None, None
else:
    p_start, p_end = chosen[1], chosen[2]
    st.caption(
        f"Período (Prazo): **{p_start.strftime('%d/%m/%Y')} – {p_end.strftime('%d/%m/%Y')}**"
    )

# --- Máscaras ---
mask = pd.Series(True, index=df.index)
if f_projects:
    mask &= df["project_code"].isin(f_projects)
if f_status:
    mask &= df["delivery_status"].isin(f_status)
if only_pending:
    mask &= ~df["delivery_status"].isin(["ENTREGUE", "FATURADO"])

# Filtro de período sobre end_date (Prazo) — com OR p/ atrasados e sem prazo
end_dates = pd.to_datetime(df["end_date"], errors="coerce").dt.date
if p_start is not None and p_end is not None:
    in_window = end_dates.between(p_start, p_end)
    extra = pd.Series(False, index=df.index)
    if include_overdue:
        overdue = (
            end_dates.notna()
            & (end_dates < today)
            & ~df["delivery_status"].isin(["ENTREGUE", "FATURADO"])
        )
        extra = extra | overdue
    if include_undated:
        extra = extra | end_dates.isna()
    mask &= in_window | extra
else:
    if not include_undated:
        mask &= end_dates.notna()

df_f = df.loc[mask].reset_index(drop=True)


# ==========================================================
# Métricas
# ==========================================================
end_dates_f = pd.to_datetime(df_f["end_date"], errors="coerce").dt.date

n_andamento = int(df_f["delivery_status"].isin(["EM_ELABORACAO", "EM_REVISAO"]).sum())
n_revisao = int(df_f["needs_revision"].fillna(False).astype(bool).sum())
atrasado_mask = (
    end_dates_f.notna()
    & (end_dates_f < today)
    & ~df_f["delivery_status"].isin(["ENTREGUE", "FATURADO"])
)
n_atrasado = int(atrasado_mask.sum())

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total exibido", len(df_f))
m2.metric("Em andamento", n_andamento)
m3.metric("Aguardando revisão", n_revisao)
m4.metric("Atrasados", n_atrasado)

st.divider()


# ==========================================================
# Tabela editável
# ==========================================================
st.subheader("Produtos")
st.caption("Edite os campos de acompanhamento e clique em **Salvar alterações**.")

# --- Busca livre + ordenação dentro do conjunto já filtrado ---
SORT_OPTIONS = {
    "Prazo (mais próximo primeiro)": ("end_date", True),
    "Prazo (mais distante primeiro)": ("end_date", False),
    "Projeto (A→Z)":                  ("project_code", True),
    "Produto (A→Z)":                  ("product_name", True),
    "Status":                         ("delivery_status", True),
    "Atualizado recentemente":        ("tracking_updated_at", False),
}

tc1, tc2 = st.columns([2.5, 1.5])
with tc1:
    search = st.text_input(
        "Buscar (Projeto · Produto · Responsável · Obs)",
        value="",
        placeholder="Ex.: relatório semestral, fulano, ASSCAF...",
    )
with tc2:
    sort_label = st.selectbox("Ordenar por", list(SORT_OPTIONS.keys()), index=0)

# Aplica busca livre
if search.strip():
    q = search.strip().lower()
    haystack = (
        df_f["project_code"].fillna("").astype(str).str.lower()
        + " | "
        + df_f["product_name"].fillna("").astype(str).str.lower()
        + " | "
        + (df_f["assignee_names"].fillna("").astype(str).str.lower() if "assignee_names" in df_f.columns else "")
        + " | "
        + df_f["tracking_notes"].fillna("").astype(str).str.lower()
    )
    df_f = df_f.loc[haystack.str.contains(q, na=False, regex=False)].reset_index(drop=True)

# Aplica ordenação
sort_col, sort_asc = SORT_OPTIONS[sort_label]
if sort_col in df_f.columns and not df_f.empty:
    df_f = df_f.sort_values(by=sort_col, ascending=sort_asc, na_position="last").reset_index(drop=True)

if df_f.empty:
    st.info("Nenhum produto corresponde aos filtros/busca atuais.")
    st.stop()

ids = safe_text_list(df_f["task_id"])

status_labels = [STATUS_LABEL.get(s, s) for s in safe_text_list(df_f["delivery_status"], "NAO_INICIADO")]

# Coluna Responsável vem de v_portfolio_tasks via v_deliverables (assignee_names)
resp_col = df_f["assignee_names"] if "assignee_names" in df_f.columns else pd.Series([""] * len(df_f))

df_show = pd.DataFrame(
    {
        "Projeto":     safe_text_list(df_f["project_code"]),
        "Produto":     safe_text_list(df_f["product_name"]),
        "Responsável": safe_text_list(resp_col),
        "Status":      status_labels,
        "Revisão?":    df_f["needs_revision"].fillna(False).astype(bool).tolist(),
        "Enviado?":    df_f["sent_to_client"].fillna(False).astype(bool).tolist(),
        "Entrega":     [to_date(x) for x in df_f["delivery_date"].tolist()],
        "Faturamento": [to_date(x) for x in df_f["invoice_date"].tolist()],
        "Prazo":       [to_date(x) for x in df_f["end_date"].tolist()],
        "Obs":         safe_text_list(df_f["tracking_notes"]),
    },
    index=ids,
)

status_label_options = [STATUS_LABEL[s] for s in DELIVERY_STATUS_OPTIONS]

edited = st.data_editor(
    df_show,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "Projeto":     st.column_config.TextColumn(disabled=True, width="small"),
        "Produto":     st.column_config.TextColumn(disabled=True, width="large"),
        "Responsável": st.column_config.TextColumn(disabled=True, width="medium"),
        "Status":      st.column_config.SelectboxColumn(options=status_label_options, width="medium"),
        "Revisão?":    st.column_config.CheckboxColumn(width="small"),
        "Enviado?":    st.column_config.CheckboxColumn(width="small", help="Marcar preenche Entrega com hoje se vazia"),
        "Entrega":     st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Faturamento": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Prazo":       st.column_config.DateColumn(format="DD/MM/YYYY", disabled=True, width="small"),
        "Obs":         st.column_config.TextColumn(width="large"),
    },
    key="deliverables_editor",
)

st.caption(
    "💡 Auto-datação ao salvar: marcar **Enviado?** ou status **Entregue** "
    "preenche **Entrega** com hoje se estiver vazia. Status **Faturado** "
    "preenche **Faturamento** com hoje."
)

bc1, bc2, _ = st.columns([1, 1, 4])
save_clicked = bc1.button("Salvar alterações", type="primary")
reload_clicked = bc2.button("Recarregar")

if reload_clicked:
    refresh()
    st.rerun()

if save_clicked:
    changes: list[dict] = []
    for task_id in ids:
        before = df_show.loc[task_id]
        after = edited.loc[task_id]

        before_status = LABEL_TO_STATUS.get(before["Status"], "NAO_INICIADO")
        after_status = LABEL_TO_STATUS.get(after["Status"], "NAO_INICIADO")

        after_sent = bool(after["Enviado?"])
        before_sent = bool(before["Enviado?"])
        after_rev = bool(after["Revisão?"])

        after_entrega = to_date(after["Entrega"])
        after_fat = to_date(after["Faturamento"])
        before_entrega = to_date(before["Entrega"])
        before_fat = to_date(before["Faturamento"])

        # --- Auto-datação ---
        # Status virou ENTREGUE OU "Enviado?" foi marcado agora → entrega = hoje (se vazia)
        if after_entrega is None and (
            (after_status == "ENTREGUE" and before_status != "ENTREGUE")
            or (after_sent and not before_sent)
        ):
            after_entrega = today
        # Status virou FATURADO → faturamento = hoje (se vazio)
        if after_fat is None and after_status == "FATURADO" and before_status != "FATURADO":
            after_fat = today

        diff = (
            before_status != after_status
            or bool(before["Revisão?"]) != after_rev
            or before_sent != after_sent
            or before_entrega != after_entrega
            or before_fat != after_fat
            or norm_text(before["Obs"]) != norm_text(after["Obs"])
        )
        if not diff:
            continue

        changes.append(
            {
                "task_id": task_id,
                "delivery_status": after_status,
                "needs_revision": after_rev,
                "sent_to_client": after_sent,
                "delivery_date": after_entrega.isoformat() if after_entrega else None,
                "invoice_date": after_fat.isoformat() if after_fat else None,
                "notes": norm_text(after["Obs"]),
            }
        )

    if not changes:
        st.info("Nenhuma alteração a salvar.")
    else:
        ok, fail = 0, 0
        errors: list[str] = []
        for row in changes:
            try:
                sb.table("task_delivery_tracking").upsert(row, on_conflict="task_id").execute()
                ok += 1
            except Exception as e:
                fail += 1
                errors.append(f"{row['task_id']}: {_api_error_message(e)}")
        if ok:
            st.success(f"{ok} produto(s) atualizado(s).")
        if fail:
            st.error(f"{fail} falha(s):")
            for err in errors:
                st.code(err)
        refresh()
        st.rerun()


# ==========================================================
# Timeline
# ==========================================================
st.divider()
st.subheader("Histórico / Timeline")

if df_f.empty:
    st.caption("Sem produtos no filtro.")
else:
    options = {
        f"{r['project_code']} — {r['product_name']}": r["task_id"]
        for _, r in df_f.iterrows()
    }
    pick = st.selectbox("Selecione um produto", list(options.keys()))
    if pick:
        task_id = options[pick]
        events = load_events(cache_key, task_id)
        if events.empty:
            st.info("Sem eventos registrados ainda.")
        else:
            def _fmt_event(row) -> str:
                ts = row["changed_at"]
                try:
                    ts = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
                except Exception:
                    ts = str(ts)
                ev = row["event_type"]
                if ev == "STATUS_CHANGE":
                    return f"**{ts}** — Status: `{row['from_value']}` → `{row['to_value']}`"
                if ev == "REVISION_FLAG":
                    return f"**{ts}** — Marcado para revisão"
                if ev == "SENT_TO_CLIENT":
                    return f"**{ts}** — Enviado ao cliente"
                if ev == "DELIVERED":
                    return f"**{ts}** — Entregue em `{row['to_value']}`"
                if ev == "INVOICED":
                    return f"**{ts}** — Faturado em `{row['to_value']}`"
                if ev == "CREATED":
                    return f"**{ts}** — Acompanhamento iniciado (`{row['to_value']}`)"
                return f"**{ts}** — {ev}"

            for _, ev in events.iterrows():
                st.markdown("• " + _fmt_event(ev))
