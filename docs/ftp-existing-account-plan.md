# Etapa 11 — conta FTP existente, preparação e aprovação de staging

Decisão: somente a conta FTP já configurada, FTP convencional 21/passivo,
sem nova conta, plano ou serviço adicional. Preservar secrets atuais e os
workflows de Goiás. Este plano não autoriza escrita na Locaweb nem corte.

## Evidências e limites

O diagnóstico autenticado `probe-ftp-staging.py inspect` usa o arquivo local
existente sem imprimir valores. PWD atual `/`; MLST confirma alcance de
`.election-publisher`, `hmac.key`, `includes` e PHP legado. Nenhum RETR de controle,
STOR, MKD, rename, DELE ou RMD foi executado. A conta possui acesso ampliado:
**isolamento não garantido**. Metadados anunciados não provam escrita efetiva.
MLST anuncia `perm=radfwMT` para chave/PHP legado e `eldfmMTcp` para diretórios.
`public_html` mantém unique `21g7a4c0c`, e a chave `21gb11d68`, coincidentes com
os inodes SSH anteriores. As quatro inboxes e o namespace de probe retornaram
550; não foram criados nem considerados existentes/graváveis por esse retorno.

A correspondência `/` → `/home/storage/4/b7/e0/afgnet1` e UID 542178 foi comprovada
na auditoria anterior por UID/inodes. Nesta etapa SSH local resolve para o
bloqueador do sandbox: a árvore SSH/app01 não foi novamente inspecionada.
Consulta de environments via gh falhou no proxy local; existência/proteções/vars
atuais permanecem não confirmadas. Nada foi configurado no GitHub.

