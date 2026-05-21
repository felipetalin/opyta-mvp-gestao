# app/pages/6_Laboratorio.py
"""
Controle de amostras enviadas ao laboratório e previsão de liberação dos laudos.

Tabela própria (lab_samples). Cada linha = uma entrega operacional que pode
conter MÚLTIPLOS tipos de amostras enviados em conjunto ao mesmo laboratório.
"""

from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO

import pandas as pd
import streamlit as st

from services.auth import require_login
from services.supabase_client import get_authed_client

try:
    from ui.brand import apply_brand, apply_app_chrome, page_header
except Exception:  # pragma: no cover
    def apply_brand(): return
    def apply_app_chrome(): return
    def page_header(title, subtitle, user_email=""):
        st.title(title)
        if subtitle:
            st.caption(subtitle)


# ==========================================================
# Boot
# ==========================================================
st.set_page_config(page_title="Laboratório", layout="wide")
apply_brand()
apply_app_chrome()

require_login()
sb = get_authed_client()
cache_key = str(st.session_state.get("access_token") or "no-token")

page_header(
    "Laboratório — Amostras & Laudos",
    "Controle das entregas ao laboratório e previsão de liberação dos laudos",
    st.session_state.get("user_email", ""),
)


# ==========================================================
# Constantes
# ==========================================================
# Conjunto completo permitido no banco (check constraint v1)
LAB_STATUS_DB = ["PENDENTE", "ENTREGUE_LAB", "AGUARDANDO_LAUDO", "LAUDO_RECEBIDO", "CONCLUIDO"]

# Conjunto simplificado usado na UI (3 estados operacionais)
LAB_STATUS_UI = ["PENDENTE", "ENTREGUE_LAB", "CONCLUIDO"]

STATUS_LABEL_UI = {
    "PENDENTE":     "🟡 Pendente",
    "ENTREGUE_LAB": "🔵 Em análise",
    "CONCLUIDO":    "🟢 Concluído",
}
# Normaliza valores legados (5 estados) → UI (3 estados)
LEGACY_TO_UI = {
    "PENDENTE":         "PENDENTE",
    "ENTREGUE_LAB":     "ENTREGUE_LAB",
    "AGUARDANDO_LAUDO": "ENTREGUE_LAB",
    "LAUDO_RECEBIDO":   "CONCLUIDO",
    "CONCLUIDO":        "CONCLUIDO",
}
LABEL_TO_STATUS_UI = {v: k for k, v in STATUS_LABEL_UI.items()}

SITUACAO_PRIORITY = {
    "🔴 Atraso":     0,
    "🟡 Pendente":   1,
    "🔵 Em análise": 2,
    "🟢 Concluído": 3,
}

DEFAULT_SLA_DAYS = 45


# ==========================================================
# Helpers
# ==========================================================
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
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return None


def norm_text(x) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    if s in ("", "None", "nan", "NaT"):
        return None
    return s


def safe_text_list(series: pd.Series, default: str = "") -> list[str]:
    out: list[str] = []
    for v in series.tolist():
        if v is None or (isinstance(v, float) and pd.isna(v)):
            out.append(default)
        else:
            s = str(v).strip()
            out.append(default if s in ("None", "nan", "NaT") else s)
    return out


def to_list(x) -> list[str]:
    if x is None:
        return []
    if isinstance(x, list):
        return [str(i) for i in x if i is not None and str(i).strip() != ""]
    if isinstance(x, float) and pd.isna(x):
        return []
    s = str(x).strip()
    if not s or s in ("None", "nan", "NaT"):
        return []
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    return [p.strip().strip('"') for p in s.split(",") if p.strip()]


def month_range(d: date) -> tuple[date, date]:
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1, day=1)
    else:
        nxt = first.replace(month=first.month + 1, day=1)
    return first, nxt - timedelta(days=1)


def shift_month_first(d: date, delta: int) -> date:
    y, m = d.year, d.month + delta
    while m > 12:
        y += 1; m -= 12
    while m < 1:
        y -= 1; m += 12
    return date(y, m, 1)


def month_label(d: date) -> str:
    meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    return f"{meses[d.month - 1]}/{d.year}"


