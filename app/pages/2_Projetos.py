# app/pages/2_Projetos.py

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
st.set_page_config(page_title="Projetos", layout="wide")
apply_brand()
apply_app_chrome()

require_login()
sb = get_authed_client()

page_header("Projetos", "Cadastro e edição", st.session_state.get("user_email", ""))


# ==========================================================
# Helpers
# ==========================================================
STATUS_OPTIONS = ["ATIVO", "PAUSADO", "CONCLUIDO"]


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


@st.cache_data(ttl=30)
def fetch_projects():
    res = (
        sb.table("projects")
        .select("id,project_code,name,client,status,start_date,end_date_planned,notes,created_at")
        .order("created_at", desc=True)
        .execute()
    )
    return pd.DataFrame(res.data or [])


def refresh_projects_cache():
    fetch_projects.clear()


def upsert_project(project_id: str | None, payload: dict):
    if project_id:
        return sb.table("projects").update(payload).eq("id", project_id).execute()
    return sb.table("projects").insert(payload).execute()


# ==========================================================
# Criar projeto
# ==========================================================
st.subheader("Criar projeto")

with st.container(border=True):
    c1, c2, c3 = st.columns([1.2, 2.2, 1.6])
    with c1:
        new_code = st.text_input("Código", value="", placeholder="ex: BRACE001")
    with c2:
        new_name = st.text_input("Nome", value="")
    with c3:
        new_client = st.text_input("Cliente", value="")

    c4, c5, c6 = st.columns([1.2, 1.2, 1.2])
    with c4:
        new_status = st.selectbox("Status", STATUS_OPTIONS, index=0)
    with c5:
        new_start = st.date_input("Início", value=date.today(), format="DD/MM/YYYY")
    with c6:
        new_end = st.date_input("Fim previsto", value=date.today(), format="DD/MM/YYYY")

    new_notes = st.text_area("Observações", value="", height=90)

    if st.button("Salvar projeto", type="primary"):
        payload = {
            "project_code": norm(new_code) or None,
            "name": norm(new_name) or None,
            "client": norm(new_client) or None,
            "status": new_status,
            "start_date": new_start.isoformat() if new_start else None,
            "end_date_planned": new_end.isoformat() if new_end else None,
            "notes": norm(new_notes) or None,
        }

        if not payload["project_code"] or not payload["name"]:
            st.error("Informe pelo menos Código e Nome.")
        else:
            try:
                upsert_project(None, payload)
                st.success("Projeto criado.")
                refresh_projects_cache()
                st.rerun()
            except Exception as e:
                st.error("Erro ao salvar projeto:")
                st.code(_api_error_message(e))


# ==========================================================
# Lista + edição inline (UX refinada: ID escondido via index)
# ==========================================================
st.divider()
st.subheader("Lista de Projetos (edite direto aqui)")

st.info("✅ Edite na tabela e clique em **Salvar alterações**. (O ID fica oculto)")

df = fetch_projects()
if df.empty:
    st.info("Nenhum projeto cadastrado.")
    st.stop()

df = df.copy()

df_show = pd.DataFrame(
    {
        "Código": df["project_code"].fillna("").astype(str),
        "Nome": df["name"].fillna("").astype(str),
        "Cliente": df["client"].fillna("").astype(str),
        "Status": df["status"].fillna("ATIVO").astype(str),
        "Início": df["start_date"].apply(to_date),
        "Fim previsto": df["end_date_planned"].apply(to_date),
        "Obs": df["notes"].fillna("").astype(str),
    },
    index=df["id"].astype(str),  # ✅ ID fica no index (oculto)
)

edited = st.data_editor(
    df_show,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "Código": st.column_config.TextColumn(width="medium"),
        "Nome": st.column_config.TextColumn(width="large"),
        "Cliente": st.column_config.TextColumn(width="medium"),
        "Status": st.column_config.SelectboxColumn(options=STATUS_OPTIONS, width="small"),
        "Início": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Fim previsto": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Obs": st.column_config.TextColumn(width="large"),
    },
)

cbtn1, cbtn2 = st.columns([1, 1])
save_inline = cbtn1.button("Salvar alterações", type="primary")
reload_inline = cbtn2.button("Recarregar")

if reload_inline:
    refresh_projects_cache()
    st.rerun()

if save_inline:
    try:
        before = df_show.copy()
        after = edited.copy()

        compare_cols = ["Código", "Nome", "Cliente", "Status", "Início", "Fim previsto", "Obs"]

        n_updates = 0
        warnings: list[str] = []

        for project_id, ra in after.iterrows():
            rb = before.loc[project_id]

            changed = False
            for c in compare_cols:
                if norm(rb[c]) != norm(ra[c]):
                    changed = True
                    break
            if not changed:
                continue

            code = norm(ra["Código"])
            name = norm(ra["Nome"])
            if not code or not name:
                warnings.append(f"Projeto '{name or '(sem nome)'}': Código e Nome são obrigatórios (update ignorado).")
                continue

            payload = {
                "project_code": code,
                "name": name,
                "client": norm(ra["Cliente"]) or None,
                "status": norm(ra["Status"]) if norm(ra["Status"]) in STATUS_OPTIONS else "ATIVO",
                "start_date": ra["Início"].isoformat() if ra["Início"] else None,
                "end_date_planned": ra["Fim previsto"].isoformat() if ra["Fim previsto"] else None,
                "notes": norm(ra["Obs"]) or None,
            }

            sb.table("projects").update(payload).eq("id", str(project_id)).execute()
            n_updates += 1

        if warnings:
            st.warning("\n".join(warnings))

        st.success(f"Atualizados: {n_updates}")
        refresh_projects_cache()
        st.rerun()

    except Exception as e:
        st.error("Erro ao salvar alterações:")
        st.code(_api_error_message(e))


