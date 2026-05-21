# app/pages/6_Laboratorio.py
"""
Controle de amostras enviadas ao laboratório e previsão de liberação dos laudos.

Tabela própria (lab_samples) — não reaproveita tasks. Cada linha = uma
entrega de amostras vinculada a um projeto.

Segue o mesmo padrão visual e operacional da aba Produtos.
"""

from __future__ import annotations

from datetime import date, timedelta

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


LAB_STATUS_OPTIONS = [
    "PENDENTE",
    "ENTREGUE_LAB",
    "AGUARDANDO_LAUDO",
    "LAUDO_RECEBIDO",
    "CONCLUIDO",
]
STATUS_LABEL = {
    "PENDENTE":         "⚪ Pendente",
    "ENTREGUE_LAB":     "📦 Entregue ao lab",
    "AGUARDANDO_LAUDO": "⏳ Aguardando laudo",
    "LAUDO_RECEBIDO":   "📄 Laudo recebido",
    "CONCLUIDO":        "✅ Concluído",
}
LABEL_TO_STATUS = {v: k for k, v in STATUS_LABEL.items()}

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


# ==========================================================
# Loads
# ==========================================================
@st.cache_data(ttl=30)
def load_samples(_k: str) -> pd.DataFrame:
    res = (
        sb.table("v_lab_samples")
        .select("*")
        .order("expected_release_date")
        .execute()
    )
    return pd.DataFrame(res.data or [])


@st.cache_data(ttl=300)
def load_projects(_k: str) -> pd.DataFrame:
    res = (
        sb.table("projects")
        .select("id, project_code, name")
        .order("project_code")
        .execute()
    )
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
        .order("sort_order")
        .order("name")
        .execute()
    )
    return pd.DataFrame(res.data or [])


def refresh():
    load_samples.clear()
    load_sample_types.clear()


# ==========================================================
# Formulário — Nova entrega
# ==========================================================
df_projects = load_projects(cache_key)
df_people = load_people(cache_key)
df_types = load_sample_types(cache_key)

# Mapas auxiliares de tipos
type_name_to_id: dict[str, str] = (
    {str(r["name"]): r["id"] for _, r in df_types.iterrows()} if not df_types.empty else {}
)
type_names_sorted = list(type_name_to_id.keys())

with st.expander("➕ Nova entrega de amostras", expanded=False):
    if df_projects.empty:
        st.warning("Nenhum projeto cadastrado. Cadastre projetos antes.")
    elif not type_names_sorted:
        st.warning(
            "Nenhum tipo de amostra cadastrado. Rode a migração "
            "`2026_05_21_lab_samples_v2.sql` no Supabase."
        )
    else:
        proj_options = {
            f"{row['project_code']} — {row['name']}": row["id"]
            for _, row in df_projects.iterrows()
        }
        people_options = {"(sem responsável)": None}
        for _, row in df_people.iterrows():
            people_options[str(row["name"])] = row["id"]

        with st.form("new_lab_sample", clear_on_submit=True):
            f1, f2 = st.columns(2)
            with f1:
                proj_label = st.selectbox("Projeto *", list(proj_options.keys()))
                sample_type_name = st.selectbox("Tipo de amostra *", type_names_sorted)
                shipment = st.date_input(
                    "Data de entrega das amostras",
                    value=date.today(),
                    format="DD/MM/YYYY",
                )
                sla = st.number_input(
                    "Prazo para liberação (dias)",
                    min_value=0, max_value=365, value=DEFAULT_SLA_DAYS, step=1,
                )
            with f2:
                resp_label = st.selectbox("Responsável", list(people_options.keys()))
                status_new = st.selectbox(
                    "Status",
                    LAB_STATUS_OPTIONS,
                    index=1,  # ENTREGUE_LAB por padrão
                    format_func=lambda s: STATUS_LABEL.get(s, s),
                )
                expected_default = calc_expected(shipment, sla)
                expected_new = st.date_input(
                    "Previsão de liberação dos laudos",
                    value=expected_default,
                    format="DD/MM/YYYY",
                    help="Calculada automaticamente (Entrega + Prazo), mas editável.",
                )
                notes_new = st.text_area("Observações", value="", height=80)

            submitted = st.form_submit_button("Salvar entrega", type="primary")
            if submitted:
                type_id = type_name_to_id.get(sample_type_name)
                if not type_id:
                    st.error("Selecione um tipo de amostra válido.")
                else:
                    payload = {
                        "project_id": proj_options[proj_label],
                        "assignee_id": people_options[resp_label],
                        "sample_type_id": type_id,
                        "sample_type": sample_type_name,  # compat com coluna texto
                        "shipment_date": shipment.isoformat() if shipment else None,
                        "status": status_new,
                        "sla_days": int(sla),
                        "expected_release_date": expected_new.isoformat() if expected_new else None,
                        "notes": norm_text(notes_new),
                    }
                    try:
                        resp = (
                            sb.table("lab_samples")
                            .insert(payload, returning="representation")
                            .execute()
                        )
                        if not getattr(resp, "data", None):
                            st.error("Insert não retornou linha (provável bloqueio por RLS).")
                        else:
                            st.success("Entrega cadastrada.")
                            refresh()
                            st.rerun()
                    except Exception as e:
                        st.error(f"Falha ao cadastrar: {_api_error_message(e)}")


