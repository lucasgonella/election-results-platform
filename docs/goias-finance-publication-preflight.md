# Preflight de publicação da PR #133

## Gatilhos e corrida original

A PR modifica ETL, auditoria e visuais. Antes desta trava, o merge podia publicar
o JSON financeiro antes do leitor visual compatível:

| Workflow | Gatilho relevante | Escrita pública |
| --- | --- | --- |
| `deploy-portal-ftp.yml` | Push na main com visuais do portal | Chama o reutilizável com `component: portal` |
| `deploy-goias-ftp.yml` | Push na main com visuais do Raio-X, exceto dados/Markdown | Único deploy visual do Raio-X; chama o reutilizável |
| `deploy-frontend-ftp.yml` | `workflow_call` | Espera Python Tests e Frontend FTP validation no SHA solicitado; publica e verifica hashes |
| `goias-finance-data.yml` | Push na main com ETL/identidade/publicador/workflow; cron `23 9,15,21 * * *`; manual | Importa, faz bot commit na main e envia o JSON pelo writer existente |
| `goias-finance-audit.yml` | Push na main com auditor/workflow; manual | Somente auditoria, sem upload do JSON |
| Workflows de CI | Pull request e seus filtros | Testes e artefatos; nenhum deploy |

O reutilizável visual usa `locaweb-frontend-production`. O importador financeiro
usava somente `goias-finance-etl`, sem dependência do deploy ou da confirmação
HTTPS visual. O tempo gasto aguardando CI tornava possível o financeiro terminar
primeiro. Agenda e execução manual tinham a mesma lacuna; retirar apenas o
gatilho de push não seria suficiente.

