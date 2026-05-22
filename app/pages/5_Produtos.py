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
    "CONCLUIDO",
]
STATUS_LABEL = {
    "NAO_INICIADO": "⚪ Não iniciado",
    "EM_ELABORACAO": "🟡 Em elaboração",
    "EM_REVISAO": "🟠 Em revisão",
    "CONCLUIDO": "🟢 Concluído",
}
LABEL_TO_STATUS = {v: k for k, v in STATUS_LABEL.items()}

LEGACY_STATUS_TO_UI = {
    "ENTREGUE": "CONCLUIDO",
    "FATURADO": "CONCLUIDO",
}
UI_STATUS_TO_DB = {
    "NAO_INICIADO": "NAO_INICIADO",
    "EM_ELABORACAO": "EM_ELABORACAO",
    "EM_REVISAO": "EM_REVISAO",
    # Mantém compatibilidade com o check atual do banco.
    "CONCLUIDO": "ENTREGUE",
}
STATUS_PRIORITY = {s: i for i, s in enumerate(DELIVERY_STATUS_OPTIONS)}


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


def to_ui_status(status: str | None) -> str:
    s = (status or "NAO_INICIADO").strip().upper()
    s = LEGACY_STATUS_TO_UI.get(s, s)
    if s not in DELIVERY_STATUS_OPTIONS:
        return "NAO_INICIADO"
    return s


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

status_all = safe_text_list(df["delivery_status"], "NAO_INICIADO")
df["delivery_status_ui"] = [to_ui_status(s) for s in status_all]


# ==========================================================
# Filtros
# ==========================================================
projects_all = sorted({p for p in safe_text_list(df["project_code"]) if p})

cur_first = shift_month_first(today, 0)
cur_start, cur_end = month_range(cur_first)

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
    only_pending = st.toggle("Apenas não concluídos", value=False)

p_start, p_end = cur_start, cur_end
st.caption(f"Mês atual travado pelo Prazo: **{p_start.strftime('%d/%m/%Y')} – {p_end.strftime('%d/%m/%Y')}**")

mask = pd.Series(True, index=df.index)
if f_projects:
    mask &= df["project_code"].isin(f_projects)
if f_status:
    mask &= df["delivery_status_ui"].isin(f_status)
if only_pending:
    mask &= df["delivery_status_ui"] != "CONCLUIDO"

end_dates = pd.to_datetime(df["end_date"], errors="coerce").dt.date
mask &= end_dates.between(p_start, p_end)

df_f = df.loc[mask].reset_index(drop=True)

st.caption(f"Quantitativo do mês: **{month_label(cur_first)}**")
qm1, qm2, qm3, qm4, qm5 = st.columns(5)
qm1.metric("Total", len(df_f))
qm2.metric(STATUS_LABEL["NAO_INICIADO"], int((df_f["delivery_status_ui"] == "NAO_INICIADO").sum()))
qm3.metric(STATUS_LABEL["EM_ELABORACAO"], int((df_f["delivery_status_ui"] == "EM_ELABORACAO").sum()))
qm4.metric(STATUS_LABEL["EM_REVISAO"], int((df_f["delivery_status_ui"] == "EM_REVISAO").sum()))
qm5.metric(STATUS_LABEL["CONCLUIDO"], int((df_f["delivery_status_ui"] == "CONCLUIDO").sum()))


# ==========================================================
# Tabela editável
# ==========================================================
st.subheader("Produtos")
st.caption("Edição rápida e inline para acompanhamento operacional.")

