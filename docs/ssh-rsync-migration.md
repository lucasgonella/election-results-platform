# Migração controlada de FTP para SSH/rsync

A missão de 16/10/2026 autoriza este transporte como exceção explícita à política
anterior de FTP. Não integra o PR 75, não altera dados oficiais, banco, aprovação
eleitoral, identidades financeiras, serviços alheios ou `/public_html/estudos`.
Código disponível não comprova transporte implantado. O relatório operacional
registra os componentes efetivamente ativados e os que continuam em FTP.

## Contrato e fronteiras

`PUBLICATION_TRANSPORT=ftp|ssh` escolhe explicitamente o transporte; o padrão
continua FTP. Valor desconhecido bloqueia. Erro SSH nunca alterna para FTP.
`deploy/ssh_transport.py` fornece I/O ao mesmo publicador e às mesmas políticas
de destinos, locks, journals, recuperação e verificação HTTPS. O atributo legado
`.ftp` contém a interface de filesystem do protocolo, sem conexão FTP em modo SSH.
Não existe um segundo writer ou mecanismo de ativação paralelo.

SSH abre um processo Python por stdio, sem daemon/porta nova no servidor.
Metadados via JSON não entram no shell; somente código fixo e constantes são
citados por `shlex`. O servidor repete validação de caminhos e recusa symlinks.
Timeouts limitam conexão, RPC, rsync e encerramento. Somente estabelecimento de
sessão e o `hello` de leitura permitem três tentativas, em conexões novas, antes
de entregar o transporte ao publicador. Falhas de home/validação não repetem.
Contadores conservam as falhas anteriores à conexão bem-sucedida.
Uma operação de escrita com
resposta perdida interrompe; o publicador consulta journal/estado real para
recuperar. Não há replay automático de ativação.

Rsync envia para `/election-ssh-staging/<escopo>/<nonce>/`, fora da raiz pública.
Objetos privados SHA-256 são verificados antes de reutilização. Lotes limitados
a 150 arquivos/64 MiB evitam uma conexão rsync por JSON. O destino público recebe
cópia em temporário exclusivo, comparação com a baseline, hash e ativação.
Não são usados `--delete`, `--inplace`, `--append`, FTP fallback ou symlinks.

O NFS observado rejeita `renameat2(RENAME_NOREPLACE)` com errno 22. Arquivos
imutáveis usam hard link exclusivo, fsync de diretório e remoção do temporário
próprio. Um arquivo final existente nunca é substituído. A preparação do primeiro
turno cria o diretório final exclusivamente e preenche somente arquivos ausentes
do inventário de 140 itens. Recibo privado vincula origem, destino e hashes;
interrupção conhecida permite retomar. Diretório existente sem recibo, extras,
symlinks ou divergência bloqueiam. O marcador continua anterior durante toda
essa preparação e só muda após os mesmos checks integrais de dados e HTTPS.
Interrupção no intervalo entre MKD exclusivo e recibo conserva um destino não
adotável: não apagar nem assumir propriedade para destravar.

As raízes existentes são preservadas: primeiro turno `/public_html/data`, segundo
`/public_html/data/turnos/2`, municipal por turno, visuais por componente.
O primeiro transporte recusa o subtree `turnos`; visuais recusam dados e o
portal recusa Goiás. Leituras dos dois locks visuais continuam compartilhadas.
Backups privados de retenção mantêm seus diretórios atuais. `ssh_archive.py`
verifica novamente TODOS os bytes baixados em blocos, além de tamanho e SHA,
antes de o procedimento existente registrar `verified` e remover um ciclo.

O ETL financeiro permanece intacto. Seu transporte SSH opcional acrescenta
backup, lock e journal em `/goias-finance-deploy`; não junta transações nem muda
identidades. `python -m deploy.ssh_finance recover --writer-stopped` verifica
backup, owner, baseline/candidata e HTTPS antes de restaurar ou concluir.
Locks sem prova, inclusive falha anterior ao journal, continuam bloqueados para
investigação. Não há remoção manual de locks.

