# app/pages/1_Portfolio_Gantt.py

import re
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from services.auth import require_login
from services.supabase_client import get_authed_client

# Branding / Chrome
from ui.brand import apply_brand, apply_app_chrome, page_header
from ui.layout import filter_bar_start


# ==========================================================
# Boot (ordem obrigatória)
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
    last = nxt - timedelta(days=1)
    return first, last


def shift_month_first(d: date, delta: int) -> date:
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


def pt_weekday_letter(d: date) -> str:
    return ["S", "T", "Q", "Q", "S", "S", "D"][d.weekday()]


def to_dt(x):
    return pd.to_datetime(x, errors="coerce")


def safe_text(x, default=""):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return default
    s = str(x).strip()
    if s in ("None", "nan", "NaT"):
        return default
    return s


def normalize_status(x):
    return safe_text(x).upper().strip()


def split_people(assignee_names):
    return [p.strip() for p in str(assignee_names or "").split("+") if p.strip()]


# ==========================================================
# Load (view)
# ==========================================================
@st.cache_data(ttl=30)
def fetch_portfolio_view():
    res = sb.table("v_portfolio_tasks").select("*").execute()
    return pd.DataFrame(res.data or [])


df = fetch_portfolio_view()
if df.empty:
    st.warning("Nenhuma tarefa encontrada na view v_portfolio_tasks.")
    st.stop()

# Datas
df["start_date"] = to_dt(df.get("start_date"))
df["end_date"] = to_dt(df.get("end_date"))
df["end_date"] = df["end_date"].fillna(df["start_date"])
df = df.dropna(subset=["start_date", "end_date"])

# Fallbacks
df["project_code"] = df.get("project_code", "").fillna("")
df["title"] = df.get("title", "").fillna("")
df["tipo_atividade"] = df.get("tipo_atividade", "CAMPO").fillna("CAMPO")
df["assignee_names"] = df.get("assignee_names", "Profissional").fillna("Profissional")
df["status"] = df.get("status", "").fillna("")
df["status_norm"] = df["status"].apply(normalize_status)

df["label"] = (
    df["project_code"].str.strip()
    + " | "
    + df["title"].str.strip()
).str.strip(" |")


# ==========================================================
# Filtros
# ==========================================================
today = date.today()
d0, d1 = month_range(today)

projects = ["Todos"] + sorted([p for p in df["project_code"].unique() if safe_text(p)])
types_all = sorted([t for t in df["tipo_atividade"].unique() if safe_text(t)])

people_set = set()
for s in df["assignee_names"]:
    for p in split_people(s):
        people_set.add(p)
people_all = sorted(people_set)

default_types = [t for t in ["CAMPO", "RELATORIO", "ADMINISTRATIVO"] if t in types_all]

# Atalhos de período
cur = shift_month_first(today, 0)
prev = shift_month_first(today, -1)
next1 = shift_month_first(today, 1)
next2 = shift_month_first(today, 2)

cur_s, cur_e = month_range(cur)
prev_s, _ = month_range(prev)
_, next1_e = month_range(next1)
_, next2_e = month_range(next2)

period_presets = [
    ("(manual)", None, None),
    (f"Mês atual ({month_label(cur)})", cur_s, cur_e),
    (f"2 meses ({month_label(cur)} + {month_label(next1)})", cur_s, next1_e),
    (f"3 meses ({month_label(cur)} + {month_label(next2)})", cur_s, next2_e),
    (f"Mês anterior + atual ({month_label(prev)} + {month_label(cur)})", prev_s, cur_e),
]

with filter_bar_start():
    c1, c2, c3, c4, c5 = st.columns([1.2, 1.7, 2.2, 1.6, 1.3])

    sel_project = c1.selectbox("Projeto", projects)
    sel_types = c2.multiselect("Tipo Atividade", types_all, default=default_types)
    sel_people = c3.multiselect("Profissionais", people_all, default=people_all)
    sel_period = c4.selectbox("Atalho (período)", [p[0] for p in period_presets], index=1)
    show_status = c5.toggle("Status na barra", value=False)
    show_cancelled = c5.toggle("Mostrar canceladas", value=True)