# ==========================================================
# Tabela principal
# ==========================================================
with st.spinner("Carregando amostras..."):
    df = load_samples(cache_key)

if df.empty:
    st.info("Nenhuma entrega cadastrada ainda. Use **Nova entrega de amostras** acima.")
    st.stop()


# ==========================================================
# Filtros
# ==========================================================
projects_all = sorted({p for p in safe_text_list(df["project_code"]) if p})
people_all = sorted({p for p in safe_text_list(df["assignee_name"]) if p})
types_all = sorted({t for t in safe_text_list(df["sample_type"]) if t})

today = date.today()
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
    f_people = st.multiselect("Responsável", people_all, default=[])
with fc3:
    f_types = st.multiselect("Tipo de amostra", types_all, default=[])

fc4, fc5, fc6 = st.columns([1.6, 1.6, 1.2])
with fc4:
    f_status = st.multiselect(
        "Status",
        LAB_STATUS_OPTIONS,
        default=[],
        format_func=lambda s: STATUS_LABEL.get(s, s),
    )
with fc5:
    sel_period = st.selectbox(
        "Atalho (período pela Previsão)",
        period_labels,
        index=0,
        help="Filtra amostras cuja previsão de liberação cai no período.",
    )
with fc6:
    only_pending = st.toggle(
        "Apenas pendentes",
        value=False,
        help="Oculta LAUDO_RECEBIDO e CONCLUIDO",
    )

fc7, fc8 = st.columns([1.5, 1.5])
with fc7:
    include_overdue = st.toggle(
        "Incluir atrasadas",
        value=False,
        help="Mostra amostras com previsão vencida e ainda não concluídas, fora do período.",
    )
with fc8:
    include_undated = st.toggle(
        "Incluir sem previsão",
        value=False,
        help="Mostra amostras sem previsão de liberação.",
    )

# Resolução do período
chosen = next(p for p in period_presets if p[0] == sel_period)
if chosen[0] == "(manual)":
    period = st.date_input(
        "Período manual (Previsão)",
        value=(cur_start, cur_end),
        format="DD/MM/YYYY",
    )
    if isinstance(period, tuple) and len(period) == 2:
        p_start, p_end = period
    else:
        p_start, p_end = cur_start, cur_end
elif chosen[0] == "Tudo":
    p_start, p_end = None, None
else:
    p_start, p_end = chosen[1], chosen[2]
    st.caption(
        f"Período (Previsão): **{p_start.strftime('%d/%m/%Y')} – {p_end.strftime('%d/%m/%Y')}**"
    )

# Máscaras
mask = pd.Series(True, index=df.index)
if f_projects:
    mask &= df["project_code"].isin(f_projects)
if f_people:
    mask &= df["assignee_name"].isin(f_people)
if f_types:
    mask &= df["sample_type"].isin(f_types)
if f_status:
    mask &= df["status"].isin(f_status)
if only_pending:
    mask &= ~df["status"].isin(["LAUDO_RECEBIDO", "CONCLUIDO"])

expected = pd.to_datetime(df["expected_release_date"], errors="coerce").dt.date
if p_start is not None and p_end is not None:
    in_window = expected.between(p_start, p_end)
    extra = pd.Series(False, index=df.index)
    if include_overdue:
        overdue = (
            expected.notna()
            & (expected < today)
            & ~df["status"].isin(["LAUDO_RECEBIDO", "CONCLUIDO"])
        )
        extra = extra | overdue
    if include_undated:
        extra = extra | expected.isna()
    mask &= in_window | extra
else:
    if not include_undated:
        mask &= expected.notna()

df_f = df.loc[mask].reset_index(drop=True)


