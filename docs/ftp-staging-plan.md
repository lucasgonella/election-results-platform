# Etapa 9 — plano de staging real

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

Menor mudança candidata: restringir a conta atual às inboxes e destino Goiás
aprovados. Se somente usuário secundário confinado for suportado, criação e
substituição dos valores dos secrets existentes exigem autorização e análise do
impacto em Goiás; não duplicar secrets. Chmod na mesma home acessível não resolve.
Se o plano não suportar confinamento, propor hospedagem/ambiente separado com
identidades distintas mantendo o mesmo protocolo. Não implementar solução
paralela. Mover apenas HMAC não protege PHP modificável pelo transporte.

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

Novo vhost TLS deve apontar somente para `ftp-staging-pr75/public`; confirmar
ausência de aliases expondo privados. O endpoint calcula sua configuração como
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
