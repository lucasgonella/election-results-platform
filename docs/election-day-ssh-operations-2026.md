# Operação de SSH/rsync — apuração de 25/10/2026

Este procedimento complementa [ssh-rsync-migration.md](ssh-rsync-migration.md).
É um runbook operacional **não destrutivo**. Não apaga locks, não altera
resultados, não limpa o checkout da app01 e não toca em `/public_html/estudos`.

## Antes de começar

- Confirmar que o acesso SSH TCP/22 à Locaweb foi habilitado no painel.
  A habilitação é temporária; registrar a hora de início e seu prazo real.
  **Não presumir renovação automática.**
- Conferir que os quatro componentes estão em `ssh`: primeiro turno,
  segundo turno, portal e Raio-X.
- Confirmar a chave de host fixada e a identidade dedicada. Nunca usar
  `StrictHostKeyChecking=no`, imprimir chaves ou desativar validação.
- Anotar SHA da `main` e o status do CI. Mudanças de código requerem checks
  aprovados antes da publicação.

## Inspeção somente leitura na app01

```bash
date -Is
systemctl is-active election-live-publisher.timer election-round2.timer
systemctl show election-live-publisher.service election-round2.service \
  -p User -p Environment -p Result -p ExecMainStatus --no-pager
systemctl list-timers --all 'election-*' --no-pager
journalctl -u election-live-publisher.service -u election-round2.service \
  --since '2 hours ago' --no-pager -n 100
```

A saída de `systemctl show -p Environment` pode revelar valores de variáveis;
**não publicar saída contendo credenciais**. Inspecionar localmente antes de
compartilhar. As identidades SSH são entregues por `LoadCredential`.

No GitHub Actions, verificar os resultados de `SSH publication readiness and
finance recovery`, `Deploy portal frontend via FTP` e
`Deploy Raio-X Goiás via FTP`. O nome histórico do workflow não determina o
transporte: validar `transport_metrics.transport=ssh_rsync` no recibo. Um
`status=unchanged` testa o caminho de controle, **não** a transferência de
uma release nova.

## Perda ou expiração da janela SSH

1. Registrar a hora da falha e o serviço/workflow afetado; **não** mudar
   automaticamente para FTP. Não iniciar deploy concorrente nem repetir
   operações de escrita que possam ter resultado desconhecido.
2. Conferir no painel da Locaweb se o SSH expirou. Habilitar novamente a
   janela TCP/22 por procedimento manual autorizado.
3. Depois do restabelecimento, fazer primeiro operações **somente leitura**:
   consultar journal, lock, pending/checkpoint, marcador e os URLs HTTPS.
   Para frontends, usar `frontend-ftp-manual.yml` com `operation=status`.
   Para turnos, usar as interfaces de `status` documentadas no módulo de
   cada coletor, com a mesma identidade dedicada e sem mexer em arquivos.
4. Se houver `pending`, lock, resultado incerto, divergência HTTPS ou erro
   de integridade, **parar a recuperação automática** e reconciliar o estado
   remoto segundo o runbook do componente. Não remover locks manualmente.
5. Só após estado consistente retomar o ciclo normal. Para o segundo turno,
   `cycle --retry-after-reconcile` existe para o caso específico de backoff,
   com as pré-condições implementadas; não usar como repetição genérica.

**Não interromper serviço ativo para testar expiração.** O ensaio de falha
deve acontecer com fixture/ambiente privado, não mediante indisponibilização do
SSH de produção.

## Ensaiar rsync sem publicar dados oficiais

O script `tools/ssh_rsync_benchmark.py` tem destino limitado a
`/election-ssh-benchmark` (privado). Consultar `--help` e executar
somente com credenciais dedicadas válidas, após confirmar quota e ausência
de publicações simultâneas. Registrar tempo, hash, `files_sent`,
`files_reused`, `rsync_failures`, `hash_failures` e origem dos arquivos.
Não usar dados reais de eleitores nem alterar a árvore pública para forçar
um envio. Um ensaio privado não equivale à validação de uma nova release pública.

## Alertas e acompanhamento

- Observar falhas SSH, rsync, hash, timeouts, backoff e divergência HTTPS nos
  journals systemd e logs do GitHub Actions.
- Confirmar **se existe** um destino externo ativo (por exemplo, Zabbix/ntfy)
  para falhas de publicação. Logs, por si só, **não comprovam alerta**.
- Alertar somente para condições comprovadas: serviço em falha, ciclo sem
  sucesso além do SLA definido, publicação pendente sem progresso, falhas
  persistentes de transporte, divergência HTTPS, ou quota crítica.
- Não criar notificações falsas de sucesso nem assumir que uma execução
  `unchanged` validou um novo upload.
- Acompanhar espaço/quota privada, pois releases e journals são retidos.

## Encerramento do turno

Registrar último ciclo saudável de cada componente, identidade do transporte,
SHA, checkpoint/snapshot quando aplicável, URLs HTTPS e incidentes; manter
backup e journals, sem limpeza destrutiva. Rever credenciais temporárias
posteriormente, apenas após verificar ausência de transações pendentes.
