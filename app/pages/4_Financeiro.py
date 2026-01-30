# app/pages/4_Financeiro.py
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


# ==========================================================
# Boot (ordem obrigatória)
# ==========================================================
st.set_page_config(page_title="Financeiro", layout="wide")
apply_brand()
apply_app_chrome()

require_login()
sb = get_authed_client()

user_email = (st.session_state.get("user_email") or "").strip().lower()
page_header("Financeiro", "Lançamentos com filtros, edição e exclusão segura", user_email)

# ==========================================================
# Acesso restrito (Felipe + Yuri)
# ==========================================================
ALLOWED_FINANCE_EMAILS = {
    "felipetalin@opyta.com.br",
    "yurisimoes@opyta.com.br",
}
if user_email not in {e.lower() for e in ALLOWED_FINANCE_EMAILS}:
    st.error("Acesso restrito ao módulo Financeiro.")
    st.stop()


# ==========================================================
# Helpers (mesmo estilo do Projetos.py)
# ==========================================================
TYPE_OPTIONS = ["RECEITA", "DESPESA", "TRANSFERENCIA"]
STATUS_OPTIONS = ["PREVISTO", "REALIZADO", "CANCELADO"]


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
    if pd.isna(x) or x is None:
        return None
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return None


def norm(x) -> str:
    return ("" if x is None else str(x)).strip()


def safe_text_list(series: pd.Series, default: str = "") -> list[str]:
    out: list[str] = []
    for v in series.tolist():
        if v is None or (isinstance(v, float) and pd.isna(v)):
            out.append(default)
        else:
            s = str(v).strip()
            out.append("" if s in ("None", "nan", "NaT") else s)
    return out


# ==========================================================
# Loads (cache)
# ==========================================================
@st.cache_data(ttl=30)
def fetch_projects():
    res = (
        sb.table("projects")
        .select("id,project_code,name")
        .order("project_code", desc=False)
        .execute()
    )
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
def fetch_transactions(date_from: date, date_to: date,
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
            "payment_method,competence_month,notes,created_at,created_by"
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


def refresh_all_caches():
    fetch_projects.clear()
    fetch_categories.clear()
    fetch_counterparties.clear()
    fetch_transactions.clear()


def insert_tx(payload: dict):
    return sb.table("finance_transactions").insert(payload).execute()


def update_tx(tx_id: str, payload: dict):
    return sb.table("finance_transactions").update(payload).eq("id", tx_id).execute()


def delete_tx(tx_id: str):
    return sb.table("finance_transactions").delete().eq("id", tx_id).execute()


# ==========================================================
# Carregar dropdowns
# ==========================================================
projects_df = fetch_projects()
categories_df = fetch_categories()
counterparties_df = fetch_counterparties()

# Mapas label -> id (sem digitação livre)
project_options = ["(Todos)"]
project_map: dict[str, str | None] = {"(Todos)": None}
if not projects_df.empty:
    for _, r in projects_df.iterrows():
        label = f"{norm(r.get('project_code'))} — {norm(r.get('name'))}".strip(" —")
        project_options.append(label)
        project_map[label] = norm(r.get("id")) or None

category_options = ["(Todas)"]
category_map: dict[str, str | None] = {"(Todas)": None}
if not categories_df.empty:
    for _, r in categories_df.iterrows():
        label = norm(r.get("name"))
        category_options.append(label)
        category_map[label] = norm(r.get("id")) or None

cp_options = ["(Todas)"]
cp_map: dict[str, str | None] = {"(Todas)": None}
if not counterparties_df.empty:
    for _, r in counterparties_df.iterrows():
        label = norm(r.get("name"))
        cp_options.append(label)
        cp_map[label] = norm(r.get("id")) or None


# ==========================================================
# Filtros
# ==========================================================
st.subheader("Filtros")

today = date.today()
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
        proj_label = st.selectbox("Projeto", project_options, index=0)
    with f6:
        cat_label = st.selectbox("Categoria", category_options, index=0)

    g1, g2 = st.columns([2.0, 2.0])
    with g1:
        cp_label = st.selectbox("Cliente/Fornecedor", cp_options, index=0)
    with g2:
        if st.button("Recarregar dados"):
            refresh_all_caches()
            st.rerun()

f_project_id = project_map.get(proj_label)
f_type = None if t_type == "(Todos)" else t_type
f_status = None if status == "(Todos)" else status
f_category_id = category_map.get(cat_label)
f_counterparty_id = cp_map.get(cp_label)


# ==========================================================
# Criar lançamento
# ==========================================================
st.divider()
st.subheader("Novo lançamento")

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
        new_cat_label = st.selectbox("Categoria", category_options, index=0, key="new_cat")
    with e2:
        new_cp_label = st.selectbox("Cliente/Fornecedor", cp_options, index=0, key="new_cp")
    with e3:
        new_proj_label = st.selectbox("Projeto (opcional)", ["(Nenhum)"] + project_options[1:], index=0, key="new_proj")

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
                "category_id": category_map.get(new_cat_label),
                "counterparty_id": cp_map.get(new_cp_label),
                "project_id": project_map.get(new_proj_label) if new_proj_label != "(Nenhum)" else None,
                "payment_method": norm(new_payment) or None,
                "competence_month": new_comp.isoformat() if new_comp else None,
                "notes": norm(new_notes) or None,
                "created_by": user_email or None,
            }

            try:
                insert_tx(payload)
                st.success("Lançamento criado.")
                fetch_transactions.clear()
                st.rerun()
            except Exception as e:
                st.error("Erro ao salvar lançamento:")
                st.code(_api_error_message(e))


