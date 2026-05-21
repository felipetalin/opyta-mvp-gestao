-- =====================================================================
-- Laboratório v2 — tabela auxiliar de tipos de amostras (lookup)
-- + migração de lab_samples para FK por id (mantendo compat).
-- Idempotente.
-- =====================================================================

-- 1) Tabela auxiliar
create table if not exists public.lab_sample_types (
  id          uuid primary key default gen_random_uuid(),
  name        text not null unique,
  active      boolean not null default true,
  sort_order  int not null default 0,
  created_at  timestamptz not null default now()
);

alter table public.lab_sample_types enable row level security;

drop policy if exists p_lst_read  on public.lab_sample_types;
drop policy if exists p_lst_write on public.lab_sample_types;
create policy p_lst_read  on public.lab_sample_types
  for select to authenticated using (true);
-- liberamos escrita autenticada para permitir adicionar novos tipos
-- direto pela UI/SQL no futuro, sem novo deploy.
create policy p_lst_write on public.lab_sample_types
  for all to authenticated using (true) with check (true);

-- 2) Seed dos tipos iniciais (idempotente)
insert into public.lab_sample_types (name, sort_order) values
  ('Fitoplâncton',      1),
  ('Zooplâncton',       2),
  ('Bentos',            3),
  ('Macrófita',         4),
  ('Sedimento',         5),
  ('Água Superficial',  6),
  ('Água Subterrânea',  7)
on conflict (name) do nothing;

-- 3) Adiciona FK em lab_samples (mantém coluna texto antiga p/ compat)
alter table public.lab_samples
  add column if not exists sample_type_id uuid references public.lab_sample_types(id);

create index if not exists ix_lab_samples_type_id
  on public.lab_samples (sample_type_id);

-- 4) Backfill: associa linhas existentes pelo nome (case-insensitive, trim)
update public.lab_samples ls
   set sample_type_id = t.id
  from public.lab_sample_types t
 where ls.sample_type_id is null
   and ls.sample_type is not null
   and lower(trim(ls.sample_type)) = lower(trim(t.name));

-- 5) Coluna sample_type vira opcional (compat — preferimos sample_type_id)
alter table public.lab_samples alter column sample_type drop not null;

-- 6) Recria a view consolidada usando o tipo resolvido por FK
drop view if exists public.v_lab_samples;
create view public.v_lab_samples as
select
  s.id                                  as sample_id,
  s.project_id,
  p.project_code,
  p.name                                as project_name,
  s.assignee_id,
  ppl.name                              as assignee_name,
  s.sample_type_id,
  coalesce(t.name, s.sample_type)       as sample_type,
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
left join public.lab_sample_types t on t.id = s.sample_type_id;

grant select on public.v_lab_samples       to authenticated;
grant select on public.lab_sample_types    to authenticated;
