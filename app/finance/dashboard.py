# ==========================================================
# DASHBOARD v1.1 (somente leitura) - UX melhor
# ==========================================================
st.subheader("Dashboard")

try:
    ms = fetch_monthly_summary()
except Exception as e:
    st.error("Erro ao carregar resumo mensal:")
    st.code(_api_error_message(e))
    ms = pd.DataFrame()

if not ms.empty:
    ms["month"] = pd.to_datetime(ms["month"]).dt.date
    month_options = [m.isoformat() for m in sorted(ms["month"].unique(), reverse=True)]
else:
    month_options = [today.replace(day=1).isoformat()]

sel_month_str = st.selectbox("Mês (competência)", month_options, index=0, key="dash_month")
sel_month = pd.to_datetime(sel_month_str).date()

m_from, m_to = month_range(sel_month)
txm = fetch_tx_min(m_from, m_to)

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

# Cards (mais “dashboard”)
c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1])
c1.metric("Receita (real) 🟢", _brl(receita_real))
c2.metric("Despesa (real) 🔴", _brl(despesa_real))
c3.metric("Saldo (real) ⚪", _brl(saldo_real))
c4.metric("Receita (prev) 🟡", _brl(receita_prev))
c5.metric("Saldo (proj) 🟠", _brl(saldo_proj))

st.divider()

# Gráfico: barras receita/despesa + linha saldo (últimos 6 meses)
try:
    import plotly.graph_objects as go
except Exception:
    go = None

if not ms.empty and go is not None:
    ms_plot = ms.copy()
    ms_plot = ms_plot.sort_values("month", ascending=True).tail(6)

    fig = go.Figure()
    fig.add_bar(x=ms_plot["month"], y=ms_plot["receita"], name="Receita")
    fig.add_bar(x=ms_plot["month"], y=ms_plot["despesa"], name="Despesa")
    fig.add_trace(go.Scatter(x=ms_plot["month"], y=ms_plot["saldo"], mode="lines+markers", name="Saldo"))

    fig.update_layout(barmode="group", height=320, margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig, use_container_width=True)
elif not ms.empty:
    # fallback simples
    st.line_chart(ms.sort_values("month", ascending=True).tail(6).set_index("month")[["receita", "despesa", "saldo"]])
else:
    st.caption("Sem dados suficientes para gráfico ainda.")

st.divider()

def _status_badge(s: str) -> str:
    s = (s or "").upper().strip()
    if s == "REALIZADO":
        return "🟢 REALIZADO"
    if s == "PREVISTO":
        return "🟡 PREVISTO"
    if s == "CANCELADO":
        return "⚫ CANCELADO"
    return s or ""

def _prep_list_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce").fillna(0.0)
    out["status"] = out["status"].apply(_status_badge)
    out["counterparty_name"] = out["counterparty_name"].fillna("")
    out["project_code"] = out["project_code"].fillna("")
    out["description"] = out["description"].fillna("")
    out = out.rename(
        columns={
            "date": "Data",
            "description": "Descrição",
            "amount": "Valor (R$)",
            "counterparty_name": "Cliente/Fornecedor",
            "project_code": "Projeto",
            "status": "Status",
        }
    )
    # formata moeda como string
    out["Valor (R$)"] = out["Valor (R$)"].apply(lambda v: _brl(float(v)))
    return out[["Data", "Descrição", "Cliente/Fornecedor", "Projeto", "Status", "Valor (R$)"]]

r1, r2 = st.columns([1, 1])

with r1:
    st.subheader("Contas a Receber (previsto)")
    df_r = fetch_receivables(limit=10)
    df_r = _prep_list_df(df_r)
    if df_r.empty:
        st.caption("Nenhuma conta a receber prevista.")
    else:
        st.dataframe(df_r, use_container_width=True, hide_index=True)

with r2:
    st.subheader("Contas a Pagar (previsto)")
    df_p = fetch_payables(limit=10)
    df_p = _prep_list_df(df_p)
    if df_p.empty:
        st.caption("Nenhuma conta a pagar prevista.")
    else:
        st.dataframe(df_p, use_container_width=True, hide_index=True)

