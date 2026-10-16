# Segundo turno: hardening e critérios operacionais para 25/10

Esta operação é exclusiva do segundo turno. O primeiro turno, PostgreSQL,
Raio-X e o publicador municipal mantêm seus namespaces, serviços e regras.
O inventário eleitoral vem da configuração oficial e dos EA14 da execução;
35 combinações são o inventário observado, não uma constante do publicador.

## Contrato de integridade e atualização

Cada EA20 continua validado contra cargo, eleição, turno e abrangência. A prova
privada é reprocessada antes da publicação. Uma segunda descoberta recusa mudança
de inventário durante a coleta. O TSE pode atualizar UFs enquanto outras são lidas:
o portal conserva os horários próprios de cada arquivo, sem alegar uma transação
global nos servidores do TSE. Divergências, regressões e alterações de elenco que
exigem revisão continuam bloqueando.

A release contém os JSONs individuais e `portal.json`, um agregado exato dos
mesmos documentos. O SHA-256 e tamanho desse agregado entram no descritor e no
marcador. O navegador valida ambos antes de usar seu conteúdo. Não há fallback
para outro turno ou para arquivos individuais quando um agregado anunciado é
corrompido. Marcadores antigos sem agregado continuam legíveis.

O publicador mantém STOR temporário, RETR/comparação, rename, nova leitura FTP,
verificação de TODOS os arquivos por FTP/HTTPS antes da ativação e novamente
após a ativação. Somente então escreve recibo/checkpoint. Não se reutiliza a
verificação da candidata entre esses dois momentos. A baseline imutável já
verificada pode ser reutilizada somente dentro da mesma operação do único writer.
Uma consulta normal posterior e o comando `status` fazem verificação completa nova.

Até dois workers preparam arquivos imutáveis disjuntos; ativação, journals, lock
remoto e checkpoint continuam serializados. Somente a preparação dos uploads
usa sessões FTP de trabalho independentes, até três sessões com o controle.
A leitura integral de uma release reutiliza uma única sessão FTP, com acesso
serializado ao socket, enquanto até duas verificações HTTPS se sobrepõem. Isso
evita deixar o controle principal ocioso durante toda a verificação e reduz
aberturas de sessão no caminho FTP que apresentou timeouts. Todos os bytes FTP
e hashes HTTPS continuam sendo conferidos. FTP passivo, porta 21, permanece
obrigatório. `ELECTION_ROUND2_FTP_WORKERS=1` permite operação serial.
HTTPS de verificação é
limitado a quatro GETs/s por publicador, configurável somente até cinco. Controle
FTP/conexão têm 15s; dados FTP, 45s. Leituras transitórias têm orçamento de três
tentativas em sessões novas; STOR/ativação não são repetidos cegamente.

Ativações repetidas de uma release conhecida preservam journals e recibos
anteriores; o backup do marcador anterior pertence à operação, não apenas ao
ID da release. Recuperação do mesmo owner conserva a primeira confirmação de
publicação, evitando apresentar uma data nova por simples repetição.

## Navegador e HTTP 429

`live-data.js` atua somente em `/data/turnos/2`. Compartilha requisições entre
componentes; Web Locks e Cache API reutilizam dados entre abas da mesma origem.
Perfis/navegadores diferentes mantêm caches próprios. Releases imutáveis ficam
no cache da aplicação; no segundo turno, somente três gerações são mantidas em
memória. A Cache API tem limite de 160 entradas e falha de quota tem fallback
para memória. Dados corrompidos são descartados do cache e continuam bloqueados.

O agregado substitui as dezenas de GETs de resultados estaduais na abertura.
Marcadores e status têm cache local curto (2s e 5s), revalidação por ETag quando
disponível, e nunca recebem a política longa dos imutáveis. A política longa
aplicada às respostas da Cache API é do navegador; não implica mudança dos
headers da hospedagem. Headers HTTP efetivos são registrados nos ensaios.

Há espaçamento de 500ms mais jitter entre inícios de requisições de dados por
página. HTTP 429 aplica cooldown exponencial e respeita Retry-After (segundos ou
data HTTP), com jitter adicional; não antecipa o prazo do servidor. Retentativas
são limitadas. Abas ocultas deixam de consultar marcadores e status. Cadastro
aguardando apuração consulta novas publicações a cada 15s; apuração ativa, 5s;
estável, 10s; terminada, 30s. A política depende do status oficial do pipeline.

Esses controles não estabelecem o limite global ou por IP da Locaweb. Limites da
hospedagem/CDN precisam de evidência do provedor para atribuição definitiva.
Não foi introduzida uma CDN ou um novo endpoint de upload.

## Coleta adaptativa

O timer verifica elegibilidade dez segundos após a conclusão, jitter de até 2s,
sem ciclos concorrentes. O runner persiste o próximo instante permitido:

| Evidência oficial | Estado | Espera depois do ciclo |
| --- | --- | --- |
| Cadastro/configuração ainda indisponível | awaiting_official_data | 120s |
| Cadastro completo, nenhuma seção totalizada | official_data_available | 120s |
| Seções totalizadas, com mudança recente | counting_in_progress | 10s |
| Pelo menos três ciclos sem mudança | counting_stable | progressiva até 120s |
| Todas as seções totalizadas | counting_finished | progressiva até 600s |

