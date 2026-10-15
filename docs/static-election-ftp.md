# Publicação estática eleitoral por FTP 21

Decisão do responsável em 11/10/2026: este fluxo substitui, na janela de corte,
o publicador eleitoral parado. Usa a credencial FTP existente, passivo, porta 21,
sem TLS. **Não usa HMAC, controlador PHP, aprovação de isolamento ou certificação
NFS multinó.** Essas propriedades não são declaradas como proteção residual.
O protocolo anterior do PR #75 fica separado; seus gates não são falsificados.

## Componentes e efeitos

- `election_release.py`: validadores e builder completo adaptados do PR #75,
  sem importador de chaves ou assinatura. Exige 137 caminhos fixos e três
  metadados, JSON sem chaves duplicadas, identidade eleitoral, contagens,
  candidatos/votos/percentuais/status, geração e metadados consistentes.
- `static_election_publish.py`: transporte eleitoral delimitado, backup integral,
  preparação, verificação, seleção por marcador, rollback e recover.
- `static_election_runner.py`: único escritor app01, checkpoint separado e
  diretórios novos por coleta. Preserva integralmente `/live/state`, `pending`
  e `stage`; não reutiliza o prepare destrutivo nessa raiz.
- `publication_health.py`: GETs públicos, data da publicação confirmada e da
  última coleta concluída, falhas e alterações aguardando revisão.

O transporte reutiliza `deploy.frontend.Transport`, `PassiveFTP` e `connect` da
main, com uma conexão persistente para os JSONs pequenos. O módulo e os workflows
visuais/financeiros permanecem byte a byte iguais à main.
O novo escritor só escreve os namespaces abaixo; não aceita dados como artefato
visual. Não instala PHP, transfere segredo ou consulta o receptor HTTPS legado.

| Uso | Produção FTP | Staging FTP |
| --- | --- | --- |
| Release selecionável | `/public_html/data/releases/<id>` | `/public_html/__election_static_staging/data/releases/<id>` |
| Marcador final | `/public_html/data/version.json` | `/public_html/__election_static_staging/data/version.json` |
| Backup/journal/preparação/lock | `/election-static-deploy/production` | `/election-static-deploy/staging` |

FTP PWD deve continuar `/`, equivalente à home já auditada. Uma mudança desse
mapeamento bloqueia o cliente. Não usar `LOCAWEB_FTP_GOIAS_DIR`. Credenciais
somente do arquivo protegido existente/EnvironmentFile; nenhum segredo em argv,
URL, stdout, relatório ou Git. O controle FTP usa login sem imprimir credenciais;
erros do publicador são sanitizados.

## Contrato e comparação

Uma release tem exatamente 140 JSONs; seu ID é SHA-256 do inventário canônico
com tamanho/hash de cada arquivo, ambiente, turno e geração. O marcador final
contém snapshot_id; leitores usam `/data/releases/<snapshot_id>/<resultado>`.
Os três metadados da release têm a mesma geração e ambiente. Manifest corresponde
aos JSONs selecionados, incluindo candidatos e IDGs, não ao pending excluído.

IDG maior sozinho não aprova alterações. O comparador exige identidade igual,
data de fonte sem regressão, ausência de reabertura de totalização e de revogação
de eleito. Mudança de elenco/status/atributos de candidato ou fonte AM requer
revisão explícita vinculada ao hash do arquivo. `--reviews` é um mapa local
`{path: sha256}` aprovado pelo responsável; não é assinatura ou autenticação.
Automação retém mudanças ambíguas na baseline e registra `review-required.json`
em cada ciclo. Esses dados não são alterados manualmente. Mudanças admissíveis
de votos passam pelas validações completas; nenhuma ambiguidade desaparece do
relatório de saúde. AM não é aprovado implicitamente pela publicação do RJ.

## Publicação, falha e recuperação

1. Parar/confirmar inatividade do timer e todos os escritores eleitorais legados.
   O novo MKD coordena só clientes deste mecanismo; não controla editores externos.
2. Congelar e validar candidata/checkpoint e plano de revisão. Conferir frontend
   ativo que fixa snapshot_id, marcador/140 hashes e backups locais do live/código/
   unidades. Nunca apagar originais para desbloquear o corte.
3. MKD exclusivo do lock eleitoral. Sem expiração nem roubo de lock.
4. Ler e verificar integralmente a baseline por FTP e HTTPS. Comparar candidata e
   watermarks. Fazer backup completo privado dos 140 bytes/hash e do marcador.
5. Salvar journal/pending, entregar 140 arquivos em staging privado, por
   temporário/STOR/RETR/hash/rename. Reconciliar resposta de FTP perdida pelo
   transporte existente. Nenhum resultado público individual é substituído.
