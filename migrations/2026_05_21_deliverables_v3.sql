-- =====================================================================
-- Produtos / Entregas — v3
-- Fix: upsert em task_delivery_tracking não persistia porque o trigger
-- fn_log_delivery_event tentava INSERT em task_delivery_events sob RLS,
-- sem policy de INSERT. Dependendo do PostgREST a resposta vinha 200 com
-- data vazia (parecia sucesso), mas a transação era rejeitada.
--
-- Solução: trigger passa a rodar como SECURITY DEFINER (dono da função,
-- normalmente postgres, bypassa RLS) + policy explícita de INSERT em
-- task_delivery_events (cinto + suspensório).
-- Idempotente.
-- =====================================================================

create or replace function public.fn_log_delivery_event() returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if tg_op = 'INSERT' then
    insert into public.task_delivery_events(task_id, event_type, to_value, changed_by)
    values (new.task_id, 'CREATED', new.delivery_status, new.updated_by);
  end if;

  if tg_op = 'UPDATE' and new.delivery_status is distinct from old.delivery_status then
    insert into public.task_delivery_events(task_id, event_type, from_value, to_value, changed_by)
    values (new.task_id, 'STATUS_CHANGE', old.delivery_status, new.delivery_status, new.updated_by);
  end if;

  if tg_op = 'UPDATE' and new.needs_revision and not coalesce(old.needs_revision,false) then
    insert into public.task_delivery_events(task_id, event_type, to_value, changed_by)
    values (new.task_id, 'REVISION_FLAG', 'true', new.updated_by);
  end if;

  if tg_op = 'UPDATE' and new.sent_to_client and not coalesce(old.sent_to_client,false) then
    insert into public.task_delivery_events(task_id, event_type, to_value, changed_by)
    values (new.task_id, 'SENT_TO_CLIENT', 'true', new.updated_by);
  end if;

  if new.delivery_date is not null
     and (tg_op = 'INSERT' or new.delivery_date is distinct from old.delivery_date) then
    insert into public.task_delivery_events(task_id, event_type, to_value, changed_by)
    values (new.task_id, 'DELIVERED', new.delivery_date::text, new.updated_by);
  end if;

  if new.invoice_date is not null
     and (tg_op = 'INSERT' or new.invoice_date is distinct from old.invoice_date) then
    insert into public.task_delivery_events(task_id, event_type, to_value, changed_by)
    values (new.task_id, 'INVOICED', new.invoice_date::text, new.updated_by);
  end if;

  return new;
end $$;

-- Cinto + suspensório: policy explícita de INSERT em events (mesmo com
-- SECURITY DEFINER acima, mantém a tabela coerente caso alguém escreva
-- direto pelo PostgREST).
drop policy if exists p_tde_insert on public.task_delivery_events;
create policy p_tde_insert on public.task_delivery_events
  for insert to authenticated
  with check (true);