Uma mudança oficial reinicia a estabilidade. O horário do dia não inicia a
apuração. Falhas têm backoff exponencial até uma hora; 429 preserva o prazo
prescrito pelo TSE. Um 404/ausência temporária após início da apuração é
indisponibilidade temporária; não volta a representar eleição ainda não iniciada.
Backoff não significa nova consulta bem-sucedida e não gera log completo repetido.

## Métricas e estado público

`health.json` guarda horário da consulta oficial bem-sucedida, mudança observada,
publicação, duração do ciclo e contadores. `metrics-history.json` conserva no
máximo 500 amostras. Etapas: descoberta/coleta, HTTP TSE, parsing, validação,
snapshot/prova, baseline, uploads/verificação FTP, ativação, HTTPS pré e pós.

```sh
python -m collector.src.second_round_metrics --state /var/lib/election-round2
```

A saída apresenta p50/máximo; p95 requer 20 amostras e p99, 100. Não confundir
idade da geração oficial com atraso de transporte: cadastro pode ficar dias
inalterado. O instante em que um arquivo passou a estar disponível no TSE não é
fornecido por nossa sondagem; mede-se a observação da alteração e as etapas
subsequentes, além da janela de espera pela próxima consulta.

O monitor independente gera `/var/lib/election-round2-monitor/status.json`,
sanitizado e legível pelo Zabbix, e publica `/data/turnos/2/status.json` pelo
transporte FTP existente, com journal próprio e confirmação HTTPS. Esse arquivo
não seleciona resultados. Horários do navegador, consulta ao TSE, geração oficial
e publicação são apresentados separadamente, em Brasília. Status antigo ou
consulta atrasada deixam de ser exibidos como atualizados. Métricas locais do
navegador estão em `LiveData.stats` e `ElectionLiveMetrics`, sem envio de
telemetria ou dados pessoais a um endpoint novo.

## Retenção

Ciclos novos usam identidade determinística. Dados inalterados são validados em
memória e não criam diretório, pacote ou prova duplicados. Mudança bloqueada
reutiliza a mesma evidência em tentativas posteriores.

A retenção toma o mesmo flock do writer; execução ocupada é adiada. Protege todos
os controles/referências, pacotes de publicação, rollback, journals e evidências
sem recibo de publicação. Só classifica duplicatas antigas com prova completa
reprocessada e recibo válido. Symlinks, segredos/arquivos desconhecidos,
inventários incompletos e transações desconhecidas bloqueiam exclusão.

```sh
python -m collector.src.second_round_retention --state /var/lib/election-round2
# Aplicação: --apply --limit 25. O padrão é dry-run e idade mínima de 24h.
```

Cada ciclo é compactado individualmente e validado contra todos os arquivos.
Backup privado: `/backup/election-results-platform/round2-cycles`, fora de
`public_html`. Tamanho e SHA-256 são conferidos após download integral; manifesto
remoto também é validado. Somente depois, sob o flock e nova conferência de
referências/conteúdo, remove-se o original. Auditoria local em
`retention-manifest.jsonl`. Nunca apagar um pacote pendente para liberar espaço.

Padrões: reserva de 2 GiB (preserva a margem do primeiro turno), teto de 1 GiB de ciclos, aviso em 80% do teto,
1,5 vezes a reserva ou crescimento acima de 256 MiB/h. Limites configuráveis:
`ELECTION_ROUND2_MIN_FREE_BYTES`, `ELECTION_ROUND2_MAX_CYCLE_BYTES` e
`ELECTION_ROUND2_GROWTH_BYTES_PER_HOUR`. Limite impede novas coletas; recuperação
pendente é tratada antes da guarda. A quota nunca autoriza excluir auditoria.

## Monitoramento e notificações

`election-round2-monitor.timer` verifica timer, coleta, checkpoint/marcador,
pendências, falhas, 429, FTP e armazenamento a cada aproximadamente um minuto.
Faltas oficiais anteriores à apuração não geram alarme por ausência de votos.
O atraso de consulta usa 600s em espera/final e 180s durante apuração. Transação
pendente acima de 600s exige recuperação. Divergência desconhecida nunca é adotada.

A chave Zabbix `election.round2.status` fornece o JSON sanitizado por UserParameter.
Instalação recarrega apenas UserParameters do agente existente, sem reiniciar
outros serviços. Um item mestre ativo nessa chave e dependentes JSONPath podem
ser vinculados ao host `app01`. Monitorar também a idade de `checked_at`: o
conteúdo antigo pode continuar legível quando o monitor parou.