def calc_expected(shipment: date | None, sla_days: int | None) -> date | None:
    if shipment is None or sla_days is None:
        return None
    try:
        return shipment + timedelta(days=int(sla_days))
    except Exception:
        return None


def sb_paginate(table: str, *, select: str = "*", order_col: str | None = None,
                desc: bool = False, page_size: int = 1000) -> list[dict]:
    """Paginação obrigatória — anon key trunca em 1000 linhas por request."""
    out: list[dict] = []
    offset = 0
    while True:
        q = sb.table(table).select(select).range(offset, offset + page_size - 1)
        if order_col:
            q = q.order(order_col, desc=desc)
        resp = q.execute()
        chunk = resp.data or []
        out.extend(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
    return out


def situacao_for(status: str | None, exp: date | None, today_: date) -> str:
    status_ui = LEGACY_TO_UI.get(status or "", "PENDENTE")
    if status_ui == "CONCLUIDO":
        return "🟢 Concluído"
    if exp is not None and exp < today_:
        return "🔴 Atraso"
    if status_ui == "PENDENTE":
        return "🟡 Pendente"
    return "🔵 Em análise"


def days_delta(exp: date | None, today_: date) -> int | None:
    if exp is None:
        return None
    return (exp - today_).days


# ==========================================================
# Loads
# ==========================================================
@st.cache_data(ttl=30)
def load_samples(_k: str) -> pd.DataFrame:
    data = sb_paginate("v_lab_samples", order_col="expected_release_date")
    return pd.DataFrame(data)


@st.cache_data(ttl=300)
def load_projects(_k: str) -> pd.DataFrame:
    res = sb.table("projects").select("id, project_code, name").order("project_code").execute()
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=300)
def load_people(_k: str) -> pd.DataFrame:
    res = sb.table("people").select("id, name").order("name").execute()
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=300)
def load_sample_types(_k: str) -> pd.DataFrame:
    res = (
        sb.table("lab_sample_types")
        .select("id, name, active, sort_order")
        .eq("active", True)
        .order("sort_order").order("name").execute()
    )
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=300)
def load_labs(_k: str) -> pd.DataFrame:
    res = (
        sb.table("labs")
        .select("id, name, active, sort_order")
        .eq("active", True)
        .order("sort_order").order("name").execute()
    )
    return pd.DataFrame(res.data or [])


def refresh():
    load_samples.clear()
    load_sample_types.clear()
    load_labs.clear()


df_projects = load_projects(cache_key)
df_people = load_people(cache_key)
df_types = load_sample_types(cache_key)
df_labs = load_labs(cache_key)

type_names_sorted = [str(r["name"]) for _, r in df_types.iterrows()] if not df_types.empty else []
lab_name_to_id = {str(r["name"]): r["id"] for _, r in df_labs.iterrows()} if not df_labs.empty else {}
lab_names_sorted = list(lab_name_to_id.keys())


# ==========================================================
# Cadastro rápido de laboratório
# ==========================================================
with st.expander("🧪 Cadastrar novo laboratório", expanded=False):
    with st.form("new_lab", clear_on_submit=True):
        new_lab_name = st.text_input("Nome do laboratório *", placeholder="Ex.: Biofile, Acquaplant...")
        c1, _ = st.columns([1, 5])
        submit_lab = c1.form_submit_button("Adicionar", type="primary")
        if submit_lab:
            nm = (new_lab_name or "").strip()
            if not nm:
                st.error("Informe o nome.")
            elif nm in lab_name_to_id:
                st.warning("Já existe um laboratório com esse nome.")
            else:
                try:
                    sb.table("labs").insert({"name": nm}, returning="representation").execute()
                    st.success(f"Laboratório '{nm}' cadastrado.")
                    refresh(); st.rerun()
                except Exception as e:
                    st.error(f"Falha: {_api_error_message(e)}")


