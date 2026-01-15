# app/pages/1_Portfolio_Gantt.py
import os
import sys
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

# Garante que /app consiga importar /services no Streamlit Cloud
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from services.auth import require_login, inject_session  # noqa: E402

# ---------------------------
# Config
# ---------------------------
load_dotenv()
st.set_page_config(page_title="Portfólio (Gantt)", layout="wide")
st.title("Portfólio (Gantt)")

require_login()
sb = inject_session()

# ---------------------------
# Helpers
# ---------------------------
def month_range(d: date):
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1, day=1)
    else:
        nxt = first.replace(month=first.month + 1, day=1)
    last = nxt - timedelta(days=1)
    return first, last


def abbreviate_name(name: str) -> str:
    """Ex.: 'Ismayllen Masson' -> 'I. Masson' ; 'Felipe' -> 'Felipe'"""
    if not name:
        return ""
    parts = [p for p in name.split() if p.strip()]
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0][0]}. {parts[-1]}"


def pt_weekday_letter(d: date) -> str:
    # Monday=0 ... Sunday=6  -> STQQSSD
    letters = ["S", "T", "Q", "Q", "S", "S", "D"]
    return letters[d.weekday()]


def to_dt(x):
    """Sempre retorna Timestamp ou NaT"""
    return pd.to_datetime(x, errors="coerce")


@st.cache_data(ttl=30)
def load_portfolio():
    res = sb.table("v_portfolio_tasks").select("*").execute()
    return pd.DataFrame(res.data or [])


# ---------------------------
# Load data
# ---------------------------
df = load_portfolio()

if df.empty:
    st.info("Ainda não há tarefas no portfólio.")
    st.stop()

# Normalizações principais
df["start_date"] = to_dt(df.get("start_date"))
df["end_date"] = to_dt(df.get("end_date"))
df["end_date"] = df["end_date"].fillna(df["start_date"])
df = df.dropna(subset=["start_date", "end_date"]).copy()

df["assignee_name"] = df.get("assignee_name", "").fillna("Gestão de Projetos")
df["project_code"] = df.get("project_code", "").astype(str)
df["title"] = df.get("title", "").astype(str)
df["tipo_atividade"] = df.get("tipo_atividade", "").astype(str)

# Label: "COD — Tarefa"
df["label"] = df["project_code"].astype(str) + " — " + df["title"].astype(str)

# Status concluída
df["status"] = df.get("status", "").astype(str)
df["is_done"] = df["status"].str.upper().eq("CONCLUIDA")

# ---------------------------
# Sidebar Filters (layout antigo/limpo)
# ---------------------------
st.sidebar.header("Filtros")

projects = ["Todos"] + sorted([p for p in df["project_code"].dropna().unique().tolist() if p and p != "nan"])
types_all = sorted([t for t in df["tipo_atividade"].dropna().unique().tolist() if t and t != "nan"])
people_all = sorted([p for p in df["assignee_name"].dropna().unique().tolist() if p and p != "nan"])

today = date.today()
d0, d1 = month_range(today)

sel_project = st.sidebar.selectbox("Projeto", projects, index=0)

sel_types = st.sidebar.multiselect(
    "Tipo de atividade",
    options=types_all if types_all else ["CAMPO", "RELATORIO"],
    default=types_all if types_all else ["CAMPO", "RELATORIO"],
)

sel_people = st.sidebar.multiselect(
    "Profissionais",
    options=people_all,
    default=people_all,
)

period = st.sidebar.date_input("Período", value=(d0, d1), format="DD/MM/YYYY")
if isinstance(period, tuple) and len(period) == 2:
    p_start, p_end = period
else:
    p_start, p_end = d0, d1

# ---------------------------
# Apply filters
# ---------------------------
f = df.copy()

if sel_project != "Todos":
    f = f[f["project_code"] == sel_project]

if sel_types:
    f = f[f["tipo_atividade"].isin(sel_types)]
else:
    f = f.iloc[0:0]

if sel_people:
    f = f[f["assignee_name"].isin(sel_people)]
else:
    f = f.iloc[0:0]