PR #75 permanece em rascunho. O commit da etapa 10 `5647d9e` já chegou ao GitHub
e CI, HTTPS e FTP Linux passaram: isso valida a etapa 9, não o diagnóstico novo
da etapa 11. Consultar os checks do SHA exato antes de enviar qualquer artefato.
O job FTP Python 3.14 registrou **258 testes aprovados**; os jobs 3.13/3.14
passaram com pytest completo, PHP/Node/Bash. Referência:
[FTP validation #6](https://github.com/lucasgonella/election-results-platform/actions/runs/38004150030).

## Destinos definidos para a conta atual

| Uso | Caminho FTP absoluto | Caminho SSH correspondente pela auditoria |
| --- | --- | --- |
| Resultados staging | `/ftp-inbox/elections/staging` | `/home/storage/4/b7/e0/afgnet1/ftp-inbox/elections/staging` |
| Código staging | `/ftp-inbox/code/staging` | `/home/storage/4/b7/e0/afgnet1/ftp-inbox/code/staging` |
| Resultados production futuro | `/ftp-inbox/elections/production` | `/home/storage/4/b7/e0/afgnet1/ftp-inbox/elections/production` |
| Código production futuro | `/ftp-inbox/code/production` | `/home/storage/4/b7/e0/afgnet1/ftp-inbox/code/production` |
| Primeiro diagnóstico | `/ftp-inbox/elections/staging/ftp-staging-pr75-etapa11` | `/home/storage/4/b7/e0/afgnet1/ftp-inbox/elections/staging/ftp-staging-pr75-etapa11` |
| PHP/estado fixture futuro | Fora do document root; não é inbox | `/home/storage/4/b7/e0/afgnet1/ftp-staging-pr75` |

Esses são destinos do plano, não alegação de diretórios provisionados. Resposta
550 não distingue inexistência de acesso negado. Criar somente a cadeia staging
aprovada e confirmar correspondência/permissões antes de executar o diagnóstico;
production não pertence à primeira aprovação. Revalidar o mapa se o provedor
restringir a mesma conta. Não usar `LOCAWEB_FTP_GOIAS_DIR` como destino novo.

## Configuração e permissões necessárias

- Credenciais: `.secrets/ftp.env` local e
  `/etc/election-results-platform/secrets/ftp.env` no app01; reutilizar os nomes
  `LOCAWEB_FTP_HOST`, `LOCAWEB_FTP_USER`, `LOCAWEB_FTP_PASSWORD`, porta 21. Nenhuma
  senha em argumento/URL/log, sem source/eval ou cópia de credenciais.
- FTP precisa atravessar/listar staging e criar arquivo/subdiretório, recuperar
  os bytes sintéticos e renomear somente no namespace de teste. DELE/RMD exigem
  aprovação de limpeza separada. MLST `perm` é apenas capacidade anunciada.
- PHP precisa ler a inbox de fixture e escrever em estado/release/marcador
  isolados. Manter chave/configuração privadas e fora da raiz servida; não mudar
  seus modos. O UID comum e NFS com lock local não estabelecem isolamento.
- Configuração PHP de fixture, layout e chave descartável gerada **no servidor**
  seguem [o plano existente](ftp-staging-plan.md). Não copiar chave real nem a
  configuração local com chave para FTP. A rota HTTPS fixture e `activation_host`
  exato ainda precisam de confirmação no serviço existente, sem nova contratação.
- app01: wrapper suporta Python Linux e o venv 3.14.4/dependências constatados na
  auditoria anterior; compatibilidade de código foi validada na matriz Linux
  3.13/3.14 da etapa 10. Isso não prova o runtime atual do app01. Não instalar
  override/runner, alterar unidade/timer ou executar coleta para validar.
- GitHub: confirmar staging/production, reviewers/proteções de production,
  `actions: read` e vars por environment. `LOCAWEB_FTP_CODE_INBOX_DIR` deve terminar
  em `code/staging` ou `code/production`; credenciais são os secrets existentes.
  `LOCAWEB_FTP_ISOLATION_APPROVED=false` e `ELECTION_FTP_CUTOVER_APPROVED=false`
  permanecem. Não disparar workflow de entrega nem alterar workflow financeiro.

## Primeiro teste remoto — pacote mínimo para aprovação

Ferramenta preparada: `deploy/scripts/probe-ftp-staging.py`. Sem argumentos,
imprime somente plano local. `inspect` faz apenas login/PWD/MLST. Transferência
e limpeza exigem a operação explícita e o namespace exato, além de aprovação
humana prévia. Não é um publicador alternativo; não transporta código, chave,
configuração ou entrega eleitoral assinada. O veto do uploader continua intacto.

Escopo de provisionamento a aprovar: criar, se ausentes, somente
`/ftp-inbox`, `/ftp-inbox/elections`, `/ftp-inbox/elections/staging`. Diretórios
compartilhados existentes não são modificados, removidos nem têm modos alterados.
Não provisionar produção, código ou PHP dentro desta primeira aprovação.

Escopo de transferência a aprovar:

1. CWD no pai staging e MKD **exclusivo** de
   `/ftp-inbox/elections/staging/ftp-staging-pr75-etapa11`; falhar se já existir.
2. STOR `probe.json.part`, exatamente 67 bytes sintéticos, sem dados reais.
3. RETR e conferir SHA-256
   `3fe5cb9e5b0a17af1bb7f7a7730b47f1c31c560b678345804bfe011a9777d585`.
4. RNFR/RNTO para `probe.json`, no mesmo diretório, e RETR/hash novamente.
5. Conservar evidências e os arquivos; não executar limpeza automaticamente.

Comando de referência, **não executado e não autorizado ainda**:

```text
python deploy/scripts/probe-ftp-staging.py transfer --approved-namespace /ftp-inbox/elections/staging/ftp-staging-pr75-etapa11
```

Critérios para autorizar: responsável aprovar esses caminhos/operações exatos;
confirmar que o pai está fora da árvore pública e que o namespace novo não existe;
revisar a ferramenta e seu teste na revisão exata; confirmar porta 21/passivo,
espaço e acesso da conta existente; aceitar explicitamente que o ensaio de
transporte **não** atesta isolamento ou segurança de produção. Não habilitar gates.

## Limpeza e recuperação

Aprovação de limpeza separada abrange apenas o leaf `ftp-staging-pr75-etapa11`:
MLSD, RETR/hash dos nomes fixos `probe.json.part`/`probe.json`, DELE desses arquivos
e RMD do leaf vazio. Não há recursão nem remoção dos pais/inboxes compartilhados.
Nome extra, symlink, conteúdo diferente, inventário vazio/inconclusivo ou falha
de listagem impede a limpeza automática e exige inspeção/aprovação específica.

```text
python deploy/scripts/probe-ftp-staging.py cleanup --approved-namespace /ftp-inbox/elections/staging/ftp-staging-pr75-etapa11
```

Interrupção antes de rename: preservar `.part`; reconectar e conferir somente
esses caminhos. Resposta perdida após rename: conferir `probe.json` por leitura,
não repetir MKD/STOR sobre o namespace existente. Arquivo truncado/corrompido
permanece como evidência; a limpeza padrão recusa apagá-lo. Limpeza parcial
preserva os restantes, sem apagar pais. Nenhum desses eventos afeta marcador,
releases, journals ou watermarks públicos porque o diagnóstico não os acessa.

Para o futuro protocolo PHP completo: namespace e configuração fixture separados,
137 resultados/140 hashes, assinatura HMAC de fixture, READY por último,
ativação/rollback/recibo sob lock e verificação dos leitores. Usar o controlador
existente e recuperação do runbook; nunca apagar estado para desbloquear gates.
O upload eleitoral normal ainda é vetado pela exposição do controle, portanto
este plano não promete execução completa enquanto esse veto persistir.

## Ensaios preparados, evidências necessárias e riscos

| Ensaio | Preparação disponível | Falta validar no ambiente real |
| --- | --- | --- |
| FTP temporário/rename/checksum | Diagnóstico limitado e testes com FTP simulado | MKD/STOR/RETR/RNFR/RNTO no namespace aprovado |
| Falha/corrupção/resposta perdida/limpeza | Testes sem rede e sem diretórios temporários | Reconexão, visibilidade e permissões reais |
| PHP recebe/valida/ativa fixture | Gerador e controlador/harness existentes | Instalação isolada autorizada, FPM/host, leitura da inbox |
| Lock e atomicidade | Testes CLI concorrentes e marcador A/B | Workers/nós reais, NFS e visibilidade/cache por nó |
| HTTP/OPcache e recuperação | Plano de hashes, marcador e rollback | URL/rota HTTPS existente confirmada e ensaio autorizado |

Riscos residuais: conta pode alcançar chave/estado/PHP; FTP sem TLS; credenciais
amplas; locks NFS locais; hostname/roteamento não comprovados; caches e
durabilidade de rename; quota/retensão; concorrência de escritores legados.
O probe não afirma resolver nenhum deles. Não usar payloads de produção no ensaio.

## Amazonas e corte

A pesquisa oficial da etapa 11 encontrou a página
[Eleições 2026 no Amazonas](https://www.tre-am.jus.br/eleicoes/eleicoes-2026), com
relatórios federal/estadual, mas não trouxe justificativa específica vinculada
às gerações `3374388`/`3376197` de 09/10 que passaram de final para não final.
O relatório federal trata de Presidente; deputados estão no relatório estadual.
Não inferir correção desses deltas a partir da existência de relatórios.
O [relatório estadual oficial de 05/10 às 09:18:08](https://www.tre-am.jus.br/eleicoes/eleicoes-2026/arquivos-eleicoes-2026-1/relatorio-resultado-da-totalizacao-estadual-05-10-2026/@@download/file/relatorio-resultado-da-totalizacao-estadual-05-10-2026.pdf)
registra 8.157 seções apuradas e anexos de eleitos/vagas. É anterior às gerações
de 09/10 e não explica sua reabertura; não estabelece legitimidade do delta.
Manter os resultados AM bloqueados, pending, watermarks e
`totalization_reopened_requires_review`. Nenhuma coleta operacional foi executada.

**Validação de código e diagnóstico de transporte não liberam produção.**
Ainda impedem o corte: exposição do controle/veto de upload, provisionamento e
mapa/permissões das inboxes, FPM/NFS/cache/rollback reais, topologia/exclusividade,
AM, environments/quota e adoção assistida da baseline. Só iniciar o primeiro
teste remoto após aprovação específica do escopo mínimo acima. Escritas PHP e
ativação fixture exigem nova aprovação com rota/caminhos reais confirmados.

Validação local da etapa 11: **19 testes do diagnóstico aprovados**, sem rede,
credenciais reais ou temporários restritos; compileall Python, links locais e
diff check aprovados. A suíte completa PHP/Node/Bash continua dependente do CI
Linux. O envio da etapa 11 pelo conector foi rejeitado com
`MCP tool call requires approval, but approval policy is never`; preparar bundle
local não dispara CI nem atualiza o PR. Não atribuir os checks de `5647d9e` a
estas mudanças novas. O primeiro ensaio remoto aguarda envio/revisão/CI e
aprovação específica dos caminhos, efeitos e limpeza acima.
