# app/pages/5_Produtos.py
"""
Acompanhamento operacional de Produtos.

Reaproveita tarefas com tipo_atividade='RELATORIO' (cadastradas na aba Tarefas)
e adiciona uma camada de controle via task_delivery_tracking + timeline em
task_delivery_events. Nenhum cadastro novo de produto e feito aqui.
"""

from __future__ import annotations

from datetime import date, datetime
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
    "Produtos",
    "Acompanhamento operacional dos produtos cadastrados em Tarefas",
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
    "NAO_INICIADO": "Nao iniciado",
    "EM_ELABORACAO": "Em elaboracao",
    "EM_REVISAO": "Em revisao",
    "CONCLUIDO": "Concluido",
}

STATUS_PRIORITY = {s: i for i, s in enumerate(DELIVERY_STATUS_OPTIONS)}

LEGACY_STATUS_MAP = {
    "ENTREGUE": "CONCLUIDO",
    "FATURADO": "CONCLUIDO",
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


def canonical_status(status: str | None) -> str:
    s = (status or "NAO_INICIADO").strip().upper()
    s = LEGACY_STATUS_MAP.get(s, s)
    if s not in DELIVERY_STATUS_OPTIONS:
        return "NAO_INICIADO"
    return s


def status_label(status: str | None) -> str:
    return STATUS_LABEL.get(canonical_status(status), "Nao iniciado")


def sb_paginate(
    table: str,
    *,
    select: str = "*",
    order_cols: list[tuple[str, bool]] | None = None,
    page_size: int = 1000,
) -> list[dict]:
    """Paginacao obrigatoria: anon key trunca em 1000 linhas por request."""
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
        "**RELATORIO** na aba Tarefas para que aparecam aqui."
    )
    st.stop()

for col, default in [
    ("task_id", ""),
    ("project_code", ""),
    ("product_name", ""),
    ("assignee_names", ""),
    ("delivery_status", "NAO_INICIADO"),
    ("delivery_date", None),
    ("end_date", None),
    ("tracking_notes", ""),
    ("tracking_updated_at", None),
    ("needs_revision", False),
    ("sent_to_client", False),
    ("invoice_date", None),
]:
    if col not in df.columns:
        df[col] = default

df["delivery_status_raw"] = safe_text_list(df["delivery_status"], "NAO_INICIADO")
df["delivery_status_norm"] = [canonical_status(s) for s in df["delivery_status_raw"]]
df["status_priority"] = [STATUS_PRIORITY.get(s, 99) for s in df["delivery_status_norm"]]


# ==========================================================
# Lista operacional
# ==========================================================
st.subheader("Produtos")
st.caption("Lista simples para atualizacao operacional interna.")

SORT_OPTIONS = {
    "Prazo (mais proximo primeiro)": ("end_date", True),
    "Prazo (mais distante primeiro)": ("end_date", False),
    "Projeto (A-Z)": ("project_code", True),
    "Produto (A-Z)": ("product_name", True),
    "Status": ("status_priority", True),
    "Atualizado recentemente": ("tracking_updated_at", False),
}

projects_all = sorted({p for p in safe_text_list(df["project_code"]) if p})

fc1, fc2, fc3 = st.columns([1.5, 1.2, 1.3])
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
    sort_label = st.selectbox("Ordenar por", list(SORT_OPTIONS.keys()), index=0)

search = st.text_input(
    "Buscar (Projeto - Produto - Responsavel - Obs)",
    value="",
    placeholder="Ex.: relatorio semestral, fulano, ASSCAF...",
)

mask = pd.Series(True, index=df.index)
if f_projects:
    mask &= df["project_code"].isin(f_projects)
if f_status:
    mask &= df["delivery_status_norm"].isin(f_status)

df_f = df.loc[mask].copy()

if search.strip():
    q = search.strip().lower()
    haystack = (
        df_f["project_code"].fillna("").astype(str).str.lower()
        + " | "
        + df_f["product_name"].fillna("").astype(str).str.lower()
        + " | "
        + df_f["assignee_names"].fillna("").astype(str).str.lower()
        + " | "
        + df_f["tracking_notes"].fillna("").astype(str).str.lower()
    )
    df_f = df_f.loc[haystack.str.contains(q, na=False, regex=False)].copy()

sort_col, sort_asc = SORT_OPTIONS[sort_label]
if sort_col in df_f.columns and not df_f.empty:
    df_f = df_f.sort_values(by=sort_col, ascending=sort_asc, na_position="last")

df_f = df_f.reset_index(drop=True)

if df_f.empty:
    st.info("Nenhum produto corresponde aos filtros atuais.")
    st.stop()


# ==========================================================
# Export
# ==========================================================
def _build_export_df(_df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Projeto": safe_text_list(_df["project_code"]),
            "Produto": safe_text_list(_df["product_name"]),
            "Responsavel": safe_text_list(_df["assignee_names"]),
            "Status": [status_label(s) for s in safe_text_list(_df["delivery_status_norm"])],
            "Data entrega cliente": [to_date(x) for x in _df["delivery_date"].tolist()],
            "Prazo": [to_date(x) for x in _df["end_date"].tolist()],
            "Obs": safe_text_list(_df["tracking_notes"]),
        }
    )


