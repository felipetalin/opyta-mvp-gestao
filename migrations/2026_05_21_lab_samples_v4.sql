-- =====================================================================
-- Laboratório v4 — adiciona quantidade de amostras (total da entrega).
-- Idempotente.
-- =====================================================================

alter table public.lab_samples
  add column if not exists sample_count int;

-- Recria a view consolidada com sample_count
drop view if exists public.v_lab_samples;
create view public.v_lab_samples as
select
  s.id                                       as sample_id,
  s.project_id,
  p.project_code,
  p.name                                     as project_name,
  s.assignee_id,
  ppl.name                                   as assignee_name,
  s.lab_id,
  l.name                                     as lab_name,
  s.sample_types,
  coalesce(array_to_string(s.sample_types, ', '),
           coalesce(t.name, s.sample_type, '')) as sample_types_label,
  s.sample_type_id,
  coalesce(t.name, s.sample_type)            as sample_type, -- compat
  s.sample_count,
  s.shipment_date,
  s.status,
  s.sla_days,
  s.expected_release_date,
  s.notes,
  s.created_at,
  s.updated_at
from public.lab_samples s
join public.projects p on p.id = s.project_id
left join public.people ppl on ppl.id = s.assignee_id
left join public.lab_sample_types t on t.id = s.sample_type_id
left join public.labs l on l.id = s.lab_id;

grant select on public.v_lab_samples to authenticated;
