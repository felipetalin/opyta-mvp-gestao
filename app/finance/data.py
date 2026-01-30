from __future__ import annotations

from datetime import date
import pandas as pd
import streamlit as st

# sb injetado pela page (conservador: evita hash do cache)
_SB = None


def set_sb(sb) -> None:
    global _SB
    _SB = sb


def _sb():
    if _SB is None:
        raise RuntimeError("Supabase client não foi inicializado. Chame set_sb(sb) na página.")
    return _SB


def norm(x) -> str:
    return ("" if x is None else str(x)).strip()


def api_error_message(e: Exception) -> str:
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


@st.cache_data(ttl=30)
def fetch_projects():
    res = _sb().table("projects").select("id,project_code,name").order("project_code", desc=False).execute()
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def fetch_categories():
    res = (
        _sb()
        .table("finance_categories")
        .select("id,name,type,active")
        .eq("active", True)
        .order("name", desc=False)
        .execute()
    )
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def fetch_counterparties():
    res = (
        _sb()
        .table("finance_counterparties")
        .select("id,name,type,active")
        .eq("active", True)
        .order("name", desc=False)
        .execute()
    )
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def fetch_transactions_view(
    date_from: date,
    date_to: date,
    project_id: str | None,
    t_type: str | None,
    status: str | None,
    category_id: str | None,
    counterparty_id: str | None,
):
    q = (
        _sb()
        .from_("v_finance_transactions")
        .select(
            "id,date,type,status,description,amount,"
            "category_id,category_name,"
            "counterparty_id,counterparty_name,"
            "project_id,project_code,project_name,"
            "payment_method,competence_month,notes,created_by"
        )
        .gte("date", date_from.isoformat())
        .lte("date", date_to.isoformat())
        .order("date", desc=True)
    )

    if project_id:
        q = q.eq("project_id", project_id)
    if t_type:
        q = q.eq("type", t_type)
    if status:
        q = q.eq("status", status)
    if category_id:
        q = q.eq("category_id", category_id)
    if counterparty_id:
        q = q.eq("counterparty_id", counterparty_id)

    res = q.execute()
    return pd.DataFrame(res.data or [])


def insert_transaction(payload: dict):
    # insert NÃO usa cache, mas usa o mesmo sb global para manter padrão simples
    return _sb().table("finance_transactions").insert(payload).execute()


@st.cache_data(ttl=30)
def fetch_monthly_summary():
    res = _sb().from_("v_finance_monthly_summary").select("month,receita,despesa,saldo").order("month", desc=False).execute()
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def fetch_tx_min(date_from: date, date_to: date):
    res = (
        _sb()
        .table("finance_transactions")
        .select("date,type,status,amount")
        .gte("date", date_from.isoformat())
        .lte("date", date_to.isoformat())
        .execute()
    )
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def fetch_receivables(limit: int = 10):
    res = (
        _sb()
        .from_("v_finance_receivables")
        .select("date,description,amount,counterparty_name,project_code,status")
        .order("date", desc=False)
        .limit(limit)
        .execute()
    )
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def fetch_payables(limit: int = 10):
    res = (
        _sb()
        .from_("v_finance_payables")
        .select("date,description,amount,counterparty_name,project_code,status")
        .order("date", desc=False)
        .limit(limit)
        .execute()
    )
    return pd.DataFrame(res.data or [])


def clear_finance_caches():
    fetch_projects.clear()
    fetch_categories.clear()
    fetch_counterparties.clear()
    fetch_transactions_view.clear()
    fetch_monthly_summary.clear()
    fetch_tx_min.clear()
    fetch_receivables.clear()
    fetch_payables.clear()

