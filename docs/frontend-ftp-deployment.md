# CI/CD visual da Locaweb

Esta é a operação central do portal e do Raio-X Goiás. A main publica alterações
visuais pelo GitHub Actions: alteração → PR → CI → merge → FTP → SHA-256 público
→ relatório. PRs validam e geram artefatos, sem publicar. O PR #75 permanece
separado para o publicador eleitoral; sua migração e seus bloqueios não são
autorizados pelo deploy visual.

## Destinos e arquivos geridos

| Componente | Origem | Raiz FTP | URL pública | Entrypoints substituídos |
| --- | --- | --- | --- | --- |
| portal | `web/public/eleicoes` | `/public_html/eleicoes` | https://afgnet.com.br/eleicoes/ | `composicao.html`, `index.html` |
| raio-x | `web/public/eleicoes/goias/raio-x` | `/public_html/eleicoes/goias/raio-x` | https://afgnet.com.br/eleicoes/goias/raio-x/ | `index.html` |

FTP PWD `/` foi confirmado como a home SSH
`/home/storage/4/b7/e0/afgnet1`. Os destinos acima já foram instalados e testados
em produção no commit `38e1054f4c07eaccbdb507b6eb768df9ea9293aa`. A configuração
única está em `deploy/frontend-targets.json`. `LOCAWEB_FTP_GOIAS_DIR` deve continuar
`public_html/eleicoes/goias/raio-x`; valor divergente interrompe o cliente.

Somente HTML, CSS, JS, imagens e fontes são empacotados. Arquivos ocultos,
symlinks, JSON, PHP, `data`, `goias` no portal, segredos e estado interno não
entram no artefato. A publicação inicial contém sete arquivos do portal e um
HTML do Raio-X. Novos assets permitidos entram na release do respectivo componente.
Os leitores de favoritos já publicados são preservados: seguem o snapshot do
marcador, sem modificar os dados nem sua ativação.

## Workflows e detecção de alterações

- `frontend-ftp-ci.yml`: todos os PRs e pushes na main; testes offline de
  transporte, ativação, falhas, concorrência, rollback e leitores; validação
  HTML/CSS/JS com Node; artefato `frontend-verified-<SHA>` dos dois componentes.
- `deploy-portal-ftp.yml`: mudanças visuais do portal, excluindo Goiás, dados e
  documentação; alterações no cliente, configuração ou workflow também disparam.
- `deploy-goias-ftp.yml`: único deploy visual de Goiás, usa o mesmo workflow
  reutilizável; exclui `data/**` e documentação. Substitui o antigo upload direto.
- `deploy-frontend-ftp.yml`: exige `Python Tests` e `Frontend FTP validation`
  aprovados no SHA exato, recusa código visual superado na main e publica um componente.
  Um push posterior só de dados financeiros não cancela o último deploy visual.
  Não depende de checks nem código do protocolo eleitoral do PR #75.
- `frontend-ftp-manual.yml`: deploy, status, rollback ou recuperação na main.

Mudanças do portal não disparam upload do Raio-X, nem vice-versa. Alterações
comuns no mecanismo podem disparar ambos; fingerprint do conteúdo fonte evita
novo upload quando o componente não mudou. O relatório distingue o SHA solicitado
do SHA efetivamente publicado. Repetir o mesmo SHA também é idempotente. A versão
do empacotador participa do fingerprint e deve ser incrementada se suas regras
de saída mudarem. Os manifests antigos sem fingerprint continuam compatíveis.

