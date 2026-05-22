-- =====================================================================
-- Produtos / Entregas - v6
-- Separa prazo interno (tasks.end_date) do prazo combinado com cliente.
-- Adiciona client_due_date no tracking + expõe na view v_deliverables.
-- =====================================================================

alter table public.task_delivery_tracking
  add column if not exists client_due_date date;

drop view if exists public.v_deliverables;

create view public.v_deliverables as
select
  vpt.task_id                                   as task_id,
  vpt.project_id,
  p.project_code,
  p.name                                        as project_name,
  vpt.title                                     as product_name,
  vpt.tipo_atividade,
  vpt.start_date,
  vpt.end_date,
  vpt.status                                    as task_status,
  vpt.assignee_names,
  coalesce(d.delivery_status,'NAO_INICIADO')    as delivery_status,
  coalesce(d.needs_revision, false)             as needs_revision,
  coalesce(d.sent_to_client, false)             as sent_to_client,
  d.client_due_date,
  d.delivery_date,
  d.invoice_date,
  d.discipline,
  d.enterprise,
  d.notes                                       as tracking_notes,
  d.updated_at                                  as tracking_updated_at
from public.v_portfolio_tasks vpt
join public.projects p on p.id = vpt.project_id
left join public.task_delivery_tracking d on d.task_id = vpt.task_id
where vpt.tipo_atividade = 'RELATORIO';

grant select on public.v_deliverables to authenticated;

