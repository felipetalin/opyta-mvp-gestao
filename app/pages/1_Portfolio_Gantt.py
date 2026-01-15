# --- PATH BOOTSTRAP (Streamlit Cloud) ---
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # raiz do repo
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# ----------------------------------------



import os
import sys
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

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
    # próximo mês
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

def parse_date(x):
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return None

@st.cache_data(ttl=30)
def load_portfolio():
    # View criada por você: public.v_portfolio_tasks
    res = sb.table("v_portfolio_tasks").select("*").execute()
    return pd.DataFrame(res.data or [])

# ---------------------------
# Load data
# ---------------------------
df = load_portfolio()

if df.empty:
    st.info("Ainda não há tarefas no portfólio (ou os filtros zeraram a lista).")
    st.stop()

# Normalizações
# colunas esperadas na view:
# task_id, project_id, project_code, project_name, title, tipo_atividade,
# assignee_name, assignee_id, status, start_date, end_date, date_confidence, priority, progress_pct

df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")

# se algum fim estiver vazio, assume início (tarefa de 1 dia)
df["end_date"] = df["end_date"].fillna(df["start_date"])

# label no formato "COD | Tarefa"
df["label"] = df["project_code"].astype(str) + " | " + df["title"].astype(str)

# responsavel display
df["assignee_name"] = df["assignee_name"].fillna("Gestao de Projetos")

# ---------------------------
# Filters
# ---------------------------
c1, c2, c3, c4 = st.columns([1.5, 1.4, 2.0, 1.8])

projects = ["Todos"] + sorted(df["project_code"].dropna().unique().tolist())
types = ["CAMPO", "RELATORIO"]
people = sorted(df["assignee_name"].dropna().unique().tolist())

today = date.today()
d0, d1 = month_range(today)

with c1:
    sel_project = st.selectbox("Projeto", projects, index=0)

with c2:
    sel_types = st.multiselect("Tipo Atividade", types, default=types)

with c3:
    sel_people = st.multiselect("Profissionais", people, default=people)

with c4:
    # Período: range
    period = st.date_input("Período", value=(d0, d1), format="DD/MM/YYYY")
    if isinstance(period, tuple) and len(period) == 2:
        p_start, p_end = period
    else:
        p_start, p_end = d0, d1

# aplica filtros
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

# filtro período (interseção com janela)
p_start_dt = pd.to_datetime(p_start)
p_end_dt = pd.to_datetime(p_end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

f = f[
    (f["start_date"] <= p_end_dt) &
    (f["end_date"] >= p_start_dt)
].copy()

if f.empty:
    st.info("Ainda não há tarefas no portfólio (ou os filtros zeraram a lista).")
    st.stop()

# recorta visualmente (clamp) para melhorar plot
f["plot_start"] = f["start_date"].clip(lower=p_start_dt)
f["plot_end"] = f["end_date"].clip(upper=p_end_dt)

# status concluída
f["is_done"] = f["status"].astype(str).str.upper().eq("CONCLUIDA")

# rótulo dentro da barra: completo ou abreviado
# (usamos abreviado quando a duração é curta)
f["dur_days"] = (f["plot_end"] - f["plot_start"]).dt.days + 1
f["bar_text"] = f["assignee_name"].astype(str)
f.loc[f["dur_days"] <= 2, "bar_text"] = f.loc[f["dur_days"] <= 2, "assignee_name"].astype(str).map(abbreviate_name)

# ---------------------------
# Colors (tons de verde)
# ---------------------------
# CAMPO = verde escuro, RELATORIO = verde claro
color_map = {
    "CAMPO": "#1B5E20",
    "RELATORIO": "#66BB6A",
}

# concluída: clareia e usa pattern
done_color_map = {
    "CAMPO": "#A5D6A7",
    "RELATORIO": "#C8E6C9",
}

# ---------------------------
# Build Gantt (2 camadas: abertas e concluídas)
# ---------------------------
open_df = f[~f["is_done"]].copy()
done_df = f[f["is_done"]].copy()

# Figura base (abertas)
fig = px.timeline(
    open_df,
    x_start="plot_start",
    x_end="plot_end",
    y="label",
    color="tipo_atividade",
    color_discrete_map=color_map,
    text="bar_text",
    hover_data={
        "project_code": True,
        "project_name": True,
        "title": True,
        "assignee_name": True,
        "status": True,
        "start_date": True,
        "end_date": True,
        "date_confidence": True,
        "tipo_atividade": True,
        "plot_start": False,
        "plot_end": False,
        "label": False,
    },
)

# Camada concluídas (sobrepõe)
if not done_df.empty:
    fig_done = px.timeline(
        done_df,
        x_start="plot_start",
        x_end="plot_end",
        y="label",
        color="tipo_atividade",
        color_discrete_map=done_color_map,
        text="bar_text",
        hover_data={
            "project_code": True,
            "project_name": True,
            "title": True,
            "assignee_name": True,
            "status": True,
            "start_date": True,
            "end_date": True,
            "date_confidence": True,
            "tipo_atividade": True,
            "plot_start": False,
            "plot_end": False,
            "label": False,
        },
    )
    for tr in fig_done.data:
        # pattern/chanfrado visual (hatch)
        tr.marker.pattern = dict(shape="/", size=6, solidity=0.3)
        tr.marker.line = dict(width=1, color="#2E7D32")
        tr.opacity = 1.0
        fig.add_trace(tr)

# ---------------------------
# Layout / Axis formatting
# ---------------------------
# Ordena y para ficar “cronológico” pela primeira data
order = (
    f.groupby("label")["plot_start"]
    .min()
    .sort_values(ascending=True)
    .index
    .tolist()
)
fig.update_yaxes(categoryorder="array", categoryarray=order, title_text="Projeto/Tarefa")

# Texto dentro das barras
fig.update_traces(
    textposition="inside",
    insidetextanchor="middle",
    cliponaxis=False,
)

# Legenda centralizada em cima
fig.update_layout(
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5, title_text=""),
    margin=dict(l=10, r=10, t=60, b=40),
)

# Range do eixo X
fig.update_xaxes(range=[p_start_dt, p_end_dt])

# Eixo X: ticks diários com STQQSSD e dia numérico
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

# Finais de semana com faixas verticais (verde bem claro)
shapes = []
for d in days:
    if d.weekday() >= 5:  # 5=sábado, 6=domingo
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
                fillcolor="rgba(102,187,106,0.10)",  # verde claro transparente
                line=dict(width=0),
                layer="below",
            )
        )
fig.update_layout(shapes=shapes)

# Altura dinâmica
row_count = f["label"].nunique()
fig.update_layout(height=max(420, 70 + row_count * 55))

# ---------------------------
# Render
# ---------------------------
st.plotly_chart(fig, use_container_width=True)




