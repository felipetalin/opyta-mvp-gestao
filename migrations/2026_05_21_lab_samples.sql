-- =====================================================================
-- Laboratório — controle de amostras enviadas ao laboratório
-- e previsão de liberação dos laudos.
--
-- Tabela própria (não reaproveita tasks) pois é um fluxo paralelo:
-- várias entregas de amostras podem existir por projeto, independentes
-- das tarefas/relatórios.
--
-- Idempotente. Reusa fn_touch_updated_at() definida na migração
-- 2026_05_21_deliverables.sql.
-- =====================================================================

create table if not exists public.lab_samples (
  id                    uuid primary key default gen_random_uuid(),
  project_id            uuid not null references public.projects(id) on delete cascade,
  assignee_id           uuid references public.people(id) on delete set null,
  sample_type           text not null,
  shipment_date         date,
  status                text not null default 'PENDENTE'
                        check (status in (
                          'PENDENTE',
                          'ENTREGUE_LAB',
                          'AGUARDANDO_LAUDO',
                          'LAUDO_RECEBIDO',
                          'CONCLUIDO'
                        )),
  sla_days              int  not null default 45 check (sla_days >= 0),
  expected_release_date date,
  notes                 text,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  created_by            uuid,
  updated_by            uuid
);

create index if not exists ix_lab_samples_project   on public.lab_samples (project_id);
create index if not exists ix_lab_samples_status    on public.lab_samples (status);
create index if not exists ix_lab_samples_expected  on public.lab_samples (expected_release_date);

-- updated_at automático (reusa função existente)
drop trigger if exists trg_lab_samples_touch on public.lab_samples;
create trigger trg_lab_samples_touch
before update on public.lab_samples
for each row execute function public.fn_touch_updated_at();

-- RLS — mesmo padrão das demais tabelas operacionais
alter table public.lab_samples enable row level security;

drop policy if exists p_lab_read  on public.lab_samples;
drop policy if exists p_lab_write on public.lab_samples;
create policy p_lab_read  on public.lab_samples
  for select to authenticated using (true);
create policy p_lab_write on public.lab_samples
  for all to authenticated using (true) with check (true);

-- View consolidada para a UI (resolve projeto e responsável)
drop view if exists public.v_lab_samples;
create view public.v_lab_samples as
select
  s.id                     as sample_id,
  s.project_id,
  p.project_code,
  p.name                   as project_name,
  s.assignee_id,
  ppl.name                 as assignee_name,
  s.sample_type,
  s.shipment_date,
  s.status,
  s.sla_days,
  s.expected_release_date,
  s.notes,
  s.created_at,
  s.updated_at
from public.lab_samples s
join public.projects p on p.id = s.project_id
left join public.people ppl on ppl.id = s.assignee_id;

grant select on public.v_lab_samples to authenticated;
