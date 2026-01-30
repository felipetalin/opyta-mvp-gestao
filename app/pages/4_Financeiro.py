from __future__ import annotations

from datetime import date
import pandas as pd
import streamlit as st

from services.auth import require_login
from services.supabase_client import get_authed_client
from services.finance_guard import require_finance_access

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


# ==========================================================
# Boot (ordem obrigatória)
# ==========================================================
st.set_page_config(page_title="Financeiro", layout="wide")
apply_brand()
apply_app_chrome()

require_login()
sb = get_authed_client()

# 🔒 Acesso silencioso (para não constranger)
user_email = require_finance_access(silent=True)

page_header("Financeiro", "Dashboard + lançamentos", user_email)

TYPE_OPTIONS = ["RECEITA", "DESPESA", "TRANSFERENCIA"]
STATUS_OPTIONS = ["PREVISTO", "REALIZADO", "CANCELADO"]
today = date.today()


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


def norm(x) -> str:
    return ("" if x is None else str(x)).strip()


def _clean_str(x) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    return "" if s in ("None", "nan", "NaT") else s


def _brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def month_range(d: date) -> tuple[date, date]:
    m0 = date(d.year, d.month, 1)
    if d.month == 12:
        m1 = date(d.year + 1, 1, 1)
    else:
        m1 = date(d.year, d.month + 1, 1)
    m_last = (pd.to_datetime(m1) - pd.Timedelta(days=1)).date()
    return m0, m_last


def _prev_month(d: date) -> date:
    if d.month == 1:
        return date(d.year - 1, 12, 1)
    return date(d.year, d.month - 1, 1)


def _pct(curr: float, prev: float) -> str:
    if prev == 0:
        return "—"
    p = ((curr - prev) / abs(prev)) * 100
    arrow = "↑" if p >= 0 else "↓"
    return f"{arrow} {abs(p):.1f}%"


# ==========================================================
# Cache / fetchs (CONSERVADOR: não passa sb como argumento)
# ==========================================================
@st.cache_data(ttl=30)
def fetch_projects():
    res = sb.table("projects").select("id,project_code,name").order("project_code", desc=False).execute()
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def fetch_categories():
    res = (
        sb.table("finance_categories")
        .select("id,name,type,active")
        .eq("active", True)
        .order("name", desc=False)
        .execute()
    )
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def fetch_counterparties():
    res = (
        sb.table("finance_counterparties")
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
        sb.from_("v_finance_transactions")
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


def insert_tx(payload: dict):
    return sb.table("finance_transactions").insert(payload).execute()


@st.cache_data(ttl=30)
def fetch_monthly_summary():
    res = (
        sb.from_("v_finance_monthly_summary")
        .select("month,receita,despesa,saldo")
        .order("month", desc=False)
        .execute()
    )
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def fetch_tx_min(date_from: date, date_to: date):
    res = (
        sb.table("finance_transactions")
        .select("date,type,status,amount")
        .gte("date", date_from.isoformat())
        .lte("date", date_to.isoformat())
        .execute()
    )
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def fetch_receivables(limit: int = 10):
    res = (
        sb.from_("v_finance_receivables")
        .select("date,description,amount,counterparty_name,project_code,status")
        .order("date", desc=False)
        .limit(limit)
        .execute()
    )
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=30)
def fetch_payables(limit: int = 10):
    res = (
        sb.from_("v_finance_payables")
        .select("date,description,amount,counterparty_name,project_code,status")
        .order("date", desc=False)
        .limit(limit)
        .execute()
    )
    return pd.DataFrame(res.data or [])


def clear_caches():
    fetch_projects.clear()
    fetch_categories.clear()
    fetch_counterparties.clear()
    fetch_transactions_view.clear()
    fetch_monthly_summary.clear()
    fetch_tx_min.clear()
    fetch_receivables.clear()
    fetch_payables.clear()


