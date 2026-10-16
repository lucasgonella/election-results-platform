# Segundo turno de 2026: operação FTP dedicada

O pipeline usa exclusivamente `https://resultados.tse.jus.br/oficial`, ciclo
`ele2026`, turno 2. A configuração comum e os EA14 anunciam eleições/cargos/
abrangências. Governos usam a interseção explícita com a configuração; presidente
expande o Brasil pelas abrangências do próprio EA14. Não usa os 137 targets,
banco, caches, checkpoints ou proteções do primeiro turno. O PR #88 continua
experimental e não é uma dependência; o PR #75 não é integrado.

## Contrato e publicação

`second_round_collection` guarda ETag/payload somente em `http-cache` dedicado,
recusa redirects, fontes simuladas e `f != o`, valida eleição/turno/abrangência/
cargo do EA14/EA20. Todos os targets e seus candidatos precisam estar presentes.
Ausência de configuração, arquivos ou cadastro de candidatos produz
`awaiting_official_round_two_data`, exit 0, sem ativação incompleta. O cadastro
oficial completo já é publicável antes da apuração: metadados anunciam
`publication_phase=candidate_roster`, e o portal mostra nomes/números/partidos,
com “Aguardando apuração” em vez de votos e percentuais. Zero seções exige votos
zero e nenhum eleito. Quando o TSE totaliza seções, a fase passa automaticamente
a `counting`; localidades ainda zeradas continuam com a indicação de espera.

O timestamp de captura é fixado na geração oficial para identidade determinística;
a hora real da coleta fica na prova privada e no health. SHA-256 de cada arquivo,
tamanho e inventário canônico determinam o ID SHA-256 da release. A prova privada
retém configuração, EA14 e EA20 e é reprocessada antes da publicação. Os hashes
protegem integridade de transporte, não autenticam um administrador comprometido.

Todos os destinos públicos são `/public_html/data/turnos/2/releases/<sha256>` e
`/public_html/data/turnos/2/version.json`. Nenhuma operação escreve o marcador
`/data/version.json`, o Raio-X ou estudos. Metadados privados de transporte ficam
em `/election-round2-deploy`, fora de `public_html`. Diretórios privados usam
um prefixo de 24 caracteres do ID; o descritor conserva e valida o ID completo.
Colisão de prefixo com bytes diferentes bloqueia sem sobrescrever. A criação
de diretórios usa CWD por componente e MKD do basename: no ensaio Locaweb, MKD
com caminho absoluto longo não respondeu, mas o mesmo destino por basename
foi criado em 0,04s. A sessão volta a `/` antes dos demais comandos. Credenciais existentes são
reutilizadas sem cópia permanente: systemd `LoadCredential` lê o `ftp.env`
protegido. FTP convencional, passivo, porta 21; os JSONs eleitorais pequenos reutilizam
uma sessão PassiveFTP/Transport, como o escritor vigente do primeiro turno,
sem secrets em argv. O transporte visual curl permanece inalterado. HTTPS
somente GET. O adaptador curl isolado serve a ensaios e usa netrc temporário 0600.

O journal local é substituído com fsync antes do lock MKD exclusivo. O flock
local serializa ciclo, recuperação e operações manuais nesta app01. O lock remoto
contém owner aleatório vinculado ao journal. Só o writer confiável desta app01
pode recuperar automaticamente o seu lock após obter flock. Outra app01/estado
não adota o owner nem rouba locks por tempo. O deploy deve manter um único writer.

Cada arquivo novo é STOR temporário → RETR/hash → rename → RETR. Release existente
não é sobrescrita. Temporários parciais de um journal conhecido podem ser
reconciliados; colisão em arquivo final interrompe. O manifesto é verificado e
todos os arquivos são comparados por FTP e HTTPS antes de trocar o marcador.
Uma nova leitura FTP/HTTPS confirma a baseline imediatamente antes da troca.
O marcador é renomeado sobre o anterior, nunca apagado previamente. Confirmação
HTTPS da seleção e de todos os arquivos precede recibo e checkpoint. Releases
anteriores, journal e marcador anterior são preservados; não há garbage collection.

FTP rename não garante atomicidade global, propagação simultânea de caches,
durabilidade física ou exclusão de writers externos. Divergência FTP/HTTPS é
resultado desconhecido: a execução não repete ativação. A conta FTP continua
ampla, sem confinamento novo, PHP, HMAC ou alteração de gates de isolamento.

## Instalação e configuração

Após PR, CI aprovado no SHA e merge na main, na app01:

```sh
sudo deploy/scripts/install-round2.sh "$PWD" SHA_MAIN_APROVADO
```