# ==========================================================
# Nova entrega
# ==========================================================
with st.expander("➕ Nova entrega de amostras", expanded=False):
    if df_projects.empty:
        st.warning("Nenhum projeto cadastrado. Cadastre projetos antes.")
    elif not type_names_sorted:
        st.warning(
            "Nenhum tipo de amostra cadastrado. Rode `2026_05_21_lab_samples_v2.sql` "
            "(e v3/v4/v5) no Supabase."
        )
    else:
        proj_options = {
            f"{row['project_code']} — {row['name']}": row["id"]
            for _, row in df_projects.iterrows()
        }
        people_options = {"(sem responsável)": None}
        for _, row in df_people.iterrows():
            people_options[str(row["name"])] = row["id"]
        lab_options = {"(sem laboratório)": None, **lab_name_to_id}

        with st.form("new_lab_sample", clear_on_submit=True):
            f1, f2 = st.columns(2)
            with f1:
                proj_label = st.selectbox("Projeto *", list(proj_options.keys()))
                sel_types = st.multiselect(
                    "Tipos de amostra *",
                    type_names_sorted,
                    help="Selecione um ou mais tipos enviados nesta entrega.",
                )
                lab_label = st.selectbox("Laboratório", list(lab_options.keys()))
                shipment = st.date_input(
                    "Data de entrega das amostras", value=date.today(), format="DD/MM/YYYY",
                )
                sample_count_new = st.number_input(
                    "Quantidade de amostras", min_value=0, max_value=10000, value=0, step=1,
                    help="Número total de amostras nesta entrega (somando todos os tipos).",
                )
            with f2:
                resp_label = st.selectbox("Responsável", list(people_options.keys()))
                sla = st.number_input(
                    "Prazo para liberação (dias)",
                    min_value=0, max_value=365, value=DEFAULT_SLA_DAYS, step=1,
                )
                status_new_ui = st.selectbox(
                    "Status",
                    LAB_STATUS_UI,
                    index=1,
                    format_func=lambda s: STATUS_LABEL_UI.get(s, s),
                )
                expected_default = calc_expected(shipment, sla)
                expected_new = st.date_input(
                    "Previsão de liberação dos laudos",
                    value=expected_default, format="DD/MM/YYYY",
                    help="Calculada (Entrega + Prazo), mas editável.",
                )
                notes_new = st.text_area("Observações", value="", height=80)

            submitted = st.form_submit_button("Salvar entrega", type="primary")
            if submitted:
                if not sel_types:
                    st.error("Selecione ao menos um tipo de amostra.")
                else:
                    payload = {
                        "project_id": proj_options[proj_label],
                        "assignee_id": people_options[resp_label],
                        "lab_id": lab_options[lab_label],
                        "sample_types": sel_types,
                        "sample_count": int(sample_count_new) if sample_count_new else None,
                        "shipment_date": shipment.isoformat() if shipment else None,
                        "status": status_new_ui,
                        "sla_days": int(sla),
                        "expected_release_date": expected_new.isoformat() if expected_new else None,
                        "notes": norm_text(notes_new),
                    }
                    try:
                        resp = sb.table("lab_samples").insert(payload, returning="representation").execute()
                        if not getattr(resp, "data", None):
                            st.error("Insert não retornou linha (provável bloqueio por RLS).")
                        else:
                            st.success("Entrega cadastrada.")
                            refresh(); st.rerun()
                    except Exception as e:
                        st.error(f"Falha ao cadastrar: {_api_error_message(e)}")


# ==========================================================
# Carrega tabela principal
# ==========================================================
with st.spinner("Carregando amostras..."):
    df = load_samples(cache_key)

if df.empty:
    st.info("Nenhuma entrega cadastrada ainda. Use **Nova entrega de amostras** acima.")
    st.stop()

# Fallbacks defensivos caso migrações v3/v4 ainda não tenham sido aplicadas
for col, default in [
    ("sample_types", None), ("lab_name", None), ("lab_id", None),
    ("sample_count", None), ("sample_types_label", None),
]:
    if col not in df.columns:
        df[col] = default

df["sample_types_list"] = df["sample_types"].apply(to_list)

today = date.today()

# Pré-computa Situação e dias restantes para todas as linhas
exp_dates = [to_date(x) for x in df["expected_release_date"].tolist()]
status_raw = safe_text_list(df["status"], "PENDENTE")
df["__situacao"] = [situacao_for(s, e, today) for s, e in zip(status_raw, exp_dates)]
df["__days"] = [days_delta(e, today) for e in exp_dates]