## Identidades e host

Host fixo `afgnet1@ftp.afgnet.com.br:22`, raiz auditada
`/home/storage/4/b7/e0/afgnet1`. A chave ED25519 anteriormente confiada apresenta
`SHA256:bahZf80pWXz9IHeBZcj5bspwnZnLfDFAaKJR7Vd+qM8`.
Essa evidência é continuidade do known_hosts existente e conexão autenticada;
não constitui certificação independente do provedor. Uma rotação requer nova
validação fora de banda e revisão do pin, nunca `StrictHostKeyChecking=no`.

O `/usr/bin/python3` da hospedagem foi identificado como 3.6.8. Somente o helper
remoto é compatível com essa família; o cliente continua no Python atual da
app01/Actions. CI executa o contrato do helper em Python 3.6, sem rede nem
credenciais. Não usar APIs recentes de string/path nesse helper.

Chaves dos serviços ficam protegidas sob `/etc/election-results-platform/ssh`;
systemd entrega `locaweb_ssh_key` e `locaweb_known_hosts` por `LoadCredential`.
Na app01 essa entrega tem owner root, ACL nominativa e modo aparente 0440
(máscara ACL), dentro de diretório root 0550. O cliente aceita esse caso apenas
no caminho gerenciado `/run/credentials`, sem symlinks e sem escrita/outros;
chaves comuns continuam exigindo 0600/0400. Não se alteram ACLs do systemd.
Os usuários `electioncollector` e `electionround2` conservam identidades e
restrições. Não recebem acesso à chave pessoal de gonella. Entradas dedicadas
em authorized_keys usam `restrict`, preservando as anteriores e um backup.
Essa opção desabilita PTY/forwarding, mas não confina a conta remota a caminhos.
A conta da hospedagem continua ampla; a allowlist é proteção de aplicação,
não isolamento contra roubo da credencial ou administrador comprometido.

Em execução interativa, usar caminhos absolutos de `LOCAWEB_SSH_IDENTITY_FILE`
e `LOCAWEB_SSH_KNOWN_HOSTS_FILE`, arquivos regulares sem escrita por terceiros,
chave privada 0600/0400. Logs mostram códigos, operação e errno; nunca ambiente,
chaves, resposta arbitrária de servidor ou conteúdo eleitoral/pessoal.

## GitHub Actions

Os workflows existentes, CI e grupos de concurrency são conservados. Seleção:

| Componente | Repository variable | Padrão |
|---|---|---|
| Portal | `LOCAWEB_PORTAL_TRANSPORT` | `ftp` |
| Raio-X visual | `LOCAWEB_RAIOX_TRANSPORT` | `ftp` |
| Municipal | `LOCAWEB_MUNICIPAL_TRANSPORT` | `ftp` |
| Financeiro Goiás | `LOCAWEB_FINANCE_TRANSPORT` | `ftp` |

Somente definir `ssh` após readiness real e ausência de transação pendente.
Secrets necessários: `LOCAWEB_SSH_PRIVATE_KEY` (identidade dedicada dos runners)
e `LOCAWEB_SSH_KNOWN_HOSTS` (entrada ED25519 do host com pin verificado).
Não reutilizar a chave pessoal da app01, nem as privadas dos serviços. Chaves
temporárias do runner têm 0600 e caminhos são passados por GITHUB_ENV; nenhum
valor secreto entra em argv/logs/artefatos. Credenciais FTP ficam para rollback.

O workflow `SSH publication readiness and finance recovery` consulta estado real
por SSH/HTTPS e falha claramente sem secrets. Finance recover compartilha a
concurrency do ETL. Visuais mantêm status/recover/rollback pelo workflow original;
municipal mantém seu fluxo próprio. PR não publica. Secrets ausentes são bloqueio
de implantação, não sucesso simulado.