Na consulta à API de Actions em 16/10/2026, o importador agendado
[38950474905](https://github.com/lucasgonella/election-results-platform/actions/runs/38950474905)
terminou com sucesso no SHA `98cd223` às 18:51 UTC. Os deploys visuais anteriores
do mesmo SHA também constavam como concluídos:
[Raio-X](https://github.com/lucasgonella/election-results-platform/actions/runs/38943077043)
e [portal](https://github.com/lucasgonella/election-results-platform/actions/runs/38943077138).
Esses recibos históricos não estabelecem uma dependência para o próximo merge;
o preflight continua exigindo prova do conteúdo ativo em cada publicação.

## Trava implementada

Os workflows, destinos, horários, seleção de transporte, escritor financeiro e
mecanismos de backup/rollback/integridade foram preservados. A alteração fica na
job financeira, no guard `deploy/finance_preflight.py` e nas entradas de geração
e publicação do schema financeiro novo:

1. A job só aceita `refs/heads/main` e fixa o checkout em `github.sha`, sem trocar
   de código enquanto espera na fila ou durante o download.
2. Conserva a exclusão própria `goias-finance-etl` e acrescenta, na job inteira,
   `locaweb-frontend-production`, `queue: max`, sem cancelar execução ativa. A
   exclusão permanece até terminar a verificação do upload financeiro.
3. Logo após o checkout, antes de testes/coleta, exige visual já compatível.
   Se o financeiro chegar primeiro e o visual antigo estiver publicado, falha
   fechado e libera a fila; **não espera nem dispara deploy enquanto segura a
   exclusão**. Uma execução posterior pode tentar de novo.
4. Repete a prova antes do bot commit. O guard lê os manifests/journals por FTP
   convencional, porta 21, passivo, reutilizando o cliente e os secrets existentes.
   Não chama STOR, MKD, rename, recuperação nem outro escritor.
5. Reempacota somente os visuais locais do Raio-X com o SHA da release publicada,
   sem dados e sem dependências novas, e exige igualdade de `source_sha256` e de
   todo o inventário de tamanhos/hashes. Fingerprint ausente ou leitor antigo
   bloqueiam. A igualdade por conteúdo aceita uma release de outro commit com
   os mesmos visuais, inclusive quando o HEAD da agenda é um bot commit de dados.
6. Reutiliza `frontend.status()` para verificar os assets versionados, o HTML
   estável e DirectoryIndex por SHA-256 em HTTPS. Exige ausência de locks e de
   journals pendentes/desconhecidos de ambos os componentes e relê o estado para
   detectar mudança durante a prova.
7. A definição nova fornece o literal `FINANCE_PREFLIGHT_PROTOCOL: '1'` dentro
   da job protegida. Uma execução criada com a definição antiga (`ref: main`)
   pode buscar o código novo, mas não terá esse marcador: o CLI do ETL em Actions
   recusa antes de gerar/escrever o JSON, e o writer recusa schema 1 antes de
   selecionar qualquer transporte. O writer também repete a prova de leitura
   imediatamente antes do caminho de upload; o marcador sozinho não autoriza
   publicação. Não é uma variável de aprovação/configuração do repositório.

O contrato legado sem `financial_schema` conserva o comportamento existente;
schema explícito desconhecido é rejeitado. O ETL local e sua função pura `build`
continuam utilizáveis com fixtures, sem exigir ambiente de Actions.

O guard não consulta "último CI verde" nem espera checks do bot commit. Os gates
de CI da publicação visual permanecem no reutilizável existente; o financeiro
exige o conteúdo efetivamente publicado, em vez de inferi-lo de um job verde.

A documentação oficial do GitHub permite a mesma exclusão entre jobs e
workflows. A ordem de despacho não estabelece dependência: a segurança vem da
prova de compatibilidade dentro da exclusão, conforme
[controle de concorrência](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

## Limites e validação

Se o financeiro for o primeiro da fila após o merge, sua execução pode ficar
vermelha por bloqueio seguro; não há promessa de conclusão imediata do importador.
As agendas existentes continuam sendo novas oportunidades, sem ativação manual
adicional nesta tarefa.

Quando o visual já é compatível, a job conserva a exclusão durante o download e
o processamento, até o timeout existente de 45 minutos. Isso pode adiar outros
visuais/rollbacks. Separar preparo e publicação em jobs com artefatos reduziria
essa espera, mas acrescentaria um novo contrato de transferência; não foi feito.

A exclusão cobre os workflows participantes no repositório. Escritores externos
ou CLI que ignorem essa exclusão não têm garantia global de serialização. O
guard detecta locks, pendências e mudanças observáveis; não reivindica atomicidade
multinó, proteção contra falha física ou transação global entre HTML e JSON.

`tests/test_goias_finance_preflight.py` usa releases inventadas e FTP/HTTPS
simulados. Cobre visual compatível com outro SHA, visual antigo, ausência de
fingerprint, inventário divergente, corrupção pública, rollback, locks/journals,
mudança durante a prova, ausência de escrita e erros sanitizados. Também cobre
definições antigas sem protocolo, recusa antes de gerar o novo JSON, marcador
sem prova, schema inválido e compatibilidade do ETL local/legado. A regressão
inclui o writer financeiro, o cliente visual e a recuperação existente.

Validação local desta alteração: **130 testes + 21 subtests** na seleção afetada;
**729 testes + 55 subtests** na suíte geral, sem falhas/skips, com Chromium e axe
em loopback obrigatórios para Raio-X e municipal. A revisão independente executou
**186 testes + 37 subtests**, incluindo regressão sintética de SSH. O override
de espaço mínimo foi aplicado somente ao processo de testes, sem mudar serviços
ou configuração operacional. O CI remoto é registrado na descrição da PR no SHA
efetivo, após o envio do commit.

Esta entrega atualiza somente a branch da PR. Nenhum merge, deploy, importação
oficial, conexão FTP de produção ou workflow de publicação foi executado para
validar a trava. A primeira prova real ocorrerá apenas numa execução autorizada
do fluxo após a publicação visual compatível.
