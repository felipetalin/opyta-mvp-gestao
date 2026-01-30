from __future__ import annotations

from datetime import date
import pandas as pd
import streamlit as st

from services.auth import require_login
from services.supabase_client import get_authed_client

# Branding (não pode quebrar o app se faltar algo)
try:
    from ui.brand import apply_brand, apply_app_chrome, page_header
except Exception:
    from ui.brand import apply_brand  # type: ignore

    def apply_app_chrome():  # type: ignore
        return

    def page_header(title, subtitle, user_email=""):  # type: ignore
        st.title(title)
        if subtitle:
            st.caption(subtitle)
        if user_email:
            st.caption(f"Logado como: {user_email}")


from app.finance.access import finance_guard
from app.finance.data import (
    set_sb,
    norm,
    api_error_message,
    fetch_projects,
    fetch_categories,
    fetch_counterparties,
    fetch_transactions_view,
    insert_transaction,
    clear_finance_caches,
)
from app.finance.dashboard import render_dashboard



# ==========================================================
# Boot (ordem obrigatória)
# ==========================================================
st.set_page_config(page_title="Financeiro", layout="wide")
apply_brand()
apply_app_chrome()

require_login()
sb = get_authed_client()
set_sb(sb)  # <<< CONSERVADOR: injeta sb no módulo data.py (cache não hasha sb)

user_email = (st.session_state.get("user_email") or "").strip().lower()
page_header("Financeiro", "Fase 2: dashboard + inserir lançamentos (sem editar/excluir)", user_email)

# Acesso restrito (Felipe + Yuri)
finance_guard(user_email)

today = date.today()
TYPE_OPTIONS = ["RECEITA", "DESPESA", "TRANSFERENCIA"]
STATUS_OPTIONS = ["PREVISTO", "REALIZADO", "CANCELADO"]

# ==========================================================
# Dashboard (somente leitura)
# ==========================================================
try:
    render_dashboard()
except Exception as e:
    st.error("Erro ao carregar dashboard:")
    st.code(api_error_message(e))

st.divider()

# ==========================================================
# Loads dropdowns
# ==========================================================
projects_df = fetch_projects()
categories_df = fetch_categories()
cp_df = fetch_counterparties()

proj_options = ["(Todos)"]
proj_map: dict[str, str | None] = {"(Todos)": None}
if not projects_df.empty:
    for _, r in projects_df.iterrows():
        label = f"{norm(r.get('project_code'))} — {norm(r.get('name'))}".strip(" —")
        proj_options.append(label)
        proj_map[label] = norm(r.get("id")) or None

cat_options = ["(Todas)"]
cat_map: dict[str, str | None] = {"(Todas)": None}
if not categories_df.empty:
    for _, r in categories_df.iterrows():
        label = norm(r.get("name"))
        cat_options.append(label)
        cat_map[label] = norm(r.get("id")) or None

cp_options = ["(Todas)"]
cp_map: dict[str, str | None] = {"(Todas)": None}
if not cp_df.empty:
    for _, r in cp_df.iterrows():
        label = norm(r.get("name"))
        cp_options.append(label)
        cp_map[label] = norm(r.get("id")) or None

# ==========================================================
# Filtros
# ==========================================================
st.subheader("Filtros")

default_from = date(today.year, today.month, 1)
default_to = today

with st.container(border=True):
    f1, f2, f3, f4, f5, f6 = st.columns([1.2, 1.2, 1.2, 1.2, 2.0, 2.0])
    with f1:
        date_from = st.date_input("De", value=default_from, format="DD/MM/YYYY")
    with f2:
        date_to = st.date_input("Até", value=default_to, format="DD/MM/YYYY")
    with f3:
        t_type = st.selectbox("Tipo", ["(Todos)"] + TYPE_OPTIONS, index=0)
    with f4:
        status = st.selectbox("Status", ["(Todos)"] + STATUS_OPTIONS, index=0)
    with f5:
        proj_label = st.selectbox("Projeto", proj_options, index=0)
    with f6:
        cat_label = st.selectbox("Categoria", cat_options, index=0)

    g1, g2 = st.columns([2.0, 1.0])
    with g1:
        cp_label = st.selectbox("Cliente/Fornecedor", cp_options, index=0)
    with g2:
        if st.button("Recarregar"):
            clear_finance_caches()
            st.rerun()

