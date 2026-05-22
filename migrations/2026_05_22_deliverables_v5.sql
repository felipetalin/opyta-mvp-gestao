-- =====================================================================
-- Produtos / Entregas - v5
-- Simplifica status operacional:
--   NAO_INICIADO, EM_ELABORACAO, EM_REVISAO, CONCLUIDO
-- Converte status legados (ENTREGUE/FATURADO) para CONCLUIDO.
-- =====================================================================

-- 1) Converte legado
update public.task_delivery_tracking
set delivery_status = 'CONCLUIDO'
where delivery_status in ('ENTREGUE', 'FATURADO');

-- 2) Remove qualquer check antigo sobre delivery_status
do $$
declare
  c record;
begin
  for c in
    select con.conname
    from pg_constraint con
    join pg_class rel on rel.oid = con.conrelid
    join pg_namespace nsp on nsp.oid = rel.relnamespace
    where nsp.nspname = 'public'
      and rel.relname = 'task_delivery_tracking'
      and con.contype = 'c'
      and pg_get_constraintdef(con.oid) ilike '%delivery_status%'
  loop
    execute format(
      'alter table public.task_delivery_tracking drop constraint if exists %I',
      c.conname
    );
  end loop;
end $$;

-- 3) Aplica nova regra de status
alter table public.task_delivery_tracking
  add constraint task_delivery_tracking_delivery_status_check
  check (
    delivery_status in ('NAO_INICIADO', 'EM_ELABORACAO', 'EM_REVISAO', 'CONCLUIDO')
  );
