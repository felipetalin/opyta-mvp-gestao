# app/pages/1_Portfolio_Gantt.py
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date

from services.auth import require_login
from services.supabase_client import get_authed_client

st.set_page_config(page_title="Portfólio Gantt", layout="wide")

require_login()
sb = get_authed_client()

st.title("Portfólio – Gantt")

# -----------------------------
# Carrega dados da VIEW (padrão)
# -----------------------------
@st.cache_data(ttl=30)
def fetch_portfolio_view():
    """
    Espera a view public.v_portfolio_tasks já criada no Supabase.
    Campos esperados (mínimo):
      - project_code, project_name
      - title
      - tipo_atividade
      - assignee_name
      - start_date, end_date
      - status (opcional)
      - date_confidence (opcional)
    """
    res = sb.table("v_portfolio_tasks").select("*").execute()
    return pd.DataFrame(res.data or [])


df = fetch_portfolio_view()

if df.empty:
    st.warning("Nenhuma tarefa encontrada na view v_portfolio_tasks.")
    st.stop()

# -----------------------------
# Normalização de tipos
# -----------------------------
for col in ["start_date", "end_date"]:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")

# remove linhas sem datas
df = df.dropna(subset=["start_date", "end_date"]).copy()
if df.empty:
    st.warning("Existem tarefas, mas nenhuma tem start_date/end_date válidos.")
    st.stop()

# -----------------------------
# Filtros (simples e úteis)
# -----------------------------
with st.container(border=True):
    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])

    # Período (padrão: mês atual)
    today = date.today()
    first_day = date(today.year, today.month, 1)
    # último dia do mês:
    if today.month == 12:
        last_day = date(today.year, 12, 31)
    else:
        last_day = date(today.year, today.month + 1, 1) - pd.Timedelta(days=1)
        

from datetime import datetime, date

# Se for datetime → pode usar .date()
if isinstance(last_day, datetime):
    last_day = last_day.date()

# Se já for date → NÃO faz nada

    with c1:
        start_filter = st.date_input("De", value=first_day)
    with c2:
        end_filter = st.date_input("Até", value=last_day)

    # projeto
    proj_opts = sorted(df["project_code"].dropna().unique().tolist()) if "project_code" in df.columns else []
    with c3:
        proj_sel = st.selectbox("Projeto (código)", ["(Todos)"] + proj_opts)

    # profissionais
    people_opts = sorted(df["assignee_name"].dropna().unique().tolist()) if "assignee_name" in df.columns else []
    with c4:
        people_sel = st.selectbox("Profissional", ["(Todos)"] + people_opts)

# aplica filtros
mask = (df["start_date"].dt.date <= end_filter) & (df["end_date"].dt.date >= start_filter)
df_f = df.loc[mask].copy()

if proj_sel != "(Todos)" and "project_code" in df_f.columns:
    df_f = df_f[df_f["project_code"] == proj_sel]

if people_sel != "(Todos)" and "assignee_name" in df_f.columns:
    df_f = df_f[df_f["assignee_name"] == people_sel]

if df_f.empty:
    st.info("Nenhuma tarefa no período/filtros selecionados.")
    st.stop()

# -----------------------------
# Ordenação cronológica (crítica)
# -----------------------------
df_f = df_f.sort_values(["start_date", "end_date", "project_code", "title"], na_position="last").reset_index(drop=True)

# -----------------------------
# Campos para visual
# -----------------------------
df_f["label"] = df_f.apply(
    lambda r: f"{r.get('project_code','')} – {r.get('title','')}".strip(" –"),
    axis=1,
)

# -----------------------------
# Gantt (Plotly Timeline)
# -----------------------------
color_col = "tipo_atividade" if "tipo_atividade" in df_f.columns else None

fig = px.timeline(
    df_f,
    x_start="start_date",
    x_end="end_date",
    y="label",
    color=color_col,
    hover_data=[
        "project_code" if "project_code" in df_f.columns else None,
        "project_name" if "project_name" in df_f.columns else None,
        "assignee_name" if "assignee_name" in df_f.columns else None,
        "status" if "status" in df_f.columns else None,
        "date_confidence" if "date_confidence" in df_f.columns else None,
        "start_date",
        "end_date",
    ],
)

# Remove None da lista do hover
fig.update_traces(hovertemplate=None)
fig.update_yaxes(autorange="reversed")  # mais “natural” (primeiras tarefas em cima)
fig.update_layout(
    height=min(1200, 300 + 18 * len(df_f)),  # ajusta altura
    margin=dict(l=10, r=10, t=30, b=10),
    xaxis_title="Datas",
    yaxis_title="",
    legend_title="Tipo",
)

st.plotly_chart(fig, use_container_width=True)

# opcional: tabela escondida (debug leve)
with st.expander("Ver dados filtrados (opcional)"):
    show_cols = [c for c in ["project_code", "project_name", "title", "tipo_atividade", "assignee_name", "status", "date_confidence", "start_date", "end_date"] if c in df_f.columns]
    st.dataframe(df_f[show_cols], use_container_width=True, hide_index=True)






