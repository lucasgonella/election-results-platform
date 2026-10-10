# Etapas 9 e 11 — plano de staging real

Complemento do runbook, revisão base 3e8bb1f / PR #75. Não autoriza execução
remota. Preserva arquitetura, serviços, pending e watermarks.

## Evidências e solução de isolamento

Evidência anterior: FTP `/` mapeia à home `/home/storage/4/b7/e0/afgnet1` e
alcança chave HMAC e PHP; NFS usa `nolock,local_lock=all`. Nesta sessão SSH
resolve para bloqueador local `.sbx-denybin/ssh.bat`; API GitHub encontra proxy
indisponível. Não se confirmou novamente plano contratado, painel ou environments.

A [documentação oficial de FTP Multiusuário](https://www.locaweb.com.br/ajuda/wiki/como-administrar-ftp-multiusuario-hospedagem-de-sites/)
prevê permissões por usuário nos planos II/III, em **Arquivos e FTP → Criar
Usuário de FTP**, com campo Diretório. O tutorial orienta deixá-lo vazio;
não comprova chroot, confinamento ou disponibilidade neste contrato.
O [SSH documentado](https://www.locaweb.com.br/ajuda/wiki/como-utilizar-o-ssh-hospedagem-de-sites/)
reutiliza usuário/senha FTP; não presumir separação de identidades.

Solicitação humana ao provedor, sem credenciais:

1. Confirmar plano, FTP Multiusuário e restrição a diretório privado externo ao
   document root, incluindo caminhos absolutos, `..`, symlinks e aliases.
2. Confirmar se a conta existente pode ser confinada sem afetar SSH/PHP/Goiás,
   com namespace virtual contendo exclusivamente destinos aprovados.
3. Confirmar UID efetivo, acesso PHP à inbox, quota/inodes, topologia NFS/FPM e
   afinidade a um host identificável. Não enfraquecer modos existentes.

Decisão da etapa 11: usar exclusivamente a conta FTP existente, sem nova conta,
troca de plano ou contratação adicional. As alternativas antes discutidas estão
descartadas. Usar os secrets e arquivos de credenciais atuais, sem duplicação.
O acesso amplo e a ausência de isolamento permanecem registrados. Pode-se
confirmar com o provedor a restrição da própria conta, sem mudar permissões da
chave/configurações nem afetar SSH/PHP/Goiás; não presumir que isso seja suportado.
Mover apenas HMAC não protege PHP modificável pelo transporte. O uploader
eleitoral continua recusando acesso ao controle; aceite do risco não habilita gates.

O [plano da etapa 11](ftp-existing-account-plan.md) define destinos, configurações,
diagnóstico sintético preparado, aprovação específica de escrita e recuperação.

Aceitação: confirmação do provedor, mapa real e negação MLST/CWD para toda área
de controle/PHP, sem leitura de conteúdo; revisão de traversal/links pelo provedor.
550 é necessário, mas não prova suficiente. Não usar STOR em área protegida.

## Layout proposto — depende de confirmação/provisionamento autorizado

```text
/home/storage/4/b7/e0/afgnet1/
  ftp-inbox/elections/staging/             # transporte eleitoral
  ftp-inbox/code/staging/                  # artefatos de código
  ftp-staging-pr75/                        # fora do public_html atual
    .election-publisher/                  # config, HMAC fixture, nonces
    private/                             # estado, journals, recibos, probe
    backups/                             # checkpoint de fixture
    public/api/election-ftp-control.php   # pacote autossuficiente existente
    public/data/releases/                # somente resultados sintéticos
    public/probe.php
    public/probe-marker.json
```

Uma rota HTTPS isolada no serviço contratado existente deve apontar somente para
`ftp-staging-pr75/public`, se o provedor confirmar suporte e houver autorização;
não contratar serviço nem criar vhost automaticamente. Confirmar ausência de
aliases expondo privados. O endpoint calcula sua configuração como
`dirname(__DIR__,2)/.election-publisher`: respeitar essa profundidade.
PWD/caminhos FTP após confinamento ainda desconhecidos. Para código o caminho
deve terminar em `code/staging`, conforme validação existente; não retirar o gate.

Preparação local, diretórios novos, sem rede:

```powershell
.venv\Scripts\python.exe deploy/scripts/prepare-ftp-staging.py --output ftp-staging-pr75-local
.venv\Scripts\python.exe deploy/scripts/ftp-code-artifact.py package --component control --directory ftp-staging-code-local
```

Revisar hashes do `transfer-manifest.json`. Ele exclui a configuração local com
chave descartável; não transferir árvore inteira, spool, credenciais ou chave
real. O inventário não substitui entrega assinada nem implementa uploader.
Enviar somente material aprovado pelo transporte existente após isolamento;
instalar localmente na hospedagem por cópia dos arquivos já recebidos via FTP,
usando o plano de código existente. SSH não deve transportar uploads.

Comandos futuros na Locaweb, **somente após autorização específica**:

```sh
set -eu
stage_root=/home/storage/4/b7/e0/afgnet1/ftp-staging-pr75
test ! -e "$stage_root"
test ! -L "$stage_root"
umask 077
mkdir "$stage_root"
mkdir "$stage_root/.election-publisher" "$stage_root/private" "$stage_root/backups"
mkdir "$stage_root/public" "$stage_root/public/api" "$stage_root/public/data"
mkdir "$stage_root/public/data/releases"
```

Inboxes/ACL e travessia FPM devem ser configuradas pelo provedor conforme identidade
confirmada; não há comando universal seguro para este plano. Não aplicar chmod
recursivo. Instalar helper do probe em private e probe em public. Gerar chave
fixture no servidor, arquivo novo protegido, sem imprimir conteúdo; não transferir
a chave local ou real. Configurar `private/staging-config.json` com fixture_only=true,
environment=fixture, root remoto exato e fixture_key nova.

Configuração do controlador em `.election-publisher/ftp-config.json`:

```json
{
  "enabled": false,
  "environment": "fixture",
  "round": 1,
  "activation_host": "HOST_FPM_CONFIRMADO_PELO_PROVEDOR",
  "public_root": "/home/storage/4/b7/e0/afgnet1/ftp-staging-pr75/public",
  "site": "/home/storage/4/b7/e0/afgnet1/ftp-staging-pr75/public/data",
  "private": "/home/storage/4/b7/e0/afgnet1/ftp-staging-pr75/private",
  "inbox": "/home/storage/4/b7/e0/afgnet1/ftp-inbox/elections/staging"
}
```

O endpoint lê chave hexadecimal de 32 bytes em `.election-publisher/hmac.key`;
usar somente fixture nova. Não chamar endpoint antes de autorização: enabled=false
não evita escritas de nonce/lock em chamadas autenticadas. Não instalar runner ou
timer do app01 para ensaiar staging.

## Ensaios supervisionados e recuperação

| Ensaio | Autorização | Critério verificável |
| --- | --- | --- |
| stat/mount/identidade/quota/vhost | Leitura | UID, FS, quota, root e host documentados, sem segredos |
| Probe runtime CLI e web | Web exige autorização de ensaio | FPM/host/OPcache registrados; CLI não comprova FPM |
| Locks de dois processos | Escrita fixture | Um adquirido e outro publication_busy |
| Hosts distintos identificados | Escrita fixture | Gate rejeita host errado antes de estado; afinidade comprovada |
| Rename A/B com leitores em todos os nós | Escrita fixture | Apenas JSON íntegro A/B; latência de visibilidade medida/aprovada |
| HTTP cache e OPcache | Escrita fixture + leitura HTTP | Headers/Age/ETag e código/marker corretos por nó; sem reset global |
| FTP interrompido/truncado/hash errado | Escrita inbox fixture | Sem ativação, marker anterior preservado |
| Completa 137, delta, reenvio/resposta perdida | Escrita fixture | 140 hashes, idempotência, recibo e ack local corretos |
| Falha pré-ativação/concorrência/rollback | Escrita fixture | Uma ativação; última release íntegra preservada/restaurada |

Usar ações existentes `runtime`, `lock`, `replace_a`, `replace_b`, `read`.
CLI futuro: `/usr/bin/php8.4 "$stage_root/public/probe.php" runtime`.
Web probe assina timestamp + newline + body; controlador assina timestamp +
nonce + body. Cliente deve ler chave protegida, sem argumentos com valores,
tracing ou logs de headers. Não executar pytest contra produção. Múltiplas
requisições ao mesmo nó não comprovam multinó; exigir destinos fornecidos pelo
provedor. Backup de fixture fica privado, fora do FTP/document root, contendo
marker, releases, configuração protegida e journal. Recuperar usando rollback
existente e verificar 140 hashes/137 resultados; não limpar remotamente nesta etapa.

## GitHub e ações externas exatas

Leitura futura em sessão com acesso permitido:

```sh
gh api repos/lucasgonella/election-results-platform/environments
gh api repos/lucasgonella/election-results-platform/environments/staging
gh api repos/lucasgonella/election-results-platform/environments/production
gh secret list
gh pr checks 75
```

Administrador deve confirmar environments, reviewers de production, branch main,
actions:read do preflight e disponibilidade das proteções no plano. Configurar
LOCAWEB_FTP_CODE_INBOX_DIR distinto por environment e aprovação de isolamento false
até certificação. Reutilizar os três secrets existentes. Não mexer em variável
Goiás. Caller main-only permanece; ensaio do PR usa artefatos revisados e
provisionamento autorizado separado, sem relaxar proteção de branch.

| Bloqueio | Estado | Dependência e ação para liberação |
| --- | --- | --- |
| Caminhos/inboxes | PENDENTE | Locaweb confirmar mapa e provisionar destinos autorizados |
| Isolamento | IMPEDITIVO | Provedor aplicar confinamento certificado e comprovar ausência de escape |
| FPM/NFS/cache | IMPEDITIVO | Provedor informar topologia; responsável autorizar ensaios acima e aprovar resultados |
| GitHub environments | PENDENTE | Administrador confirmar proteção, vars e acesso ao preflight |
| Amazonas | IMPEDITIVO para dados | TSE/TRE-AM esclarecer oficialmente reabertura/reprocessamento ligado aos IDGs documentados e alterações de eleitos/vagas |

AM: faltam ato ou explicação oficial específica e vínculo às gerações federal e
estadual. Leiaute EA20 e 100% de seções não justificam s→n. Preservar pending,
watermarks e gate; a dúvida não impede staging com fixtures.

**BLOQUEADO para corte.** O plano local não demonstra capacidade não verificada
do contrato nem representa autorização de provisionamento.

## Componentes preparados na retomada

`probe-ftp-staging.py reconcile` faz apenas MLSD/RETR do namespace fixo,
confere tamanho e SHA-256 e distingue part pendente, rename confirmado,
diretório vazio e inventário ambíguo. Não repete upload nem remove evidências.
O upload recusa namespace não vazio mesmo se o servidor aceitar MKD.

`probe-ftp-web.py plan` não usa rede ou credenciais. `observe` consulta
runtime/read e o marcador sintético; `exercise` requer aprovação explícita
do namespace `/home/storage/4/b7/e0/afgnet1/ftp-staging-pr75` e host esperado.
Usa chave exclusiva da fixture em arquivo protegido, nunca a chave real.
Exige PHP-FPM, respostas de controle no-store, recusa redirects e verifica
GET normal e GET com cache busting. Disputa dois locks, alterna A/B e restaura
o marcador inicial inclusive após falha. A aprovação deve incluir esses
locks/escritas de fixture e sua recuperação; o cliente não autoriza execução.

O gerador fixa `activation_host` inicialmente ao host de preparação: ajustar
ao hostname real de FPM antes da instalação autorizada. O probe PHP recusa
mutação sem esse host ou em outro host. Leituras permitem observar diferenças
entre processos; isso não comprova locks NFS multinó.

Testes locais dos dois clientes: 42 aprovados, sem rede. Quatro regressões PHP
adicionais verificam recusa antes de modificar marker/estado; dependem do CI
Linux. PHP, Node e Bash não foram validados localmente nesta retomada. A suíte
completa e o CI precisam validar a nova revisão antes de qualquer conclusão.

A [análise da fronteira de confiança](ftp-trust-boundary.md) descreve a menor
restrição necessária na conta existente, incluindo possíveis acessos SSH.
Nenhum gate de isolamento, corte ou Amazonas foi alterado.

## Etapa 12 — primeiro ensaio delimitado

Na etapa 12, o GitHub confirmou `a92e184` como HEAD do PR draft e sucesso de
CI, FTP publication validation e Validate HTTPS publisher. Os jobs FTP em
Python 3.13/3.14 concluíram pytest, PHP/Bash, Node e sintaxe/integridade.
Esses checks não cobrem as alterações locais adicionais descritas abaixo.

Inventário FTP atual somente leitura: PWD `/`, MLSD da raiz com 28 entradas,
nenhuma `ftp-inbox`; MLST dos três pais staging e do namespace do ensaio
retornou 550. Isso não transforma 550 em prova universal de inexistência:
revalidar inventário e exigir criação exclusiva antes de escrever.
O destino definido continua `/ftp-inbox/elections/staging/ftp-staging-pr75-etapa11`,
fora de `/public_html`, `/data`, releases, PHP e controle privado.

Preparado localmente o arquivo sintético fixo de 67 bytes, SHA-256
`3fe5cb9e5b0a17af1bb7f7a7730b47f1c31c560b678345804bfe011a9777d585`.
O plano para aprovação inclui apenas os pais ausentes `/ftp-inbox`,
`/ftp-inbox/elections`, `/ftp-inbox/elections/staging`, a folha exclusiva,
STOR `.part`, RETR/hash, rename no mesmo diretório e RETR/hash.
Limpeza pode ser aprovada junto ao ensaio, explicitamente: conferir inventário
e bytes, remover somente os dois nomes sintéticos presentes e a folha;
conservar os pais. Arquivo extra, link, colisão ou hash divergente impede a
limpeza. Interrupção exige reconciliação somente leitura, sem repetir upload.
Essa descrição não constitui autorização nem registra execução de escrita.

O cliente registra somente verbos, códigos FTP e tempos de resposta, inclusive
login negado; argumentos USER/PASS e mensagens brutas não entram na evidência.
Tempos de códigos preliminares/finais são medidos desde o comando emitido,
não representam latência isolada de disco ou throughput. Diagnóstico somente
leitura mediu 2,76 segundos totais, login 230, MLSD/RETR 125/226 e MLST 250/550.
Hashes de cinco arquivos públicos (marker, HTML e três JS) foram preservados
para comparação antes/depois do futuro ensaio; isso cobre esses arquivos,
não constitui inventário integral de toda a hospedagem. O limite de escrita
por comandos/caminhos é a proteção principal do ensaio.

O probe PHP preparado passou a informar UID/GID efetivos quando POSIX está
disponível, raiz da fixture e `/proc/self/root` quando legível, sem expor
configuração ou chave. Não foi instalado. Uma regressão PHP verifica que
`runtime` não cria estado privado; aguarda Linux. Os dois clientes somam
46 testes locais aprovados; sintaxe Python e diff check aprovados. Nenhuma
mudança de serviço, timer, banco, gates, pending ou watermarks.

SSH local resolve para bloqueador do ambiente; app01/FPM não foram novamente
inspecionados. UID 542178 e NFS v3 nolock/local_lock=all/nocto são evidências
anteriores, não confirmação atual. GET dos arquivos estáticos via HTTPS e
consulta de environments via gh falharam na rede local; cache HTTP atual,
OPcache, raiz efetiva FPM, topologia e proteções GitHub seguem desconhecidos.
O runner continua opt-in no código, valida gates antes de tocar state/TSE,
preserva entrega pendente e reconcilia recibo antes de confirmar state. Isso
não comprova o estado das units instaladas no app01 nesta etapa.

Primeiro upload e limpeza aguardam autorização específica. Instalação e
ensaios FPM/NFS/cache usam outra aprovação, com rota HTTPS e host reais
confirmados. Transporte aprovado não certificará isolamento ou produção.

### Resultado do ensaio autorizado

Após confirmação explícita do escopo de upload e limpeza, o primeiro ensaio
real concluiu em **7,74 segundos**, usando FTP 21/passivo sem TLS e as
credenciais existentes. Criados somente os três pais staging ausentes e a
folha exclusiva acima. Os pais permanecem; nenhuma inbox production/code foi
criada. Não houve mudança de modos de chave, configurações ou arquivos existentes.

STOR `probe.json.part` recebeu 125/226. RETR conferiu os 67 bytes e o SHA-256
antes e depois do rename; RNFR recebeu 350 e RNTO 250. Reconciliação somente
leitura confirmou apenas `probe.json` íntegro. Após conferir inventário e bytes,
DELE e RMD receberam 250. A inbox `/ftp-inbox/elections/staging` ficou vazia;
nova leitura confirmou ausência da folha (MLST 550 + inventário vazio).

Hashes de `data/version.json`, `eleicoes/index.html`, `app.js`, `favorites.js`
e `composition.js` permaneceram iguais antes/depois e após a limpeza. Isso
cobre os cinco arquivos observados; não afirma auditoria integral de arquivos
da hospedagem nem ausência de escritores externos. O executor restringiu
STOR/rename/delete/mkdir/rmdir exclusivamente aos caminhos do plano.
Relatórios datados com códigos, tempos e hashes ficam localmente, fora do Git.

**TESTADO NA LOCAWEB:** login, criação da inbox staging, upload de fixture,
integridade, rename, reconciliação e limpeza delimitada. **VALIDADO EM STAGING
(aplicação): não.** Não houve instalação PHP,
ativação de release, escrita de resultado real ou mudança de serviço.
FPM/NFS/multinó/cache, recuperação da aplicação, fronteira de confiança,
environments e Amazonas continuam pendentes. Os gates permanecem fechados.

O envio autorizado de `11dae67` e a atualização do PR encontraram o bloqueio
do conector GitHub nesta sessão: `MCP tool call requires approval, but approval
policy is never`. O PR remoto continua em `a92e184`; seus três workflows estão
aprovados, mas não validam a instrumentação local adicional. A confirmação
humana não muda a política de ferramentas da sessão. Conservar bundle para
envio por sessão com permissão, sem force push ou merge.

## Etapa 13 — sincronização confirmada e preparação PHP

Nova consulta ao GitHub confirmou `77d3fe866daecc80d4dfdb645db505e37252013f`
como HEAD do PR #75, aberto/em rascunho. A comparação com `a92e184` confirmou
dois commits descendentes, `11dae67` e `77d3fe8`, sem divergência. Não foi
necessário repetir o envio. CI, FTP publication validation e Validate HTTPS
publisher dessa revisão passaram. O [CI FTP Linux](https://github.com/lucasgonella/election-results-platform/actions/runs/38013434610)
executou **309 testes em cada versão Python 3.13/3.14**, PHP 8.3.6 CLI,
lint PHP/Bash, sintaxe Python e Node. Essa versão PHP pertence ao runner,
não é evidência da versão instalada na Locaweb.

O checkout original permanece em `3e8bb1f`, com suas alterações preexistentes
preservadas. Uma cópia isolada em `.stage13-validation/review`, branch local
`etapa13-validation`, importou o bundle verificado para trabalhar sobre o HEAD
confirmado. O comando documentado do gerador falhou fora do pytest com
`ModuleNotFoundError: collector`: a correção acrescenta a raiz do repositório
ao caminho de importação. A regressão executa o CLI de outro diretório, sem
PYTHONPATH. O harness agora informa PID além de host/SAPI/UID/GID; o cliente
preserva esse campo sem revelar a configuração privada.

Testes locais: 46 testes dos clientes aprovados; regressão do CLI aprovada
em execução autorizada fora do sandbox após falha de acesso ao temporário.
O gerador corrigido preparou somente fixtures locais em
`.stage13-validation/ftp-staging-pr75-etapa13-final`. Não foram alteradas ACLs ou
controles de segurança. A revisão nova exige seus próprios checks Linux;
consultar o SHA efetivo do PR, sem reutilizar a aprovação de `77d3fe8`.

### Diagnóstico atual somente leitura

- FTP 21/passivo sem TLS, credenciais existentes: PWD `/`, servidor UNIX;
  raiz com 29 entradas e `/ftp-inbox/elections/staging` existente e vazio.
  A folha `ftp-staging-pr75-etapa11` permanece ausente no inventário/MLST.
- `/ftp-staging-pr75` não aparece na raiz e MLST responde 550; a criação
  exclusiva continua obrigatória. A home física
  `/home/storage/4/b7/e0/afgnet1` é evidência SSH anterior. Esse caminho absoluto
  responde 550 via FTP: usar o namespace FTP `/`, sem inferir que o caminho
  físico possa ser enviado ao servidor FTP.
- MLST da chave e de `public_html/api/election-publish.php` responde 250,
  com capacidades anunciadas de leitura/escrita/rename/delete. Nenhum conteúdo
  protegido foi lido; isolamento permanece insuficiente e gates fechados.
- GET HTTPS em `afgnet.com.br/eleicoes/`, `/data/version.json` e
  `/eleicoes/goias/raio-x/` responde 200. Nginx 1.24.0, ETag e Last-Modified
  observados; sem Cache-Control/Age nessas respostas. Isso não comprova
  coerência de cache, PHP-FPM, OPcache ou disponibilidade de rota de staging.
- SSH local resolve para um bloqueador; a tentativa autorizada não produziu
  diagnóstico remoto. PHP CLI/FPM, host real, mount/opções NFS, quota/inodes,
  permissões efetivas FPM e domínios/subdomínios adicionais não foram revalidados.
  `nolock,local_lock=all,nocto` permanece evidência anterior, não medição atual.
- API GitHub lista somente `https-staging`, com política de branches. Não há
  environments `staging` e `production` usados pelo fluxo FTP nessa consulta.
  Nenhuma configuração GitHub foi criada ou alterada.

### Primeiro ensaio PHP: pacote preparado, execução ainda não autorizada

Origem local: `C:/Users/gonella/election-results-platform/.stage13-validation/ftp-staging-pr75-etapa13-final`.
Destino FTP proposto: `/ftp-staging-pr75`, irmão de `/public_html`, com home
física a reconfirmar como `/home/storage/4/b7/e0/afgnet1/ftp-staging-pr75`.

Primeiro inventário mínimo:

| Origem relativa | Destino FTP exato | Papel |
| --- | --- | --- |
| `private/ftp-publication.php` | `/ftp-staging-pr75/private/ftp-publication.php` | Primitivas existentes, carregadas pelo probe |
| `public/probe.php` | `/ftp-staging-pr75/public/probe.php` | Harness autenticado, separado do publicador |
| `public/probe-marker.json` | `/ftp-staging-pr75/public/probe-marker.json` | Marcador A sintético descartável |

O inventário completo local inclui fixtures full/delta para os ensaios
posteriores: 147 arquivos, 102.809 bytes. O primeiro probe usa apenas os
três arquivos da tabela, 20.833 bytes; não enviar full/delta nesse diagnóstico.
`private/staging-config.json` e sua chave local continuam excluídos da
transferência. A configuração remota requer chave fixture nova gerada no
servidor, root remoto exato e host confirmado antes de qualquer mutação.
Ainda falta um meio autorizado para criar essa configuração no servidor.

Dependências antes de apresentar a aprovação final executável: rota HTTPS
existente servindo **somente** `ftp-staging-pr75/public`, sem aliases dos
privados; método autorizado de provisionamento da configuração fixture;
permissões de travessia/leitura PHP e namespace novo confirmado. Não alterar
DNS, certificados, virtual hosts ou PHP/serviços principais por inferência.
Uma rota sob o document root atual não autoriza instalar ali este pacote.

Operações futuras a aprovar: MKD exclusivo da raiz e `private`/`public`, STOR
somente dos três arquivos allowlisted com temporário + RETR/hash + RNFR/RNTO
no mesmo diretório novo; geração da configuração fixture no servidor; POST
autenticado `runtime`/`read`, sem conteúdo de arquivo, e GET do marcador.
Esse primeiro escopo não inclui locks ou replace A/B: depois de identificar
host/SAPI, apresentar separadamente essas mutações e recuperação.

Rollback/limpeza propostos: como não há substituição de arquivo público
existente, interromper em qualquer colisão/hash divergente; reconciliar
inventário, remover somente os arquivos novos explicitamente autorizados e
íntegros, conferir diretórios vazios e removê-los de dentro para fora.
Arquivo extra, link, caminho divergente ou estado ambíguo interrompe a
limpeza. Inboxes anteriores e árvore pública existente permanecem preservadas.
Não fazer remoção recursiva nem limpeza automática de releases.

**IMPLEMENTADO:** gerador/harness/clientes e regressões. **TESTADO LOCALMENTE:**
preparação e clientes; PHP novo depende do CI Linux. **TESTADO NA LOCAWEB:**
transporte da etapa 12 e diagnóstico FTP/HTTP atual. **VALIDADO EM STAGING:**
aplicação ainda não. **ATIVO EM PRODUÇÃO:** protocolo novo não ativado.
Nenhum upload, criação, rename, exclusão, chamada ao receptor eleitoral,
instalação PHP, alteração de banco/timer/serviço ou merge foi executado nesta
etapa. Fronteira de confiança, Amazonas e ensaios FPM/NFS/cache/rollback seguem
pendentes; não solicitar outra conta nem habilitar isolamento por declaração.
