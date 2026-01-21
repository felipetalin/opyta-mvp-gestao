# app/pages/1_Portfolio_Gantt.py

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, timedelta

from services.auth import require_login
from services.supabase_client import get_authed_client

st.set_page_config(page_title="Portfólio (Gantt)", layout="wide")
st.title("Portfólio (Gantt) — MOCK")

require_login()
sb = get_authed_client()

# -----------------------------
# Helpers
# -----------------------------
def month_range(d: date):
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1, day=1)
    else:
        nxt = first.replace(month=first.month + 1, day=1)
    last = nxt - timedelta(days=1)
    return first, last

def pt_weekday_letter(d: date) -> str:
    letters = ["S", "T", "Q", "Q", "S", "S", "D"]
    return letters[d.weekday()]

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
# Normalização de datas + colunas
# -----------------------------
df["start_date"] = pd.to_datetime(df.get("start_date"), errors="coerce")
df["end_date"] = pd.to_datetime(df.get("end_date"), errors="coerce")
df["end_date"] = df["end_date"].fillna(df["start_date"])
df = df.dropna(subset=["start_date", "end_date"]).copy()

if df.empty:
    st.warning("Existem registros, mas sem start_date/end_date válidos.")
    st.stop()

# fallback de colunas
for col, default in [
    ("project_code", ""),
    ("title", ""),
    ("tipo_atividade", "CAMPO"),
    ("status", "PLANEJADA"),
    ("assignee_names", "Profissional a definir"),
]:
    if col not in df.columns:
        df[col] = default
    df[col] = df[col].fillna(default)

df["label"] = (
    df["project_code"].astype(str).fillna("") + " | " + df["title"].astype(str).fillna("")
).str.strip(" |")

# -----------------------------
# Filtros (mock)
# -----------------------------
today = date.today()
d0, d1 = month_range(today)

projects = ["Todos"] + sorted([p for p in df["project_code"].dropna().unique().tolist() if str(p).strip() != ""])
types_all = sorted([t for t in df["tipo_atividade"].dropna().unique().tolist() if str(t).strip() != ""])

# para filtro de profissionais: explode assignee_names ("A + B + C")
people_all = sorted(
    set(
        p.strip()
        for names in df["assignee_names"].astype(str).fillna("").tolist()
        for p in names.split("+")
        if p.strip()
    )
)

default_types = [t for t in ["CAMPO", "RELATORIO", "ADMINISTRATIVO"] if t in types_all] or types_all
default_people = people_all

c1, c2, c3, c4 = st.columns([1.2, 1.3, 1.8, 1.2])

with c1:
    sel_project = st.selectbox("Projeto", projects, index=0)

with c2:
    sel_types = st.multiselect("Tipo Atividade", types_all, default=default_types)

with c3:
    sel_people = st.multiselect("Profissionais", people_all, default=default_people)

with c4:
    period = st.date_input("Período", value=(d0, d1), format="DD/MM/YYYY")
    if isinstance(period, tuple) and len(period) == 2:
        p_start, p_end = period
    else:
        p_start, p_end = d0, d1

p_start_dt = pd.to_datetime(p_start)
p_end_dt = pd.to_datetime(p_end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

# -----------------------------
# Aplicar filtros
# -----------------------------
f = df.copy()

if sel_project != "Todos":
    f = f[f["project_code"] == sel_project]

if sel_types:
    f = f[f["tipo_atividade"].isin(sel_types)]
else:
    f = f.iloc[0:0]

# filtra pessoas: se alguma das pessoas selecionadas estiver na string
if sel_people:
    patt = "|".join([pd.regex.escape(p.strip()) for p in sel_people if p.strip()])
    if patt.strip():
        f = f[f["assignee_names"].astype(str).str.contains(patt, regex=True, na=False)]
else:
    f = f.iloc[0:0]

# interseção com janela
f = f[(f["start_date"] <= p_end_dt) & (f["end_date"] >= p_start_dt)].copy()

if f.empty:
    st.info("Ainda não há tarefas no portfólio (ou os filtros zeraram a lista).")
    st.stop()

# Recorte visual
f["plot_start"] = f["start_date"].clip(lower=p_start_dt)
f["plot_end"] = f["end_date"].clip(upper=p_end_dt)

# Ordenação cronológica
order = (
    f.groupby("label")["plot_start"]
    .min()
    .sort_values(ascending=True)
    .index
    .tolist()
)

# Texto dentro da barra: TODOS os nomes
f["bar_text"] = f["assignee_names"].astype(str)

# -----------------------------
# Cores
# -----------------------------
color_map = {
    "CAMPO": "#1B5E20",
    "RELATORIO": "#66BB6A",
    "ADMINISTRATIVO": "#2E7D32",
}

# -----------------------------
# Gantt
# -----------------------------
fig = px.timeline(
    f,
    x_start="plot_start",
    x_end="plot_end",
    y="label",
    color="tipo_atividade",
    color_discrete_map=color_map,
    text="bar_text",
    hover_data={
        "project_code": True,
        "title": True,
        "assignee_names": True,
        "tipo_atividade": True,
        "status": True,
        "date_confidence": True,
        "start_date": True,
        "end_date": True,
        "plot_start": False,
        "plot_end": False,
        "label": False,
    },
)

fig.update_yaxes(categoryorder="array", categoryarray=order, title_text="Projeto / Tarefa", autorange="reversed")
fig.update_traces(textposition="inside", insidetextanchor="middle", cliponaxis=False)
fig.update_xaxes(range=[p_start_dt, p_end_dt])

# Ticks diários
days = pd.date_range(p_start_dt.date(), p_end_dt.date(), freq="D")
tickvals = [pd.to_datetime(d) for d in days]
ticktext = [f"{pt_weekday_letter(d.date())} {d.day:02d}/{d.month:02d}" for d in days]

fig.update_xaxes(
    tickmode="array",
    tickvals=tickvals,
    ticktext=ticktext,
    tickangle=-90,
    showgrid=True,
    gridcolor="rgba(0,0,0,0.06)",
    title_text="",
)

# Fim de semana sombreado
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

fig.update_layout(
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5, title_text=""),
    margin=dict(l=10, r=10, t=60, b=40),
)

row_count = f["label"].nunique()
fig.update_layout(height=max(420, 80 + row_count * 55))

st.plotly_chart(fig, use_container_width=True)

with st.expander("Dados (opcional)"):
    st.dataframe(f, use_container_width=True, hide_index=True)