export_df = _build_export_df(df_f)
csv_bytes = export_df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
xc1, xc2, _ = st.columns([1.2, 1.2, 4])
xc1.download_button(
    "Exportar CSV",
    data=csv_bytes,
    file_name=f"produtos_{date.today().isoformat()}.csv",
    mime="text/csv",
)
try:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Produtos")
    xc2.download_button(
        "Exportar Excel",
        data=buf.getvalue(),
        file_name=f"produtos_{date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
except Exception:
    pass


# ==========================================================
# Editor inline
# ==========================================================
ids = safe_text_list(df_f["task_id"])
status_labels = [status_label(s) for s in safe_text_list(df_f["delivery_status_norm"], "NAO_INICIADO")]

df_show = pd.DataFrame(
    {
        "Projeto": safe_text_list(df_f["project_code"]),
        "Produto": safe_text_list(df_f["product_name"]),
        "Responsavel": safe_text_list(df_f["assignee_names"]),
        "Status": status_labels,
        "Data entrega cliente": [to_date(x) for x in df_f["delivery_date"].tolist()],
        "Prazo": [to_date(x) for x in df_f["end_date"].tolist()],
        "Obs": safe_text_list(df_f["tracking_notes"]),
    },
    index=ids,
)

status_label_options = [STATUS_LABEL[s] for s in DELIVERY_STATUS_OPTIONS]

# Assinatura dos filtros: forca reset do data_editor quando filtros mudam.
_editor_signature = hash(
    (
        tuple(f_projects),
        tuple(f_status),
        sort_label,
        search.strip(),
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
        "Responsavel": st.column_config.TextColumn(disabled=True, width="medium"),
        "Status": st.column_config.SelectboxColumn(options=status_label_options, width="medium"),
        "Data entrega cliente": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Prazo": st.column_config.DateColumn(format="DD/MM/YYYY", disabled=True, width="small"),
        "Obs": st.column_config.TextColumn(width="large"),
    },
    key=f"deliverables_editor::{_editor_signature}",
)

bc1, bc2, _ = st.columns([1, 1, 4])
save_clicked = bc1.button("Salvar alteracoes", type="primary")
reload_clicked = bc2.button("Recarregar")

if reload_clicked:
    refresh()
    st.rerun()

if save_clicked:
    changes: list[dict] = []
    warnings: list[str] = []
    by_task_id = {str(r["task_id"]): r for _, r in df_f.iterrows()}

    for task_id in ids:
        before = df_show.loc[task_id]
        after = edited.loc[task_id]

        before_status = LABEL_TO_STATUS.get(norm_text(before["Status"]) or "", "NAO_INICIADO")
        after_status = LABEL_TO_STATUS.get(norm_text(after["Status"]) or "", "NAO_INICIADO")

        before_delivery = to_date(before["Data entrega cliente"])
        after_delivery = to_date(after["Data entrega cliente"])

        before_obs = norm_text(before["Obs"])
        after_obs = norm_text(after["Obs"])

        diff = (
            before_status != after_status
            or before_delivery != after_delivery
            or before_obs != after_obs
        )
        if not diff:
            continue

        row = by_task_id.get(str(task_id))
        if row is None:
            continue

        keep_revision = bool(row.get("needs_revision", False))
        keep_sent = bool(row.get("sent_to_client", False))
        keep_invoice = to_date(row.get("invoice_date"))

        if after_status == "CONCLUIDO" and after_delivery is None:
            label = f"{after.get('Projeto', '?')} - {after.get('Produto', '?')}"
            warnings.append(f"{label}: status Concluido sem Data entrega cliente.")

        changes.append(
            {
                "task_id": task_id,
                "delivery_status": after_status,
                "needs_revision": keep_revision,
                "sent_to_client": keep_sent,
                "delivery_date": after_delivery.isoformat() if after_delivery else None,
                "invoice_date": keep_invoice.isoformat() if keep_invoice else None,
                "notes": after_obs,
            }
        )

    if not changes:
        st.info("Nenhuma alteracao para salvar.")
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
                        f"{row['task_id']}: upsert nao retornou linha "
                        "(possivel bloqueio por RLS/trigger no banco)."
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
# Historico
# ==========================================================
with st.expander("Historico / Timeline", expanded=False):
    options = {
        f"{r['project_code']} - {r['product_name']}": r["task_id"]
        for _, r in df_f.iterrows()
    }
    if not options:
        st.caption("Sem produtos no filtro.")
    else:
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
                        from_label = status_label(norm_text(row.get("from_value")) or "")
                        to_label = status_label(norm_text(row.get("to_value")) or "")
                        return f"**{ts}** - Status: `{from_label}` -> `{to_label}`"
                    if ev == "DELIVERED":
                        return f"**{ts}** - Entrega ao cliente em `{row['to_value']}`"
                    if ev == "CREATED":
                        created_label = status_label(norm_text(row.get("to_value")) or "")
                        return f"**{ts}** - Acompanhamento iniciado (`{created_label}`)"
                    return f"**{ts}** - {ev}"

                hidden_events = {"INVOICED", "REVISION_FLAG", "SENT_TO_CLIENT"}
                for _, ev in events.iterrows():
                    if str(ev.get("event_type") or "").upper() in hidden_events:
                        continue
                    st.markdown(f"- {_fmt_event(ev)}")