Rotação: gerar nova identidade específica, cadastrar a pública, validar o host
e uma operação privada, atualizar o secret/LoadCredential e observar publicação.
Só retirar a pública anterior após não existir transação pendente e terminar a
janela supervisionada de rollback; nunca retirar a chave pessoal como efeito
colateral desta migração. Revisar/revogar credenciais temporárias após a eleição.

## Corte e rollback supervisionados

1. Conferir SHA de main e CI efetivo. Instalar código root-owned por SHA, sem
   limpar/resetar o checkout de produção nem alterar seus arquivos locais.
2. Parar somente timers do componente em corte e esperar seus serviços. Não
   interromper um processo ativo. Conferir flock, journal, checkpoint, marcador,
   locks remotos e HTTPS com a identidade dedicada.
3. Resolver transação existente pelo procedimento do transporte anterior. Nunca
   trocar transporte para tentar apagar um lock ou concluir estado desconhecido.
4. Instalar drop-in com `Environment=PUBLICATION_TRANSPORT=ssh` e os dois
   LoadCredential. Preservar ExecStart, usuários, TSE_ROUND, configuração e estado.
   Monitor e retenção do turno usam o mesmo código/seleção e sua identidade.
5. Validar autenticação e ensaio privado, duas execuções supervisionadas,
   marcadores e arquivos públicos completos. Reativar timers e observar ciclos
   reais antes de declarar o componente migrado.
6. Rollback: parar timer, aguardar quiescência, consultar/reconciliar qualquer
   journal pelo SSH atual, verificar publicação e só então selecionar `ftp`.
   Manter código que compreende o formato atual. Não misturar checkpoints ou
   restaurar votos antigos por downgrade do transporte.

Não reinstalar o serviço coletor/banco para mudar I/O. Não reduzir revisões
pendentes do Amazonas/outros estados. Um ciclo inalterado confirma leitura e
verificação, não comprova nova ativação nem desempenho de publicação com votos.

Se o turno 2 estiver em backoff após falha de transporte já investigada, a CLI
oferece `cycle --retry-after-reconcile` para uma tentativa supervisionada. Ela
adquire o mesmo flock, executa recovery e exige status remoto/HTTPS verificado,
checkpoint correspondente e ausência de pending/lock antes de consultar o TSE.
Registra a prova e o prazo anterior em metrics-history, sem editar health à mão,
zerar contadores históricos ou repetir automaticamente uma escrita incerta.
Não aceita dry-run, estado rate_limited ou cadência de ciclo saudável. Uma nova
falha conserva o backoff normal. O timer não recebe essa opção.

## Ensaios e limites

`tools/ssh_rsync_benchmark.py` aceita somente destino privado UUID em
`/election-ssh-benchmark`. Pequeno, médio, release representativa, repetição e
poucas mudanças registram conexão, transferência, verificação, bytes e arquivos.
`--batch --cold` muda apenas whitespace de cópias JSON privadas para não herdar
cache de ensaios anteriores; não altera arquivos oficiais/originais. O relatório
deve distinguir cache frio/quente, ensaios sobrepostos e operações normais.

Os testes locais usam fixtures sintéticas, filesystem real, stdio real e falhas
injetadas em transferência, hash, marcador, checkpoint e promoção parcial.
Nenhum teste automatizado de CI acessa TSE, hospedagem ou credenciais reais.
Benchmarks privados reais não comprovam durabilidade física, comportamento de
todos os caches/NFS, capacidade sob alta audiência ou taxa de falhas de longo
prazo. SHA detecta corrupção observada; não autentica um host comprometido.

Objetos/journals privados e releases anteriores são retidos, sem GC destrutivo.
Monitorar espaço/quota da hospedagem e crescimento antes de uma política de
retenção futura. Transporte não configura sozinho alertas externos/capacidade.
