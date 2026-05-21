-- =====================================================================
-- Produtos v4 — índices para acelerar filtros/ordenação.
-- Idempotente.
-- =====================================================================

create index if not exists ix_tdt_delivery_status
  on public.task_delivery_tracking (delivery_status);

create index if not exists ix_tdt_delivery_date
  on public.task_delivery_tracking (delivery_date);

create index if not exists ix_tdt_invoice_date
  on public.task_delivery_tracking (invoice_date);

create index if not exists ix_tasks_end_date
  on public.tasks (end_date);

create index if not exists ix_tasks_tipo_atividade
  on public.tasks (tipo_atividade);
