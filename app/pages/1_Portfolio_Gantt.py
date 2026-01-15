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
# Carregar dados da VIEW
# -----------------------------
@st.cache_data(ttl=30)
def fetch_portfolio_view():
    res = sb.table("v_portfolio_tasks").select("*").execute()
    return pd.DataFrame(res.data or [])

df = fetch_portfolio_view()

if df.empty:
    st.warning("Nenhuma tarefa encontrada na view v_portfolio_tasks.")
    st.stop()

# -----------------------------
# Normalização de datas
# -----------------------------
df["start_date"] = pd.to_datetime(df.get("start_date"), errors="coerce")
df["end_date"] = pd.to_datetime(df.get("end_date"), errors="coerce")

df = df.dropna(subset=["start_date", "end_date"]).copy()
if df.empty:
    st.warning("Existem registros, mas sem start_date/end_date válidos.")
    st.stop()

# -----------------------------
# Filtros (PERÍODO + Projeto + Profissional + Tipo)
# -----------------------------
today = date.today()
first_day = date(today.year, today.month, 1)

# último dia do mês atual (sem gambiarra)
if today.month == 12:
    last_day = date(today.year, 12, 31)
else:
    next_month_first = date(today.year, today.month + 1, 1)
    last_day = next_month_first - pd.Timedelta(days=1)
    last_day = last_day.to_pydatetime().date()  # garante date

project_options = ["(Todos)"] + sorted(df["project_code"].dropna().unique().tolist()) if "project_code" in df.columns else ["(Todos)"]
assignee_options = ["(Todos)"] + sorted(df["assignee_name"].dropna().unique().tolist()) if "assignee_name" in df.columns else ["(Todos)"]
tipo_options = ["(Todos)"] + sorted(df["tipo_atividade"].dropna().unique().tolist()) if "tipo_atividade" in df.columns else ["(Todos)"]

with st.container(border=True):
    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])

    with c1:
        period = st.date_input(
            "Período",
            value=(first_day, last_day),
            format="DD/MM/YYYY",
        )

    with c2:
        project_sel = st.selectbox("Projeto", project_options, index=0)

    with c3:
        assignee_sel = st.selectbox("Profissional", assignee_options, index=0)

    with c4:
        tipo_sel = st.selectbox("Atividade", tipo_options, index=0)

if not isinstance(period, tuple) or len(period) != 2:
    st.error("Selecione um período válido (início e fim).")
    st.stop()

period_start, period_end = period
period_start = pd.to_datetime(period_start)
period_end = pd.to_datetime(period_end)

df_f = df.copy()

# filtro por interseção do período
df_f = df_f[
    (df_f["end_date"] >= period_start) &
    (df_f["start_date"] <= period_end)
].copy()

if project_sel != "(Todos)" and "project_code" in df_f.columns:
    df_f = df_f[df_f["project_code"] == project_sel]

if assignee_sel != "(Todos)" and "assignee_name" in df_f.columns:
    df_f = df_f[df_f["assignee_name"] == assignee_sel]

if tipo_sel != "(Todos)" and "tipo_atividade" in df_f.columns:
    df_f = df_f[df_f["tipo_atividade"] == tipo_sel]

if df_f.empty:
    st.info("Nenhuma tarefa para os filtros/período selecionados.")
    st.stop()

# ordenação cronológica
sort_cols = [c for c in ["start_date", "end_date", "project_code", "title"] if c in df_f.columns]
df_f = df_f.sort_values(sort_cols, na_position="last").reset_index(drop=True)

# label no eixo Y: PROJ — TAREFA
proj = df_f["project_code"].fillna("") if "project_code" in df_f.columns else ""
titl = df_f["title"].fillna("") if "title" in df_f.columns else ""
df_f["label"] = (proj + " — " + titl).str.strip(" —")

# -----------------------------
# Gantt (Plotly Timeline)
# -----------------------------
color_col = "tipo_atividade" if "tipo_atividade" in df_f.columns else None

hover_cols = []
for c in ["project_code", "project_name", "title", "assignee_name", "tipo_atividade", "status", "date_confidence", "start_date", "end_date"]:
    if c in df_f.columns:
        hover_cols.append(c)

fig = px.timeline(
    df_f,
    x_start="start_date",
    x_end="end_date",
    y="label",
    color=color_col,
    hover_data=hover_cols,
)

fig.update_yaxes(autorange="reversed")
fig.update_layout(
    height=min(1200, 300 + 18 * len(df_f)),
    margin=dict(l=10, r=10, t=30, b=10),
    xaxis_title="Datas",
    yaxis_title="",
    legend_title="Atividade",
)

# fixa janela no período
fig.update_xaxes(range=[period_start, period_end])

st.plotly_chart(fig, use_container_width=True)

with st.expander("Dados (opcional)"):
    st.dataframe(df_f, use_container_width=True, hide_index=True)