# ==========================================================
# Lista + edição inline
# ==========================================================
st.divider()
st.subheader("Lançamentos (edite direto aqui)")
st.caption("✅ Edite na tabela e clique em **Salvar alterações**.")

df = fetch_transactions(
    date_from=date_from,
    date_to=date_to,
    project_id=f_project_id,
    t_type=f_type,
    status=f_status,
    category_id=f_category_id,
    counterparty_id=f_counterparty_id,
)

if df.empty:
    st.info("Nenhum lançamento encontrado.")
    st.stop()

# montar DF por LISTAS e guardar id no index (igual Projetos.py)
ids = safe_text_list(df["id"])

df_show = pd.DataFrame(
    {
        "Data": [to_date(x) for x in df["date"].tolist()],
        "Tipo": safe_text_list(df["type"]),
        "Status": safe_text_list(df["status"]),
        "Descrição": safe_text_list(df["description"]),
        "Valor": df["amount"].tolist(),
        "Pagamento": safe_text_list(df["payment_method"]),
        "Competência": [to_date(x) for x in df["competence_month"].tolist()],
        "Obs": safe_text_list(df["notes"]),
        # Exibição (não editáveis por enquanto)
        "Categoria": safe_text_list(df["category_name"]),
        "Contraparte": safe_text_list(df["counterparty_name"]),
        "Projeto": safe_text_list(df["project_code"]),
    },
    index=ids,
)

edited = st.data_editor(
    df_show,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "Data": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Tipo": st.column_config.SelectboxColumn(options=TYPE_OPTIONS, width="small"),
        "Status": st.column_config.SelectboxColumn(options=STATUS_OPTIONS, width="small"),
        "Descrição": st.column_config.TextColumn(width="large"),
        "Valor": st.column_config.NumberColumn(format="R$ %.2f", width="small"),
        "Pagamento": st.column_config.TextColumn(width="small"),
        "Competência": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Obs": st.column_config.TextColumn(width="large"),
        "Categoria": st.column_config.TextColumn(disabled=True, width="medium"),
        "Contraparte": st.column_config.TextColumn(disabled=True, width="medium"),
        "Projeto": st.column_config.TextColumn(disabled=True, width="small"),
    },
)

cbtn1, cbtn2 = st.columns([1, 1])
save_inline = cbtn1.button("Salvar alterações", type="primary")
reload_inline = cbtn2.button("Recarregar")

if reload_inline:
    fetch_transactions.clear()
    st.rerun()

if save_inline:
    try:
        before = df_show.copy()
        after = edited.copy()

        compare_cols = ["Data", "Tipo", "Status", "Descrição", "Valor", "Pagamento", "Competência", "Obs"]
        n_updates = 0
        warnings: list[str] = []

        for tx_id, ra in after.iterrows():
            rb = before.loc[tx_id]

            changed = False
            for c in compare_cols:
                if norm(rb[c]) != norm(ra[c]):
                    changed = True
                    break
            if not changed:
                continue

            if norm(ra["Descrição"]) == "":
                warnings.append(f"Lançamento {tx_id}: descrição obrigatória (update ignorado).")
                continue
            try:
                amount = float(ra["Valor"])
                if amount <= 0:
                    warnings.append(f"Lançamento {tx_id}: valor deve ser > 0 (update ignorado).")
                    continue
            except Exception:
                warnings.append(f"Lançamento {tx_id}: valor inválido (update ignorado).")
                continue

            payload = {
                "date": ra["Data"].isoformat() if ra["Data"] else None,
                "type": norm(ra["Tipo"]) if norm(ra["Tipo"]) in TYPE_OPTIONS else "DESPESA",
                "status": norm(ra["Status"]) if norm(ra["Status"]) in STATUS_OPTIONS else "REALIZADO",
                "description": norm(ra["Descrição"]),
                "amount": float(ra["Valor"]),
                "payment_method": norm(ra["Pagamento"]) or None,
                "competence_month": ra["Competência"].isoformat() if ra["Competência"] else None,
                "notes": norm(ra["Obs"]) or None,
            }

            update_tx(str(tx_id), payload)
            n_updates += 1

        if warnings:
            st.warning("\n".join(warnings))

        st.success(f"Atualizados: {n_updates}")
        fetch_transactions.clear()
        st.rerun()

    except Exception as e:
        st.error("Erro ao salvar alterações:")
        st.code(_api_error_message(e))


# ==========================================================
# Excluir seguro (checkbox + confirmação)
# ==========================================================
st.divider()
st.subheader("Excluir lançamento")
st.caption("⚠️ Exclusão é permanente. Selecione e confirme antes de excluir.")

with st.container(border=True):
    d1, d2 = st.columns([1.2, 3.0])
    with d1:
        delete_mode = st.checkbox("Excluir?", value=False)

    if delete_mode:
        # montar opções com label amigável
        options = []
        opt_map: dict[str, str] = {}

        for _, r in df.iterrows():
            tx_id = norm(r.get("id"))
            label = f"{norm(r.get('date'))} | {norm(r.get('type'))} | R$ {r.get('amount')} | {norm(r.get('description'))}"
            options.append(label)
            opt_map[label] = tx_id

        with d2:
            sel = st.selectbox("Selecione o lançamento", options)

        confirm = st.checkbox("Confirmo que quero excluir este lançamento", value=False)

        if st.button("Excluir definitivamente", disabled=(not confirm)):
            try:
                delete_tx(opt_map.get(sel))
                st.success("Lançamento excluído.")
                fetch_transactions.clear()
                st.rerun()
            except Exception as e:
                st.error("Erro ao excluir:")
                st.code(_api_error_message(e))