# ==========================================================
# CSS Global
# ==========================================================
st.markdown(
    """
<style>
.op-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-top: 8px; }
.op-card {
  border-radius: 10px; padding: 14px 16px; color: #fff;
  box-shadow: 0 6px 16px rgba(0,0,0,.12);
  border: 1px solid rgba(255,255,255,.12);
  position: relative; min-height: 92px;
}
.op-title { font-size: 14px; font-weight: 600; opacity: .95; margin-bottom: 4px; }
.op-value { font-size: 30px; font-weight: 800; line-height: 1.05; margin: 0; }
.op-sub   { font-size: 12px; opacity: .9; margin-top: 6px; }
.op-green  { background: linear-gradient(135deg, #2f7d55 0%, #3e9a6b 100%); }
.op-blue   { background: linear-gradient(135deg, #1e5aa7 0%, #2d79d3 100%); }
.op-orange { background: linear-gradient(135deg, #c66b10 0%, #f39a2a 100%); }
.op-red    { background: linear-gradient(135deg, #a11e1e 0%, #e04a4a 100%); }

.op-panel {
  border: 1px solid rgba(0,0,0,.08);
  border-radius: 10px;
  padding: 12px 12px 10px 12px;
  background: rgba(255,255,255,.55);
}
.op-row {
  display: flex; justify-content: space-between; align-items: center;
  gap: 10px; padding: 10px 8px; border-radius: 8px;
}
.op-row + .op-row { border-top: 1px solid rgba(0,0,0,.06); }
.op-left { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.op-topline { font-size: 12px; opacity: .85; }
.op-mainline { font-size: 14px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 520px; }
.op-subline { font-size: 12px; opacity: .75; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 520px; }
.op-chip {
  padding: 6px 10px; border-radius: 999px; font-weight: 800; font-size: 12px;
  color: #fff; white-space: nowrap;
}
.op-chip-green { background: #2f7d55; }
.op-chip-orange{ background: #c66b10; }
.op-chip-gray  { background: #555; }

@media (max-width: 1100px) {
  .op-cards { grid-template-columns: repeat(2, 1fr); }
  .op-mainline, .op-subline { max-width: 360px; }
}
@media (max-width: 650px) {
  .op-cards { grid-template-columns: 1fr; }
  .op-mainline, .op-subline { max-width: 260px; }
}
</style>
""",
    unsafe_allow_html=True,
)


# ==========================================================
# DROPDOWNS (para filtros + insert + editor)
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
# FILTROS
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
        stt = st.selectbox("Status", ["(Todos)"] + STATUS_OPTIONS, index=0)
    with f5:
        proj_label = st.selectbox("Projeto", proj_options, index=0)
    with f6:
        cat_label = st.selectbox("Categoria", cat_options, index=0)

    g1, g2 = st.columns([2.0, 1.0])
    with g1:
        cp_label = st.selectbox("Cliente/Fornecedor", cp_options, index=0)
    with g2:
        if st.button("Recarregar"):
            clear_caches()
            st.rerun()

f_project_id = proj_map.get(proj_label)
f_type = None if t_type == "(Todos)" else t_type
f_status = None if stt == "(Todos)" else stt
f_category_id = cat_map.get(cat_label)
f_cp_id = cp_map.get(cp_label)


# ==========================================================
# DASHBOARD
# ==========================================================
st.divider()
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

def _calc_month(tx: pd.DataFrame):
    r_real = d_real = r_prev = d_prev = 0.0
    if not tx.empty:
        t = tx.copy()
        t["type"] = t["type"].astype(str).str.upper()
        t["status"] = t["status"].astype(str).str.upper()
        t["amount"] = pd.to_numeric(t["amount"], errors="coerce").fillna(0.0)
        r_real = float(t[(t["type"]=="RECEITA")&(t["status"]=="REALIZADO")]["amount"].sum())
        d_real = float(t[(t["type"]=="DESPESA")&(t["status"]=="REALIZADO")]["amount"].sum())
        r_prev = float(t[(t["type"]=="RECEITA")&(t["status"]=="PREVISTO")]["amount"].sum())
        d_prev = float(t[(t["type"]=="DESPESA")&(t["status"]=="PREVISTO")]["amount"].sum())
    return {"saldo": r_real - d_real, "r_prev": r_prev, "d_prev": d_prev}

curr = _calc_month(txm)

pm = _prev_month(sel_month)
pm_from, pm_to = month_range(pm)
txm_prev = fetch_tx_min(pm_from, pm_to)
prev = _calc_month(txm_prev)

