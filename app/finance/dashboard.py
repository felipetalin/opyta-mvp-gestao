from __future__ import annotations

from datetime import date
import pandas as pd
import streamlit as st

from finance.data import fetch_monthly_summary, fetch_tx_min, fetch_receivables, fetch_payables


def month_range(d: date) -> tuple[date, date]:
    m0 = date(d.year, d.month, 1)
    if d.month == 12:
        m1 = date(d.year + 1, 1, 1)
    else:
        m1 = date(d.year, d.month + 1, 1)
    m_last = (pd.to_datetime(m1) - pd.Timedelta(days=1)).date()
    return m0, m_last


def render_dashboard(sb):
    st.subheader("Dashboard")

    # selector de mês (por competência via summary)
    ms = fetch_monthly_summary(sb)
    if not ms.empty:
        ms["month"] = pd.to_datetime(ms["month"]).dt.date
        month_options = [m.isoformat() for m in sorted(ms["month"].unique(), reverse=True)]
    else:
        month_options = [date.today().replace(day=1).isoformat()]

    sel_month_str = st.selectbox("Mês (competência)", month_options, index=0, key="dash_month")
    sel_month = pd.to_datetime(sel_month_str).date()

    m_from, m_to = month_range(sel_month)
    txm = fetch_tx_min(sb, m_from, m_to)

    receita_real = despesa_real = receita_prev = despesa_prev = 0.0
    if not txm.empty:
        txm["type"] = txm["type"].astype(str).str.upper()
        txm["status"] = txm["status"].astype(str).str.upper()
        txm["amount"] = pd.to_numeric(txm["amount"], errors="coerce").fillna(0)

        receita_real = float(txm[(txm["type"] == "RECEITA") & (txm["status"] == "REALIZADO")]["amount"].sum())
        despesa_real = float(txm[(txm["type"] == "DESPESA") & (txm["status"] == "REALIZADO")]["amount"].sum())
        receita_prev = float(txm[(txm["type"] == "RECEITA") & (txm["status"] == "PREVISTO")]["amount"].sum())
        despesa_prev = float(txm[(txm["type"] == "DESPESA") & (txm["status"] == "PREVISTO")]["amount"].sum())

    saldo_real = receita_real - despesa_real
    saldo_proj = (receita_real + receita_prev) - (despesa_real + despesa_prev)

    c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1])
    c1.metric("Receita (real)", f"R$ {receita_real:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c2.metric("Despesa (real)", f"R$ {despesa_real:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c3.metric("Saldo (real)", f"R$ {saldo_real:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c4.metric("Receita (prev)", f"R$ {receita_prev:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c5.metric("Saldo (projetado)", f"R$ {saldo_proj:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    st.divider()

    # Gráfico mensal (usa summary)
    try:
        import plotly.express as px
    except Exception:
        px = None

    if not ms.empty:
        ms_plot = ms.copy()
        ms_plot = ms_plot.sort_values("month", ascending=True).tail(6)
        if px is not None:
            fig = px.bar(ms_plot, x="month", y=["receita", "despesa"], barmode="group")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.line_chart(ms_plot.set_index("month")[["receita", "despesa", "saldo"]])
    else:
        st.info("Sem dados para gráfico ainda.")

    st.divider()

    # Receber / Pagar
    r1, r2 = st.columns([1, 1])

    with r1:
        st.subheader("Contas a Receber (previsto)")
        df_r = fetch_receivables(sb, limit=10)
        if df_r.empty:
            st.caption("Nenhuma conta a receber prevista.")
        else:
            st.dataframe(df_r, use_container_width=True, hide_index=True)

    with r2:
        st.subheader("Contas a Pagar (previsto)")
        df_p = fetch_payables(sb, limit=10)
        if df_p.empty:
            st.caption("Nenhuma conta a pagar prevista.")
        else:
            st.dataframe(df_p, use_container_width=True, hide_index=True)