# ==========================================================
# Métricas
# ==========================================================
expected_f = pd.to_datetime(df_f["expected_release_date"], errors="coerce").dt.date
n_aguardando = int(df_f["status"].isin(["ENTREGUE_LAB", "AGUARDANDO_LAUDO"]).sum())
atrasado_mask = (
    expected_f.notna()
    & (expected_f < today)
    & ~df_f["status"].isin(["LAUDO_RECEBIDO", "CONCLUIDO"])
)
n_atrasado = int(atrasado_mask.sum())
n_concluido = int(df_f["status"].isin(["LAUDO_RECEBIDO", "CONCLUIDO"]).sum())

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total exibido", len(df_f))
m2.metric("Aguardando laudo", n_aguardando)
m3.metric("Atrasadas", n_atrasado)
m4.metric("Recebidas/Concluídas", n_concluido)

st.divider()


# ==========================================================
# Busca + ordenação
# ==========================================================
st.subheader("Amostras")
st.caption("Edite os campos e clique em **Salvar alterações**. Marque **Excluir?** para remover linhas.")

SORT_OPTIONS = {
    "Previsão (mais próxima primeiro)":  ("expected_release_date", True),
    "Previsão (mais distante primeiro)": ("expected_release_date", False),
    "Entrega (mais recente)":            ("shipment_date", False),
    "Projeto (A→Z)":                     ("project_code", True),
    "Status":                            ("status", True),
    "Atualizado recentemente":           ("updated_at", False),
}

tc1, tc2 = st.columns([2.5, 1.5])
with tc1:
    search = st.text_input(
        "Buscar (Projeto · Tipo · Responsável · Obs)",
        value="",
        placeholder="Ex.: água, ictio, fulano, ASSCAF...",
    )
with tc2:
    sort_label = st.selectbox("Ordenar por", list(SORT_OPTIONS.keys()), index=0)

if search.strip():
    q = search.strip().lower()
    haystack = (
        df_f["project_code"].fillna("").astype(str).str.lower()
        + " | "
        + df_f["sample_type"].fillna("").astype(str).str.lower()
        + " | "
        + df_f["assignee_name"].fillna("").astype(str).str.lower()
        + " | "
        + df_f["notes"].fillna("").astype(str).str.lower()
    )
    df_f = df_f.loc[haystack.str.contains(q, na=False, regex=False)].reset_index(drop=True)

sort_col, sort_asc = SORT_OPTIONS[sort_label]
if sort_col in df_f.columns and not df_f.empty:
    df_f = df_f.sort_values(by=sort_col, ascending=sort_asc, na_position="last").reset_index(drop=True)

if df_f.empty:
    st.info("Nenhuma amostra corresponde aos filtros/busca atuais.")
    st.stop()


# ==========================================================
# Editor
# ==========================================================
people_names_sorted = sorted({n for n in safe_text_list(df_people["name"]) if n}) if not df_people.empty else []
name_to_id = {row["name"]: row["id"] for _, row in df_people.iterrows()} if not df_people.empty else {}

ids = safe_text_list(df_f["sample_id"])
status_labels = [STATUS_LABEL.get(s, s) for s in safe_text_list(df_f["status"], "PENDENTE")]

df_show = pd.DataFrame(
    {
        "Projeto":     safe_text_list(df_f["project_code"]),
        "Tipo":        safe_text_list(df_f["sample_type"]),
        "Responsável": safe_text_list(df_f["assignee_name"]),
        "Status":      status_labels,
        "Entrega":     [to_date(x) for x in df_f["shipment_date"].tolist()],
        "Prazo (dias)": df_f["sla_days"].fillna(DEFAULT_SLA_DAYS).astype(int).tolist(),
        "Previsão":    [to_date(x) for x in df_f["expected_release_date"].tolist()],
        "Obs":         safe_text_list(df_f["notes"]),
        "Excluir?":    [False] * len(df_f),
    },
    index=ids,
)

status_label_options = [STATUS_LABEL[s] for s in LAB_STATUS_OPTIONS]