# ==========================================================
# Painel: Próximos vencimentos
# ==========================================================
def _vencimento_panel():
    horizons = [7, 15]
    cols = st.columns(len(horizons) + 1)
    # Atrasadas
    overdue = df[df["__situacao"] == "🔴 Atraso"]
    cols[0].metric("🔴 Atrasadas", len(overdue))
    for i, h in enumerate(horizons, start=1):
        m = df[
            (df["__situacao"].isin(["🔵 Em análise", "🟡 Pendente"]))
            & df["__days"].notna()
            & (df["__days"] >= 0)
            & (df["__days"] <= h)
        ]
        cols[i].metric(f"⏰ Vencem em ≤ {h}d", len(m))


_vencimento_panel()


# ==========================================================
# Filtros (mesmo padrão da Produtos)
# ==========================================================
projects_all = sorted({p for p in safe_text_list(df["project_code"]) if p})
labs_all = sorted({p for p in safe_text_list(df["lab_name"]) if p})
people_all = sorted({p for p in safe_text_list(df["assignee_name"]) if p})

cur_first = shift_month_first(today, 0)
next_first = shift_month_first(today, 1)
prev_first = shift_month_first(today, -1)
next2_first = shift_month_first(today, 2)

cur_start, cur_end = month_range(cur_first)
next_start, next_end = month_range(next_first)
prev_start, _ = month_range(prev_first)
_, next2_end = month_range(next2_first)

period_presets: list[tuple[str, date | None, date | None]] = [
    (f"Mês atual ({month_label(cur_first)})", cur_start, cur_end),
    (f"Próximo mês ({month_label(next_first)})", next_start, next_end),
    (f"2 meses ({month_label(cur_first)} + {month_label(next_first)})", cur_start, next_end),
    (f"3 meses ({month_label(cur_first)} + {month_label(next2_first)})", cur_start, next2_end),
    (f"Mês anterior + atual ({month_label(prev_first)} + {month_label(cur_first)})", prev_start, cur_end),
    ("(manual)", None, None),
    ("Tudo", None, None),
]
period_labels = [p[0] for p in period_presets]

fc1, fc2, fc3 = st.columns([1.6, 1.6, 1.2])
with fc1:
    f_projects = st.multiselect("Projeto", projects_all, default=[])
with fc2:
    f_status_ui = st.multiselect(
        "Status",
        LAB_STATUS_UI,
        default=[],
        format_func=lambda s: STATUS_LABEL_UI.get(s, s),
    )
with fc3:
    only_pending = st.toggle(
        "Apenas pendentes", value=False,
        help="Oculta entregas concluídas.",
    )

fc4, fc5, fc6 = st.columns([2.0, 1.2, 1.2])
with fc4:
    sel_period = st.selectbox(
        "Atalho (período pela Previsão)", period_labels, index=3,
        help="Padrão = 3 meses (acomoda SLAs típicos de 30–60 dias).",
    )
with fc5:
    include_overdue = st.toggle("Incluir atrasadas", value=True,
                                help="Mostra atrasadas mesmo fora do período.")
with fc6:
    include_undated = st.toggle("Incluir sem previsão", value=False)

chosen = next(p for p in period_presets if p[0] == sel_period)
if chosen[0] == "(manual)":
    period = st.date_input("Período manual (Previsão)", value=(cur_start, cur_end), format="DD/MM/YYYY")
    if isinstance(period, tuple) and len(period) == 2:
        p_start, p_end = period
    else:
        p_start, p_end = cur_start, cur_end
elif chosen[0] == "Tudo":
    p_start, p_end = None, None
else:
    p_start, p_end = chosen[1], chosen[2]
    st.caption(f"Período (Previsão): **{p_start.strftime('%d/%m/%Y')} – {p_end.strftime('%d/%m/%Y')}**")

# Máscaras
mask = pd.Series(True, index=df.index)
if f_projects:
    mask &= df["project_code"].isin(f_projects)
if f_status_ui:
    status_norm = df["status"].fillna("PENDENTE").map(lambda s: LEGACY_TO_UI.get(s, "PENDENTE"))
    mask &= status_norm.isin(f_status_ui)
if only_pending:
    mask &= df["__situacao"] != "🟢 Concluído"

expected = pd.to_datetime(df["expected_release_date"], errors="coerce").dt.date
if p_start is not None and p_end is not None:
    in_window = expected.between(p_start, p_end)
    extra = pd.Series(False, index=df.index)
    if include_overdue:
        extra = extra | (df["__situacao"] == "🔴 Atraso")
    if include_undated:
        extra = extra | expected.isna()
    mask &= in_window | extra
