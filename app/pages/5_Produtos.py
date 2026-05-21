# app/pages/5_Produtos.py
"""
Acompanhamento operacional de Produtos / Entregas.

Reaproveita tarefas com tipo_atividade='RELATORIO' (cadastradas na aba Tarefas)
e adiciona uma camada de controle via task_delivery_tracking + timeline em
task_delivery_events. Nenhum cadastro novo de produto é feito aqui.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO

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


# ==========================================================
# Constantes
# ==========================================================
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

SITUACAO_OPTIONS = [
    "🔴 Atrasado",
    "⏰ Próximo",
    "🟠 Em revisão",
    "🟡 Em elaboração",
    "⚪ Não iniciado",
    "🟢 Entregue",
    "💰 Faturado",
]
SITUACAO_PRIORITY = {s: i for i, s in enumerate(SITUACAO_OPTIONS)}

PROXIMO_DIAS = 7  # janela usada para 'Próximo' na coluna Situação


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


def sb_paginate(table: str, *, select: str = "*", order_cols: list[tuple[str, bool]] | None = None,
                page_size: int = 1000) -> list[dict]:
    """Paginação obrigatória — anon key trunca em 1000 linhas por request."""
    out: list[dict] = []
    offset = 0
    while True:
        q = sb.table(table).select(select).range(offset, offset + page_size - 1)
        for col, desc in (order_cols or []):
            q = q.order(col, desc=desc)
        resp = q.execute()
        chunk = resp.data or []
        out.extend(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
    return out


def situacao_for(status: str | None, end: date | None, needs_revision: bool, today_: date) -> str:
    s = status or "NAO_INICIADO"
    if s == "FATURADO":
        return "💰 Faturado"
    if s == "ENTREGUE":
        return "🟢 Entregue"
    if s == "EM_REVISAO" or needs_revision:
        # Revisão domina, mas ainda mostra atraso se vencido
        if end is not None and end < today_:
            return "🔴 Atrasado"
        return "🟠 Em revisão"
    if end is not None and end < today_:
        return "🔴 Atrasado"
    if end is not None and 0 <= (end - today_).days <= PROXIMO_DIAS:
        return "⏰ Próximo"
    if s == "EM_ELABORACAO":
        return "🟡 Em elaboração"
    return "⚪ Não iniciado"


def days_delta(end: date | None, today_: date) -> int | None:
    if end is None:
        return None
    return (end - today_).days


def format_days(d) -> str:
    if d is None or (isinstance(d, float) and pd.isna(d)):
        return ""
    d = int(d)
    if d < 0:
        return f"⚠ −{-d}d (atraso)"
    if d == 0:
        return "Hoje"
    return f"+{d}d"


# ==========================================================
# Loads
# ==========================================================
@st.cache_data(ttl=30)
def load_deliverables(_k: str) -> pd.DataFrame:
    data = sb_paginate(
        "v_deliverables",
        order_cols=[("project_code", False), ("end_date", False)],
    )
    return pd.DataFrame(data)


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

today = date.today()

# Pré-computa Situação e dias restantes
end_dates_all = [to_date(x) for x in df["end_date"].tolist()]
status_all = safe_text_list(df["delivery_status"], "NAO_INICIADO")
needs_rev_all = df["needs_revision"].fillna(False).astype(bool).tolist()
df["__situacao"] = [situacao_for(s, e, r, today) for s, e, r in zip(status_all, end_dates_all, needs_rev_all)]
df["__days"] = [days_delta(e, today) for e in end_dates_all]


# ==========================================================
# Painel: Próximos vencimentos
# ==========================================================
def _vencimento_panel():
    horizons = [7, 15]
    cols = st.columns(len(horizons) + 1)
    overdue = df[df["__situacao"] == "🔴 Atrasado"]
    cols[0].metric("🔴 Atrasados", len(overdue))
    pending_mask = ~df["delivery_status"].isin(["ENTREGUE", "FATURADO"])
    for i, h in enumerate(horizons, start=1):
        m = df[
            pending_mask
            & df["__days"].notna()
            & (df["__days"] >= 0)
            & (df["__days"] <= h)
        ]
        cols[i].metric(f"⏰ Vencem em ≤ {h}d", len(m))


_vencimento_panel()


# ==========================================================
# Filtros
# ==========================================================
projects_all = sorted({p for p in safe_text_list(df["project_code"]) if p})

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
default_period_idx = 0  # Mês atual por padrão

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
        "Incluir atrasados", value=True,
        help="Mostra atrasados mesmo fora do período.",
    )
with fc6:
    include_undated = st.toggle("Incluir sem prazo", value=False)

chosen = next(p for p in period_presets if p[0] == sel_period)
if chosen[0] == "(manual)":
    period = st.date_input("Período manual (Prazo)", value=(cur_start, cur_end), format="DD/MM/YYYY")
    if isinstance(period, tuple) and len(period) == 2:
        p_start, p_end = period
    else:
        p_start, p_end = cur_start, cur_end
elif chosen[0] == "Tudo":
    p_start, p_end = None, None
else:
    p_start, p_end = chosen[1], chosen[2]
    st.caption(f"Período (Prazo): **{p_start.strftime('%d/%m/%Y')} – {p_end.strftime('%d/%m/%Y')}**")

mask = pd.Series(True, index=df.index)
if f_projects:
    mask &= df["project_code"].isin(f_projects)
if f_status:
    mask &= df["delivery_status"].isin(f_status)
if only_pending:
    mask &= ~df["delivery_status"].isin(["ENTREGUE", "FATURADO"])

end_dates = pd.to_datetime(df["end_date"], errors="coerce").dt.date
if p_start is not None and p_end is not None:
    in_window = end_dates.between(p_start, p_end)
    extra = pd.Series(False, index=df.index)
    if include_overdue:
        extra = extra | (df["__situacao"] == "🔴 Atrasado")
    if include_undated:
        extra = extra | end_dates.isna()
    mask &= in_window | extra
else:
    if not include_undated:
        mask &= end_dates.notna()

df_f = df.loc[mask].reset_index(drop=True)


# ==========================================================
# Métricas (alinhadas à Situação)
# ==========================================================
n_atrasado = int((df_f["__situacao"] == "🔴 Atrasado").sum())
n_proximo  = int((df_f["__situacao"] == "⏰ Próximo").sum())
n_revisao  = int((df_f["__situacao"] == "🟠 Em revisão").sum())
n_entreg   = int((df_f["__situacao"] == "🟢 Entregue").sum())
n_fat      = int((df_f["__situacao"] == "💰 Faturado").sum())

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Total exibido", len(df_f))
m2.metric("🔴 Atrasados", n_atrasado)
m3.metric("⏰ Próximos", n_proximo)
m4.metric("🟠 Em revisão", n_revisao)
m5.metric("🟢 Entregues", n_entreg)
m6.metric("💰 Faturados", n_fat)

# Indicador: atraso médio (entregas concluídas)
delivered = df_f[df_f["delivery_status"].isin(["ENTREGUE", "FATURADO"])].copy()
if not delivered.empty:
    deliv_end = pd.to_datetime(delivered["end_date"], errors="coerce").dt.date
    deliv_dt = pd.to_datetime(delivered["delivery_date"], errors="coerce").dt.date
    diffs = []
    for d_end, d_real in zip(deliv_end, deliv_dt):
        if d_end is not None and d_real is not None:
            diffs.append((d_real - d_end).days)
    if diffs:
        med = sum(diffs) / len(diffs)
        sign = "+" if med >= 0 else ""
        st.caption(
            f"📊 **Atraso médio (entregues no filtro):** {sign}{med:.1f} dia(s) "
            f"em {len(diffs)} entrega(s) com Prazo e Entrega preenchidos."
        )

st.divider()


# ==========================================================
# Tabela editável
# ==========================================================
st.subheader("Produtos")
st.caption("Edite os campos de acompanhamento e clique em **Salvar alterações**.")

SORT_OPTIONS = {
    "Situação (Atrasado → Faturado)":  ("__sit_priority", True),
    "Prazo (mais próximo primeiro)":   ("end_date", True),
    "Prazo (mais distante primeiro)":  ("end_date", False),
    "Projeto (A→Z)":                   ("project_code", True),
    "Produto (A→Z)":                   ("product_name", True),
    "Status":                          ("delivery_status", True),
    "Atualizado recentemente":         ("tracking_updated_at", False),
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

rc1, _ = st.columns([1.5, 4])
with rc1:
    f_sit = st.multiselect("Situação", SITUACAO_OPTIONS, default=[])

if f_sit:
    df_f = df_f[df_f["__situacao"].isin(f_sit)].reset_index(drop=True)

if search.strip():
    q = search.strip().lower()
    haystack = (
        df_f["project_code"].fillna("").astype(str).str.lower() + " | "
        + df_f["product_name"].fillna("").astype(str).str.lower() + " | "
        + (df_f["assignee_names"].fillna("").astype(str).str.lower() if "assignee_names" in df_f.columns else "")
        + " | "
        + df_f["tracking_notes"].fillna("").astype(str).str.lower()
    )
    df_f = df_f.loc[haystack.str.contains(q, na=False, regex=False)].reset_index(drop=True)

df_f["__sit_priority"] = df_f["__situacao"].map(SITUACAO_PRIORITY).fillna(99).astype(int)
sort_col, sort_asc = SORT_OPTIONS[sort_label]
if sort_col in df_f.columns and not df_f.empty:
    df_f = df_f.sort_values(by=sort_col, ascending=sort_asc, na_position="last").reset_index(drop=True)

if df_f.empty:
    st.info(
        f"Nenhum produto corresponde aos filtros/busca atuais. "
        f"Existem **{len(df)}** produto(s) no total — tente o atalho **Tudo** ou amplie o período."
    )
    st.stop()


# ==========================================================
# Export CSV / Excel
# ==========================================================
def _build_export_df(_df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Projeto":     safe_text_list(_df["project_code"]),
        "Produto":     safe_text_list(_df["product_name"]),
        "Situação":    _df["__situacao"].tolist(),
        "Responsável": safe_text_list(_df["assignee_names"]) if "assignee_names" in _df.columns else [""] * len(_df),
        "Status (DB)": safe_text_list(_df["delivery_status"]),
        "Revisão?":    _df["needs_revision"].fillna(False).astype(bool).tolist(),
        "Enviado?":    _df["sent_to_client"].fillna(False).astype(bool).tolist(),
        "Entrega":     [to_date(x) for x in _df["delivery_date"].tolist()],
        "Faturamento": [to_date(x) for x in _df["invoice_date"].tolist()],
        "Prazo":       [to_date(x) for x in _df["end_date"].tolist()],
        "Dias":        _df["__days"].tolist(),
        "Obs":         safe_text_list(_df["tracking_notes"]),
    })


export_df = _build_export_df(df_f)
csv_bytes = export_df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
xc1, xc2, _ = st.columns([1.2, 1.2, 4])
xc1.download_button(
    "⬇️ Exportar CSV",
    data=csv_bytes,
    file_name=f"produtos_{today.isoformat()}.csv",
    mime="text/csv",
)
try:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Produtos")
    xc2.download_button(
        "⬇️ Exportar Excel",
        data=buf.getvalue(),
        file_name=f"produtos_{today.isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
except Exception:
    pass


# ==========================================================
# Editor
# ==========================================================
ids = safe_text_list(df_f["task_id"])
status_labels = [STATUS_LABEL.get(s, s) for s in safe_text_list(df_f["delivery_status"], "NAO_INICIADO")]
resp_col = df_f["assignee_names"] if "assignee_names" in df_f.columns else pd.Series([""] * len(df_f))
dias_strings = [format_days(d) for d in df_f["__days"].tolist()]

df_show = pd.DataFrame(
    {
        "Projeto":     safe_text_list(df_f["project_code"]),
        "Produto":     safe_text_list(df_f["product_name"]),
        "Situação":    df_f["__situacao"].tolist(),
        "Responsável": safe_text_list(resp_col),
        "Status":      status_labels,
        "Revisão?":    df_f["needs_revision"].fillna(False).astype(bool).tolist(),
        "Enviado?":    df_f["sent_to_client"].fillna(False).astype(bool).tolist(),
        "Entrega":     [to_date(x) for x in df_f["delivery_date"].tolist()],
        "Faturamento": [to_date(x) for x in df_f["invoice_date"].tolist()],
        "Prazo":       [to_date(x) for x in df_f["end_date"].tolist()],
        "Dias":        dias_strings,
        "Obs":         safe_text_list(df_f["tracking_notes"]),
    },
    index=ids,
)

status_label_options = [STATUS_LABEL[s] for s in DELIVERY_STATUS_OPTIONS]

# Assinatura dos filtros — força reset do data_editor quando filtros mudam.
# Sem isso, o editor cacheia as edições por índice e mostra dados defasados.
_editor_signature = hash(
    (
        tuple(f_projects), tuple(f_status), tuple(f_sit),
        only_pending, include_overdue, include_undated,
        sel_period, sort_label, search.strip(),
        tuple(ids),
    )
)

edited = st.data_editor(
    df_show,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "Projeto":     st.column_config.TextColumn(disabled=True, width="small"),
        "Produto":     st.column_config.TextColumn(disabled=True, width="large"),
        "Situação":    st.column_config.TextColumn(
            disabled=True, width="small",
            help="Calculada automaticamente a partir de Status, Prazo, Revisão e datas.",
        ),
        "Responsável": st.column_config.TextColumn(disabled=True, width="medium"),
        "Status":      st.column_config.SelectboxColumn(options=status_label_options, width="medium"),
        "Revisão?":    st.column_config.CheckboxColumn(width="small"),
        "Enviado?":    st.column_config.CheckboxColumn(width="small", help="Marcar preenche Entrega com hoje se vazia"),
        "Entrega":     st.column_config.DateColumn(
            format="DD/MM/YYYY", width="small",
            help="Edite manualmente para corrigir a data real de entrega.",
        ),
        "Faturamento": st.column_config.DateColumn(
            format="DD/MM/YYYY", width="small",
            help="Edite manualmente para corrigir a data real do faturamento.",
        ),
        "Prazo":       st.column_config.DateColumn(format="DD/MM/YYYY", disabled=True, width="small"),
        "Dias":        st.column_config.TextColumn(
            disabled=True, width="small",
            help="Dias restantes (+) ou de atraso (−) em relação ao Prazo.",
        ),
        "Obs":         st.column_config.TextColumn(width="large"),
    },
    key=f"deliverables_editor::{_editor_signature}",
)

st.caption(
    "💡 **Entrega** e **Faturamento** são editáveis. Auto-datação preenche apenas "
    "se a célula estiver vazia (Enviado? ou Status=Entregue → Entrega; "
    "Status=Faturado → Faturamento). **Situação** e **Dias** são recalculadas após salvar."
)

bc1, bc2, _ = st.columns([1, 1, 4])
save_clicked = bc1.button("Salvar alterações", type="primary")
reload_clicked = bc2.button("Recarregar")

if reload_clicked:
    refresh()
    st.rerun()

if save_clicked:
    changes: list[dict] = []
    warnings: list[str] = []
    for task_id in ids:
        before = df_show.loc[task_id]
        after = edited.loc[task_id]

        before_status = LABEL_TO_STATUS.get(before["Status"], "NAO_INICIADO")
        after_status = LABEL_TO_STATUS.get(after["Status"], "NAO_INICIADO")

        after_sent = bool(after["Enviado?"])
        before_sent = bool(before["Enviado?"])
        after_rev = bool(after["Revisão?"])
        before_rev = bool(before["Revisão?"])

        after_entrega = to_date(after["Entrega"])
        after_fat = to_date(after["Faturamento"])
        before_entrega = to_date(before["Entrega"])
        before_fat = to_date(before["Faturamento"])

        # Auto-datação (somente quando célula vazia)
        if after_entrega is None and (
            (after_status == "ENTREGUE" and before_status != "ENTREGUE")
            or (after_sent and not before_sent)
        ):
            after_entrega = today
        if after_fat is None and after_status == "FATURADO" and before_status != "FATURADO":
            after_fat = today

        diff = (
            before_status != after_status
            or before_rev != after_rev
            or before_sent != after_sent
            or before_entrega != after_entrega
            or before_fat != after_fat
            or norm_text(before["Obs"]) != norm_text(after["Obs"])
        )
        if not diff:
            continue

        label = f"{after.get('Projeto','?')} — {after.get('Produto','?')}"
        # Validações não-bloqueantes
        if after_status == "FATURADO" and after_entrega is None:
            warnings.append(f"{label}: marcado como **Faturado** sem data de **Entrega** preenchida.")
        if after_rev and after_status in ("ENTREGUE", "FATURADO"):
            warnings.append(
                f"{label}: **Revisão?** marcada mas Status é **{STATUS_LABEL[after_status]}** "
                "— confira se a revisão já foi resolvida."
            )
        if after_status == "ENTREGUE" and after_entrega is None:
            warnings.append(f"{label}: status **Entregue** sem data de **Entrega** preenchida.")

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
                resp = (
                    sb.table("task_delivery_tracking")
                    .upsert(row, on_conflict="task_id", returning="representation")
                    .execute()
                )
                if not getattr(resp, "data", None):
                    fail += 1
                    errors.append(
                        f"{row['task_id']}: upsert não retornou linha "
                        "(provável bloqueio por RLS/trigger no banco)."
                    )
                else:
                    ok += 1
            except Exception as e:
                fail += 1
                errors.append(f"{row['task_id']}: {_api_error_message(e)}")
        if ok:
            st.success(f"{ok} produto(s) atualizado(s).")
        if warnings:
            for w in warnings:
                st.warning(w)
        if fail:
            st.error(f"{fail} falha(s):")
            for err in errors:
                st.code(err)
        if ok or fail:
            refresh()
            st.rerun()


# ==========================================================
# Visão colorida (read-only)
# ==========================================================
with st.expander("🎨 Visão colorida (somente leitura)", expanded=False):
    def _row_style(row):
        sit = row.get("Situação", "")
        color = {
            "🔴 Atrasado":     "#fee2e2",
            "⏰ Próximo":      "#ffe4cc",
            "🟠 Em revisão":   "#ffedd5",
            "🟡 Em elaboração":"#fef3c7",
            "⚪ Não iniciado": "#f3f4f6",
            "🟢 Entregue":     "#dcfce7",
            "💰 Faturado":     "#cffafe",
        }.get(sit, "")
        return [f"background-color: {color}" if color else ""] * len(row)

    view_df = export_df.copy()
    try:
        styled = view_df.style.apply(_row_style, axis=1)
        st.dataframe(styled, use_container_width=True, hide_index=True)
    except Exception:
        st.dataframe(view_df, use_container_width=True, hide_index=True)


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
