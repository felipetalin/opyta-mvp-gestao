import re
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from services.auth import require_login
from services.supabase_client import get_authed_client

# Branding / layout
from ui.brand import apply_brand
from ui.layout import apply_app_chrome, page_header, filter_bar_start


# ==========================================================
# Boot (ORDEM OBRIGATÓRIA)
# ==========================================================
st.set_page_config(page_title="Portfólio (Gantt)", layout="wide")
apply_brand()
apply_app_chrome()

require_login()
sb = get_authed_client()

page_header(
    "Portfólio (Gantt)",
    "Filtros + cronograma",
    st.session_state.get("user_email", ""),
)


# ==========================================================
# Helpers
# ==========================================================
def month_range(d: date):
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1, day=1)
    else:
        nxt = first.replace(month=first.month + 1, day=1)
    return first, nxt - timedelta(days=1)


def shift_month(d: date, delta: int) -> date:
    y = d.year
    m = d.month + delta
    while m > 12:
        y += 1
        m -= 12
    while m < 1:
        y -= 1
        m += 12
    return date(y, m, 1)


def month_label(d: date) -> str:
    meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
              "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    return f"{meses[d.month-1]}/{d.year}"


def weekday_letter(d: date) -> str:
    return ["S", "T", "Q", "Q", "S", "S", "D"][d.weekday()]


# ==========================================================
# Load data
# ==========================================================
@st.cache_data(ttl=30)
def load_portfolio():
    res = sb.table("v_portfolio_tasks").select("*").execute()
    return pd.DataFrame(res.data or [])


df = load_portfolio()
if df.empty:
    st.warning("Nenhuma tarefa encontrada.")
    st.stop()

# Normalização
df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
df["end_date"] = df["end_date"].fillna(df["start_date"])
df = df.dropna(subset=["start_date", "end_date"])

# Campos esperados
df["project_code"] = df.get("project_code", "").fillna("")
df["title"] = df.get("title", "").fillna("")
df["tipo_atividade"] = df.get("tipo_atividade", "CAMPO").fillna("CAMPO")
df["assignee_names"] = df.get("assignee_names", "Profissional").fillna("Profissional")
df["status"] = df.get("status", "").fillna("")

df["label"] = (
    df["project_code"].str.strip()
    + " | "
    + df["title"].str.strip()
).str.strip(" |")


# ==========================================================
# Filtros
# ==========================================================
today = date.today()

projects = ["Todos"] + sorted(df["project_code"].unique().tolist())
types_all = sorted(df["tipo_atividade"].unique().tolist())

people = set()
for s in df["assignee_names"]:
    for p in s.split("+"):
        if p.strip():
            people.add(p.strip())
people_all = sorted(people)

# Atalho de mês
month_opts = []
for d in [-2, -1, 0, 1, 2]:
    md = shift_month(today, d)
    m0, m1 = month_range(md)
    month_opts.append((month_label(md), m0, m1))

month_labels = ["(manual)"] + [m[0] for m in month_opts]

with filter_bar_start():
    c1, c2, c3, c4, c5 = st.columns([1.2, 1.8, 2.2, 1.4, 1.2])

    with c1:
        sel_project = st.selectbox("Projeto", projects)

    with c2:
        sel_types = st.multiselect(
            "Tipo Atividade",
            types_all,
            default=types_all,
        )

    with c3:
        sel_people = st.multiselect(
            "Profissionais",
            people_all,
            default=people_all,
        )

    with c4:
        sel_month = st.selectbox(
            "Atalho (período)",
            month_labels,
            index=month_labels.index(month_label(today))
            if month_label(today) in month_labels else 0,
        )

    with c5:
        show_status = st.toggle("Status na barra", value=True)


# Período
if sel_month != "(manual)":
    m = [x for x in month_opts if x[0] == sel_month][0]
    p_start, p_end = m[1], m[2]
    st.caption(f"Período: **{p_start:%d/%m/%Y} – {p_end:%d/%m/%Y}**")
else:
    p_start, p_end = st.date_input(
        "Período",
        value=month_range(today),
        format="DD/MM/YYYY",
    )

p_start_dt = pd.to_datetime(p_start)
p_end_dt = pd.to_datetime(p_end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)


# ==========================================================
# Aplicar filtros
# ==========================================================
f = df.copy()

if sel_project != "Todos":
    f = f[f["project_code"] == sel_project]

if sel_types:
    f = f[f["tipo_atividade"].isin(sel_types)]
else:
    f = f.iloc[0:0]

if sel_people:
    patt = "|".join(re.escape(p) for p in sel_people)
    f = f[f["assignee_names"].str.contains(patt, regex=True)]
else:
    f = f.iloc[0:0]

f = f[(f["start_date"] <= p_end_dt) & (f["end_date"] >= p_start_dt)]

if f.empty:
    st.info("Nenhuma tarefa para os filtros selecionados.")
    st.stop()

f["plot_start"] = f["start_date"].clip(lower=p_start_dt)
f["plot_end"] = f["end_date"].clip(upper=p_end_dt)

order = (
    f.groupby("label")["plot_start"]
    .min()
    .sort_values()
    .index
    .tolist()
)

# Texto da barra
if show_status:
    icons = {
        "CONCLUIDA": "✓",
        "EM_ANDAMENTO": "…",
        "AGUARDANDO_CONFIRMACAO": "⏳",
        "CANCELADA": "✖",
    }
    f["bar_text"] = f.apply(
        lambda r: f"{icons.get(r['status'], '')} {r['assignee_names']}".strip(),
        axis=1,
    )
else:
    f["bar_text"] = f["assignee_names"]


# ==========================================================
# Gantt
# ==========================================================
colors = {
    "CAMPO": "#1B5E20",
    "RELATORIO": "#66BB6A",
    "ADMINISTRATIVO": "#2F6DAE",
}

fig = px.timeline(
    f,
    x_start="plot_start",
    x_end="plot_end",
    y="label",
    color="tipo_atividade",
    color_discrete_map=colors,
    text="bar_text",
)

fig.update_yaxes(
    categoryorder="array",
    categoryarray=order,
    autorange="reversed",
    title="Projeto / Tarefa",
)

fig.update_traces(
    textposition="inside",
    insidetextanchor="middle",
    cliponaxis=False,
)

# eixo X diário
days = pd.date_range(p_start_dt.date(), p_end_dt.date(), freq="D")
fig.update_xaxes(
    tickmode="array",
    tickvals=days,
    ticktext=[f"{weekday_letter(d.date())} {d.day:02d}/{d.month:02d}" for d in days],
    tickangle=-90,
    showgrid=True,
    gridcolor="rgba(0,0,0,0.05)",
)

# fim de semana + hoje
shapes = []
for d in days:
    if d.weekday() >= 5:
        shapes.append(
            dict(
                type="rect",
                xref="x",
                yref="paper",
                x0=d,
                x1=d + pd.Timedelta(days=1),
                y0=0,
                y1=1,
                fillcolor="rgba(102,187,106,0.10)",
                line=dict(width=0),
                layer="below",
            )
        )

today_dt = pd.to_datetime(today)
if p_start_dt <= today_dt <= p_end_dt:
    shapes.append(
        dict(
            type="line",
            xref="x",
            yref="paper",
            x0=today_dt,
            x1=today_dt,
            y0=0,
            y1=1,
            line=dict(color="red", width=2),
        )
    )

fig.update_layout(
    shapes=shapes,
    legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center"),
    margin=dict(l=10, r=10, t=60, b=40),
    height=max(420, 80 + f["label"].nunique() * 55),
)

st.plotly_chart(fig, use_container_width=True)