saldo_delta = _pct(curr["saldo"], prev["saldo"])
rprev_delta = _pct(curr["r_prev"], prev["r_prev"])
dprev_delta = _pct(curr["d_prev"], prev["d_prev"])
saldo_projetado = (curr["saldo"] + curr["r_prev"]) - curr["d_prev"]

# contagens (a receber / a pagar)
n_receber = 0
n_pagar = 0
if not txm.empty:
    t2 = txm.copy()
    t2["type"] = t2["type"].astype(str).str.upper()
    t2["status"] = t2["status"].astype(str).str.upper()
    n_receber = int(((t2["type"] == "RECEITA") & (t2["status"] == "PREVISTO")).sum())
    n_pagar = int(((t2["type"] == "DESPESA") & (t2["status"] == "PREVISTO")).sum())

st.markdown(
    f"""
<div class="op-cards">
  <div class="op-card op-green">
    <div class="op-title">Saldo Atual</div>
    <div class="op-value">{_brl(curr["saldo"])}</div>
    <div class="op-sub">{saldo_delta} vs mês anterior</div>
  </div>

  <div class="op-card op-blue">
    <div class="op-title">Receitas Previstas</div>
    <div class="op-value">{_brl(curr["r_prev"])}</div>
    <div class="op-sub">{n_receber} a receber • {rprev_delta} vs mês anterior</div>
  </div>

  <div class="op-card op-orange">
    <div class="op-title">Despesas Previstas</div>
    <div class="op-value">{_brl(curr["d_prev"])}</div>
    <div class="op-sub">{n_pagar} a pagar • {dprev_delta} vs mês anterior</div>
  </div>

  <div class="op-card op-red">
    <div class="op-title">Saldo Projetado</div>
    <div class="op-value">{_brl(saldo_projetado)}</div>
    <div class="op-sub">Atual + previstas</div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

st.divider()

# ==========================================================
# ALERTAS DE VENCIMENTO
# ==========================================================
st.subheader("Alertas")

today_dt = today
next_7 = (pd.to_datetime(today_dt) + pd.Timedelta(days=7)).date()

try:
    df_alert = fetch_transactions_view(
        date_from=today_dt,
        date_to=next_7,
        project_id=None,
        t_type=None,
        status="PREVISTO",
        category_id=None,
        counterparty_id=None,
    )
except Exception as e:
    st.error("Erro ao carregar alertas de vencimento:")
    st.code(_api_error_message(e))
    df_alert = pd.DataFrame()

if df_alert.empty:
    st.caption("Nenhum lançamento previsto para vencer nos próximos dias.")
else:
    df_alert = df_alert.copy()
    df_alert["date"] = pd.to_datetime(df_alert["date"], errors="coerce").dt.date
    df_alert["amount"] = pd.to_numeric(df_alert["amount"], errors="coerce").fillna(0.0)
    df_alert["type"] = df_alert["type"].astype(str).str.upper()

    df_today = df_alert[df_alert["date"] == today_dt]
    df_week = df_alert[(df_alert["date"] > today_dt) & (df_alert["date"] <= next_7)]

    def _alert_card(title: str, dfx: pd.DataFrame):
        if dfx.empty:
            st.markdown(
                f"""
                <div class="op-panel">
                  <strong>{title}</strong>
                  <div style="opacity:.75; margin-top:6px;">Nenhum lançamento</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            return

        total = float(dfx["amount"].sum())
        n = len(dfx)
        rec = float(dfx[dfx["type"] == "RECEITA"]["amount"].sum())
        desp = float(dfx[dfx["type"] == "DESPESA"]["amount"].sum())

        st.markdown(
            f"""
            <div class="op-panel">
              <strong>{title}</strong>
              <div style="margin-top:6px;">
                <b>{n}</b> lançamentos • <b>{_brl(total)}</b>
              </div>
              <div style="opacity:.85; margin-top:4px; font-size:13px;">
                Receitas: {_brl(rec)} • Despesas: {_brl(desp)}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    a1, a2 = st.columns([1, 1])
    with a1:
        _alert_card("⚠️ Vencem hoje", df_today)
    with a2:
        _alert_card("📅 Vencem nos próximos 7 dias", df_week)

st.divider()

# ==========================================================
# FLUXO DE CAIXA MENSAL (6 meses)
# ==========================================================
st.subheader("Fluxo de Caixa Mensal")

def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)

def _add_months(d: date, n: int) -> date:
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return date(y, m, 1)

end_m = _month_start(sel_month)
start_m = _add_months(end_m, -5)
range_from = start_m
range_to = month_range(end_m)[1]

df_range = fetch_tx_min(range_from, range_to)

if df_range.empty:
    st.caption("Sem dados no intervalo para montar o gráfico.")
else:
    df_range = df_range.copy()
    df_range["date"] = pd.to_datetime(df_range["date"], errors="coerce")
    df_range["month"] = df_range["date"].dt.to_period("M").dt.to_timestamp().dt.date
    df_range["type"] = df_range["type"].astype(str).str.upper()
    df_range["amount"] = pd.to_numeric(df_range["amount"], errors="coerce").fillna(0.0)

    receita_m = df_range[df_range["type"] == "RECEITA"].groupby("month")["amount"].sum().rename("receita")
    despesa_m = df_range[df_range["type"] == "DESPESA"].groupby("month")["amount"].sum().rename("despesa")

    months = pd.date_range(pd.to_datetime(start_m), pd.to_datetime(end_m), freq="MS").date
    plot_df = pd.DataFrame({"month": months}).set_index("month")
    plot_df["receita"] = receita_m.reindex(plot_df.index).fillna(0.0)
    plot_df["despesa"] = despesa_m.reindex(plot_df.index).fillna(0.0)
    plot_df["saldo_final"] = (plot_df["receita"] - plot_df["despesa"]).cumsum()
    plot_df = plot_df.reset_index()

    import plotly.graph_objects as go

    fig = go.Figure()
    fig.add_bar(x=plot_df["month"], y=plot_df["receita"], name="Receitas")
    fig.add_bar(x=plot_df["month"], y=plot_df["despesa"], name="Despesas")
    fig.add_trace(
        go.Scatter(
            x=plot_df["month"],
            y=plot_df["saldo_final"],
            mode="lines+markers",
            name="Saldo Final (R$)",
            yaxis="y2",
        )
    )

    fig.update_layout(
        barmode="group",
        height=360,
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis=dict(title="", tickformat="%b/%y"),
        yaxis=dict(title="R$"),
        yaxis2=dict(title="", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )

    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ==========================================================
# DESPESAS POR CATEGORIA (donut)
# ==========================================================
st.subheader("Despesas por Categoria")

try:
    df_month_full = fetch_transactions_view(
        date_from=m_from,
        date_to=m_to,
        project_id=None,
        t_type="DESPESA",
        status=None,
        category_id=None,
        counterparty_id=None,
    )
except Exception as e:
    st.error("Erro ao montar despesas por categoria:")
    st.code(_api_error_message(e))
    df_month_full = pd.DataFrame()

if df_month_full.empty:
    st.caption("Sem despesas no mês selecionado.")
else:
    dfc = df_month_full.copy()
    dfc["amount"] = pd.to_numeric(dfc["amount"], errors="coerce").fillna(0.0)
    dfc["category_name"] = dfc.get("category_name", "").apply(_clean_str)
    dfc = dfc[dfc["amount"] > 0]

    if dfc.empty:
        st.caption("Sem despesas válidas para exibir.")
    else:
        by_cat = dfc.groupby("category_name")["amount"].sum().sort_values(ascending=False).reset_index()
        by_cat["category_name"] = by_cat["category_name"].replace("", "(Sem categoria)")

        import plotly.express as px

        fig = px.pie(by_cat, names="category_name", values="amount", hole=0.55)
        fig.update_traces(textposition="outside", textinfo="percent+label")
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

        st.caption("Top categorias (mês):")
        topn = by_cat.head(6).copy()
        topn["Valor (R$)"] = topn["amount"].apply(lambda v: _brl(float(v)))
        st.dataframe(
            topn[["category_name", "Valor (R$)"]].rename(columns={"category_name": "Categoria"}),
            use_container_width=True,
            hide_index=True,
        )

st.divider()

# ==========================================================
# Contas a receber / pagar (painel)
# ==========================================================
r1, r2 = st.columns([1, 1])

def _render_list_panel(df_in: pd.DataFrame, empty_text: str):
    if df_in is None or df_in.empty:
        st.caption(empty_text)
        return

    dfp = df_in.copy()
    dfp["date"] = pd.to_datetime(dfp["date"], errors="coerce").dt.date
    dfp["amount"] = pd.to_numeric(dfp["amount"], errors="coerce").fillna(0.0)
    for col in ["description", "counterparty_name", "project_code", "status"]:
        if col in dfp.columns:
            dfp[col] = dfp[col].apply(_clean_str)

    html = '<div class="op-panel">'
    for _, row in dfp.iterrows():
        d = row.get("date")
        d_txt = d.strftime("%d/%m") if isinstance(d, date) else ""
        proj = row.get("project_code") or ""
        cpty = row.get("counterparty_name") or ""
        desc = row.get("description") or ""
        amt = _brl(float(row.get("amount") or 0.0))
        topline = " • ".join([x for x in [proj, cpty] if x])
        subline = " • ".join([x for x in [d_txt, (row.get("status") or "").title()] if x])

        html += f"""
        <div class="op-row">
          <div class="op-left">
            <div class="op-topline">{topline}</div>
            <div class="op-mainline">{desc}</div>
            <div class="op-subline">{subline}</div>
          </div>
          <div class="op-chip op-chip-orange">{amt}</div>
        </div>
        """
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)

with r1:
    st.subheader("Contas a Receber (previsto)")
    try:
        df_r = fetch_receivables(limit=10)
    except Exception as e:
        st.error("Erro ao carregar contas a receber:")
        st.code(_api_error_message(e))
        df_r = pd.DataFrame()
    _render_list_panel(df_r, "Nenhuma conta a receber prevista.")

with r2:
    st.subheader("Contas a Pagar (previsto)")
    try:
        df_p = fetch_payables(limit=10)
    except Exception as e:
        st.error("Erro ao carregar contas a pagar:")
        st.code(_api_error_message(e))
        df_p = pd.DataFrame()
    _render_list_panel(df_p, "Nenhuma conta a pagar prevista.")

st.divider()

# ==========================================================
# NOVO LANÇAMENTO (INSERT)
# ==========================================================
st.subheader("Novo lançamento")
st.caption("✅ Criar lançamentos. (Você pode editar/excluir na tabela abaixo.)")

with st.container(border=True):
    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.2, 1.2])
    with c1:
        new_date = st.date_input("Data", value=today, format="DD/MM/YYYY", key="new_date")
    with c2:
        new_type = st.selectbox("Tipo", TYPE_OPTIONS, index=1, key="new_type")
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
                insert_tx(payload)
                st.success("Lançamento criado.")
                clear_caches()
                st.rerun()
            except Exception as e:
                st.error("Erro ao salvar lançamento:")
                st.code(_api_error_message(e))

st.divider()

# ==========================================================
# LISTA (EDIÇÃO INLINE + EXCLUSÃO com confirmação)
# ==========================================================
st.subheader("Lançamentos (edição inline)")
st.caption("✏️ Edite na tabela e clique em **Salvar alterações**. Para excluir, marque a caixa e confirme.")

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
    st.code(_api_error_message(e))
    st.stop()

if df.empty:
    st.info("Nenhum lançamento encontrado para os filtros.")
    st.stop()

# -------------------------
# Normalização
# -------------------------
df2 = df.copy()
df2["id"] = df2["id"].astype(str)
df2["date"] = pd.to_datetime(df2["date"], errors="coerce").dt.date
df2["amount"] = pd.to_numeric(df2["amount"], errors="coerce").fillna(0.0)

for col in ["description", "payment_method", "notes"]:
    if col in df2.columns:
        df2[col] = df2[col].apply(_clean_str)

# -------------------------
# Options (editor) + placeholders para evitar "None"
# -------------------------
CAT_NONE = "(Sem)"
CP_NONE = "(Sem)"
PROJ_NONE = "(Sem)"

# remove o "(Todas)/(Todos)" da lista editável e adiciona "(Sem)"
cat_options_editor = [CAT_NONE] + [k for k in cat_map.keys() if k != "(Todas)"]
cp_options_editor = [CP_NONE] + [k for k in cp_map.keys() if k != "(Todas)"]
proj_options_editor = [PROJ_NONE] + [k for k in proj_map.keys() if k != "(Todos)"]

# Map id -> label
cat_label_by_id = {v: k for k, v in cat_map.items() if v}
cp_label_by_id = {v: k for k, v in cp_map.items() if v}
proj_label_by_id = {v: k for k, v in proj_map.items() if v}

# =========================
# DataFrame editável (index = id)
# =========================
CAT_NONE = "(Sem)"
CP_NONE = "(Sem)"
PROJ_NONE = "(Sem)"

cat_options_editor = [CAT_NONE] + [k for k in cat_map.keys() if k != "(Todas)"]
cp_options_editor  = [CP_NONE]  + [k for k in cp_map.keys() if k != "(Todas)"]
proj_options_editor= [PROJ_NONE]+ [k for k in proj_map.keys() if k != "(Todos)"]

cat_label_by_id = {v: k for k, v in cat_map.items() if v}
cp_label_by_id  = {v: k for k, v in cp_map.items() if v}
proj_label_by_id= {v: k for k, v in proj_map.items() if v}

# normaliza colunas base (pra não virar None por NaN)
df2["type"] = df2["type"].astype(str).str.upper().replace({"NAN": ""}).fillna("")
df2["status"] = df2["status"].astype(str).str.upper().replace({"NAN": ""}).fillna("")
df2["description"] = df2["description"].fillna("").apply(_clean_str)

df_edit = pd.DataFrame(
    {
        "Excluir?": False,
        "Data": df2["date"],
        "Tipo": df2["type"],
        "Status": df2["status"],
        "Descrição": df2["description"],
        "Categoria": df2["category_id"].map(cat_label_by_id).fillna(CAT_NONE),
        "Cliente/Fornecedor": df2["counterparty_id"].map(cp_label_by_id).fillna(CP_NONE),
        "Projeto": df2["project_id"].map(proj_label_by_id).fillna(PROJ_NONE),
        "Valor": df2["amount"],
        "Pagamento": df2.get("payment_method", "").apply(_clean_str),
        "Obs": df2.get("notes", "").apply(_clean_str),
    },
    index=df2["id"],
)

edited = st.data_editor(
    df_edit,
    key="finance_editor",
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_order=[
        "Excluir?",
        "Data",
        "Tipo",
        "Status",
        "Descrição",
        "Categoria",
        "Cliente/Fornecedor",
        "Projeto",
        "Valor",
        "Pagamento",
        "Obs",
    ],
    column_config={
        "Excluir?": st.column_config.CheckboxColumn(width="small"),
        "Data": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Tipo": st.column_config.SelectboxColumn(options=TYPE_OPTIONS, width="small"),
        "Status": st.column_config.SelectboxColumn(options=STATUS_OPTIONS, width="small"),
        "Categoria": st.column_config.SelectboxColumn(options=cat_options_editor),
        "Cliente/Fornecedor": st.column_config.SelectboxColumn(options=cp_options_editor),
        "Projeto": st.column_config.SelectboxColumn(options=proj_options_editor),
        "Valor": st.column_config.NumberColumn(min_value=0.01, step=10.0, width="small"),
        "Descrição": st.column_config.TextColumn(width="large"),
        "Obs": st.column_config.TextColumn(width="large"),
    },
)

# Atualiza estado com a edição atual
st.session_state["finance_editor_df"] = edited.copy()

c1, c2, c3 = st.columns([1, 1, 2])
save_btn = c1.button("Salvar alterações", type="primary")
reload_btn = c2.button("Recarregar lançamentos")

if reload_btn:
    clear_caches()
    if "finance_editor" in st.session_state:
        del st.session_state["finance_editor"]
    st.rerun()


# -------------------------
# Confirmação de exclusão em 2 etapas
# -------------------------
if "finance_confirm_delete" not in st.session_state:
    st.session_state["finance_confirm_delete"] = False

if save_btn:
    before = df_edit.copy()
    after = edited.copy()

    # quais IDs estão marcados pra excluir?
    delete_ids = [tx_id for tx_id, row in after.iterrows() if bool(row.get("Excluir?", False))]

    # Se tem exclusão, pede confirmação (2ª etapa)
    if delete_ids and not st.session_state["finance_confirm_delete"]:
        st.session_state["finance_confirm_delete"] = True
        st.warning(
            f"Você marcou **{len(delete_ids)}** lançamento(s) para excluir. "
            "Clique em **Confirmar exclusões** para apagar de verdade."
        )
        st.stop()

    # Se não tem exclusão, ou já confirmou, segue
    n_updates = 0
    n_deletes = 0
    warnings: list[str] = []

    # Executa deleções confirmadas
    if st.session_state["finance_confirm_delete"] and delete_ids:
        for tx_id in delete_ids:
            try:
                sb.table("finance_transactions").delete().eq("id", tx_id).execute()
                n_deletes += 1
            except Exception as e:
                warnings.append(f"Erro ao excluir {tx_id}: {_api_error_message(e)}")

    # Executa updates (somente itens NÃO excluídos)
    for tx_id, ra in after.iterrows():
        if tx_id in delete_ids:
            continue

        rb = before.loc[tx_id]

        # Mudou algo?
        changed = False
        for c in before.columns:
            if c == "Excluir?":
                continue
            if norm(rb[c]) != norm(ra[c]):
                changed = True
                break
        if not changed:
            continue

        # Validações mínimas
        if ra["Data"] is None:
            warnings.append(f"{tx_id}: Data vazia (update ignorado).")
            continue
        if float(ra["Valor"]) <= 0:
            warnings.append(f"{tx_id}: Valor deve ser > 0 (update ignorado).")
            continue
        if norm(ra["Descrição"]) == "":
            warnings.append(f"{tx_id}: Descrição obrigatória (update ignorado).")
            continue

        payload = {
            "date": ra["Data"].isoformat() if ra["Data"] else None,
            "type": ra["Tipo"],
            "status": ra["Status"],
            "description": norm(ra["Descrição"]),
            "amount": float(ra["Valor"]),
            "category_id": None if ra["Categoria"] == CAT_NONE else cat_map.get(ra["Categoria"]),
            "counterparty_id": None if ra["Cliente/Fornecedor"] == CP_NONE else cp_map.get(ra["Cliente/Fornecedor"]),
            "project_id": None if ra["Projeto"] == PROJ_NONE else proj_map.get(ra["Projeto"]),
            "payment_method": norm(ra["Pagamento"]) or None,
            "notes": norm(ra["Obs"]) or None,
        }

        try:
            sb.table("finance_transactions").update(payload).eq("id", tx_id).execute()
            n_updates += 1
        except Exception as e:
            warnings.append(f"Erro ao atualizar {tx_id}: {_api_error_message(e)}")

    # Limpa flag de confirmação
    st.session_state["finance_confirm_delete"] = False

    if warnings:
        st.warning("\n".join(warnings))

    st.success(f"Atualizados: {n_updates} • Excluídos: {n_deletes}")
    clear_caches()
    st.session_state.pop("finance_editor_df", None)
    st.rerun()

# Botão explícito da 2ª etapa (aparece só se tiver pendente)
if st.session_state.get("finance_confirm_delete", False):
    confirm = st.button("Confirmar exclusões", type="secondary")
    cancel = st.button("Cancelar exclusões", type="tertiary")

    if cancel:
        st.session_state["finance_confirm_delete"] = False
        # desmarca as exclusões no editor (para não ficar armadilha)
        df_tmp = st.session_state["finance_editor_df"].copy()
        if "Excluir?" in df_tmp.columns:
            df_tmp["Excluir?"] = False
        st.session_state["finance_editor_df"] = df_tmp
        st.rerun()

    if confirm:
        # dispara o fluxo de save de novo já confirmando
        # (apenas seta e rerun; o save acontecerá ao clicar "Salvar alterações" novamente)
        st.info("Agora clique em **Salvar alterações** para aplicar as exclusões confirmadas.")