else:
    if not include_undated:
        mask &= expected.notna()

df_f = df.loc[mask].reset_index(drop=True)


# ==========================================================
# Métricas (alinhadas à Situação)
# ==========================================================
n_pend  = int((df_f["__situacao"] == "🟡 Pendente").sum())
n_anal  = int((df_f["__situacao"] == "🔵 Em análise").sum())
n_atras = int((df_f["__situacao"] == "🔴 Atraso").sum())
n_conc  = int((df_f["__situacao"] == "🟢 Concluído").sum())

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total exibido", len(df_f))
m2.metric("🟡 Pendente", n_pend)
m3.metric("🔵 Em análise", n_anal)
m4.metric("🔴 Atraso", n_atras)
m5.metric("🟢 Concluído", n_conc)

st.divider()


# ==========================================================
# Busca + ordenação + filtros refinados
# ==========================================================
st.subheader("Amostras")
st.caption("Edite os campos e clique em **Salvar alterações**. Marque **Excluir?** para remover linhas.")

SORT_OPTIONS = {
    "Situação (Atraso → Concluído)":     ("__sit_priority", True),
    "Previsão (mais próxima primeiro)":  ("expected_release_date", True),
    "Previsão (mais distante primeiro)": ("expected_release_date", False),
    "Entrega (mais recente)":            ("shipment_date", False),
    "Projeto (A→Z)":                     ("project_code", True),
    "Atualizado recentemente":           ("updated_at", False),
}

tc1, tc2 = st.columns([2.5, 1.5])
with tc1:
    search = st.text_input(
        "Buscar (Projeto · Tipo · Lab · Responsável · Obs)",
        value="", placeholder="Ex.: bentos, biofile, ASSCAF, fulano...",
    )
with tc2:
    sort_label = st.selectbox("Ordenar por", list(SORT_OPTIONS.keys()), index=0)

rc1, rc2, rc3, rc4 = st.columns([1.2, 1.2, 1.2, 1.4])
with rc1:
    f_types = st.multiselect("Tipo de amostra", type_names_sorted, default=[])
with rc2:
    f_labs = st.multiselect("Laboratório", labs_all, default=[])
with rc3:
    f_people = st.multiselect("Responsável", people_all, default=[])
with rc4:
    sit_options = ["🔴 Atraso", "🟡 Pendente", "🔵 Em análise", "🟢 Concluído"]
    f_sit = st.multiselect("Situação", sit_options, default=[])

if f_types:
    df_f = df_f[df_f["sample_types_list"].apply(lambda lst: any(t in lst for t in f_types))].reset_index(drop=True)
if f_labs:
    df_f = df_f[df_f["lab_name"].isin(f_labs)].reset_index(drop=True)
if f_people:
    df_f = df_f[df_f["assignee_name"].isin(f_people)].reset_index(drop=True)
if f_sit:
    df_f = df_f[df_f["__situacao"].isin(f_sit)].reset_index(drop=True)

if search.strip():
    q = search.strip().lower()
    haystack = (
        df_f["project_code"].fillna("").astype(str).str.lower() + " | "
        + df_f["sample_types_list"].apply(lambda lst: ", ".join(lst).lower()) + " | "
        + df_f["lab_name"].fillna("").astype(str).str.lower() + " | "
        + df_f["assignee_name"].fillna("").astype(str).str.lower() + " | "
        + df_f["notes"].fillna("").astype(str).str.lower()
    )
    df_f = df_f.loc[haystack.str.contains(q, na=False, regex=False)].reset_index(drop=True)

df_f["__sit_priority"] = df_f["__situacao"].map(SITUACAO_PRIORITY).fillna(99).astype(int)
sort_col, sort_asc = SORT_OPTIONS[sort_label]
if sort_col in df_f.columns and not df_f.empty:
    df_f = df_f.sort_values(by=sort_col, ascending=sort_asc, na_position="last").reset_index(drop=True)