Notificações ntfy usam configuração protegida em
`/etc/election-results-platform/round2-alerts.env`: `ELECTION_ROUND2_NTFY_URL` e,
se necessário, `ELECTION_ROUND2_NTFY_TOKEN`. Não versionar destino/token nem
copiar valores para arquivos públicos. Alertas exigem duas observações relevantes,
são deduplicados por condição por uma hora e notificam recuperação. Falha no
canal não impede a gravação do estado operacional. Não seguir redirects de
notificação. `python -m collector.src.second_round_monitor --test-alert` exige
confirmar o recibo do servidor. Teste loopback não comprova entrega externa.

Se o canal/credencial do servidor Zabbix/ntfy não estiver disponível, a emissão
externa e a vinculação do template são bloqueios explícitos: não declarar que
alertas chegaram a um operador. Informar somente caminho protegido ou URL/tópico
operacional existente; não pedir segredos em mensagens públicas.

## CI, implantação e rollback

Desenvolvimento: branch `feat/election-2026-production-hardening` no staging.
CI inclui suites existentes e `Election hardening and recovery`, com FTP
loopback, corrupção, recuperação, retenção e navegador real. Ensaio de CI usa
somente loopback e fixtures inventadas. Nenhum fixture é enviado à hospedagem.

Após aprovação dos checks no SHA exato e merge:

1. Aguardar deploy visual automático, verificar artefato, HTML/assets e HTTPS.
2. Conferir `status`, prova local, estado dos timers, locks e pending.
3. Pausar somente `election-round2.timer`, aguardar o serviço concluir, sem matar
   um processo/transação. O primeiro turno continua ativo.
4. Executar como root `deploy/scripts/install-round2.sh CHECKOUT SHA_MAIN_APROVADO`.
   O instalador mantém release/venv próprios, faz preflight oficial sem FTP,
   executa ciclo real e instala timers específicos de monitor/retention.
5. Verificar status real FTP/HTTPS, ciclo seguinte inalterado sem novo diretório,
   status público, chave Zabbix, alertas, primeiro turno e páginas financeiras.

Rollback visual usa o workflow existente com journal/backup. Se o writer anterior
à introdução do agregado precisar voltar, primeiro, com o timer do segundo turno
pausado e serviço concluído, usar o NOVO código:

```sh
python -m collector.src.second_round_runner legacy-rollback
```

Esse comando verifica publicação ativa por FTP/HTTPS e prova oficial local,
constrói o formato anterior dos MESMOS dados e usa a transação normal para
publicá-lo. Não retorna a votos antigos. Só então selecionar a release anterior
do código, reinstalar sua unidade/timer e reativar o segundo turno. Manter a
última versão íntegra se faltar prova ou houver lock/journal desconhecido.
Não remover locks manualmente nem fazer downgrade de código que não lê o formato
público ainda ativo. Nenhuma exclusão remota faz parte da migração.

No workflow visual, RNFR/RNTO usam basenames após CWD por componente e PWD
confirmado. Um timeout após rename continua sendo resultado desconhecido: a
reconciliação confere bytes em sessão nova, sem repetir STOR. A recuperação
automática só ocorre dentro do mesmo workflow serializado, para journal
`prepared` de um Actions comprovadamente terminado com falha/cancelamento/timeout,
no repositório, branch, workflow, SHA e tentativa correspondentes. Antes de qualquer
restauração, verifica todos os backups e exige que estado e HTML atuais sejam
exatamente a baseline ou candidata daquele journal. Owner ativo/desconhecido,
backup inválido ou publicação externa bloqueiam; não há adoção por idade.

## Ensaios limitados e decisão

`tools/election_hardening_probe.py` aceita somente loopback e, com `--public`,
`afgnet.com.br`: GET/HEAD, no máximo quatro sessões, 8 req/s sustentadas, burst
inicial até 64 requisições, 400 requisições totais e 90s. Interrompe em 429/5xx.
Não acessa TSE, terceiros ou métodos de escrita. Registrar burst e ritmo
separadamente: uma média baixa não comprova tolerância a picos.

`tools/election_hardening_rehearsal.py` serve o frontend real em 127.0.0.1 com
fixtures inventadas e gerações imutáveis, 429/Retry-After, usuários independentes
e medições. Limites: até 1.000 usuários, 1.800s e 55 gerações; dimensionar memória
antes de aumentar. Na app01, executar com CPU/memória limitadas em unidade própria.
Resultados de loopback não são capacidade comprovada da Locaweb nem tempo real
de atualização de votos futuros do TSE.

Metas iniciais para verificar na infraestrutura real, sob operação saudável:
publicação após dados validados até 90s; detecção no navegador visível até 15s;
primeira detecção de apuração inclui a consulta prévia de 120s e a execução.
São objetivos de teste, não garantias em falhas/rede indisponível. Produção precisa
comparar durações novas com a baseline de 97–114s da etapa de publicação.

GO exige integridade, zero 429 no perfil público documentado, recuperação
verificada e capacidade/alertas comprovados no escopo anunciado. GO COM RESSALVAS
exige limitações quantificadas e comunicação pública compatível. Usar NO-GO se
houver 429 no perfil-alvo, inconsistência ou capacidade necessária sem evidência.
O relatório final deve distinguir testes sintéticos, transporte real, observação
de dados oficiais e qualquer impedimento externo.