O instalador recusa SHA diferente da main, preserva o usuário e serviços do
primeiro turno, instala código root-owned por SHA em `/opt/election-round2`,
venv separado, usuário `electionround2` sem login, configuração `round2.env`
root:group 0640 e estado `/var/lib/election-round2` 0700. O serviço limita CPU
25%, memória 384 MB, duração 20 min e grava journald. `ProtectSystem=strict`
e `StateDirectory` restringem escrita local. O instalador faz preflight sem FTP
em um subdiretório separado, executa um ciclo real e somente então habilita timer.
Não instalar um segundo writer do mesmo namespace em outra máquina.

Timer: 60 segundos após conclusão, jitter até 10s. Cadastro anterior à apuração ou ausência de dados faz nova
consulta após 300s. 429 respeita Retry-After limitado a 60–3600s; falhas de rede
usam backoff exponencial limitado a 3600s, sem replay imediato de STOR/ativação.
Não há retentativa dentro de uma execução que ignore journal. A execução seguinte
reconcilia transação anterior antes de consultar dados novos. Configuração e
coleta usam os valores oficiais fixos no código; não dependem da configuração do
primeiro turno.

Leituras FTP (`MLST` e `RETR`) possuem um único orçamento de três tentativas.
Timeout, reset, EOF e encerramento 421 substituem a sessão antes da próxima
leitura; bytes parciais são descartados. Não há retentativa de STOR, rename ou
ativação. Erros permanentes, arquivos inválidos e divergências de integridade
continuam bloqueando. Falha nas três leituras mantém o backoff do ciclo.

## Status e saúde

```sh
systemctl status election-round2.timer election-round2.service
journalctl -u election-round2.service --since '-20 minutes' --no-pager
sudo systemd-run --wait --collect --unit=election-round2-status \
  --property=User=electionround2 --property=WorkingDirectory=/opt/election-round2/current \
  --property=LoadCredential=ftp.env:/etc/election-results-platform/secrets/ftp.env \
  /opt/election-round2-venv/bin/python -m collector.src.second_round_runner status
sudo -u electionround2 sh -c 'cd /opt/election-round2/current && /opt/election-round2-venv/bin/python -m collector.src.second_round_runner health'
```

`status` lê o estado remoto real e confere todos os hashes e HTTPS; não muda
checkpoint. `health` verifica informação recente (900s) e retorna exit 2 em erro.
`health.json`, `http-cache`, `cycles/*/source-proof.json`, `pending.json`,
`journals`, `receipts` e `checkpoint.json` ficam no estado dedicado. Somente uma
publicação confirmada escreve checkpoint. Enquanto não há pacote oficial completo, checkpoint ausente é
normal. Um cadastro oficial completo publicado já tem recibo e checkpoint, mesmo
antes de haver votos apurados. Não existe notificação externa configurada; journald/health são auditáveis.

## Recuperação

A execução normal recupera automaticamente transação conhecida com lock de owner
correto. Operações `recover` e `reconcile` usam o mesmo flock. Para operação
supervisionada, pare **apenas** `election-round2.timer`, espere a unidade terminar
e use o comando systemd-run acima substituindo `status` por `recover` ou
`reconcile`. Depois de exit 0 e status íntegro, reative somente esse timer.

- Marcador anterior: conferir a release anterior, completar arquivos conhecidos,
  validar FTP/HTTPS e só depois ativar a candidata.
- Marcador novo: verificar release/HTTPS e concluir recibo/checkpoint; não repetir
  rename. Isso cobre falha após ativação ou durante escrita do checkpoint.
- FTP/HTTPS discordantes ou timeout: manter journal/lock e aguardar visibilidade;
  nunca inferir resultado pela mensagem da transferência.
- Marcador externo, bytes corrompidos, pacote/prova modificados, regressão de
  totalização, revogação de eleito ou mudança de elenco: falhar fechado; preservar
  seleção anterior e interromper somente o pipeline do turno 2 para investigação.
- Lock sem owner confiável/journal, incluindo interrupção no intervalo MKD→owner:
  bloquear. Não remover cegamente. Confirmar todos os writers inativos e obter
  evidência do proprietário antes de uma reparação supervisionada. Não há comando
  de force-unlock. A ausência dessa prova é bloqueio real de segurança.

`publish --directory PACOTE` exige prova oficial privada adjacente; `verify`
reprocessa essa prova offline. Nunca fornecer fixture nesse comando de produção.
Todos os testes de dados sintéticos usam mocks, FTP loopback ou o namespace de
staging separado. O frontend fixa `/data/turnos/2/releases/<id>` após marcador
válido; enquanto 404, informa espera e não busca os arquivos do primeiro turno.

## Hardening para 25/10

A política de coleta, publicação, retenção, métricas e monitoramento atualizada
está em [hardening de produção](election-2026-hardening.md). Ela substitui os
intervalos e limites descritos anteriormente neste documento. Releases antigas
continuam legíveis; rollback de código anterior ao agregado exige a conversão
verificada `legacy-rollback`, preservando exatamente os dados oficiais ativos.
