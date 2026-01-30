001  from __future__ import annotations
002
003  from datetime import date
004  import pandas as pd
005  import streamlit as st
006
007  from services.auth import require_login
008  from services.supabase_client import get_authed_client
009  from services.finance_guard import require_finance_access
010
011  # Branding (não pode quebrar o app se faltar algo)
012  try:
013      from ui.brand import apply_brand, apply_app_chrome, page_header
014  except Exception:
015      from ui.brand import apply_brand  # type: ignore
016
017      def apply_app_chrome():  # type: ignore
018          return
019
020      def page_header(title, subtitle, user_email=""):  # type: ignore
021          st.title(title)
022          if subtitle:
023              st.caption(subtitle)
024          if user_email:
025              st.caption(f"Logado como: {user_email}")
026
027
028  # ==========================================================
029  # Boot (ordem obrigatória)
030  # ==========================================================
031  st.set_page_config(page_title="Financeiro", layout="wide")
032  apply_brand()
033  apply_app_chrome()
034
035  require_login()
036  sb = get_authed_client()
037
038  # 🔒 Acesso silencioso (para não constranger)
039  user_email = require_finance_access(silent=True)
040
041  page_header("Financeiro", "Dashboard + lançamentos", user_email)
042
043  TYPE_OPTIONS = ["RECEITA", "DESPESA", "TRANSFERENCIA"]
044  STATUS_OPTIONS = ["PREVISTO", "REALIZADO", "CANCELADO"]
045  today = date.today()
046
047
048  # ==========================================================
049  # Helpers
050  # ==========================================================
051  def _api_error_message(e: Exception) -> str:
052      try:
053          if getattr(e, "args", None) and len(e.args) > 0 and isinstance(e.args[0], dict):
054              d = e.args[0]
055              msg = d.get("message") or str(d)
056              details = d.get("details")
057              hint = d.get("hint")
058              out = msg
059              if hint:
060                  out += f"\nHint: {hint}"
061              if details:
062                  out += f"\nDetalhes: {details}"
063              return out
064          return str(e)
065      except Exception:
066          return "Erro desconhecido."
067
068
069  def norm(x) -> str:
070      return ("" if x is None else str(x)).strip()
071
072
073  def _clean_str(x) -> str:
074      if x is None:
075          return ""
076      s = str(x).strip()
077      return "" if s in ("None", "nan", "NaT") else s
078
079
080  def _brl(v: float) -> str:
081      return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
082
083
084  def month_range(d: date) -> tuple[date, date]:
085      m0 = date(d.year, d.month, 1)
086      if d.month == 12:
087          m1 = date(d.year + 1, 1, 1)
088      else:
089          m1 = date(d.year, d.month + 1, 1)
090      m_last = (pd.to_datetime(m1) - pd.Timedelta(days=1)).date()
091      return m0, m_last
092
093
094  def _prev_month(d: date) -> date:
095      if d.month == 1:
096          return date(d.year - 1, 12, 1)
097      return date(d.year, d.month - 1, 1)
098
099
100  def _pct(curr: float, prev: float) -> str:
101      if prev == 0:
102          return "—"
103      p = ((curr - prev) / abs(prev)) * 100
104      arrow = "↑" if p >= 0 else "↓"
105      return f"{arrow} {abs(p):.1f}%"
106
107
108  # ==========================================================
109  # Cache / fetchs
110  # ==========================================================
111  @st.cache_data(ttl=30)
112  def fetch_projects():
113      res = sb.table("projects").select("id,project_code,name").order("project_code", desc=False).execute()
114      return pd.DataFrame(res.data or [])
115
116
117  @st.cache_data(ttl=30)
118  def fetch_categories():
119      res = (
120          sb.table("finance_categories")
121          .select("id,name,type,active")
122          .eq("active", True)
123          .order("name", desc=False)
124          .execute()
125      )
126      return pd.DataFrame(res.data or [])
127
128
129  @st.cache_data(ttl=30)
130  def fetch_counterparties():
131      res = (
132          sb.table("finance_counterparties")
133          .select("id,name,type,active")
134          .eq("active", True)
135          .order("name", desc=False)
136          .execute()
137      )
138      return pd.DataFrame(res.data or [])
139
140
141  @st.cache_data(ttl=30)
142  def fetch_transactions_view(
143      date_from: date,
144      date_to: date,
145      project_id: str | None,
146      t_type: str | None,
147      status: str | None,
148      category_id: str | None,
149      counterparty_id: str | None,
150  ):
151      q = (
152          sb.from_("v_finance_transactions")
153          .select(
154              "id,date,type,status,description,amount,"
155              "category_id,category_name,"
156              "counterparty_id,counterparty_name,"
157              "project_id,project_code,project_name,"
158              "payment_method,competence_month,notes,created_by"
159          )
160          .gte("date", date_from.isoformat())
161          .lte("date", date_to.isoformat())
162          .order("date", desc=True)
163      )
164
165      if project_id:
166          q = q.eq("project_id", project_id)
167      if t_type:
168          q = q.eq("type", t_type)
169      if status:
170          q = q.eq("status", status)
171      if category_id:
172          q = q.eq("category_id", category_id)
173      if counterparty_id:
174          q = q.eq("counterparty_id", counterparty_id)
175
176      res = q.execute()
177      return pd.DataFrame(res.data or [])
178
179
180  def insert_tx(payload: dict):
181      return sb.table("finance_transactions").insert(payload).execute()
182
183
184  @st.cache_data(ttl=30)
185  def fetch_monthly_summary():
186      res = (
187          sb.from_("v_finance_monthly_summary")
188          .select("month,receita,despesa,saldo")
189          .order("month", desc=False)
190          .execute()
191      )
192      return pd.DataFrame(res.data or [])
193
194
195  @st.cache_data(ttl=30)
196  def fetch_tx_min(date_from: date, date_to: date):
197      res = (
198          sb.table("finance_transactions")
199          .select("date,type,status,amount")
200          .gte("date", date_from.isoformat())
201          .lte("date", date_to.isoformat())
202          .execute()
203      )
204      return pd.DataFrame(res.data or [])
205
206
207  @st.cache_data(ttl=30)
208  def fetch_receivables(limit: int = 10):
209      res = (
210          sb.from_("v_finance_receivables")
211          .select("date,description,amount,counterparty_name,project_code,status")
212          .order("date", desc=False)
213          .limit(limit)
214          .execute()
215      )
216      return pd.DataFrame(res.data or [])
217
218
219  @st.cache_data(ttl=30)
220  def fetch_payables(limit: int = 10):
221      res = (
222          sb.from_("v_finance_payables")
223          .select("date,description,amount,counterparty_name,project_code,status")
224          .order("date", desc=False)
225          .limit(limit)
226          .execute()
227      )
228      return pd.DataFrame(res.data or [])
229
230
231  def clear_caches():
232      fetch_projects.clear()
233      fetch_categories.clear()
234      fetch_counterparties.clear()
235      fetch_transactions_view.clear()
236      fetch_monthly_summary.clear()
237      fetch_tx_min.clear()
238      fetch_receivables.clear()
239      fetch_payables.clear()
240
241
242  # ==========================================================
243  # CSS Global
244  # ==========================================================
245  st.markdown(
246      """
247  <style>
248  .op-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-top: 8px; }
249  .op-card { border-radius: 10px; padding: 14px 16px; color: #fff;
250    box-shadow: 0 6px 16px rgba(0,0,0,.12); border: 1px solid rgba(255,255,255,.12);
251    position: relative; min-height: 92px; }
252  .op-title { font-size: 14px; font-weight: 600; opacity: .95; margin-bottom: 4px; }
253  .op-value { font-size: 30px; font-weight: 800; line-height: 1.05; margin: 0; }
254  .op-sub   { font-size: 12px; opacity: .9; margin-top: 6px; }
255  .op-green  { background: linear-gradient(135deg, #2f7d55 0%, #3e9a6b 100%); }
256  .op-blue   { background: linear-gradient(135deg, #1e5aa7 0%, #2d79d3 100%); }
257  .op-orange { background: linear-gradient(135deg, #c66b10 0%, #f39a2a 100%); }
258  .op-red    { background: linear-gradient(135deg, #a11e1e 0%, #e04a4a 100%); }
259
260  .op-panel { border: 1px solid rgba(0,0,0,.08); border-radius: 10px;
261    padding: 12px 12px 10px 12px; background: rgba(255,255,255,.55); }
262  .op-row { display: flex; justify-content: space-between; align-items: center;
263    gap: 10px; padding: 10px 8px; border-radius: 8px; }
264  .op-row + .op-row { border-top: 1px solid rgba(0,0,0,.06); }
265  .op-left { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
266  .op-topline { font-size: 12px; opacity: .85; }
267  .op-mainline { font-size: 14px; font-weight: 700; white-space: nowrap; overflow: hidden;
268    text-overflow: ellipsis; max-width: 520px; }
269  .op-subline { font-size: 12px; opacity: .75; white-space: nowrap; overflow: hidden;
270    text-overflow: ellipsis; max-width: 520px; }
271  .op-chip { padding: 6px 10px; border-radius: 999px; font-weight: 800; font-size: 12px;
272    color: #fff; white-space: nowrap; }
273  .op-chip-green { background: #2f7d55; }
274  .op-chip-orange{ background: #c66b10; }
275  .op-chip-gray  { background: #555; }
276
277  @media (max-width: 1100px) {
278    .op-cards { grid-template-columns: repeat(2, 1fr); }
279    .op-mainline, .op-subline { max-width: 360px; }
280  }
281  @media (max-width: 650px) {
282    .op-cards { grid-template-columns: 1fr; }
283    .op-mainline, .op-subline { max-width: 260px; }
284  }
285  </style>
286  """,
287      unsafe_allow_html=True,
288  )
289
290
291  # ==========================================================
292  # DROPDOWNS (para filtros + insert + editor)
293  # ==========================================================
294  projects_df = fetch_projects()
295  categories_df = fetch_categories()
296  cp_df = fetch_counterparties()
297
298  proj_options = ["(Todos)"]
299  proj_map: dict[str, str | None] = {"(Todos)": None}
300  if not projects_df.empty:
301      for _, r in projects_df.iterrows():
302          label = f"{norm(r.get('project_code'))} — {norm(r.get('name'))}".strip(" —")
303          proj_options.append(label)
304          proj_map[label] = norm(r.get("id")) or None
305
306  cat_options = ["(Todas)"]
307  cat_map: dict[str, str | None] = {"(Todas)": None}
308  if not categories_df.empty:
309      for _, r in categories_df.iterrows():
310          label = norm(r.get("name"))
311          cat_options.append(label)
312          cat_map[label] = norm(r.get("id")) or None
313
314  cp_options = ["(Todas)"]
315  cp_map: dict[str, str | None] = {"(Todas)": None}
316  if not cp_df.empty:
317      for _, r in cp_df.iterrows():
318          label = norm(r.get("name"))
319          cp_options.append(label)
320          cp_map[label] = norm(r.get("id")) or None
321
322
323  # ==========================================================
324  # FILTROS
325  # ==========================================================
326  st.subheader("Filtros")
327
328  default_from = date(today.year, today.month, 1)
329  default_to = today
330
331  with st.container(border=True):
332      f1, f2, f3, f4, f5, f6 = st.columns([1.2, 1.2, 1.2, 1.2, 2.0, 2.0])
333      with f1:
334          date_from = st.date_input("De", value=default_from, format="DD/MM/YYYY")
335      with f2:
336          date_to = st.date_input("Até", value=default_to, format="DD/MM/YYYY")
337      with f3:
338          t_type = st.selectbox("Tipo", ["(Todos)"] + TYPE_OPTIONS, index=0)
339      with f4:
340          stt = st.selectbox("Status", ["(Todos)"] + STATUS_OPTIONS, index=0)
341      with f5:
342          proj_label = st.selectbox("Projeto", proj_options, index=0)
343      with f6:
344          cat_label = st.selectbox("Categoria", cat_options, index=0)
345
346      g1, g2 = st.columns([2.0, 1.0])
347      with g1:
348          cp_label = st.selectbox("Cliente/Fornecedor", cp_options, index=0)
349      with g2:
350          if st.button("Recarregar"):
351              clear_caches()
352              if "finance_editor" in st.session_state:
353                  del st.session_state["finance_editor"]
354              if "finance_confirm_delete" in st.session_state:
355                  del st.session_state["finance_confirm_delete"]
356              st.rerun()
357
358  f_project_id = proj_map.get(proj_label)
359  f_type = None if t_type == "(Todos)" else t_type
360  f_status = None if stt == "(Todos)" else stt
361  f_category_id = cat_map.get(cat_label)
362  f_cp_id = cp_map.get(cp_label)
363
364
365  # ==========================================================
366  # DASHBOARD
367  # ==========================================================
368  st.divider()
369  st.subheader("Dashboard")
370
371  try:
372      ms = fetch_monthly_summary()
373  except Exception as e:
374      st.error("Erro ao carregar resumo mensal:")
375      st.code(_api_error_message(e))
376      ms = pd.DataFrame()
377
378  if not ms.empty:
379      ms["month"] = pd.to_datetime(ms["month"]).dt.date
380      month_options = [m.isoformat() for m in sorted(ms["month"].unique(), reverse=True)]
381  else:
382      month_options = [today.replace(day=1).isoformat()]
383
384  sel_month_str = st.selectbox("Mês (competência)", month_options, index=0, key="dash_month")
385  sel_month = pd.to_datetime(sel_month_str).date()
386
387  m_from, m_to = month_range(sel_month)
388  txm = fetch_tx_min(m_from, m_to)
389
390  def _calc_month(tx: pd.DataFrame):
391      r_real = d_real = r_prev = d_prev = 0.0
392      if not tx.empty:
393          t = tx.copy()
394          t["type"] = t["type"].astype(str).str.upper()
395          t["status"] = t["status"].astype(str).str.upper()
396          t["amount"] = pd.to_numeric(t["amount"], errors="coerce").fillna(0.0)
397          r_real = float(t[(t["type"] == "RECEITA") & (t["status"] == "REALIZADO")]["amount"].sum())
398          d_real = float(t[(t["type"] == "DESPESA") & (t["status"] == "REALIZADO")]["amount"].sum())
399          r_prev = float(t[(t["type"] == "RECEITA") & (t["status"] == "PREVISTO")]["amount"].sum())
400          d_prev = float(t[(t["type"] == "DESPESA") & (t["status"] == "PREVISTO")]["amount"].sum())
401      return {"saldo": r_real - d_real, "r_prev": r_prev, "d_prev": d_prev}
402
403  curr = _calc_month(txm)
404
405  pm = _prev_month(sel_month)
406  pm_from, pm_to = month_range(pm)
407  txm_prev = fetch_tx_min(pm_from, pm_to)
408  prev = _calc_month(txm_prev)
409
410  saldo_delta = _pct(curr["saldo"], prev["saldo"])
411  rprev_delta = _pct(curr["r_prev"], prev["r_prev"])
412  dprev_delta = _pct(curr["d_prev"], prev["d_prev"])
413  saldo_projetado = (curr["saldo"] + curr["r_prev"]) - curr["d_prev"]
414
415  n_receber = 0
416  n_pagar = 0
417  if not txm.empty:
418      t2 = txm.copy()
419      t2["type"] = t2["type"].astype(str).str.upper()
420      t2["status"] = t2["status"].astype(str).str.upper()
421      n_receber = int(((t2["type"] == "RECEITA") & (t2["status"] == "PREVISTO")).sum())
422      n_pagar = int(((t2["type"] == "DESPESA") & (t2["status"] == "PREVISTO")).sum())
423
424  st.markdown(
425      f"""
426  <div class="op-cards">
427    <div class="op-card op-green">
428      <div class="op-title">Saldo Atual</div>
429      <div class="op-value">{_brl(curr["saldo"])}</div>
430      <div class="op-sub">{saldo_delta} vs mês anterior</div>
431    </div>
432
433    <div class="op-card op-blue">
434      <div class="op-title">Receitas Previstas</div>
435      <div class="op-value">{_brl(curr["r_prev"])}</div>
436      <div class="op-sub">{n_receber} a receber • {rprev_delta} vs mês anterior</div>
437    </div>
438
439    <div class="op-card op-orange">
440      <div class="op-title">Despesas Previstas</div>
441      <div class="op-value">{_brl(curr["d_prev"])}</div>
442      <div class="op-sub">{n_pagar} a pagar • {dprev_delta} vs mês anterior</div>
443    </div>
444
445    <div class="op-card op-red">
446      <div class="op-title">Saldo Projetado</div>
447      <div class="op-value">{_brl(saldo_projetado)}</div>
448      <div class="op-sub">Atual + previstas</div>
449    </div>
450  </div>
451  """,
452      unsafe_allow_html=True,
453  )
454
455  st.divider()
456
457
458  # ==========================================================
459  # ALERTAS DE VENCIMENTO
460  # ==========================================================
461  st.subheader("Alertas")
462
463  today_dt = today
464  next_7 = (pd.to_datetime(today_dt) + pd.Timedelta(days=7)).date()
465
466  try:
467      df_alert = fetch_transactions_view(
468          date_from=today_dt,
469          date_to=next_7,
470          project_id=None,
471          t_type=None,
472          status="PREVISTO",
473          category_id=None,
474          counterparty_id=None,
475      )
476  except Exception as e:
477      st.error("Erro ao carregar alertas de vencimento:")
478      st.code(_api_error_message(e))
479      df_alert = pd.DataFrame()
480
481  if df_alert.empty:
482      st.caption("Nenhum lançamento previsto para vencer nos próximos dias.")
483  else:
484      df_alert = df_alert.copy()
485      df_alert["date"] = pd.to_datetime(df_alert["date"], errors="coerce").dt.date
486      df_alert["amount"] = pd.to_numeric(df_alert["amount"], errors="coerce").fillna(0.0)
487      df_alert["type"] = df_alert["type"].astype(str).str.upper()
488
489      df_today = df_alert[df_alert["date"] == today_dt]
490      df_week = df_alert[(df_alert["date"] > today_dt) & (df_alert["date"] <= next_7)]
491
492      def _alert_card(title: str, dfx: pd.DataFrame):
493          if dfx.empty:
494              st.markdown(
495                  f"""
496                  <div class="op-panel">
497                    <strong>{title}</strong>
498                    <div style="opacity:.75; margin-top:6px;">Nenhum lançamento</div>
499                  </div>
500                  """,
501                  unsafe_allow_html=True,
502              )
503              return
504
505          total = float(dfx["amount"].sum())
506          n = len(dfx)
507          rec = float(dfx[dfx["type"] == "RECEITA"]["amount"].sum())
508          desp = float(dfx[dfx["type"] == "DESPESA"]["amount"].sum())
509
510          st.markdown(
511              f"""
512              <div class="op-panel">
513                <strong>{title}</strong>
514                <div style="margin-top:6px;">
515                  <b>{n}</b> lançamentos • <b>{_brl(total)}</b>
516                </div>
517                <div style="opacity:.85; margin-top:4px; font-size:13px;">
518                  Receitas: {_brl(rec)} • Despesas: {_brl(desp)}
519                </div>
520              </div>
521              """,
522              unsafe_allow_html=True,
523          )
524
525      a1, a2 = st.columns([1, 1])
526      with a1:
527          _alert_card("⚠️ Vencem hoje", df_today)
528      with a2:
529          _alert_card("📅 Vencem nos próximos 7 dias", df_week)
530
531  st.divider()
532
533
534  # ==========================================================
535  # FLUXO DE CAIXA MENSAL (6 meses)
536  # ==========================================================
537  st.subheader("Fluxo de Caixa Mensal")
538
539  def _month_start(d: date) -> date:
540      return date(d.year, d.month, 1)
541
542  def _add_months(d: date, n: int) -> date:
543      y = d.year + (d.month - 1 + n) // 12
544      m = (d.month - 1 + n) % 12 + 1
545      return date(y, m, 1)
546
547  end_m = _month_start(sel_month)
548  start_m = _add_months(end_m, -5)
549  range_from = start_m
550  range_to = month_range(end_m)[1]
551
552  df_range = fetch_tx_min(range_from, range_to)
553
554  if df_range.empty:
555      st.caption("Sem dados no intervalo para montar o gráfico.")
556  else:
557      df_range = df_range.copy()
558      df_range["date"] = pd.to_datetime(df_range["date"], errors="coerce")
559      df_range["month"] = df_range["date"].dt.to_period("M").dt.to_timestamp().dt.date
560      df_range["type"] = df_range["type"].astype(str).str.upper()
561      df_range["amount"] = pd.to_numeric(df_range["amount"], errors="coerce").fillna(0.0)
562
563      receita_m = df_range[df_range["type"] == "RECEITA"].groupby("month")["amount"].sum().rename("receita")
564      despesa_m = df_range[df_range["type"] == "DESPESA"].groupby("month")["amount"].sum().rename("despesa")
565
566      months = pd.date_range(pd.to_datetime(start_m), pd.to_datetime(end_m), freq="MS").date
567      plot_df = pd.DataFrame({"month": months}).set_index("month")
568      plot_df["receita"] = receita_m.reindex(plot_df.index).fillna(0.0)
569      plot_df["despesa"] = despesa_m.reindex(plot_df.index).fillna(0.0)
570      plot_df["saldo_final"] = (plot_df["receita"] - plot_df["despesa"]).cumsum()
571      plot_df = plot_df.reset_index()
572
573      import plotly.graph_objects as go
574
575      fig = go.Figure()
576      fig.add_bar(x=plot_df["month"], y=plot_df["receita"], name="Receitas")
577      fig.add_bar(x=plot_df["month"], y=plot_df["despesa"], name="Despesas")
578      fig.add_trace(
579          go.Scatter(
580              x=plot_df["month"],
581              y=plot_df["saldo_final"],
582              mode="lines+markers",
583              name="Saldo Final (R$)",
584              yaxis="y2",
585          )
586      )
587
588      fig.update_layout(
589          barmode="group",
590          height=360,
591          margin=dict(l=10, r=10, t=20, b=10),
592          xaxis=dict(title="", tickformat="%b/%y"),
593          yaxis=dict(title="R$"),
594          yaxis2=dict(title="", overlaying="y", side="right"),
595          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
596      )
597
598      st.plotly_chart(fig, use_container_width=True)
599
600  st.divider()
601
602
603  # ==========================================================
604  # DESPESAS POR CATEGORIA (donut)
605  # ==========================================================
606  st.subheader("Despesas por Categoria")
607
608  try:
609      df_month_full = fetch_transactions_view(
610          date_from=m_from,
611          date_to=m_to,
612          project_id=None,
613          t_type="DESPESA",
614          status=None,
615          category_id=None,
616          counterparty_id=None,
617      )
618  except Exception as e:
619      st.error("Erro ao montar despesas por categoria:")
620      st.code(_api_error_message(e))
621      df_month_full = pd.DataFrame()
622
623  if df_month_full.empty:
624      st.caption("Sem despesas no mês selecionado.")
625  else:
626      dfc = df_month_full.copy()
627      dfc["amount"] = pd.to_numeric(dfc["amount"], errors="coerce").fillna(0.0)
628      dfc["category_name"] = dfc.get("category_name", "").fillna("").apply(_clean_str)
629      dfc = dfc[dfc["amount"] > 0]
630
631      if dfc.empty:
632          st.caption("Sem despesas válidas para exibir.")
633      else:
634          by_cat = dfc.groupby("category_name")["amount"].sum().sort_values(ascending=False).reset_index()
635          by_cat["category_name"] = by_cat["category_name"].replace("", "(Sem categoria)")
636
637          import plotly.express as px
638
639          fig = px.pie(by_cat, names="category_name", values="amount", hole=0.55)
640          fig.update_traces(textposition="outside", textinfo="percent+label")
641          fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
642          st.plotly_chart(fig, use_container_width=True)
643
644          st.caption("Top categorias (mês):")
645          topn = by_cat.head(6).copy()
646          topn["Valor (R$)"] = topn["amount"].apply(lambda v: _brl(float(v)))
647          st.dataframe(
648              topn[["category_name", "Valor (R$)"]].rename(columns={"category_name": "Categoria"}),
649              use_container_width=True,
650              hide_index=True,
651          )
652
653  st.divider()
654
655
656  # ==========================================================
657  # Contas a receber / pagar (painel)
658  # ==========================================================
659  r1, r2 = st.columns([1, 1])
660
661  def _render_list_panel(df_in: pd.DataFrame, empty_text: str):
662      if df_in is None or df_in.empty:
663          st.caption(empty_text)
664          return
665
666      dfp = df_in.copy()
667      dfp["date"] = pd.to_datetime(dfp["date"], errors="coerce").dt.date
668      dfp["amount"] = pd.to_numeric(dfp["amount"], errors="coerce").fillna(0.0)
669      for col in ["description", "counterparty_name", "project_code", "status"]:
670          if col in dfp.columns:
671              dfp[col] = dfp[col].fillna("").apply(_clean_str)
672
673      html = '<div class="op-panel">'
674      for _, row in dfp.iterrows():
675          d = row.get("date")
676          d_txt = d.strftime("%d/%m") if isinstance(d, date) else ""
677          proj = row.get("project_code") or ""
678          cpty = row.get("counterparty_name") or ""
679          desc = row.get("description") or ""
680          amt = _brl(float(row.get("amount") or 0.0))
681          topline = " • ".join([x for x in [proj, cpty] if x])
682          subline = " • ".join([x for x in [d_txt, (row.get("status") or "").title()] if x])
683
684          html += f"""
685          <div class="op-row">
686            <div class="op-left">
687              <div class="op-topline">{topline}</div>
688              <div class="op-mainline">{desc}</div>
689              <div class="op-subline">{subline}</div>
690            </div>
691            <div class="op-chip op-chip-orange">{amt}</div>
692          </div>
693          """
694      html += "</div>"
695      st.markdown(html, unsafe_allow_html=True)
696
697  with r1:
698      st.subheader("Contas a Receber (previsto)")
699      try:
700          df_r = fetch_receivables(limit=10)
701      except Exception as e:
702          st.error("Erro ao carregar contas a receber:")
703          st.code(_api_error_message(e))
704          df_r = pd.DataFrame()
705      _render_list_panel(df_r, "Nenhuma conta a receber prevista.")
706
707  with r2:
708      st.subheader("Contas a Pagar (previsto)")
709      try:
710          df_p = fetch_payables(limit=10)
711      except Exception as e:
712          st.error("Erro ao carregar contas a pagar:")
713          st.code(_api_error_message(e))
714          df_p = pd.DataFrame()
715      _render_list_panel(df_p, "Nenhuma conta a pagar prevista.")
716
717  st.divider()
718
719
720  # ==========================================================
721  # NOVO LANÇAMENTO (INSERT)
722  # ==========================================================
723  st.subheader("Novo lançamento")
724  st.caption("✅ Criar lançamentos. (Você pode editar/excluir na tabela abaixo.)")
725
726  with st.container(border=True):
727      c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.2, 1.2])
728      with c1:
729          new_date = st.date_input("Data", value=today, format="DD/MM/YYYY", key="new_date")
730      with c2:
731          new_type = st.selectbox("Tipo", TYPE_OPTIONS, index=1, key="new_type")
732      with c3:
733          new_status = st.selectbox("Status", ["REALIZADO", "PREVISTO", "CANCELADO"], index=0, key="new_status")
734      with c4:
735          new_amount = st.number_input("Valor (R$)", min_value=0.01, value=0.01, step=10.0, key="new_amount")
736
737      d1, d2, d3 = st.columns([2.6, 1.6, 1.6])
738      with d1:
739          new_desc = st.text_input("Descrição", value="", key="new_desc")
740      with d2:
741          new_payment = st.text_input("Forma de pagamento (opcional)", value="", key="new_payment")
742      with d3:
743          new_comp = st.date_input("Competência (opcional)", value=None, format="DD/MM/YYYY", key="new_comp")
744
745      e1, e2, e3 = st.columns([2.0, 2.0, 2.0])
746      with e1:
747          new_cat_label = st.selectbox("Categoria", cat_options, index=0, key="new_cat")
748      with e2:
749          new_cp_label = st.selectbox("Cliente/Fornecedor", cp_options, index=0, key="new_cp")
750      with e3:
751          new_proj_label = st.selectbox("Projeto (opcional)", ["(Nenhum)"] + proj_options[1:], index=0, key="new_proj")
752
753      new_notes = st.text_area("Observações (opcional)", value="", height=80, key="new_notes")
754
755      if st.button("Salvar lançamento", type="primary"):
756          if norm(new_desc) == "":
757              st.error("Descrição é obrigatória.")
758          elif float(new_amount) <= 0:
759              st.error("Valor deve ser maior que zero.")
760          else:
761              payload = {
762                  "date": new_date.isoformat() if new_date else None,
763                  "type": new_type,
764                  "status": new_status,
765                  "description": norm(new_desc),
766                  "amount": float(new_amount),
767                  "category_id": cat_map.get(new_cat_label),
768                  "counterparty_id": cp_map.get(new_cp_label),
769                  "project_id": proj_map.get(new_proj_label) if new_proj_label != "(Nenhum)" else None,
770                  "payment_method": norm(new_payment) or None,
771                  "competence_month": new_comp.isoformat() if new_comp else None,
772                  "notes": norm(new_notes) or None,
773                  "created_by": user_email or None,
774              }
775
776              try:
777                  insert_tx(payload)
778                  st.success("Lançamento criado.")
779                  clear_caches()
780                  if "finance_editor" in st.session_state:
781                      del st.session_state["finance_editor"]
782                  st.rerun()
783              except Exception as e:
784                  st.error("Erro ao salvar lançamento:")
785                  st.code(_api_error_message(e))
786
787  st.divider()
788
789
790  # ==========================================================
791  # LISTA (EDIÇÃO INLINE + EXCLUSÃO com confirmação)
792  # ==========================================================
793  st.subheader("Lançamentos (edição inline)")
794  st.caption("✏️ Edite na tabela e clique em **Salvar alterações**. Para excluir, marque e confirme.")
795
796  try:
797      df = fetch_transactions_view(
798          date_from=date_from,
799          date_to=date_to,
800          project_id=f_project_id,
801          t_type=f_type,
802          status=f_status,
803          category_id=f_category_id,
804          counterparty_id=f_cp_id,
805      )
806  except Exception as e:
807      st.error("Erro ao carregar lançamentos:")
808      st.code(_api_error_message(e))
809      st.stop()
810
811  if df.empty:
812      st.info("Nenhum lançamento encontrado para os filtros.")
813      st.stop()
814
815  # -------------------------
816  # Normalização FORTE (evita "None" no grid)
817  # -------------------------
818  df2 = df.copy()
819  df2["id"] = df2["id"].astype(str)
820  df2["date"] = pd.to_datetime(df2["date"], errors="coerce").dt.date
821  df2["amount"] = pd.to_numeric(df2["amount"], errors="coerce").fillna(0.0)
822
823  # garante colunas sempre presentes e SEM NaN/None
824  for col in ["type", "status", "description", "payment_method", "notes"]:
825      if col not in df2.columns:
826          df2[col] = ""
827      df2[col] = df2[col].fillna("").apply(_clean_str)
828
829  # ids relacionais podem vir NaN (float). Mantém como object e preenche depois
830  for col in ["category_id", "counterparty_id", "project_id"]:
831      if col not in df2.columns:
832          df2[col] = None
833
834  # -------------------------
835  # Options (editor) + placeholders
836  # -------------------------
837  CAT_NONE = "(Sem)"
838  CP_NONE = "(Sem)"
839  PROJ_NONE = "(Sem)"
840
841  # remove "(Todas)/(Todos)" e adiciona "(Sem)"
842  cat_options_editor = [CAT_NONE] + [k for k in cat_map.keys() if k != "(Todas)"]
843  cp_options_editor = [CP_NONE] + [k for k in cp_map.keys() if k != "(Todas)"]
844  proj_options_editor = [PROJ_NONE] + [k for k in proj_map.keys() if k != "(Todos)"]
845
846  # Map id -> label (para mostrar no editor)
847  cat_label_by_id = {v: k for k, v in cat_map.items() if v}
848  cp_label_by_id = {v: k for k, v in cp_map.items() if v}
849  proj_label_by_id = {v: k for k, v in proj_map.items() if v}
850
851  # -------------------------
852  # DataFrame editável (index = id)
853  # -------------------------
854  df_edit = pd.DataFrame(
855      {
856          "Excluir?": False,
857          "Data": df2["date"],
858          "Tipo": df2["type"].astype(str).str.upper().replace({"NAN": ""}).fillna(""),
859          "Status": df2["status"].astype(str).str.upper().replace({"NAN": ""}).fillna(""),
860          "Descrição": df2["description"],
861          "Categoria": df2["category_id"].map(cat_label_by_id).fillna(CAT_NONE),
862          "Cliente/Fornecedor": df2["counterparty_id"].map(cp_label_by_id).fillna(CP_NONE),
863          "Projeto": df2["project_id"].map(proj_label_by_id).fillna(PROJ_NONE),
864          "Valor": df2["amount"],
865          "Pagamento": df2["payment_method"],
866          "Obs": df2["notes"],
867      },
868      index=df2["id"],
869  )
870
871  # -------------------------
872  # Editor
873  # -------------------------
874  edited = st.data_editor(
875      df_edit,
876      key="finance_editor",
877      use_container_width=True,
878      hide_index=True,
879      num_rows="fixed",
880      column_order=[
881          "Excluir?",
882          "Data",
883          "Tipo",
884          "Status",
885          "Descrição",
886          "Categoria",
887          "Cliente/Fornecedor",
888          "Projeto",
889          "Valor",
890          "Pagamento",
891          "Obs",
892      ],
893      column_config={
894          "Excluir?": st.column_config.CheckboxColumn(width="small"),
895          "Data": st.column_config.DateColumn(format="DD/MM/YYYY", width="small"),
896          "Tipo": st.column_config.SelectboxColumn(options=TYPE_OPTIONS, width="small"),
897          "Status": st.column_config.SelectboxColumn(options=STATUS_OPTIONS, width="small"),
898          "Categoria": st.column_config.SelectboxColumn(options=cat_options_editor),
899          "Cliente/Fornecedor": st.column_config.SelectboxColumn(options=cp_options_editor),
900          "Projeto": st.column_config.SelectboxColumn(options=proj_options_editor),
901          "Valor": st.column_config.NumberColumn(min_value=0.01, step=10.0, width="small"),
902          "Descrição": st.column_config.TextColumn(width="large"),
903          "Obs": st.column_config.TextColumn(width="large"),
904      },
905  )
906
907  c1, c2 = st.columns([1, 1])
908  save_btn = c1.button("Salvar alterações", type="primary")
909  reload_btn = c2.button("Recarregar lançamentos")
910
911  if reload_btn:
912      clear_caches()
913      # reset do editor (evita grid "preso" em DF antigo)
914      if "finance_editor" in st.session_state:
915          del st.session_state["finance_editor"]
916      if "finance_confirm_delete" in st.session_state:
917          del st.session_state["finance_confirm_delete"]
918      st.rerun()
919
920  # -------------------------
921  # Confirmação em 2 etapas
922  # -------------------------
923  if "finance_confirm_delete" not in st.session_state:
924      st.session_state["finance_confirm_delete"] = False
925
926  # Detecta ids marcados para excluir (a partir do grid atual)
927  delete_ids = [tx_id for tx_id, row in edited.iterrows() if bool(row.get("Excluir?", False))]
928
929  if st.session_state["finance_confirm_delete"] and delete_ids:
930      st.warning(
931          f"⚠️ Exclusão pendente: **{len(delete_ids)}** lançamento(s) marcado(s). "
932          "Clique em **Confirmar exclusões** ou **Cancelar**."
933      )
934      b1, b2 = st.columns([1, 1])
935      with b1:
936          confirm_del = st.button("Confirmar exclusões", type="secondary")
937      with b2:
938          cancel_del = st.button("Cancelar", type="tertiary")
939
940      if cancel_del:
941          st.session_state["finance_confirm_delete"] = False
942          # desmarca no editor (evita armadilha)
943          tmp = edited.copy()
944          if "Excluir?" in tmp.columns:
945              tmp["Excluir?"] = False
946          # injeta no state do editor
947          st.session_state["finance_editor"] = tmp
948          st.rerun()
949
950      if confirm_del:
951          # mantém a flag e pede pra clicar salvar (sem deletar no clique do confirm)
952          st.info("Agora clique em **Salvar alterações** para aplicar as exclusões confirmadas.")
953          st.stop()
954
955  # -------------------------
956  # SALVAR (updates + delete confirmada)
957  # -------------------------
958  if save_btn:
959      before = df_edit.copy()
960      after = edited.copy()
961
962      delete_ids_now = [tx_id for tx_id, row in after.iterrows() if bool(row.get("Excluir?", False))]
963
964      # Se marcou exclusão e ainda não confirmou, ativa confirmação e para
965      if delete_ids_now and not st.session_state["finance_confirm_delete"]:
966          st.session_state["finance_confirm_delete"] = True
967          st.warning(
968              f"Você marcou **{len(delete_ids_now)}** lançamento(s) para excluir. "
969              "Clique em **Confirmar exclusões** para prosseguir, ou **Cancelar**."
970          )
971          st.stop()
972
973      n_updates = 0
974      n_deletes = 0
975      warnings: list[str] = []
976
977      # 1) Deleções (somente se confirmou)
978      if st.session_state["finance_confirm_delete"] and delete_ids_now:
979          for tx_id in delete_ids_now:
980              try:
981                  sb.table("finance_transactions").delete().eq("id", tx_id).execute()
982                  n_deletes += 1
983              except Exception as e:
984                  warnings.append(f"Erro ao excluir {tx_id}: {_api_error_message(e)}")
985
986      # 2) Updates (somente itens NÃO excluídos)
987      for tx_id, ra in after.iterrows():
988          if tx_id in delete_ids_now:
989              continue
990
991          rb = before.loc[tx_id]
992
993          # Mudou algo?
994          changed = False
995          for c in before.columns:
996              if c == "Excluir?":
997                  continue
998              if norm(rb[c]) != norm(ra[c]):
999                  changed = True
1000                 break
1001         if not changed:
1002             continue
1003
1004         # Validações mínimas
1005         if ra["Data"] is None:
1006             warnings.append(f"{tx_id}: Data vazia (update ignorado).")
1007             continue
1008         if float(ra["Valor"]) <= 0:
1009             warnings.append(f"{tx_id}: Valor deve ser > 0 (update ignorado).")
1010             continue
1011         if norm(ra["Descrição"]) == "":
1012             warnings.append(f"{tx_id}: Descrição obrigatória (update ignorado).")
1013             continue
1014
1015         payload = {
1016             "date": ra["Data"].isoformat() if ra["Data"] else None,
1017             "type": ra["Tipo"],
1018             "status": ra["Status"],
1019             "description": norm(ra["Descrição"]),
1020             "amount": float(ra["Valor"]),
1021             "category_id": None if ra["Categoria"] == CAT_NONE else cat_map.get(ra["Categoria"]),
1022             "counterparty_id": None if ra["Cliente/Fornecedor"] == CP_NONE else cp_map.get(ra["Cliente/Fornecedor"]),
1023             "project_id": None if ra["Projeto"] == PROJ_NONE else proj_map.get(ra["Projeto"]),
1024             "payment_method": norm(ra["Pagamento"]) or None,
1025             "notes": norm(ra["Obs"]) or None,
1026         }
1027
1028         try:
1029             sb.table("finance_transactions").update(payload).eq("id", tx_id).execute()
1030             n_updates += 1
1031         except Exception as e:
1032             warnings.append(f"Erro ao atualizar {tx_id}: {_api_error_message(e)}")
1033
1034     # reseta confirmação sempre que salvar
1035     st.session_state["finance_confirm_delete"] = False
1036
1037     if warnings:
1038         st.warning("\n".join(warnings))
1039
1040     st.success(f"Atualizados: {n_updates} • Excluídos: {n_deletes}")
1041     clear_caches()
1042     if "finance_editor" in st.session_state:
1043         del st.session_state["finance_editor"]
1044     st.rerun()

