# app/pages/5_Produtos.py
"""
Acompanhamento operacional de Produtos / Entregas.

Reaproveita tarefas com tipo_atividade='RELATORIO' (cadastradas na aba Tarefas)
e adiciona uma camada de controle via task_delivery_tracking + timeline em
task_delivery_events. Nenhum cadastro novo de produto é feito aqui.
"""

from __future__ import annotations

from datetime import date, datetime

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
disc_all = sorted({d for d in safe_text_list(df["discipline"]) if d})
ent_all = sorted({e for e in safe_text_list(df["enterprise"]) if e})

fc1, fc2, fc3, fc4, fc5 = st.columns([1.4, 1.2, 1.4, 1.4, 1.0])
with fc1:
    f_projects = st.multiselect("Projeto", projects_all, default=[])
with fc2:
    f_disc = st.multiselect("Disciplina", disc_all, default=[])
with fc3:
    f_ent = st.multiselect("Empreendimento", ent_all, default=[])
with fc4:
    f_status = st.multiselect(
        "Status",
        DELIVERY_STATUS_OPTIONS,
        default=[],
        format_func=lambda s: STATUS_LABEL.get(s, s),
    )
with fc5:
    only_pending = st.toggle("Pendentes", value=False, help="Oculta ENTREGUE e FATURADO")

mask = pd.Series(True, index=df.index)
if f_projects:
    mask &= df["project_code"].isin(f_projects)
if f_disc:
    mask &= df["discipline"].isin(f_disc)
if f_ent:
    mask &= df["enterprise"].isin(f_ent)
if f_status:
    mask &= df["delivery_status"].isin(f_status)
if only_pending:
    mask &= ~df["delivery_status"].isin(["ENTREGUE", "FATURADO"])

df_f = df.loc[mask].reset_index(drop=True)


# ==========================================================
# Métricas
# ==========================================================
today = date.today()
end_dates = pd.to_datetime(df_f["end_date"], errors="coerce").dt.date

n_andamento = int(df_f["delivery_status"].isin(["EM_ELABORACAO", "EM_REVISAO"]).sum())
n_revisao = int(df_f["needs_revision"].fillna(False).astype(bool).sum())
atrasado_mask = (
    end_dates.notna()
    & (end_dates < today)
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

ids = safe_text_list(df_f["task_id"])

status_labels = [STATUS_LABEL.get(s, s) for s in safe_text_list(df_f["delivery_status"], "NAO_INICIADO")]

df_show = pd.DataFrame(
    {
        "Projeto": safe_text_list(df_f["project_code"]),
        "Produto": safe_text_list(df_f["product_name"]),
        "Disciplina": safe_text_list(df_f["discipline"]),
        "Empreendimento": safe_text_list(df_f["enterprise"]),
        "Status": status_labels,
        "Revisão?": df_f["needs_revision"].fillna(False).astype(bool).tolist(),
        "Enviado?": df_f["sent_to_client"].fillna(False).astype(bool).tolist(),
        "Entrega": [to_date(x) for x in df_f["delivery_date"].tolist()],
        "Faturamento": [to_date(x) for x in df_f["invoice_date"].tolist()],
        "Prazo": [to_date(x) for x in df_f["end_date"].tolist()],
        "Obs": safe_text_list(df_f["tracking_notes"]),
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
        "Projeto":        st.column_config.TextColumn(disabled=True, width="small"),
        "Produto":        st.column_config.TextColumn(disabled=True, width="large"),
        "Disciplina":     st.column_config.TextColumn(width="small"),
        "Empreendimento": st.column_config.TextColumn(width="medium"),
        "Status":         st.column_config.SelectboxColumn(options=status_label_options, width="medium"),
        "Revisão?":       st.column_config.CheckboxColumn(width="small"),
        "Enviado?":       st.column_config.CheckboxColumn(width="small"),
        "Entrega":        st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Faturamento":    st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Prazo":          st.column_config.DateColumn(format="DD/MM/YYYY", disabled=True, width="small"),
        "Obs":            st.column_config.TextColumn(width="large"),
    },
    key="deliverables_editor",
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

        diff = (
            before_status != after_status
            or bool(before["Revisão?"]) != bool(after["Revisão?"])
            or bool(before["Enviado?"]) != bool(after["Enviado?"])
            or (before["Entrega"] or None) != (after["Entrega"] or None)
            or (before["Faturamento"] or None) != (after["Faturamento"] or None)
            or norm_text(before["Disciplina"]) != norm_text(after["Disciplina"])
            or norm_text(before["Empreendimento"]) != norm_text(after["Empreendimento"])
            or norm_text(before["Obs"]) != norm_text(after["Obs"])
        )
        if not diff:
            continue

        changes.append(
            {
                "task_id": task_id,
                "delivery_status": after_status,
                "needs_revision": bool(after["Revisão?"]),
                "sent_to_client": bool(after["Enviado?"]),
                "delivery_date": after["Entrega"].isoformat() if after["Entrega"] else None,
                "invoice_date": after["Faturamento"].isoformat() if after["Faturamento"] else None,
                "discipline": norm_text(after["Disciplina"]),
                "enterprise": norm_text(after["Empreendimento"]),
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