6. Conferir novamente os 140 arquivos. Renomear o diretório completo para a
   release imutável, conferir FTP e **140 GETs HTTPS antes de selecionar**.
   Falha de rename não usa delete do destino nem fallback para JSONs avulsos.
7. Conferir marcador anterior contra escritor externo e renomear o temporário
   do marcador sobre o atual. Nunca remover primeiro o marcador.
8. GET do marcador, 140 arquivos por HTTPS e novo GET do marcador; conferir
   bytes/hash e validações eleitorais. Registrar timestamp de confirmação,
   journal/current/watermarks. Só então adotar checkpoint local separado.

```text
python -m collector.src.static_election_publish verify --directory CANDIDATA
python -m collector.src.static_election_publish publish --directory CANDIDATA --reviews REVISOES --report RELATORIO
python -m collector.src.static_election_runner adopt --package PACOTE_COMPLETO
```

Caso o cliente interrompa, o lock/pending/journal e todos os releases ficam
preservados. **Parar o writer e confirmar quiescência**, depois:

```text
python -m collector.src.static_election_publish recover --writer-stopped --report RELATORIO
python -m collector.src.static_election_publish rollback --report RELATORIO
python -m collector.src.static_election_runner reconcile --writer-stopped
```

Recover restaura somente a baseline do journal, após verificar os 140 backups e
a release retida; recusa marcador externo. Se a interrupção ocorreu antes de
journal, também exige `--expected-snapshot ID_ANTERIOR` e verifica os 140 públicos.
Rollback verifica a seleção corrente e usa o backup/journal anterior. Watermarks
nunca são reduzidos; uma nova candidata deve alcançar o máximo já publicado.
Não limpar release, estado ou temporário desconhecido automaticamente.
Falha depois da seleção e antes de commit local pode exigir recuperação remota
ou confirmação completa do job antes de `reconcile`; nunca iniciar outra coleta
com um job ainda não reconciliado. Rollback remoto requer manter o timer parado
e reconciliar explicitamente o checkpoint anterior antes de nova coleta.

Se a tentativa não selecionou sua candidata, `reconcile --writer-stopped`
também reconhece a baseline já adotada: exige ausência de lock remoto, journal
`complete`/`restored` para a mesma baseline, checkpoint/descritor correspondentes,
140 arquivos idênticos por FTP/HTTPS e watermarks válidos. Confere novamente
marcador e metadados antes de concluir o job local. Preserva a candidata, o job
original, checkpoints, watermarks e data da última coleta. Não publica o pacote
interrompido nem transforma a verificação em uma coleta nova. Estados externos,
pendentes ou inconsistentes continuam bloqueados; a próxima coleta constrói
uma candidata nova pelos controles eleitorais existentes.

## Automação e monitor

Instalar a revisão com CI aprovado em diretório isolado app01, reutilizando venv
e o arquivo `/etc/election-results-platform/secrets/ftp.env`. O override exemplo
substitui ExecStart da unidade existente; não cria outro writer. Backup dos
drop-ins legados antes da instalação. EnvironmentFile e ownership existentes
devem ser preservados. Fixar WorkingDirectory no SHA instalado tanto no publisher
quanto no monitor. Não apontar o monitor ao checkout antigo de /opt.

Estado novo: `/var/lib/election-results-platform/static-ftp`; ciclos e gerações
retidos. Coleta só acontece em árvore nova de cada ciclo. Não sobrescrever o
pending/stage original. O ciclo compara e publica somente alterações admissíveis,
com todos os 137 preservados/selecionados e três metadados reconstruídos.
Quando nada mudou, verifica a release atual e registra coleta concluída sem
inventar uma nova publicação. `health.json` registra published_at, collected_at,
public_verified_at, último erro e itens em revisão; alertas não dependem da
idade da fonte de um resultado que já está finalizado.

Após corte confirmado, executar dois ciclos supervisionados antes de habilitar
o timer, e observar novos ciclos automáticos. Intervalo proposto 60s após cada
conclusão, limite 15min por serviço. Monitor a cada 5min, limite de atraso 900s,
exit 2 e journal/estado failed em falha ou revisão pendente. Não há webhook ou
destinatário externo configurado; notificação remota requer canal operacional.
Backups e releases anteriores permanecem disponíveis. A retenção local de ciclos
segue o procedimento de arquivamento verificado abaixo.

## Retenção e limite de armazenamento

`cycle_retention` compartilha `runner.lock` com o único publicador. O padrão é
dry-run, sem conexão FTP. A aplicação exige `--apply`; o serviço horário processa
até 100 ciclos com pelo menos 24 horas. Uma execução concorrente é adiada.