f_project_id = proj_map.get(proj_label)
f_type = None if t_type == "(Todos)" else t_type
f_status = None if status == "(Todos)" else status
f_category_id = cat_map.get(cat_label)
f_cp_id = cp_map.get(cp_label)

# ==========================================================
# Novo lançamento (APENAS INSERT)
# ==========================================================
st.divider()
st.subheader("Novo lançamento")
st.caption("✅ Nesta fase: criar lançamentos (sem editar/excluir).")

with st.container(border=True):
    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.2, 1.2])
    with c1:
        new_date = st.date_input("Data", value=today, format="DD/MM/YYYY", key="new_date")
    with c2:
        new_type = st.selectbox("Tipo", TYPE_OPTIONS, index=1, key="new_type")  # default DESPESA
    with c3:
        new_status = st.selectbox("Status", ["REALIZADO", "PREVISTO", "CANCELADO"], index=0, key="new_status")
    with c4:
        new_amount = st.number_input("Valor (R$)", min_value=0.01, value=0.01, step=10.0, key="new_amount")

    d1, d2, d3 = st.columns([2.6, 1.6, 1.6])
    with d1:
        new_desc = st.text_input("Descrição", value="", key="new_desc")
    with d2:
        new_payment = st.text_input("Forma de pagamento (opcional)", value="", key="new_payment")
    with d3:
        new_comp = st.date_input("Competência (opcional)", value=None, format="DD/MM/YYYY", key="new_comp")

    e1, e2, e3 = st.columns([2.0, 2.0, 2.0])
    with e1:
        new_cat_label = st.selectbox("Categoria", cat_options, index=0, key="new_cat")
    with e2:
        new_cp_label = st.selectbox("Cliente/Fornecedor", cp_options, index=0, key="new_cp")
    with e3:
        new_proj_label = st.selectbox("Projeto (opcional)", ["(Nenhum)"] + proj_options[1:], index=0, key="new_proj")

    new_notes = st.text_area("Observações (opcional)", value="", height=80, key="new_notes")

    if st.button("Salvar lançamento", type="primary"):
        if norm(new_desc) == "":
            st.error("Descrição é obrigatória.")
        elif float(new_amount) <= 0:
            st.error("Valor deve ser maior que zero.")
        else:
            payload = {
                "date": new_date.isoformat() if new_date else None,
                "type": new_type,
                "status": new_status,
                "description": norm(new_desc),
                "amount": float(new_amount),
                "category_id": cat_map.get(new_cat_label),
                "counterparty_id": cp_map.get(new_cp_label),
                "project_id": proj_map.get(new_proj_label) if new_proj_label != "(Nenhum)" else None,
                "payment_method": norm(new_payment) or None,
                "competence_month": new_comp.isoformat() if new_comp else None,
                "notes": norm(new_notes) or None,
                "created_by": user_email or None,
            }

            try:
                insert_transaction(payload)
                st.success("Lançamento criado.")
                fetch_transactions_view.clear()
                st.rerun()
            except Exception as e:
                st.error("Erro ao salvar lançamento:")
                st.code(api_error_message(e))

# ==========================================================
# Lançamentos (somente leitura)
# ==========================================================
st.divider()
st.subheader("Lançamentos (somente leitura)")

try:
    df = fetch_transactions_view(
        date_from=date_from,
        date_to=date_to,
        project_id=f_project_id,
        t_type=f_type,
        status=f_status,
        category_id=f_category_id,
        counterparty_id=f_cp_id,
    )
except Exception as e:
    st.error("Erro ao carregar lançamentos:")
    st.code(api_error_message(e))
    st.stop()

if df.empty:
    st.info("Nenhum lançamento encontrado para os filtros.")
    st.stop()

show_cols = [
    "date", "type", "status", "description", "amount",
    "category_name", "counterparty_name", "project_code",
    "payment_method", "competence_month", "notes",
]
show_cols = [c for c in show_cols if c in df.columns]

st.dataframe(df[show_cols], use_container_width=True, hide_index=True)