edited = st.data_editor(
    df_show,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "Projeto":     st.column_config.TextColumn(disabled=True, width="small"),
        "Tipo":        st.column_config.SelectboxColumn(
            options=type_names_sorted,
            width="medium",
            help="Tipos cadastrados em lab_sample_types.",
        ),
        "Responsável": st.column_config.SelectboxColumn(
            options=[""] + people_names_sorted,
            width="medium",
            help="Selecione um responsável já cadastrado. Vazio = sem responsável.",
        ),
        "Status":      st.column_config.SelectboxColumn(options=status_label_options, width="medium"),
        "Entrega":     st.column_config.DateColumn(
            format="DD/MM/YYYY", width="small",
            help="Data em que as amostras foram entregues ao laboratório.",
        ),
        "Prazo (dias)": st.column_config.NumberColumn(
            min_value=0, max_value=365, step=1, width="small",
            help="Prazo do laboratório para liberar os laudos.",
        ),
        "Previsão":    st.column_config.DateColumn(
            format="DD/MM/YYYY", width="small",
            help="Recalculada (Entrega + Prazo) se você não tocar; "
                 "edite manualmente para travar a data.",
        ),
        "Obs":         st.column_config.TextColumn(width="large"),
        "Excluir?":    st.column_config.CheckboxColumn(width="small"),
    },
    key="lab_editor",
)

st.caption(
    "💡 **Previsão** é recalculada automaticamente ao salvar quando você muda "
    "**Entrega** ou **Prazo (dias)** *e* não editou Previsão manualmente. "
    "Se editar Previsão diretamente, o valor manual é mantido."
)

bc1, bc2, _ = st.columns([1, 1, 4])
save_clicked = bc1.button("Salvar alterações", type="primary")
reload_clicked = bc2.button("Recarregar")

if reload_clicked:
    refresh()
    st.rerun()

if save_clicked:
    ok, fail, deleted = 0, 0, 0
    errors: list[str] = []

    for sample_id in ids:
        before = df_show.loc[sample_id]
        after = edited.loc[sample_id]

        # Exclusão
        if bool(after["Excluir?"]):
            try:
                sb.table("lab_samples").delete().eq("id", sample_id).execute()
                deleted += 1
            except Exception as e:
                fail += 1
                errors.append(f"{sample_id} (delete): {_api_error_message(e)}")
            continue

        before_status = LABEL_TO_STATUS.get(before["Status"], "PENDENTE")
        after_status = LABEL_TO_STATUS.get(after["Status"], "PENDENTE")

        before_entrega = to_date(before["Entrega"])
        after_entrega = to_date(after["Entrega"])
        before_prev = to_date(before["Previsão"])
        after_prev = to_date(after["Previsão"])

        before_sla = int(before["Prazo (dias)"]) if before["Prazo (dias)"] is not None else DEFAULT_SLA_DAYS
        try:
            after_sla = int(after["Prazo (dias)"])
        except Exception:
            after_sla = before_sla

        before_resp = norm_text(before["Responsável"])
        after_resp = norm_text(after["Responsável"])
        before_tipo = norm_text(before["Tipo"]) or ""
        after_tipo = norm_text(after["Tipo"]) or ""
        before_obs = norm_text(before["Obs"])
        after_obs = norm_text(after["Obs"])

        # Auto-cálculo: se usuário não editou Previsão manualmente
        # mas mexeu em Entrega ou Prazo → recalcula.
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
            or before_resp != after_resp
            or before_tipo != after_tipo
            or before_obs != after_obs
        )
        if not diff:
            continue

        if not after_tipo:
            fail += 1
            errors.append(f"{sample_id}: Tipo de amostra é obrigatório.")
            continue

        after_type_id = type_name_to_id.get(after_tipo)
        if not after_type_id:
            fail += 1
            errors.append(
                f"{sample_id}: Tipo '{after_tipo}' não cadastrado em lab_sample_types."
            )
            continue

        payload = {
            "sample_type_id": after_type_id,
            "sample_type": after_tipo,  # compat com coluna texto
            "status": after_status,
            "shipment_date": after_entrega.isoformat() if after_entrega else None,
            "sla_days": int(after_sla),
            "expected_release_date": after_prev.isoformat() if after_prev else None,
            "notes": after_obs,
            "assignee_id": name_to_id.get(after_resp) if after_resp else None,
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
                errors.append(
                    f"{sample_id}: update não retornou linha "
                    "(provável bloqueio por RLS)."
                )
            else:
                ok += 1
        except Exception as e:
            fail += 1
            errors.append(f"{sample_id}: {_api_error_message(e)}")

    if ok:
        st.success(f"{ok} amostra(s) atualizada(s).")
    if deleted:
        st.success(f"{deleted} amostra(s) excluída(s).")
    if fail:
        st.error(f"{fail} falha(s):")
        for err in errors:
            st.code(err)
    if ok or deleted or fail:
        refresh()
        st.rerun()
    else:
        st.info("Nenhuma alteração a salvar.")