# Período (interseção)
p_start_dt = pd.to_datetime(p_start)
p_end_dt = pd.to_datetime(p_end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

f = f[(f["start_date"] <= p_end_dt) & (f["end_date"] >= p_start_dt)].copy()

if f.empty:
    st.info("Nenhuma tarefa nesse filtro/período.")
    st.stop()

# Clamp para plot
f["plot_start"] = f["start_date"].clip(lower=p_start_dt)
f["plot_end"] = f["end_date"].clip(upper=p_end_dt)

# Texto dentro da barra
f["dur_days"] = (f["plot_end"] - f["plot_start"]).dt.days + 1
f["bar_text"] = f["assignee_name"].astype(str)
short = f["dur_days"] <= 2
f.loc[short, "bar_text"] = f.loc[short, "assignee_name"].astype(str).map(abbreviate_name)

# ---------------------------
# Colors
# ---------------------------
color_map = {"CAMPO": "#1B5E20", "RELATORIO": "#66BB6A", "ADMINISTRATIVO": "#6A1B9A"}
done_color_map = {"CAMPO": "#A5D6A7", "RELATORIO": "#C8E6C9", "ADMINISTRATIVO": "#D1C4E9"}

# ---------------------------
# Build Gantt (abertas + concluídas)
# ---------------------------
open_df = f[~f["is_done"]].copy()
done_df = f[f["is_done"]].copy()

fig = px.timeline(
    open_df,
    x_start="plot_start",
    x_end="plot_end",
    y="label",
    color="tipo_atividade",
    color_discrete_map=color_map,
    text="bar_text",
)

# Concluídas por cima com hatch
if not done_df.empty:
    fig_done = px.timeline(
        done_df,
        x_start="plot_start",
        x_end="plot_end",
        y="label",
        color="tipo_atividade",
        color_discrete_map=done_color_map,
        text="bar_text",
    )
    for tr in fig_done.data:
        tr.marker.pattern = dict(shape="/", size=6, solidity=0.3)
        tr.marker.line = dict(width=1, color="#2E7D32")
        tr.opacity = 1.0
        fig.add_trace(tr)

# Ordem cronológica por menor data
order = f.groupby("label")["plot_start"].min().sort_values().index.tolist()
fig.update_yaxes(categoryorder="array", categoryarray=order, title_text="")

# Texto nas barras
fig.update_traces(textposition="inside", insidetextanchor="middle", cliponaxis=False)

# Legenda horizontal
fig.update_layout(
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5, title_text=""),
    margin=dict(l=10, r=10, t=60, b=40),
)

# Range do eixo X
fig.update_xaxes(range=[p_start_dt, p_end_dt])

# Eixo X: ticks diários com STQQSSD e dia
days = pd.date_range(p_start_dt.date(), p_end_dt.date(), freq="D")
tickvals = [pd.to_datetime(d) for d in days]
ticktext = [f"{pt_weekday_letter(d.date())} {d.day:02d}" for d in days]

fig.update_xaxes(
    tickmode="array",
    tickvals=tickvals,
    ticktext=ticktext,
    tickangle=-90,
    showgrid=True,
    gridcolor="rgba(0,0,0,0.05)",
    title_text="",
)

# Finais de semana com faixas
shapes = []
for d in days:
    if d.weekday() >= 5:
        x0 = pd.to_datetime(d.date())
        x1 = x0 + pd.Timedelta(days=1)
        shapes.append(
            dict(
                type="rect",
                xref="x",
                yref="paper",
                x0=x0,
                x1=x1,
                y0=0,
                y1=1,
                fillcolor="rgba(102,187,106,0.10)",
                line=dict(width=0),
                layer="below",
            )
        )
fig.update_layout(shapes=shapes)

# Altura dinâmica
row_count = f["label"].nunique()
fig.update_layout(height=max(420, 70 + row_count * 55))

st.plotly_chart(fig, use_container_width=True)

with st.expander("Dados (opcional)"):
    cols = [
        "project_code",
        "project_name",
        "title",
        "tipo_atividade",
        "assignee_name",
        "status",
        "start_date",
        "end_date",
        "date_confidence",
    ]
    available = [c for c in cols if c in f.columns]
    st.dataframe(
        f[available].sort_values(["start_date", "project_code", "title"]),
        use_container_width=True,
        hide_index=True,
    )