if df_f.empty:
    st.info(
        f"Nenhuma amostra corresponde aos filtros/busca atuais. "
        f"Existem **{len(df)}** entrega(s) cadastrada(s) no total — "
        "tente o atalho **Tudo**, ampliar o período ou ativar *Incluir sem previsão*."
    )
    st.stop()


# ==========================================================
# Export CSV
# ==========================================================
def _build_export_df(_df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "Projeto": safe_text_list(_df["project_code"]),
        "Situação": _df["__situacao"].tolist(),
        "Tipos": [", ".join(lst) for lst in _df["sample_types_list"].tolist()],
        "Qtd": _df["sample_count"].fillna(0).astype(int).tolist(),
        "Laboratório": safe_text_list(_df["lab_name"]),
        "Responsável": safe_text_list(_df["assignee_name"]),
        "Status (DB)": safe_text_list(_df["status"]),
        "Entrega": [to_date(x) for x in _df["shipment_date"].tolist()],
        "Prazo (dias)": _df["sla_days"].fillna(DEFAULT_SLA_DAYS).astype(int).tolist(),
        "Previsão": [to_date(x) for x in _df["expected_release_date"].tolist()],
        "Dias": _df["__days"].tolist(),
        "Obs": safe_text_list(_df["notes"]),
    })
    return out


export_df = _build_export_df(df_f)
csv_bytes = export_df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
xc1, xc2, _ = st.columns([1.2, 1.2, 4])
xc1.download_button(
    "⬇️ Exportar CSV",
    data=csv_bytes,
    file_name=f"laboratorio_{today.isoformat()}.csv",
    mime="text/csv",
)
try:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Amostras")
    xc2.download_button(
        "⬇️ Exportar Excel",
        data=buf.getvalue(),
        file_name=f"laboratorio_{today.isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
except Exception:
    pass  # xlsxwriter pode não estar instalado; o CSV cobre o caso


# ==========================================================
# Editor principal
# ==========================================================
people_names_sorted = sorted({n for n in safe_text_list(df_people["name"]) if n}) if not df_people.empty else []
name_to_id = {row["name"]: row["id"] for _, row in df_people.iterrows()} if not df_people.empty else {}

ids = safe_text_list(df_f["sample_id"])
status_norm = [LEGACY_TO_UI.get(s, "PENDENTE") for s in safe_text_list(df_f["status"], "PENDENTE")]
status_labels = [STATUS_LABEL_UI[s] for s in status_norm]

def _format_days(d):
    if d is None or (isinstance(d, float) and pd.isna(d)):
        return ""
    d = int(d)
    if d < 0:
        return f"⚠ −{-d}d (atraso)"
    if d == 0:
        return "Hoje"
    return f"+{d}d"

dias_strings = [_format_days(d) for d in df_f["__days"].tolist()]

df_show = pd.DataFrame(
    {
        "Projeto":      safe_text_list(df_f["project_code"]),
        "Situação":     df_f["__situacao"].tolist(),
        "Tipos":        [", ".join(lst) for lst in df_f["sample_types_list"].tolist()],
        "Qtd":          df_f["sample_count"].fillna(0).astype(int).tolist(),
        "Laboratório":  safe_text_list(df_f["lab_name"]),
        "Responsável":  safe_text_list(df_f["assignee_name"]),
        "Status":       status_labels,
        "Entrega":      [to_date(x) for x in df_f["shipment_date"].tolist()],
        "Prazo (dias)": df_f["sla_days"].fillna(DEFAULT_SLA_DAYS).astype(int).tolist(),
        "Previsão":     [to_date(x) for x in df_f["expected_release_date"].tolist()],
        "Dias":         dias_strings,
        "Obs":          safe_text_list(df_f["notes"]),
        "Excluir?":     [False] * len(df_f),
    },
    index=ids,
)

status_label_options_ui = [STATUS_LABEL_UI[s] for s in LAB_STATUS_UI]

edited = st.data_editor(
    df_show,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "Projeto":      st.column_config.TextColumn(disabled=True, width="small"),
        "Situação":     st.column_config.TextColumn(
            disabled=True, width="small",
            help="Calculada automaticamente: 🔴 Atraso (previsão vencida), "
                 "🟡 Pendente (não entregue), 🔵 Em análise (no prazo), 🟢 Concluído.",
        ),
        "Tipos":        st.column_config.TextColumn(
            disabled=True, width="medium",
            help="Para alterar, use **Editar tipos** abaixo da tabela.",
        ),
        "Qtd":          st.column_config.NumberColumn(
            min_value=0, max_value=10000, step=1, width="small",
            help="Quantidade total de amostras nesta entrega.",
        ),
        "Laboratório":  st.column_config.SelectboxColumn(
            options=[""] + lab_names_sorted, width="medium",
        ),
        "Responsável":  st.column_config.SelectboxColumn(
            options=[""] + people_names_sorted, width="medium",
        ),
        "Status":       st.column_config.SelectboxColumn(
            options=status_label_options_ui, width="small",
            help="3 estados: Pendente · Em análise · Concluído.",
        ),
        "Entrega":      st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
        "Prazo (dias)": st.column_config.NumberColumn(
            min_value=0, max_value=365, step=1, width="small",
            help="Prazo do laboratório para liberar os laudos.",
        ),
        "Previsão":     st.column_config.DateColumn(
            format="DD/MM/YYYY", width="small",
            help="Recalculada (Entrega + Prazo) ao salvar se você não a editar manualmente.",
        ),
        "Dias":         st.column_config.TextColumn(
            disabled=True, width="small",
            help="Dias restantes (+) ou de atraso (−) em relação à Previsão.",
        ),
        "Obs":          st.column_config.TextColumn(width="large"),
        "Excluir?":     st.column_config.CheckboxColumn(width="small"),
    },
    key="lab_editor",
)