SORT_OPTIONS = {
    "Prazo (mais próximo primeiro)": ("end_date", True),
    "Prazo (mais distante primeiro)": ("end_date", False),
    "Projeto (A→Z)": ("project_code", True),
    "Produto (A→Z)": ("product_name", True),
    "Status": ("__status_priority", True),
    "Atualizado recentemente": ("tracking_updated_at", False),
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

df_f["__status_priority"] = (
    df_f["delivery_status_ui"].map(STATUS_PRIORITY).fillna(99).astype(int)
)
sort_col, sort_asc = SORT_OPTIONS[sort_label]
if sort_col in df_f.columns and not df_f.empty:
    df_f = df_f.sort_values(by=sort_col, ascending=sort_asc, na_position="last").reset_index(drop=True)

if df_f.empty:
    st.info(
        f"Nenhum produto corresponde aos filtros/busca atuais. "
        f"Existem **{len(df)}** produto(s) no total."
    )
    st.stop()


# ==========================================================
# Export CSV / Excel
# ==========================================================
def _build_export_df(_df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Projeto": safe_text_list(_df["project_code"]),
        "Produto": safe_text_list(_df["product_name"]),
        "Responsável": (
            safe_text_list(_df["assignee_names"])
            if "assignee_names" in _df.columns else [""] * len(_df)
        ),
        "Status": [STATUS_LABEL.get(s, s) for s in safe_text_list(_df["delivery_status_ui"])],
        "Data de entrega ao cliente": [to_date(x) for x in _df["delivery_date"].tolist()],
        "Prazo": [to_date(x) for x in _df["end_date"].tolist()],
        "Obs": safe_text_list(_df["tracking_notes"]),
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
status_labels = [STATUS_LABEL.get(s, s) for s in safe_text_list(df_f["delivery_status_ui"], "NAO_INICIADO")]
resp_col = df_f["assignee_names"] if "assignee_names" in df_f.columns else pd.Series([""] * len(df_f))

df_show = pd.DataFrame(
    {
        "Projeto": safe_text_list(df_f["project_code"]),
        "Produto": safe_text_list(df_f["product_name"]),
        "Responsável": safe_text_list(resp_col),
        "Status": status_labels,
        "Data de entrega ao cliente": [to_date(x) for x in df_f["delivery_date"].tolist()],
        "Prazo": [to_date(x) for x in df_f["end_date"].tolist()],
        "Obs": safe_text_list(df_f["tracking_notes"]),
    },
    index=ids,
)

status_label_options = [STATUS_LABEL[s] for s in DELIVERY_STATUS_OPTIONS]

# Assinatura dos filtros — força reset do data_editor quando filtros mudam.
# Sem isso, o editor cacheia as edições por índice e mostra dados defasados.
_editor_signature = hash(
    (
        tuple(f_projects), tuple(f_status),
        only_pending, sort_label, search.strip(),
        tuple(ids),
    )
)

edited = st.data_editor(
    df_show,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "Projeto": st.column_config.TextColumn(disabled=True, width="small"),
        "Produto": st.column_config.TextColumn(disabled=True, width="large"),
        "Responsável": st.column_config.TextColumn(disabled=True, width="medium"),
        "Status": st.column_config.SelectboxColumn(options=status_label_options, width="medium"),
        "Data de entrega ao cliente": st.column_config.DateColumn(
            format="DD/MM/YYYY",
            width="small",
            help="Data de entrega efetiva ao cliente.",
        ),
        "Prazo": st.column_config.DateColumn(format="DD/MM/YYYY", disabled=True, width="small"),
        "Obs": st.column_config.TextColumn(width="large"),
    },
    key=f"deliverables_editor::{_editor_signature}",
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
    rows_by_task_id = {str(r["task_id"]): r for _, r in df_f.iterrows()}

    for task_id in ids:
        before = df_show.loc[task_id]
        after = edited.loc[task_id]

        before_status_ui = LABEL_TO_STATUS.get(before["Status"], "NAO_INICIADO")
        after_status_ui = LABEL_TO_STATUS.get(after["Status"], "NAO_INICIADO")

        after_entrega = to_date(after["Data de entrega ao cliente"])
        before_entrega = to_date(before["Data de entrega ao cliente"])
        before_obs = norm_text(before["Obs"])
        after_obs = norm_text(after["Obs"])

        diff = (
            before_status_ui != after_status_ui
            or before_entrega != after_entrega
            or before_obs != after_obs
        )
        if not diff:
            continue

        row = rows_by_task_id.get(str(task_id))
        if row is None:
            continue

        current_db_status = str(row.get("delivery_status") or "NAO_INICIADO").strip().upper()
        current_ui_status = to_ui_status(current_db_status)
        if after_status_ui == current_ui_status:
            # Se o status visual não mudou, preserva exatamente o valor atual no banco.
            after_status_db = current_db_status
        else:
            after_status_db = UI_STATUS_TO_DB.get(after_status_ui, "NAO_INICIADO")

        keep_revision = bool(row.get("needs_revision", False))
        keep_sent = bool(row.get("sent_to_client", False))
        keep_invoice = to_date(row.get("invoice_date"))

        if after_status_ui == "CONCLUIDO" and after_entrega is None:
            label = f"{after.get('Projeto','?')} — {after.get('Produto','?')}"
            warnings.append(f"{label}: status **Concluído** sem data de entrega ao cliente.")

        changes.append(
            {
                "task_id": task_id,
                "delivery_status": after_status_db,
                "needs_revision": keep_revision,
                "sent_to_client": keep_sent,
                "delivery_date": after_entrega.isoformat() if after_entrega else None,
                "invoice_date": keep_invoice.isoformat() if keep_invoice else None,
                "notes": after_obs,
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
                    from_status = STATUS_LABEL.get(to_ui_status(row.get("from_value")), row.get("from_value"))
                    to_status = STATUS_LABEL.get(to_ui_status(row.get("to_value")), row.get("to_value"))
                    return f"**{ts}** — Status: `{from_status}` → `{to_status}`"
                if ev == "DELIVERED":
                    return f"**{ts}** — Entrega ao cliente em `{row['to_value']}`"
                if ev == "CREATED":
                    created_status = STATUS_LABEL.get(to_ui_status(row.get("to_value")), row.get("to_value"))
                    return f"**{ts}** — Acompanhamento iniciado (`{created_status}`)"
                return f"**{ts}** — {ev}"

            hidden_events = {"REVISION_FLAG", "SENT_TO_CLIENT", "INVOICED"}
            for _, ev in events.iterrows():
                if str(ev.get("event_type") or "").upper() in hidden_events:
                    continue
                st.markdown("• " + _fmt_event(ev))
