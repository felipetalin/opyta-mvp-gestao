-- =====================================================================
-- Laboratório v3 — multi-tipos por entrega + cadastro de laboratórios.
-- Idempotente. Mantém compat com v1/v2.
-- =====================================================================

-- 1) Tabela auxiliar de laboratórios
create table if not exists public.labs (
  id          uuid primary key default gen_random_uuid(),
  name        text not null unique,
  active      boolean not null default true,
  sort_order  int not null default 0,
  created_at  timestamptz not null default now()
);

alter table public.labs enable row level security;

drop policy if exists p_labs_read  on public.labs;
drop policy if exists p_labs_write on public.labs;
create policy p_labs_read  on public.labs for select to authenticated using (true);
create policy p_labs_write on public.labs for all    to authenticated using (true) with check (true);

grant select on public.labs to authenticated;

-- 2) Colunas novas em lab_samples
alter table public.lab_samples
  add column if not exists lab_id uuid references public.labs(id) on delete set null;

alter table public.lab_samples
  add column if not exists sample_types text[];

create index if not exists ix_lab_samples_lab_id      on public.lab_samples (lab_id);
create index if not exists ix_lab_samples_types_gin   on public.lab_samples using gin (sample_types);

-- 3) Backfill sample_types a partir de sample_type_id (preferencial) ou sample_type texto
update public.lab_samples ls
   set sample_types = array[t.name]
  from public.lab_sample_types t
 where ls.sample_types is null
   and ls.sample_type_id = t.id;

update public.lab_samples
   set sample_types = array[sample_type]
 where sample_types is null
   and sample_type is not null
   and length(trim(sample_type)) > 0;

-- 4) Recria a view consolidada
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