chosen = [p for p in period_presets if p[0] == sel_period][0]
if chosen[0] != "(manual)":
    p_start, p_end = chosen[1], chosen[2]
else:
    p_start, p_end = st.date_input("Período", value=(d0, d1))

p_start_dt = pd.to_datetime(p_start)
p_end_dt = pd.to_datetime(p_end) + pd.Timedelta(days=1)


# ==========================================================
# Aplicar filtros
# ==========================================================
f = df.copy()

if sel_project != "Todos":
    f = f[f["project_code"] == sel_project]

f = f[f["tipo_atividade"].isin(sel_types)]

if sel_people:
    patt = "|".join(re.escape(p) for p in sel_people)
    f = f[f["assignee_names"].str.contains(patt, regex=True)]

if not show_cancelled:
    f = f[f["status_norm"] != "CANCELADA"]

f = f[(f["start_date"] <= p_end_dt) & (f["end_date"] >= p_start_dt)]

f["plot_start"] = f["start_date"].clip(lower=p_start_dt)
f["plot_end"] = f["end_date"].clip(upper=p_end_dt)

order = f.groupby("label")["plot_start"].min().sort_values().index.tolist()


# ==========================================================
# Texto da barra (STATUS VISÍVEL)
# ==========================================================
status_label = {
    "CONCLUIDA": "CONCLUIDA",
    "EM_ANDAMENTO": "EM ANDAMENTO",
    "AGUARDANDO_CONFIRMACAO": "AGUARDANDO",
    "PLANEJADA": "PLANEJADA",
    "CANCELADA": "CANCELADA",
}

if show_status:
    f["bar_text"] = f.apply(
        lambda r: f"{status_label.get(r['status_norm'], '—')} • {r['assignee_names']}",
        axis=1,
    )
else:
    f["bar_text"] = f["assignee_names"]


# Cor: cancelada cinza
f["tipo_plot"] = f["tipo_atividade"]
f.loc[f["status_norm"] == "CANCELADA", "tipo_plot"] = "CANCELADA"

color_map = {
    "CAMPO": "#1B5E20",
    "RELATORIO": "#66BB6A",
    "ADMINISTRATIVO": "#2F6DAE",
    "CANCELADA": "#9E9E9E",
}


# ==========================================================
# Gantt
# ==========================================================
fig = px.timeline(
    f,
    x_start="plot_start",
    x_end="plot_end",
    y="label",
    color="tipo_plot",
    color_discrete_map=color_map,
    text="bar_text",
)

fig.update_yaxes(categoryorder="array", categoryarray=order, autorange="reversed")
fig.update_traces(textposition="inside", cliponaxis=False)

days = pd.date_range(p_start_dt.date(), p_end_dt.date(), freq="D")
fig.update_xaxes(
    tickvals=days,
    ticktext=[f"{pt_weekday_letter(d.date())} {d.day:02d}/{d.month:02d}" for d in days],
    tickangle=-90,
)

shapes = []
for d in days:
    if d.weekday() >= 5:
        shapes.append(dict(type="rect", xref="x", yref="paper",
                           x0=d, x1=d + pd.Timedelta(days=1),
                           y0=0, y1=1,
                           fillcolor="rgba(102,187,106,0.10)", line=dict(width=0)))

today_dt = pd.to_datetime(today)
if p_start_dt <= today_dt <= p_end_dt:
    shapes.append(dict(type="line", xref="x", yref="paper",
                       x0=today_dt, x1=today_dt,
                       y0=0, y1=1, line=dict(color="red", width=2)))

fig.update_layout(shapes=shapes, height=max(420, 80 + f["label"].nunique() * 55))

st.plotly_chart(fig, use_container_width=True)







