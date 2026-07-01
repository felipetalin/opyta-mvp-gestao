# app/pages/7_Reembolsos.py
"""
Reembolsos & Despesas Internas.

Controle de despesas pagas por colaboradores em nome da empresa, com
passivo atual, pagamentos, comprovantes e historico de alteracoes.
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
import html
import re
import uuid

import pandas as pd
import streamlit as st

from services.auth import require_login
from services.supabase_client import get_authed_client
from services.finance_guard import can_finance_write

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
st.set_page_config(page_title="Reembolsos", layout="wide")
apply_brand()
apply_app_chrome()

require_login()
sb = get_authed_client()
cache_key = str(st.session_state.get("access_token") or "no-token")

user_email = (st.session_state.get("user_email") or "").strip().lower()
can_write = can_finance_write(user_email)

page_header(
    "Reembolsos & Despesas Internas",
    "Controle de despesas, comprovantes, pagamentos e passivo por colaborador/projeto",
    user_email,
)
if not can_write:
    st.info("Acesso em modo leitura: voce pode consultar, mas nao criar/editar/excluir lancamentos.")


# ==========================================================
# Constantes
# ==========================================================
BUCKET = "reimbursement-receipts"
ALLOWED_MIMES = {"application/pdf", "image/jpeg", "image/png"}
ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}

STATUS_OPTIONS = ["PENDENTE", "APROVADO", "PAGO", "GLOSADO"]
STATUS_LABEL = {
    "PENDENTE": "🟡 Pendente",
    "APROVADO": "🔵 Aprovado",
    "PAGO": "🟢 Pago",
    "GLOSADO": "⚫ Glosado",
}
LABEL_TO_STATUS = {v: k for k, v in STATUS_LABEL.items()}
LABEL_TO_STATUS.update(
    {
        "Pendente": "PENDENTE",
        "Aprovado": "APROVADO",
        "Pago": "PAGO",
        "Glosado": "GLOSADO",
    }
)

SITUATION_OPTIONS = ["ATRASADO", "PENDENTE", "APROVADO", "PAGO", "GLOSADO"]
SITUATION_LABEL = {
    "ATRASADO": "🔴 Atrasado",
    "PENDENTE": "🟡 Pendente",
    "APROVADO": "🔵 Aprovado",
    "PAGO": "🟢 Pago",
    "GLOSADO": "⚫ Glosado",
}

EVENT_LABEL = {
    "CREATED": "Lancamento criado",
    "STATUS_CHANGE": "Status alterado",
    "DUE_DATE_CHANGE": "Prazo de pagamento alterado",
    "PAYMENT_DATE_CHANGE": "Data de pagamento alterada",
    "UPDATED": "Campos atualizados",
    "ATTACHMENT_ADDED": "Comprovante anexado",
    "ATTACHMENT_REMOVED": "Comprovante removido",
}

SORT_OPTIONS = {
    "Data da despesa (mais recente)": ("expense_date", False),
    "Data da despesa (mais antiga)": ("expense_date", True),
    "Prazo de pagamento (mais proximo)": ("due_date", True),
    "Prazo de pagamento (mais distante)": ("due_date", False),
    "Valor (maior primeiro)": ("amount", False),
    "Valor (menor primeiro)": ("amount", True),
    "Situacao": ("__situation_priority", True),
    "Status": ("__status_priority", True),
    "Atualizado recentemente": ("updated_at", False),
    "Colaborador (A-Z)": ("collaborator_name", True),
    "Projeto (A-Z)": ("project_code", True),
}
STATUS_PRIORITY = {"PENDENTE": 0, "APROVADO": 1, "PAGO": 2, "GLOSADO": 3}
SITUATION_PRIORITY = {
    SITUATION_LABEL["ATRASADO"]: 0,
    SITUATION_LABEL["PENDENTE"]: 1,
    SITUATION_LABEL["APROVADO"]: 2,
    SITUATION_LABEL["PAGO"]: 3,
    SITUATION_LABEL["GLOSADO"]: 4,
}


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


def _is_missing_reimbursement_schema(e: Exception) -> bool:
    msg = _api_error_message(e)
    return "PGRST205" in msg and "reimbursement" in msg


def _show_missing_schema_notice(e: Exception) -> None:
    st.error("O modulo de Reembolsos ja esta publicado, mas a migration ainda nao foi aplicada no Supabase.")
    st.markdown(
        "Aplique o arquivo `migrations/2026_07_01_reimbursements.sql` no **SQL Editor** do Supabase "
        "e depois recarregue esta pagina."
    )
    with st.expander("Detalhe tecnico"):
        st.code(_api_error_message(e))


def norm(x) -> str:
    return ("" if x is None else str(x)).strip()


def norm_text(x) -> str | None:
    s = norm(x)
    if s in ("", "None", "nan", "NaT"):
        return None
    return s


def _clean_str(x) -> str:
    s = norm(x)
    return "" if s in ("None", "nan", "NaT") else s


def _html(x) -> str:
    return html.escape(_clean_str(x))


def to_date(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        if isinstance(x, date) and not isinstance(x, datetime):
            return x
        if isinstance(x, str) and "/" in x:
            dt = pd.to_datetime(x, dayfirst=True, errors="coerce")
        else:
            dt = pd.to_datetime(x, errors="coerce")
        return dt.date() if not pd.isna(dt) else None
    except Exception:
        return None


def _brl(v: float) -> str:
    return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def situation_for(status: str | None, due_date, today_: date) -> str:
    status_norm = (status or "PENDENTE").strip().upper()
    if status_norm == "PAGO":
        return SITUATION_LABEL["PAGO"]
    if status_norm == "GLOSADO":
        return SITUATION_LABEL["GLOSADO"]

    due = to_date(due_date)
    if due is not None and due < today_:
        return SITUATION_LABEL["ATRASADO"]
    if status_norm == "APROVADO":
        return SITUATION_LABEL["APROVADO"]
    return SITUATION_LABEL["PENDENTE"]


def _safe_text_list(series: pd.Series, default: str = "") -> list[str]:
    out: list[str] = []
    for v in series.tolist():
        s = _clean_str(v)
        out.append(s if s else default)
    return out


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _add_months(d: date, n: int) -> date:
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return date(y, m, 1)


def _month_label(d: date) -> str:
    meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    return f"{meses[d.month - 1]}/{d.year}"


def _file_name_safe(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "comprovante")
    return stem[:120] or "comprovante"


def _mime_for_file(uploaded) -> str:
    mime = norm(getattr(uploaded, "type", ""))
    if mime in ALLOWED_MIMES:
        return mime
    name = norm(getattr(uploaded, "name", "")).lower()
    if name.endswith(".pdf"):
        return "application/pdf"
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".jpg") or name.endswith(".jpeg"):
        return "image/jpeg"
    return mime


def _signed_url(bucket: str, path: str) -> str | None:
    try:
        resp = sb.storage.from_(bucket).create_signed_url(path, 3600)
        if isinstance(resp, dict):
            return (
                resp.get("signedURL")
                or resp.get("signedUrl")
                or resp.get("signed_url")
                or resp.get("data", {}).get("signedURL")
            )
        data = getattr(resp, "data", None)
        if isinstance(data, dict):
            return data.get("signedURL") or data.get("signedUrl") or data.get("signed_url")
        return getattr(resp, "signedURL", None) or getattr(resp, "signed_url", None)
    except Exception:
        return None


def apply_data_editor_state(base: pd.DataFrame, returned: pd.DataFrame, key: str) -> pd.DataFrame:
    out = returned.copy()
    if len(out) == len(base):
        out.index = base.index.copy()

    state = st.session_state.get(key)
    if not isinstance(state, dict):
        return out

    for row_key, changes in (state.get("edited_rows") or {}).items():
        if not isinstance(changes, dict):
            continue
        try:
            pos = int(row_key)
            if not (0 <= pos < len(out)):
                continue
            idx = out.index[pos]
        except Exception:
            continue
        for col, val in changes.items():
            if col in out.columns:
                out.at[idx, col] = val
    return out


def sb_paginate(table: str, *, select: str = "*", order_col: str | None = None,
                desc: bool = False, page_size: int = 1000) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        q = sb.table(table).select(select).range(offset, offset + page_size - 1)
        if order_col:
            q = q.order(order_col, desc=desc)
        resp = q.execute()
        chunk = resp.data or []
        out.extend(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
    return out


# ==========================================================
# Fetchs
# ==========================================================
@st.cache_data(ttl=30)
def load_reimbursements(_k: str) -> pd.DataFrame:
    data = sb_paginate("v_reimbursements", order_col="expense_date", desc=True)
    return pd.DataFrame(data)


@st.cache_data(ttl=300)
def load_people(_k: str) -> pd.DataFrame:
    res = sb.table("people").select("id,name").order("name").execute()
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=300)
def load_projects(_k: str) -> pd.DataFrame:
    res = sb.table("projects").select("id,project_code,name").order("project_code").execute()
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=300)
def load_categories(_k: str) -> pd.DataFrame:
    res = (
        sb.table("reimbursement_categories")
        .select("id,name,active,sort_order")
        .eq("active", True)
        .order("sort_order")
        .order("name")
        .execute()
    )
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def load_attachments(_k: str, reimbursement_id: str) -> pd.DataFrame:
    res = (
        sb.table("reimbursement_attachments")
        .select("id,reimbursement_id,file_name,storage_bucket,storage_path,mime_type,file_size,uploaded_at,uploaded_by_email")
        .eq("reimbursement_id", reimbursement_id)
        .order("uploaded_at", desc=True)
        .execute()
    )
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def load_events(_k: str, reimbursement_id: str) -> pd.DataFrame:
    res = (
        sb.table("reimbursement_events")
        .select("event_type,from_value,to_value,notes,changed_by_email,changed_at")
        .eq("reimbursement_id", reimbursement_id)
        .order("changed_at", desc=True)
        .limit(100)
        .execute()
    )
    return pd.DataFrame(res.data or [])


def clear_caches() -> None:
    load_reimbursements.clear()
    load_people.clear()
    load_projects.clear()
    load_categories.clear()
    load_attachments.clear()
    load_events.clear()


def _reset_editor_state() -> None:
    for key in list(st.session_state.keys()):
        if str(key).startswith("reimbursements_editor::"):
            del st.session_state[key]


def _upload_receipts(reimbursement_id: str, files: list, actor_email: str) -> tuple[int, list[str]]:
    ok = 0
    errors: list[str] = []

    for uploaded in files or []:
        file_name = _file_name_safe(getattr(uploaded, "name", "comprovante"))
        mime = _mime_for_file(uploaded)
        ext = "." + file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""

        if mime not in ALLOWED_MIMES or ext not in ALLOWED_EXTS:
            errors.append(f"{file_name}: formato nao permitido.")
            continue

        data = uploaded.getvalue()
        path = f"{reimbursement_id}/{uuid.uuid4().hex}_{file_name}"

        try:
            sb.storage.from_(BUCKET).upload(
                path,
                data,
                file_options={"content-type": mime, "upsert": "false"},
            )
            sb.table("reimbursement_attachments").insert(
                {
                    "reimbursement_id": reimbursement_id,
                    "file_name": file_name,
                    "storage_bucket": BUCKET,
                    "storage_path": path,
                    "mime_type": mime,
                    "file_size": len(data),
                    "uploaded_by_email": actor_email or None,
                }
            ).execute()
            ok += 1
        except Exception as e:
            errors.append(f"{file_name}: {_api_error_message(e)}")

    if ok:
        load_attachments.clear()
        load_events.clear()
        load_reimbursements.clear()
    return ok, errors


# ==========================================================
# Dados de referencia
# ==========================================================
try:
    people_df = load_people(cache_key)
    projects_df = load_projects(cache_key)
    categories_df = load_categories(cache_key)
except Exception as e:
    if _is_missing_reimbursement_schema(e):
        _show_missing_schema_notice(e)
    else:
        st.error("Nao foi possivel carregar o modulo de Reembolsos.")
        st.code(_api_error_message(e))
    st.stop()

people_options: dict[str, str] = {}
if not people_df.empty:
    for _, row in people_df.iterrows():
        people_options[_clean_str(row.get("name"))] = _clean_str(row.get("id"))

project_options: dict[str, str] = {}
if not projects_df.empty:
    for _, row in projects_df.iterrows():
        label = f"{_clean_str(row.get('project_code'))} - {_clean_str(row.get('name'))}".strip(" -")
        project_options[label] = _clean_str(row.get("id"))

category_options: dict[str, str] = {}
if not categories_df.empty:
    for _, row in categories_df.iterrows():
        category_options[_clean_str(row.get("name"))] = _clean_str(row.get("id"))


# ==========================================================
# Cadastro rapido de categoria
# ==========================================================
with st.expander("Cadastrar categoria de despesa", expanded=False):
    if not can_write:
        st.caption("Somente leitura para seu usuario.")
    else:
        with st.form("new_reimbursement_category", clear_on_submit=True):
            c1, c2, c3 = st.columns([2.0, 1.0, 1.0])
            with c1:
                new_cat_name = st.text_input("Nome da categoria", placeholder="Ex.: Taxi, estacionamento, ART...")
            with c2:
                new_cat_order = st.number_input("Ordem", min_value=1, max_value=9999, value=100, step=10)
            with c3:
                st.write("")
                st.write("")
                submit_cat = st.form_submit_button("Adicionar", type="primary")

            if submit_cat:
                name = norm(new_cat_name)
                if not name:
                    st.error("Informe o nome da categoria.")
                elif name in category_options:
                    st.warning("Essa categoria ja existe.")
                else:
                    try:
                        sb.table("reimbursement_categories").insert(
                            {"name": name, "sort_order": int(new_cat_order)}
                        ).execute()
                        st.success("Categoria cadastrada.")
                        clear_caches()
                        st.rerun()
                    except Exception as e:
                        st.error("Falha ao cadastrar categoria:")
                        st.code(_api_error_message(e))


# ==========================================================
# Novo lancamento
# ==========================================================
with st.expander("Novo reembolso / despesa interna", expanded=False):
    if not can_write:
        st.caption("Somente leitura para seu usuario.")
    elif not people_options:
        st.warning("Nenhum colaborador encontrado. Cadastre pessoas antes de lancar reembolsos.")
    elif not project_options:
        st.warning("Nenhum projeto encontrado. Cadastre projetos antes de lancar reembolsos.")
    elif not category_options:
        st.warning("Nenhuma categoria de despesa encontrada.")
    else:
        with st.form("new_reimbursement", clear_on_submit=True):
            a1, a2, a3, a4 = st.columns([1.1, 1.7, 2.0, 1.4])
            with a1:
                new_expense_date = st.date_input("Data da despesa *", value=date.today(), format="DD/MM/YYYY")
            with a2:
                new_collaborator = st.selectbox("Colaborador *", list(people_options.keys()))
            with a3:
                new_project = st.selectbox("Projeto *", list(project_options.keys()))
            with a4:
                new_status_label = st.selectbox(
                    "Status *",
                    [STATUS_LABEL[s] for s in STATUS_OPTIONS],
                    index=0,
                )

            b1, b2, b3, b4 = st.columns([1.8, 1.0, 1.0, 1.0])
            with b1:
                new_category = st.selectbox("Categoria da despesa *", list(category_options.keys()))
            with b2:
                new_amount = st.number_input("Valor (R$) *", min_value=0.01, value=0.01, step=10.0)
            with b3:
                new_due_date = st.date_input("Prazo de pagamento *", value=date.today(), format="DD/MM/YYYY")
            with b4:
                new_payment_date = st.date_input("Data do pagamento", value=None, format="DD/MM/YYYY")

            new_description = st.text_input("Descricao *", placeholder="Ex.: hospedagem durante vistoria de campo")
            new_observations = st.text_area("Observacoes", value="", height=80)
            new_files = st.file_uploader(
                "Comprovantes (PDF, JPG ou PNG)",
                type=["pdf", "jpg", "jpeg", "png"],
                accept_multiple_files=True,
            )

            submitted = st.form_submit_button("Salvar lancamento", type="primary")
            if submitted:
                status_new = LABEL_TO_STATUS.get(new_status_label, "PENDENTE")
                due_date = to_date(new_due_date)
                pay_date = to_date(new_payment_date)

                if norm(new_description) == "":
                    st.error("Descricao e obrigatoria.")
                elif due_date is None:
                    st.error("Prazo de pagamento e obrigatorio.")
                elif status_new == "PAGO" and pay_date is None:
                    st.error("Despesas com status Pago precisam de Data do pagamento.")
                else:
                    payload = {
                        "expense_date": new_expense_date.isoformat() if new_expense_date else None,
                        "collaborator_id": people_options[new_collaborator],
                        "project_id": project_options[new_project],
                        "category_id": category_options[new_category],
                        "description": norm(new_description),
                        "amount": float(new_amount),
                        "status": status_new,
                        "due_date": due_date.isoformat(),
                        "payment_date": pay_date.isoformat() if status_new == "PAGO" and pay_date else None,
                        "observations": norm_text(new_observations),
                        "created_by_email": user_email or None,
                        "updated_by_email": user_email or None,
                    }
                    try:
                        res = sb.table("reimbursements").insert(payload, returning="representation").execute()
                        row = (res.data or [None])[0]
                        if not row:
                            st.error("Insert nao retornou linha. Verifique permissoes/RLS.")
                        else:
                            rid = str(row["id"])
                            ok_files, file_errors = _upload_receipts(rid, new_files, user_email)
                            clear_caches()
                            msg = "Lancamento criado."
                            if ok_files:
                                msg += f" Comprovantes anexados: {ok_files}."
                            st.success(msg)
                            for err in file_errors:
                                st.warning(err)
                            st.rerun()
                    except Exception as e:
                        st.error("Falha ao salvar lancamento:")
                        st.code(_api_error_message(e))


# ==========================================================
# Carrega lancamentos
# ==========================================================
try:
    with st.spinner("Carregando reembolsos..."):
        df = load_reimbursements(cache_key)
except Exception as e:
    if _is_missing_reimbursement_schema(e):
        _show_missing_schema_notice(e)
    else:
        st.error("Erro ao carregar reembolsos.")
        st.code(_api_error_message(e))
    st.stop()

if df.empty:
    st.info("Nenhum reembolso cadastrado ainda. Use **Novo reembolso / despesa interna** acima.")
    st.stop()

today = date.today()

for col, default in [
    ("receipt_count", 0),
    ("observations", ""),
    ("due_date", None),
    ("payment_date", None),
    ("updated_at", None),
    ("created_at", None),
]:
    if col not in df.columns:
        df[col] = default

df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
df["expense_date_dt"] = pd.to_datetime(df["expense_date"], errors="coerce").dt.date
df["due_date_dt"] = pd.to_datetime(df["due_date"], errors="coerce").dt.date
df["due_date_dt"] = df["due_date_dt"].where(df["due_date_dt"].notna(), df["expense_date_dt"])
df["due_date"] = df["due_date_dt"]
df["payment_date_dt"] = pd.to_datetime(df["payment_date"], errors="coerce").dt.date
df["status"] = df["status"].fillna("PENDENTE").astype(str).str.upper()
df["__situacao"] = [situation_for(s, d, today) for s, d in zip(df["status"].tolist(), df["due_date_dt"].tolist())]
df["__status_priority"] = df["status"].map(STATUS_PRIORITY).fillna(99).astype(int)
df["__situation_priority"] = df["__situacao"].map(SITUATION_PRIORITY).fillna(99).astype(int)


# ==========================================================
# Filtros
# ==========================================================
st.subheader("Filtros")

expense_dates = [d for d in df["expense_date_dt"].tolist() if isinstance(d, date)]
default_from = min(expense_dates) if expense_dates else _month_start(today)
default_to = max(expense_dates) if expense_dates else today

with st.container(border=True):
    f1, f2, f3, f4, f5 = st.columns([1.1, 1.1, 1.7, 1.8, 1.5])
    with f1:
        date_from = st.date_input("De", value=default_from, format="DD/MM/YYYY", key="reimb_filter_from_v2")
    with f2:
        date_to = st.date_input("Ate", value=default_to, format="DD/MM/YYYY", key="reimb_filter_to_v2")
    with f3:
        f_collaborators = st.multiselect(
            "Colaborador",
            sorted({x for x in _safe_text_list(df["collaborator_name"]) if x}),
            default=[],
        )
    with f4:
        f_projects = st.multiselect(
            "Projeto",
            sorted({x for x in _safe_text_list(df["project_code"]) if x}),
            default=[],
        )
    with f5:
        f_status_labels = st.multiselect(
            "Status",
            [STATUS_LABEL[s] for s in STATUS_OPTIONS],
            default=[],
        )

    g1, g2, g3, g4 = st.columns([1.4, 1.6, 2.2, 1.4])
    with g1:
        f_situation_labels = st.multiselect(
            "Situacao",
            [SITUATION_LABEL[s] for s in SITUATION_OPTIONS],
            default=[],
        )
    with g2:
        f_categories = st.multiselect(
            "Categoria",
            sorted({x for x in _safe_text_list(df["category_name"]) if x}),
            default=[],
        )
    with g3:
        search = st.text_input(
            "Buscar",
            value="",
            placeholder="Descricao, observacao, colaborador, projeto...",
        )
    with g4:
        sort_label = st.selectbox("Ordenar por", list(SORT_OPTIONS.keys()), index=0)

    h1, h2, h3 = st.columns([1.0, 1.2, 3.8])
    with h1:
        if st.button("Recarregar"):
            clear_caches()
            _reset_editor_state()
            st.rerun()
    with h2:
        if st.button("Mostrar todos"):
            st.session_state["reimb_filter_from_v2"] = default_from
            st.session_state["reimb_filter_to_v2"] = default_to
            clear_caches()
            _reset_editor_state()
            st.rerun()
    with h3:
        st.caption(
            "Atraso e calculado automaticamente pelo Prazo de pagamento. Pago e Glosado encerram a pendencia operacional."
        )

if date_from > date_to:
    st.error("A data inicial nao pode ser maior que a data final.")
    st.stop()

mask = pd.Series(True, index=df.index)
mask &= df["expense_date_dt"].between(date_from, date_to)
if f_collaborators:
    mask &= df["collaborator_name"].isin(f_collaborators)
if f_projects:
    mask &= df["project_code"].isin(f_projects)
if f_categories:
    mask &= df["category_name"].isin(f_categories)
if f_status_labels:
    selected_status = [LABEL_TO_STATUS.get(s, s) for s in f_status_labels]
    mask &= df["status"].isin(selected_status)
if f_situation_labels:
    mask &= df["__situacao"].isin(f_situation_labels)

df_f = df.loc[mask].copy().reset_index(drop=True)

if search.strip():
    q = search.strip().lower()
    haystack = (
        df_f["description"].fillna("").astype(str).str.lower() + " | "
        + df_f["observations"].fillna("").astype(str).str.lower() + " | "
        + df_f["collaborator_name"].fillna("").astype(str).str.lower() + " | "
        + df_f["project_code"].fillna("").astype(str).str.lower() + " | "
        + df_f["project_name"].fillna("").astype(str).str.lower() + " | "
        + df_f["category_name"].fillna("").astype(str).str.lower() + " | "
        + df_f["__situacao"].fillna("").astype(str).str.lower()
    )
    df_f = df_f.loc[haystack.str.contains(q, na=False, regex=False)].reset_index(drop=True)

sort_col, sort_asc = SORT_OPTIONS[sort_label]
if sort_col in df_f.columns and not df_f.empty:
    df_f = df_f.sort_values(sort_col, ascending=sort_asc, na_position="last").reset_index(drop=True)


# ==========================================================
# Indicadores
# ==========================================================
st.divider()
st.subheader("Indicadores")

if df_f.empty:
    if expense_dates:
        st.info(
            "Nenhum lancamento corresponde aos filtros atuais. "
            f"Existem {len(df)} lancamento(s) cadastrados entre "
            f"{default_from.strftime('%d/%m/%Y')} e {default_to.strftime('%d/%m/%Y')}."
        )
    else:
        st.info("Nenhum lancamento corresponde aos filtros atuais.")
    st.stop()

pending_df = df_f[df_f["status"] == "PENDENTE"]
paid_df = df_f[df_f["status"] == "PAGO"]
open_df = df_f[df_f["status"].isin(["PENDENTE", "APROVADO"])]
overdue_df = df_f[df_f["__situacao"] == SITUATION_LABEL["ATRASADO"]]

total_pending = float(pending_df["amount"].sum())
total_paid = float(paid_df["amount"].sum())
qty_pending = int(len(pending_df))
qty_overdue = int(len(overdue_df))

k1, k2, k3, k4 = st.columns(4)
k1.metric("🟡 Total pendente de reembolso", _brl(total_pending))
k2.metric("🟢 Total pago", _brl(total_paid))
k3.metric("🟡 Despesas pendentes", qty_pending)
k4.metric("🔴 Despesas atrasadas", qty_overdue)

rp1, rp2 = st.columns(2)
with rp1:
    by_collab = (
        open_df.groupby("collaborator_name", dropna=False)["amount"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={"collaborator_name": "Colaborador", "amount": "Valor em aberto"})
    )
    if by_collab.empty:
        st.caption("Sem valores em aberto por colaborador nos filtros atuais.")
    else:
        view = by_collab.copy()
        view["Valor em aberto"] = view["Valor em aberto"].apply(_brl)
        st.dataframe(view, use_container_width=True, hide_index=True)

with rp2:
    by_project = (
        open_df.groupby("project_code", dropna=False)["amount"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={"project_code": "Projeto", "amount": "Valor em aberto"})
    )
    if by_project.empty:
        st.caption("Sem valores em aberto por projeto nos filtros atuais.")
    else:
        view = by_project.copy()
        view["Valor em aberto"] = view["Valor em aberto"].apply(_brl)
        st.dataframe(view, use_container_width=True, hide_index=True)


# ==========================================================
# Exportacao
# ==========================================================
st.divider()

def _build_export_df(_df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "Data da despesa": [to_date(x) for x in _df["expense_date"].tolist()],
            "Colaborador": _safe_text_list(_df["collaborator_name"]),
            "Projeto": _safe_text_list(_df["project_code"]),
            "Nome do projeto": _safe_text_list(_df["project_name"]),
            "Categoria": _safe_text_list(_df["category_name"]),
            "Descricao": _safe_text_list(_df["description"]),
            "Valor (R$)": pd.to_numeric(_df["amount"], errors="coerce").fillna(0.0).tolist(),
            "Status": [STATUS_LABEL.get(s, s) for s in _safe_text_list(_df["status"])],
            "Situacao": _safe_text_list(_df["__situacao"]),
            "Prazo de pagamento": [to_date(x) for x in _df["due_date"].tolist()],
            "Data do pagamento": [to_date(x) for x in _df["payment_date"].tolist()],
            "Observacoes": _safe_text_list(_df["observations"]),
            "Comprovantes": pd.to_numeric(_df["receipt_count"], errors="coerce").fillna(0).astype(int).tolist(),
            "Criado por": _safe_text_list(_df["created_by_email"]),
            "Atualizado por": _safe_text_list(_df["updated_by_email"]),
        }
    )
    return out


export_df = _build_export_df(df_f)
csv_bytes = export_df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
ec1, ec2, _ = st.columns([1.2, 1.2, 4])
ec1.download_button(
    "Exportar CSV",
    data=csv_bytes,
    file_name=f"reembolsos_{today.isoformat()}.csv",
    mime="text/csv",
)
try:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Reembolsos")
    ec2.download_button(
        "Exportar Excel",
        data=buf.getvalue(),
        file_name=f"reembolsos_{today.isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
except Exception as e:
    ec2.caption(f"Excel indisponivel: {_api_error_message(e)}")


# ==========================================================
# Editor principal
# ==========================================================
st.subheader("Lancamentos")
st.caption("Edite os campos e clique em Salvar alteracoes. Marque Excluir? para remover lancamentos.")

id_list = _safe_text_list(df_f["id"])
collab_label_by_id = {v: k for k, v in people_options.items()}
project_label_by_id = {v: k for k, v in project_options.items()}
category_label_by_id = {v: k for k, v in category_options.items()}

df_edit = pd.DataFrame(
    {
        "id": id_list,
        "Excluir?": [False] * len(df_f),
        "Data da despesa": [to_date(x) for x in df_f["expense_date"].tolist()],
        "Colaborador": [
            collab_label_by_id.get(_clean_str(x), _clean_str(n))
            for x, n in zip(df_f["collaborator_id"].tolist(), df_f["collaborator_name"].tolist())
        ],
        "Projeto": [
            project_label_by_id.get(_clean_str(x), _clean_str(c))
            for x, c in zip(df_f["project_id"].tolist(), df_f["project_code"].tolist())
        ],
        "Categoria": [
            category_label_by_id.get(_clean_str(x), _clean_str(n))
            for x, n in zip(df_f["category_id"].tolist(), df_f["category_name"].tolist())
        ],
        "Descricao": _safe_text_list(df_f["description"]),
        "Valor (R$)": pd.to_numeric(df_f["amount"], errors="coerce").fillna(0.0).tolist(),
        "Status": [STATUS_LABEL.get(s, s) for s in _safe_text_list(df_f["status"], "PENDENTE")],
        "Situacao": _safe_text_list(df_f["__situacao"]),
        "Prazo de pagamento": [to_date(x) for x in df_f["due_date"].tolist()],
        "Data do pagamento": [to_date(x) for x in df_f["payment_date"].tolist()],
        "Observacoes": _safe_text_list(df_f["observations"]),
        "Comprovantes": pd.to_numeric(df_f["receipt_count"], errors="coerce").fillna(0).astype(int).tolist(),
    }
).reset_index(drop=True)

editor_signature = hash(
    (
        tuple(id_list),
        date_from,
        date_to,
        tuple(f_collaborators),
        tuple(f_projects),
        tuple(f_categories),
        tuple(f_status_labels),
        tuple(f_situation_labels),
        search.strip(),
        sort_label,
    )
)
editor_key = f"reimbursements_editor::{editor_signature}"

edited = st.data_editor(
    df_edit,
    key=editor_key,
    use_container_width=True,
    hide_index=True,
    disabled=not can_write,
    num_rows="fixed",
    column_order=[
        "Excluir?",
        "Data da despesa",
        "Colaborador",
        "Projeto",
        "Categoria",
        "Descricao",
        "Valor (R$)",
        "Status",
        "Situacao",
        "Prazo de pagamento",
        "Data do pagamento",
        "Observacoes",
        "Comprovantes",
    ],
    column_config={
        "Excluir?": st.column_config.CheckboxColumn(width="small"),
        "Data da despesa": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Colaborador": st.column_config.SelectboxColumn(options=list(people_options.keys()), width="medium"),
        "Projeto": st.column_config.SelectboxColumn(options=list(project_options.keys()), width="medium"),
        "Categoria": st.column_config.SelectboxColumn(options=list(category_options.keys()), width="medium"),
        "Descricao": st.column_config.TextColumn(width="large"),
        "Valor (R$)": st.column_config.NumberColumn(min_value=0.01, step=10.0, format="R$ %.2f", width="small"),
        "Status": st.column_config.SelectboxColumn(options=[STATUS_LABEL[s] for s in STATUS_OPTIONS], width="small"),
        "Situacao": st.column_config.TextColumn(disabled=True, width="small"),
        "Prazo de pagamento": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Data do pagamento": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Observacoes": st.column_config.TextColumn(width="large"),
        "Comprovantes": st.column_config.NumberColumn(disabled=True, width="small"),
    },
)
edited = apply_data_editor_state(df_edit, edited, editor_key)

save_col, reload_col, _ = st.columns([1.0, 1.0, 4.0])
save_btn = save_col.button("Salvar alteracoes", type="primary", disabled=not can_write)
reload_btn = reload_col.button("Recarregar tabela")

if reload_btn:
    clear_caches()
    _reset_editor_state()
    st.rerun()

delete_rows = edited[edited["Excluir?"] == True]  # noqa: E712
delete_ids = delete_rows["id"].astype(str).tolist() if not delete_rows.empty else []
confirm_delete = False
if delete_ids:
    with st.container(border=True):
        st.error(f"Exclusao: {len(delete_ids)} lancamento(s) marcado(s).")
        confirm_delete = st.checkbox("Confirmo a exclusao definitiva dos lancamentos marcados", value=False)

if save_btn:
    if not can_write:
        st.warning("Seu perfil nao possui permissao de escrita.")
        st.stop()

    before = df_edit.copy()
    after = edited.copy()
    warnings: list[str] = []
    n_updates = 0
    n_deletes = 0

    if delete_ids:
        if not confirm_delete:
            st.warning("Marque a confirmacao para excluir os lancamentos selecionados.")
            st.stop()

        for rid in delete_ids:
            try:
                att = load_attachments(cache_key, rid)
                if not att.empty:
                    paths = _safe_text_list(att["storage_path"])
                    try:
                        sb.storage.from_(BUCKET).remove(paths)
                    except Exception:
                        pass
                sb.table("reimbursements").delete().eq("id", rid).execute()
                n_deletes += 1
            except Exception as e:
                warnings.append(f"Erro ao excluir {rid}: {_api_error_message(e)}")

    for i in range(len(after)):
        rid = str(after.loc[i, "id"])
        if rid in delete_ids:
            continue

        compare_cols = [
            "Data da despesa",
            "Colaborador",
            "Projeto",
            "Categoria",
            "Descricao",
            "Valor (R$)",
            "Status",
            "Prazo de pagamento",
            "Data do pagamento",
            "Observacoes",
        ]
        if all(norm(before.loc[i, c]) == norm(after.loc[i, c]) for c in compare_cols):
            continue

        expense_date = to_date(after.loc[i, "Data da despesa"])
        status = LABEL_TO_STATUS.get(norm(after.loc[i, "Status"]), "PENDENTE")
        due_date = to_date(after.loc[i, "Prazo de pagamento"])
        payment_date = to_date(after.loc[i, "Data do pagamento"])
        amount = float(after.loc[i, "Valor (R$)"] or 0)

        if expense_date is None:
            warnings.append(f"{rid}: Data da despesa vazia. Atualizacao ignorada.")
            continue
        if due_date is None:
            warnings.append(f"{rid}: Prazo de pagamento vazio. Atualizacao ignorada.")
            continue
        if amount <= 0:
            warnings.append(f"{rid}: Valor deve ser maior que zero. Atualizacao ignorada.")
            continue
        if norm(after.loc[i, "Descricao"]) == "":
            warnings.append(f"{rid}: Descricao obrigatoria. Atualizacao ignorada.")
            continue
        if status == "PAGO" and payment_date is None:
            warnings.append(f"{rid}: status Pago exige Data do pagamento. Atualizacao ignorada.")
            continue

        payload = {
            "expense_date": expense_date.isoformat(),
            "collaborator_id": people_options.get(norm(after.loc[i, "Colaborador"])),
            "project_id": project_options.get(norm(after.loc[i, "Projeto"])),
            "category_id": category_options.get(norm(after.loc[i, "Categoria"])),
            "description": norm(after.loc[i, "Descricao"]),
            "amount": amount,
            "status": status,
            "due_date": due_date.isoformat(),
            "payment_date": payment_date.isoformat() if status == "PAGO" and payment_date else None,
            "observations": norm_text(after.loc[i, "Observacoes"]),
            "updated_by_email": user_email or None,
        }

        if not payload["collaborator_id"] or not payload["project_id"] or not payload["category_id"]:
            warnings.append(f"{rid}: colaborador, projeto ou categoria invalido. Atualizacao ignorada.")
            continue

        try:
            sb.table("reimbursements").update(payload, returning="representation").eq("id", rid).execute()
            n_updates += 1
        except Exception as e:
            warnings.append(f"Erro ao atualizar {rid}: {_api_error_message(e)}")

    if warnings:
        st.warning("\n".join(warnings))

    st.success(f"Atualizados: {n_updates} - Excluidos: {n_deletes}")
    clear_caches()
    _reset_editor_state()
    st.rerun()


# ==========================================================
# Comprovantes e historico
# ==========================================================
st.divider()
st.subheader("Comprovantes e historico")

label_to_id: dict[str, str] = {}
for _, row in df_f.iterrows():
    d = to_date(row.get("expense_date"))
    d_txt = d.strftime("%d/%m/%Y") if d else ""
    label = (
        f"{_clean_str(row.get('__situacao'))} - {d_txt} - {_clean_str(row.get('collaborator_name'))} - "
        f"{_clean_str(row.get('project_code'))} - {_brl(float(row.get('amount') or 0))}"
    )
    label_to_id[label] = _clean_str(row.get("id"))

selected_label = st.selectbox("Lancamento", list(label_to_id.keys()))
selected_id = label_to_id[selected_label]

att_col, hist_col = st.columns([1.1, 1.0])
with att_col:
    st.caption("Comprovantes vinculados")

    if can_write:
        new_receipts = st.file_uploader(
            "Adicionar comprovantes",
            type=["pdf", "jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key=f"receipt_uploader_{selected_id}",
        )
        if st.button("Anexar comprovantes", type="primary", disabled=not new_receipts, key=f"upload_btn_{selected_id}"):
            ok, errs = _upload_receipts(selected_id, new_receipts, user_email)
            if ok:
                st.success(f"Comprovantes anexados: {ok}.")
            for err in errs:
                st.warning(err)
            clear_caches()
            st.rerun()

    attachments = load_attachments(cache_key, selected_id)
    if attachments.empty:
        st.info("Nenhum comprovante anexado.")
    else:
        for _, a in attachments.iterrows():
            file_name = _clean_str(a.get("file_name"))
            mime = _clean_str(a.get("mime_type"))
            bucket = _clean_str(a.get("storage_bucket")) or BUCKET
            path = _clean_str(a.get("storage_path"))
            uploaded_at = _clean_str(a.get("uploaded_at"))
            url = _signed_url(bucket, path)

            with st.container(border=True):
                st.write(f"**{_html(file_name)}**")
                st.caption(f"{mime} - {uploaded_at}")
                if url:
                    if mime.startswith("image/"):
                        st.image(url, use_container_width=True)
                    st.link_button("Abrir comprovante", url)
                else:
                    st.warning("Nao foi possivel gerar link temporario para visualizacao.")

                if can_write:
                    remove_key = f"remove_attachment_{_clean_str(a.get('id'))}"
                    if st.button("Excluir comprovante", key=remove_key):
                        try:
                            try:
                                sb.storage.from_(bucket).remove([path])
                            except Exception:
                                pass
                            sb.table("reimbursement_attachments").delete().eq("id", _clean_str(a.get("id"))).execute()
                            st.success("Comprovante excluido.")
                            clear_caches()
                            st.rerun()
                        except Exception as e:
                            st.error("Falha ao excluir comprovante:")
                            st.code(_api_error_message(e))

with hist_col:
    st.caption("Historico de alteracoes")
    events = load_events(cache_key, selected_id)
    if events.empty:
        st.info("Sem eventos registrados.")
    else:
        for _, ev in events.iterrows():
            raw_ts = ev.get("changed_at")
            try:
                ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
            except Exception:
                ts = _clean_str(raw_ts)

            event_type = _clean_str(ev.get("event_type"))
            title = EVENT_LABEL.get(event_type, event_type)
            actor = _clean_str(ev.get("changed_by_email"))
            from_value = _clean_str(ev.get("from_value"))
            to_value = _clean_str(ev.get("to_value"))
            notes = _clean_str(ev.get("notes"))

            detail = ""
            if from_value or to_value:
                detail = f"`{from_value or '-'} -> {to_value or '-'}`"
            elif notes:
                detail = notes

            actor_txt = f" por `{actor}`" if actor else ""
            st.markdown(f"- **{ts}** - {title}{actor_txt}. {detail}")
