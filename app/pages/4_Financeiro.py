from services.finance_guard import require_finance_access

user_email = require_finance_access(silent=True)


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
        st.caption("FINANCE PAGE VERSION: 170476b (dashboard.py UX)")
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

# ==========================================================
# Acesso restrito (Felipe + Yuri)
# ==========================================================

from services.finance_guard import require_finance_access

user_email = require_finance_access()
page_header("Financeiro", "Dashboard + inserir lançamentos (sem editar/excluir)", user_email)



# ==========================================================
# Helpers
# ==========================================================
TYPE_OPTIONS = ["RECEITA", "DESPESA", "TRANSFERENCIA"]
STATUS_OPTIONS = ["PREVISTO", "REALIZADO", "CANCELADO"]
today = date.today()


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


# ==========================================================
# Cache / fetchs
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
def fetch_transactions_view(date_from: date, date_to: date,
                            project_id: str | None,
                            t_type: str | None,
                            status: str | None,
                            category_id: str | None,
                            counterparty_id: str | None):
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
    res = sb.from_("v_finance_monthly_summary").select("month,receita,despesa,saldo").order("month", desc=False).execute()
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
# DASHBOARD v1 (somente leitura)
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

c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1])
c1.metric("Receita (real)", _brl(receita_real))
c2.metric("Despesa (real)", _brl(despesa_real))
c3.metric("Saldo (real)", _brl(saldo_real))
c4.metric("Receita (prev)", _brl(receita_prev))
c5.metric("Saldo (projetado)", _brl(saldo_proj))

st.divider()

# gráfico mensal (últimos 6 meses)
try:
    import plotly.express as px
except Exception:
    px = None

if not ms.empty:
    ms_plot = ms.sort_values("month", ascending=True).tail(6)
    if px is not None:
        fig = px.bar(ms_plot, x="month", y=["receita", "despesa"], barmode="group")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.line_chart(ms_plot.set_index("month")[["receita", "despesa", "saldo"]])
else:
    st.caption("Sem dados suficientes para gráfico ainda.")

st.divider()

r1, r2 = st.columns([1, 1])
with r1:
    st.subheader("Contas a Receber (previsto)")
    df_r = fetch_receivables(limit=10)
    if df_r.empty:
        st.caption("Nenhuma conta a receber prevista.")
    else:
        st.dataframe(df_r, use_container_width=True, hide_index=True)

with r2:
    st.subheader("Contas a Pagar (previsto)")
    df_p = fetch_payables(limit=10)
    if df_p.empty:
        st.caption("Nenhuma conta a pagar prevista.")
    else:
        st.dataframe(df_p, use_container_width=True, hide_index=True)

st.divider()

# ==========================================================
# DROPDOWNS (para filtros + insert)
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
            clear_caches()
            st.rerun()

f_project_id = proj_map.get(proj_label)
f_type = None if t_type == "(Todos)" else t_type
f_status = None if status == "(Todos)" else status
f_category_id = cat_map.get(cat_label)
f_cp_id = cp_map.get(cp_label)

# ==========================================================
# NOVO LANÇAMENTO (APENAS INSERT)
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
                insert_tx(payload)
                st.success("Lançamento criado.")
                fetch_transactions_view.clear()
                st.rerun()
            except Exception as e:
                st.error("Erro ao salvar lançamento:")
                st.code(_api_error_message(e))

# ==========================================================
# LISTA (somente leitura) - UX melhor
# ==========================================================
st.divider()
st.subheader("Lançamentos (somente leitura)")

def _status_badge(s: str) -> str:
    s = (s or "").upper().strip()
    if s == "REALIZADO":
        return "🟢 REALIZADO"
    if s == "PREVISTO":
        return "🟡 PREVISTO"
    if s == "CANCELADO":
        return "⚫ CANCELADO"
    return s or ""

def _clean_str(x) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    return "" if s in ("None", "nan", "NaT") else s

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

# garante tipos e “None” limpo
df2 = df.copy()
df2["date"] = pd.to_datetime(df2["date"], errors="coerce").dt.date
df2["amount"] = pd.to_numeric(df2["amount"], errors="coerce").fillna(0.0)

for col in ["description", "category_name", "counterparty_name", "project_code", "payment_method", "notes"]:
    if col in df2.columns:
        df2[col] = df2[col].apply(_clean_str)

if "status" in df2.columns:
    df2["status"] = df2["status"].apply(_status_badge)

# monta tabela de exibição
show = pd.DataFrame(
    {
        "Data": df2["date"],
        "Tipo": df2["type"].apply(_clean_str),
        "Status": df2["status"].apply(_clean_str),
        "Descrição": df2["description"],
        "Categoria": df2.get("category_name", "").apply(_clean_str),
        "Cliente/Fornecedor": df2.get("counterparty_name", "").apply(_clean_str),
        "Projeto": df2.get("project_code", "").apply(_clean_str),
        "Valor (R$)": df2["amount"].apply(lambda v: _brl(float(v))),
        "Pagamento": df2.get("payment_method", "").apply(_clean_str),
        "Obs": df2.get("notes", "").apply(_clean_str),
    }
)

st.dataframe(
    show,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Data": st.column_config.DateColumn(format="DD/MM/YYYY"),
        "Valor (R$)": st.column_config.TextColumn(width="small"),
        "Descrição": st.column_config.TextColumn(width="large"),
        "Obs": st.column_config.TextColumn(width="large"),
    },
)