```text
python -m collector.src.cycle_retention --root /var/lib/election-results-platform/static-ftp
python -m collector.src.cycle_retention --apply --min-age-hours 24 --limit 100
```

A seleção lê recursivamente referências em registros JSON de controle,
aprovações, reconciliações e recuperações. Preserva todos os pacotes de
publicação/rollback, todas as gerações, ciclos incompletos/desconhecidos, ciclos
recentes e a última evidência de cada fonte/motivo distinto de revisão. Idade
ou presença de `review-required.json` isoladamente nunca autoriza exclusão.
Registros inválidos bloqueiam a limpeza. Symlinks e arquivos desconhecidos não
são arquivados. Somente saídas conhecidas do coletor entram nos arquivos.

Cada ciclo elegível é compactado individualmente, conferido contra o inventário
original e enviado por FTP passivo 21 ao diretório privado
`/backup/election-results-platform/ftp-cycles`, fora de `/public_html`. Não existe
fallback público. O arquivo temporário remoto e o arquivo renomeado são baixados
e comparados por tamanho e SHA-256. Um manifesto remoto imutável também é
conferido. O journal local `archive-manifest.jsonl` recebe um registro `verified`
com fsync antes da remoção e um registro `deleted` depois dela. Referências e
todos os hashes locais são conferidos novamente antes de remover o original.
Uma falha mantém o original e a próxima tentativa verifica arquivos remotos já
existentes. Não se repetem operações de publicação para contornar erros de FTP.
O processamento padrão mantém um único arquivo temporário; `--workers 2` ou
`--workers 3` permite lotes pequenos na recuperação inicial de espaço.

Coletas agora usam um workspace temporário separado. Apenas uma alteração
elegível preserva o ciclo completo, antes de qualquer escrita FTP. Revisões novas
preservam os JSONs propostos, metadados e motivos em um ciclo compacto. A mesma
fonte e baseline reutilizam a evidência, sem acumular cópias por captura. Um poll
sem mudanças, inclusive respostas 304, não cria ciclo persistente. Essa política
não aprova revisões nem adota checkpoints de resultados retidos.

O override de produção fixa uma reserva de 2 GiB e teto local de ciclos de
4 GiB (`ELECTION_MIN_FREE_BYTES`, `ELECTION_CYCLE_MAX_BYTES`). O espaço livre é
conferido antes de toda coleta; o uso de ciclos é amostrado a cada cinco minutos.
O limite bloqueia nova coleta e preserva o espaço para estado/recuperação. Avisos
começam a 80% do teto ou abaixo de 1,5 vezes a reserva, em `storage.json`, journal
e monitor. Falhas não provocam exclusão sem backup. Pacotes/gerações protegidos
podem exigir intervenção ao atingir o teto. Nenhum destinatário externo de
alertas foi configurado.

Instalar `election-cycle-retention.service` e `.timer`, fixando o WorkingDirectory
na mesma release aprovada do publicador. Manter o timer do publicador parado
durante a recuperação inicial. Executar os fluxos oficiais de recover/reconcile
para jobs interrompidos, sem remover `in-flight.json`. Depois verificar dois
ciclos supervisionados antes de reativar o timer e observar ciclos automáticos.
Os logs resumem revisões por quantidade; saúde e evidências mantêm os detalhes.

FTP mantém controle com timeout de 15s e permite até 60s no socket de dados.
GETs HTTPS públicos repetem somente falhas transitórias, até três tentativas,
descartando bytes parciais. Redirecionamentos, corrupção e divergências de hash
continuam bloqueantes. Ativação incerta continua exigindo recuperação explícita.

## Garantias e limites declarados

Os checksums detectam bytes diferentes e falhas de transmissão observadas; não
autenticam conteúdo frente a atacante que controle a credencial/servidor. FTP
sem TLS transmite senha/conteúdo sem criptografia. A conta continua ampla.
HMAC, confinamento e autenticação de controlador não existem neste novo fluxo.

O único ponto de seleção é rename do marcador sobre arquivos já verificados;
isso evita os 137 uploads diretos no caminho selecionado. Ensaios precisam
comprovar que o servidor aceita RNTO sobre o marcador existente e que leitores
observam JSON antigo/novo completos no endpoint testado. Não declarar transação
global multinó, visibilidade simultânea em caches, exclusão de writers externos
ou durabilidade física NFS. Se o servidor não aceitar a troca sem remover o
marcador, manter baseline e parar a ativação. A alternativa mínima exige rename
do servidor/ativador de marcador provido pela hospedagem, sem upload HTTPS.

Staging real usa somente fixtures sob os namespaces exclusivos acima; não
induzir falha física no NFS nem realizar teste destrutivo em produção. A decisão
do responsável dispensa a certificação multinó como gate, não cria essa garantia.
