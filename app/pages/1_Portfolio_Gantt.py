# app/pages/1_Portfolio_Gantt.py

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, timedelta

from services.auth import require_login
from services.supabase_client import get_authed_client

# -------------------------------------------------
# Configuração básica
# -------------------------------------------------
st.set_page_config(page_title="Portfólio (Gantt)", layout="wide")
st.title("Portfólio (Gantt)")

require_login()
sb = get_authed_client()

# -------------------------------------------------
# Carregar dados
# -------------------------------------------------
@st.cache_data(ttl=30)
def fetch_portfolio():
    res = sb.table("v_portfolio_tasks").select("*").execute()
    return pd.DataFrame(res.data or [])

df = fetch_portfolio()

if df.empty:
    st.info("Nenhuma tarefa encontrada.")
    st.stop()

# -------------------------------------------------
# Normalização
# -------------------------------------------------
df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
df["end_date"] = df["end_date"].fillna(df["start_date"])
df = df.dropna(subset=["start_date", "end_date"])

df["assignee_name"] = df["assignee_name"].fillna("Gestão de Projetos")

df["label"] = (
    df["project_code"].fillna("") + " | " + df["title"].fillna("")
).str.strip(" |")

# -------------------------------------------------
# Filtros (layout mock)
# -------------------------------------------------
today = date.today()
first_day = date(today.year, today.month, 1)
next_month = first_day.replace(day=28) + timedelta(days=4)
last_day = next_month - timedelta(days=next_month.day)

c1, c2, c3, c4 = st.columns([1.6, 2.2, 2.8, 2.2])

with c1:
    project_sel = st.selectbox(
        "Projeto",
        ["Todos"] + sorted(df["project_code"].dropna().unique().tolist()),
    )

with c2:
    type_sel = st.multiselect(
        "Tipo Atividade",
        sorted(df["tipo_atividade"].dropna().unique().tolist()),
        default=sorted(df["tipo_atividade"].dropna().unique().tolist()),
    )

with c3:
    people_sel = st.multiselect(
        "Profissionais",
        sorted(df["assignee_name"].unique().tolist()),
        default=sorted(df["assignee_name"].unique().tolist()),
    )

with c4:
    period = st.date_input(
        "Período",
        value=(first_day, last_day),
        format="DD/MM/YYYY",
    )

if not isinstance(period, tuple):
    st.stop()

p_start, p_end = map(pd.to_datetime, period)

# -------------------------------------------------
# Aplicar filtros
# -------------------------------------------------
f = df.copy()

f = f[(f["start_date"] <= p_end) & (f["end_date"] >= p_start)]

if project_sel != "Todos":
    f = f[f["project_code"] == project_sel]

f = f[f["tipo_atividade"].isin(type_sel)]
f = f[f["assignee_name"].isin(people_sel)]

if f.empty:
    st.info("Nenhuma tarefa para os filtros selecionados.")
    st.stop()

f["plot_start"] = f["start_date"].clip(lower=p_start)
f["plot_end"] = f["end_date"].clip(upper=p_end)

# -------------------------------------------------
# GANTT
# -------------------------------------------------
color_map = {
    "CAMPO": "#1B5E20",
    "RELATORIO": "#66BB6A",
}

fig = px.timeline(
    f,
    x_start="plot_start",
    x_end="plot_end",
    y="label",
    color="tipo_atividade",
    color_discrete_map=color_map,
    text="assignee_name",
    hover_data=[
        "project_code",
        "project_name",
        "title",
        "assignee_name",
        "status",
        "date_confidence",
        "start_date",
        "end_date",
    ],
)

fig.update_yaxes(autorange="reversed", title="Projeto / Tarefa")

fig.update_traces(
    textposition="inside",
    insidetextanchor="middle",
    cliponaxis=False,
)

# -------------------------------------------------
# Eixo X diário + fins de semana
# -------------------------------------------------
days = pd.date_range(p_start, p_end, freq="D")

fig.update_xaxes(
    range=[p_start, p_end],
    tickangle=-90,
    showgrid=True,
    gridcolor="rgba(0,0,0,0.05)",
)

shapes = []
for d in days:
    if d.weekday() >= 5:
        shapes.append(
            dict(
                type="rect",
                xref="x",
                yref="paper",
                x0=d,
                x1=d + timedelta(days=1),
                y0=0,
                y1=1,
                fillcolor="rgba(102,187,106,0.12)",
                line=dict(width=0),
                layer="below",
            )
        )

fig.update_layout(
    shapes=shapes,
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="center",
        x=0.5,
        title="",
    ),
    height=max(450, 80 + f["label"].nunique() * 55),
    margin=dict(l=10, r=10, t=50, b=40),
)

# -------------------------------------------------
# Render
# -------------------------------------------------
st.plotly_chart(fig, use_container_width=True)

with st.expander("Dados (opcional)"):
    st.dataframe(f, use_container_width=True, hide_index=True)