`goias-finance-data.yml` e `goias-finance-audit.yml`, seus horários, importador,
dados e testes permanecem intactos. Somente o ETL publica `data/go-2026.json`.
Nenhum outro workflow visual envia esse JSON ou HTML diretamente. Não adicionar
outro escritor de entrypoints: todos devem usar o reutilizável e o mesmo grupo
`locaweb-frontend-production`. A conta e o servidor são compartilhados: todos os
deploys/status/rollbacks visuais são serializados no Actions. Há também MKD exclusivo no namespace privado por
componente; portal e Goiás têm entrypoints, releases e metadados distintos.
`queue: max` conserva até 100 execuções pendentes, sem substituir a publicação de
outro componente: [semântica oficial da fila](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

## Publicação e instalação inicial

As credenciais existentes são `LOCAWEB_FTP_HOST`, `LOCAWEB_FTP_USER` e
`LOCAWEB_FTP_PASSWORD`. Todo upload usa FTP convencional, porta 21, passivo,
sem TLS. EPSV é preferido, com PASV somente quando não suportado em IPv4; nunca
modo ativo. Timeout FTP limitado a 90 segundos. HTTPS é exclusivamente GET de verificação; não transfere arquivos.
O cliente independente é `python -m deploy.frontend`, sem imports do coletor.
Não se instala endpoint PHP, executor remoto, DNS ou serviço.

1. Build gera `artifact.json` com commit, inventário, tamanho e SHA-256; confere
   pacote exato antes de conectar. Artefato versionado é conservado no Actions.
2. Confere FTP PWD, destino e HTML público por FTP e HTTPS. Guarda backup de todos
   os entrypoints em `/frontend-deploy/<componente>/transactions/<id>/before/`.
   Journal, hashes e estado anterior ficam privados. Não há retenção destrutiva.
3. Registra `pending.json` antes da preparação. STOR em temporário novo, RETR para
   comparação integral, RNFR/RNTO e novo RETR. Colisões e corrupção interrompem.
   Só remove o temporário criado pela própria tentativa.
4. Envia assets para `<raiz FTP>/frontend-releases/<SHA>/`; HTML aponta para assets
   dessa versão. Verifica todos por HTTPS antes de substituir entrypoints.
   Dados continuam em suas URLs estáveis; Raio-X usa seu `data/` existente.
5. Substitui entrypoints por rename individual, conferindo baseline antes de cada
   troca. Conserva assets antigos da raiz e releases anteriores.
6. Verifica SHA-256 de cada URL versionada, HTML estável e DirectoryIndex. Somente
   então registra `versions/<SHA>.json`, `current.json` e sucesso.

Na implantação inicial já executada, backups originais estão em
`/frontend-deploy/{portal,raio-x}/transactions/initial-38e1054f4c07/before/`.
Após a integração à main, mudanças comuns não exigem comandos na Locaweb.
Não recriar a instalação nem sobrescrever metadados para resolver divergências.

## Acompanhar, executar manualmente e verificar

Actions → workflow do componente → execução do commit. O Step Summary e o
artefato `frontend-report-<componente>-<run>-<attempt>` informam resultado,
commit, arquivos, URLs e transação. Upload sem confirmação pública não é sucesso.

Actions → **Manual frontend deploy status rollback recovery** → **Run workflow**:

- branch `main`, componente `portal` ou `raio-x`, operação `deploy`: reexecuta o
  build/deploy do HEAD aprovado; conteúdo já publicado não é reenviado.
- operação `status`: consulta FTP e verifica todas as URLs por SHA-256, mostra
  versão anterior, pending e presença de lock, sem escrever ou adquirir lock.
- operação `rollback`, versão `previous` ou SHA40: somente manifest privado de
  versão previamente publicada, assets conservados e hashes válidos. Faz backup
  da versão que sai. Nunca baixa artefato arbitrário para instalar.
- operação `recover`: somente após confirmar que não há cliente ativo; restaura
  backup do journal pendente, verifica FTP/HTTPS e remove apenas o lock vazio.

CLI equivalente, com credenciais no ambiente protegido e nunca na linha de comando:

```sh
python -m deploy.frontend build --component portal --commit SHA40 --directory PACOTE_NOVO
python -m deploy.frontend deploy --component portal --directory PACOTE_NOVO --report report.json
python -m deploy.frontend status --component portal --report status.json
python -m deploy.frontend rollback --component portal --version previous --report rollback.json
python -m deploy.frontend recover --component portal --report recovery.json
```

## Falhas e recuperação

Falha de FTP ou HTTP tenta restaurar os entrypoints e metadados anteriores. O lock
é preservado após erro para impedir outra publicação antes da investigação.
Interrupção abrupta mantém journal/pending e exige `recover`; não roubar lock por
timeout. Backup faltante, hash divergente ou pending desconhecido falham fechado.
Interrupção antes do journal exige inspeção delimitada: não houve troca pública,
mas o cliente não apaga um lock sem plano verificável.

Erros de transferência podem invalidar a conexão de controle. O relatório conserva
tipos/códigos numéricos da falha original e da recuperação, sem mensagens do servidor
ou credenciais. Se a compensação falhar, `recover` abre uma nova conexão e usa o
journal verificado; não repetir upload sobre temporário preexistente. A primeira
execução automática foi interrompida antes da ativação dos HTMLs e recuperada,
preservando a versão anterior. Temporários de tentativas falhas não são versões
aprovadas e não podem ser escolhidos para rollback.

A inspeção real encontrou os dois HTMLs temporários completos com SHA-256 correto,
apesar da falha de resposta. Em perda de conexão durante PUT, o cliente reconecta
uma única vez e consulta temporário/destino. Somente bytes exatos permitem concluir
o rename/verificação; não repete STOR nem adota um temporário preexistente a esta
tentativa. Corrupção ou mudança externa interrompem. O recibo informa a quantidade
de transferências reconciliadas; confirmação pública por HTTPS continua obrigatória.

Verifique CI do SHA, var de Goiás, secrets presentes, conexão FTP21/passiva,
metadados, colisões `.upload`, pending e URLs do relatório. Não imprimir secrets
nem afrouxar permissões. HTTP 200 com bytes diferentes é falha, inclusive cache.
Rollback e compensação foram testados com fixtures offline; não simular falhas
de serviços/NFS de produção. Não apagar releases, estado eleitoral ou dados
financeiros para corrigir uma publicação visual.

## Limites e separação eleitoral

Rename é por arquivo; não há transação atômica de todo o site. Cada HTML aponta
para sua versão completa, mas dois entrypoints estáveis podem ser observados em
versões diferentes durante troca/rollback. NFSv3 `soft/nocto/nolock`, caches e
topologia FPM não oferecem garantia multinó comprovada. Escritores externos não
participam do MKD; verificar baseline reduz, mas não elimina, essa corrida.

FTP transmite credenciais sem criptografia e a conta acessa PHP/chave HMAC. O
cliente limita destinos, não confina a conta. Não usa a chave, não altera
`LOCAWEB_FTP_ISOLATION_APPROVED` e não aprova isolamento. Os gates e riscos do
publicador eleitoral continuam pendentes. Merge visual não ativa resultados,
controladores TSE, `/data/version.json`, timer, state, pending ou stage do app01.
