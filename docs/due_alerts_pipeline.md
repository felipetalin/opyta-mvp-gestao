# Pipeline de alertas de vencimento

## Objetivo

Enviar avisos por e-mail para responsaveis por itens com prazo vencido ou proximo
do vencimento, reaproveitando o Supabase e a automacao via GitHub Actions.

## Fontes monitoradas

- `gantt`: tarefas de `v_portfolio_tasks`, usando `end_date`.
- `laboratorio`: amostras de `v_lab_samples`, usando `expected_release_date`.
- `produtos`: entregas de `v_deliverables`, usando `client_due_date` quando existir;
  caso contrario, usa o fallback ja tratado na aba Produtos (`enterprise`/`end_date`).
- `reembolsos`: despesas de `v_reimbursements`, usando `due_date`.

## Regras iniciais

- Janelas: vencido, vence hoje, vence em 1, 3 ou 7 dias.
- Atrasados entram por ate 30 dias de atraso por padrao.
- Itens concluidos/pagos/cancelados/glosados nao entram no aviso.
- Os avisos sao agrupados em um e-mail por destinatario.
- O envio real registra cada item em `due_notification_log` para evitar duplicidade.

## Arquivos

- Script: `scripts/notifications/send_due_alerts.py`
- Workflow: `.github/workflows/due-alerts.yml`
- Migration: `migrations/2026_07_01_due_notifications.sql`

## Checklist para ativar

1. Aplicar `migrations/2026_07_01_due_notifications.sql` no SQL Editor do Supabase.
2. Preencher `people.email` para os colaboradores ativos.
3. Garantir que o GitHub tenha os secrets:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `GOOGLE_SERVICE_ACCOUNT_JSON`
4. No Admin do Google Workspace, autorizar a service account para o escopo:
   - `https://www.googleapis.com/auth/gmail.send`
5. Rodar o workflow `Due Alerts` manualmente com `dry_run=true`.
6. Rodar manualmente com `dry_run=false` para validar envio real.
7. Depois de validado, alterar o workflow para agenda real sem dry-run.

## Execucao local

Dry-run:

```bash
python scripts/notifications/send_due_alerts.py --dry-run
```

Forcar data de referencia:

```bash
python scripts/notifications/send_due_alerts.py --dry-run --today 2026-07-01
```

Envio real exige:

```bash
set NOTIFICATION_DRY_RUN=0
set NOTIFICATION_FROM_EMAIL=felipetalin@opyta.com.br
set FALLBACK_OWNER_EMAIL=felipetalin@opyta.com.br
set GOOGLE_SERVICE_ACCOUNT_JSON=secrets_gcal/service-account-gcal.json
set GOOGLE_SCOPES=https://www.googleapis.com/auth/gmail.send
python scripts/notifications/send_due_alerts.py
```

## Observacoes

- Enquanto `people.email` estiver vazio, os itens aparecem no contador
  `missing_recipient_count` e nao sao enviados.
- Para teste controlado sem preencher todos os e-mails, e possivel definir
  `NOTIFICATION_FALLBACK_RECIPIENT`, mas isso deve ser temporario.
- A agenda do workflow esta em 08:00 BRT em dias uteis, mas fica em dry-run ate a
  virada final da chave.