st.caption(
    "💡 **Previsão** é recalculada ao salvar quando você muda **Entrega** ou "
    "**Prazo (dias)** *e* não editou Previsão manualmente. "
    "**Situação** e **Dias** são recalculadas após salvar."
)

bc1, bc2, _ = st.columns([1, 1, 4])
save_clicked = bc1.button("Salvar alterações", type="primary")
reload_clicked = bc2.button("Recarregar")

if reload_clicked:
    refresh(); st.rerun()

if save_clicked:
    ok, fail, deleted = 0, 0, 0
    errors: list[str] = []
    warnings: list[str] = []

    for sample_id in ids:
        before = df_show.loc[sample_id]
        after = edited.loc[sample_id]

        if bool(after["Excluir?"]):
            try:
                sb.table("lab_samples").delete().eq("id", sample_id).execute()
                deleted += 1
            except Exception as e:
                fail += 1
                errors.append(f"{sample_id} (delete): {_api_error_message(e)}")
            continue

        before_status = LABEL_TO_STATUS_UI.get(before["Status"], "PENDENTE")
        after_status = LABEL_TO_STATUS_UI.get(after["Status"], "PENDENTE")

        before_entrega = to_date(before["Entrega"])
        after_entrega = to_date(after["Entrega"])
        before_prev = to_date(before["Previsão"])
        after_prev = to_date(after["Previsão"])

        before_sla = int(before["Prazo (dias)"]) if before["Prazo (dias)"] is not None else DEFAULT_SLA_DAYS
        try:
            after_sla = int(after["Prazo (dias)"])
        except Exception:
            after_sla = before_sla

        try:
            before_qtd = int(before["Qtd"]) if before["Qtd"] is not None else 0
        except Exception:
            before_qtd = 0
        try:
            after_qtd = int(after["Qtd"])
        except Exception:
            after_qtd = before_qtd

        before_resp = norm_text(before["Responsável"])
        after_resp = norm_text(after["Responsável"])
        before_lab = norm_text(before["Laboratório"])
        after_lab = norm_text(after["Laboratório"])
        before_obs = norm_text(before["Obs"])
        after_obs = norm_text(after["Obs"])

        # Auto-cálculo da Previsão
        prev_user_changed = before_prev != after_prev
        if not prev_user_changed and (before_entrega != after_entrega or before_sla != after_sla):
            recalc = calc_expected(after_entrega, after_sla)
            if recalc is not None:
                after_prev = recalc

        diff = (
            before_status != after_status
            or before_entrega != after_entrega
            or before_sla != after_sla
            or before_prev != after_prev
            or before_qtd != after_qtd
            or before_resp != after_resp
            or before_lab != after_lab
            or before_obs != after_obs
        )
        if not diff:
            continue

        # Validação: CONCLUIDO com previsão futura
        if after_status == "CONCLUIDO" and after_prev is not None and after_prev > today:
            warnings.append(
                f"{after.get('Projeto','?')}: marcado como **Concluído** "
                f"mas Previsão é futura ({after_prev.strftime('%d/%m/%Y')}) — confira."
            )

        payload = {
            "status": after_status,
            "shipment_date": after_entrega.isoformat() if after_entrega else None,
            "sla_days": int(after_sla),
            "sample_count": int(after_qtd) if after_qtd else None,
            "expected_release_date": after_prev.isoformat() if after_prev else None,
            "notes": after_obs,
            "assignee_id": name_to_id.get(after_resp) if after_resp else None,
            "lab_id": lab_name_to_id.get(after_lab) if after_lab else None,
        }
        try:
            resp = (
                sb.table("lab_samples")
                .update(payload, returning="representation")
                .eq("id", sample_id)
                .execute()
            )
            if not getattr(resp, "data", None):
                fail += 1
                errors.append(f"{sample_id}: update não retornou linha (provável RLS).")
            else:
                ok += 1
        except Exception as e:
            fail += 1
            errors.append(f"{sample_id}: {_api_error_message(e)}")

    if ok:
        st.success(f"{ok} amostra(s) atualizada(s).")
    if deleted:
        st.success(f"{deleted} amostra(s) excluída(s).")
    if warnings:
        for w in warnings:
            st.warning(w)
    if fail:
        st.error(f"{fail} falha(s):")
        for err in errors:
            st.code(err)
    if ok or deleted or fail:
        refresh(); st.rerun()
    elif not warnings:
        st.info("Nenhuma alteração a salvar.")


