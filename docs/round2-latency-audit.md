# Latência real do segundo turno: auditoria somente leitura

O objetivo é medir etapas **observáveis**, sem prometer sincronismo instantâneo com o TSE.

```bash
# app01, via conta com permissão de leitura dos arquivos locais:
sudo python3 /opt/election-round2/current/tools/round2_latency_audit.py
# ou depois de copiar o script versionado (sem reinstalar publicador):
sudo python3 tools/round2_latency_audit.py --state /var/lib/election-round2
```

O script realiza no máximo dois GET HTTPS para URLs fixas no domínio público
(`/data/turnos/2/version.json` e `status.json`), sem seguir redirects, sem
consultar o TSE, sem alteração remota e sem ler ou imprimir credenciais.
`--local-only` não realiza requisições externas. Os campos de diagnóstico são
apenas status/tempos/identificadores e controle de cache; não há dados pessoais.

Leia `observed_equals_checkpoint` e `checkpoint_equals_public` antes de concluir
qualquer latência. `observed_to_verified_seconds` só é calculado quando o ID
observado ainda corresponde ao checkpoint; representa o intervalo entre a primeira
observação local registrada e a confirmação da publicação. Não mede a hora exata
em que o TSE disponibilizou o arquivo, nem o instante em que cada navegador
detectou a versão. Um registro `unchanged` não demonstra desempenho de upload
de novos resultados. `source_last_success_age_seconds` é idade de consulta, não
atraso eleitoral quando os dados oficiais não mudaram.

Use `python3 -m collector.src.second_round_metrics --state /var/lib/election-round2`
para p50 e máximos das fases e p95 (20 amostras) / p99 (100 amostras). Ensaio de
navegadores com fixtures sintéticas em loopback é separado:
`tools/election_hardening_rehearsal.py`. Não usar mudanças reais ou uploads
em produção para gerar amostras artificiais.

Metas iniciais do hardening: até 90s entre dados validados e confirmação da
publicação, e até 15s de detecção no navegador visível. **Não são SLA comprovado.**
Investigue diferenças entre métricas de ciclo, confirmação HTTPS, versão pública,
cache e verificação do navegador. Antes de 25/10 valide também a disponibilidade
da janela temporária SSH da Locaweb e a capacidade pública com ensaios limitados.

Nenhum cronjob da Locaweb, novo writer, trigger Zabbix ou fallback FTP é criado
por este script. Para incidentes, seguir `docs/election-day-ssh-operations-2026.md`.