# ==========================================================
# Visão colorida (read-only) — st.dataframe styler
# ==========================================================
with st.expander("🎨 Visão colorida (somente leitura)", expanded=False):
    def _row_style(row):
        sit = row.get("Situação", "")
        if sit == "🔴 Atraso":
            return ["background-color: #fee2e2"] * len(row)
        if sit == "🟡 Pendente":
            return ["background-color: #fef3c7"] * len(row)
        if sit == "🔵 Em análise":
            return ["background-color: #dbeafe"] * len(row)
        if sit == "🟢 Concluído":
            return ["background-color: #dcfce7"] * len(row)
        return [""] * len(row)

    view_df = export_df.copy()
    try:
        styled = view_df.style.apply(_row_style, axis=1)
        st.dataframe(styled, use_container_width=True, hide_index=True)
    except Exception:
        st.dataframe(view_df, use_container_width=True, hide_index=True)


# ==========================================================
# Editar tipos de uma entrega existente (popover)
# ==========================================================
edit_types_container = getattr(st, "popover", None)
if edit_types_container is None:
    edit_types_container = lambda label: st.expander(label, expanded=False)  # noqa: E731

with edit_types_container("✏️ Editar tipos de amostras de uma entrega"):
    if df_f.empty or not type_names_sorted:
        st.caption("Sem entregas para editar.")
    else:
        labels = []
        label_to_pos: dict[str, int] = {}
        for i in range(len(df_f)):
            r = df_f.iloc[i]
            label = (
                f"{r['project_code']} · "
                f"{', '.join(to_list(r['sample_types'])) or '—'} · "
                f"entrega {to_date(r['shipment_date']) or '—'}"
            )
            labels.append(label)
            label_to_pos[label] = i
        sel = st.selectbox("Entrega", labels, key="edit_types_sel")
        row = df_f.iloc[label_to_pos[sel]]
        current_types = to_list(row["sample_types"])
        new_types = st.multiselect(
            "Tipos de amostra",
            type_names_sorted,
            default=[t for t in current_types if t in type_names_sorted],
            key="edit_types_multi",
        )
        if st.button("Salvar tipos", type="primary", key="edit_types_save"):
            if not new_types:
                st.error("Selecione ao menos um tipo.")
            else:
                try:
                    sb.table("lab_samples").update(
                        {"sample_types": new_types}, returning="representation"
                    ).eq("id", str(row["sample_id"])).execute()
                    st.success("Tipos atualizados.")
                    refresh(); st.rerun()
                except Exception as e:
                    st.error(f"Falha: {_api_error_message(e)}")
