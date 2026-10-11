# CI/CD do portal e Raio-X: FTP 21, ativação e recuperação

O fluxo do front-end é independente da publicação de resultados TSE. A autorização
posterior do responsável inclui operação em produção; não permite fabricar prova
de isolamento da conta ou chamar upload para uma inbox de deploy concluído.

## Componentes e destinos confirmados por leitura

`deploy/frontend-targets.json` é a configuração central, revalidada pelo código:

| Componente | Fonte | FTP (PWD `/` = home SSH) | HTTPS |
|---|---|---|---|
| portal | `web/public/eleicoes`, exclui Goiás e dados | `/public_html/eleicoes` | `https://afgnet.com.br/eleicoes/` |
| raio-x | `web/public/eleicoes/goias/raio-x`, exclui `data` | `/public_html/eleicoes/goias/raio-x` | `https://afgnet.com.br/eleicoes/goias/raio-x/` |

Home: `/home/storage/4/b7/e0/afgnet1`. Ambos os diretórios responderam MLST 250/type=dir.
`LOCAWEB_FTP_GOIAS_DIR=public_html/eleicoes/goias/raio-x` foi conferida no GitHub;
divergência impede operação de Goiás. Reutilizar os três secrets FTP existentes.
Porta diferente de 21 é rejeitada; `ftplib.FTP` usa passivo e não negocia TLS.

## O que os workflows fazem

- `frontend-ftp-ci.yml`: todo PR/main valida a implementação com fixtures, HTML,
  CSS via tinycss2, JS externo e inline via Node; prepara os dois pacotes, sem FTP.
- `deploy-portal-ftp.yml`: push/merge em main com alterações visuais do portal ou
  infraestrutura do seu deploy. Exclui Goiás, dados e documentação do frontend.
- `deploy-goias-ftp.yml`: preserva nome e destino existentes; passa a chamar o
  mesmo mecanismo restrito para o front-end de Goiás. Exclui dados financeiros.
- `deploy-frontend-ftp.yml`: transporte/ativação reutilizáveis; aceita somente
  portal/raio-x, ref main, aguarda CI geral, FTP nas duas versões Python e CI
  frontend aprovados no SHA exato. Concurrency por componente e MKD exclusivo
  remoto bloqueiam dois clientes deste mecanismo no mesmo destino.
- `frontend-ftp-manual.yml`: deploy, rollback (`previous` ou SHA de uma versão já
  instalada), recuperação explícita após cliente interrompido. Executar na main.

Os workflows financeiros `goias-finance-data.yml` e `goias-finance-audit.yml` da
main foram inspecionados. Seus ETLs, horários e arquivos permanecem intactos. A
importação continua proprietária de `raio-x/data/go-2026.json`; o deploy visual
nunca envia esse JSON nem exige que ele seja copiado para a branch do portal.
São namespaces de arquivos distintos. A integração financeira não participa do
lock dos HTMLs e não deve passar a escrever seus entrypoints.

`election-data` não existe como opção nestes workflows. `ftp_live_runner`, sua
inbox/controlador, baseline assinada, watermarks e gates continuam separados.
Nenhum simples push/merge ativa a publicação TSE nem altera timers do app01.

## Instalação inicial e publicação

Não se instala PHP nem endpoint de cópia/execução. No primeiro deploy autorizado,
o cliente cria `/frontend-deploy/<componente>` fora de public_html para metadados
e backups, e `<ftp_root>/frontend-releases/<SHA>` para assets estáticos imutáveis.
Confirma metadata/PWD e recusa colisões, symlinks conhecidos e bytes divergentes.
Confirma também que os HTMLs públicos lidos por FTP e HTTPS coincidem antes da
troca. Não alterar ACL/global PHP/DNS/certificados para contornar falhas.

1. Pacote com SHA do commit, inventário exato, tamanho/SHA-256 por arquivo. Só
   HTML/CSS/JS/imagens/fontes; sem JSON, PHP, `.env`, chaves ou arquivo oculto.
2. Backup de todos os entrypoints antes de mutá-los:
   `/frontend-deploy/<componente>/transactions/<id>/before/<html>`; journal com
   hashes, inventário e estado anterior. Conservação sem limpeza automática.
3. STOR de temporário novo; RETR e comparação integral; RNFR/RNTO; novo RETR.
   Nunca remover o destino para conseguir RNTO. Upload incompleto remove somente
   seu temporário, nunca arquivo remoto preexistente.
4. Assets em URL nova com SHA. Referências dos HTMLs fixadas nessa release.
   Navegação para composição é igualmente versionada; dados continuam nas URLs
   estáveis. Raio-X usa `/eleicoes/goias/raio-x/data/`, inclusive na HTML imutável.
5. GET HTTPS sem redirecionamento verifica todos os assets antes de ativar.
6. Rename dos entrypoints fixos: portal `composicao.html`, depois `index.html`;
   Goiás somente `index.html`. Assets antigos da raiz não são apagados.
7. GET de TODOS os arquivos versionados, entrypoints estáveis e URL de diretório
   deve ter tamanho/SHA exatos. Só então se registra `current.json` e sucesso.
   Repetição do mesmo SHA é idempotente: verifica e não cria outra versão anterior.

Artefatos e relatório ficam no Actions; Step Summary informa SHA, arquivos,
URLs e resultado. Nenhuma credencial entra no relatório. Falha sem recibo não é
sucesso. 550 pode ser ausência ou negação: MKD/STOR ainda precisam ser aceitos;
não se infere isolamento a partir de MLST negado.

## Operação e rollback

Após merge, não é necessário comando na Locaweb. Para intervenção, usar Actions →
Manual frontend deploy rollback recovery, componente, operação e versão.

Também existe CLI com credenciais fornecidas pelo ambiente protegido, não argv:

```sh
python -m collector.src.frontend_deploy build --component portal --commit SHA40 --directory PACOTE_NOVO
python -m collector.src.frontend_deploy deploy --component portal --directory PACOTE_NOVO --report report.json
python -m collector.src.frontend_deploy rollback --component portal --version previous --report rollback.json
python -m collector.src.frontend_deploy recover --component portal --report recovery.json
```

Não executar recover enquanto existir cliente ativo. Concurrency do Actions
serializa deploy/rollback/recover deste componente. Interrupção abrupta conserva
`lock` e `pending.json`; não roubar lock por timeout. Recover restaura backups de
hash comprovado por destinos fixos, verifica FTP/HTTPS, restaura metadados e só
então remove o lock vazio. Pending desconhecido/backup faltante falha fechado.
Se a interrupção ocorreu antes de journal, não houve troca pública: inspecionar
metadata/baseline e recuperar esse lock explicitamente, sem apagar namespaces.

Rollback para SHA publicado usa o inventário privado e os assets conservados;
verifica tudo novamente e guarda backup da versão que está saindo. `previous`
após primeiro deploy restaura os HTMLs originais capturados na inicialização.
Falha normal na ativação tenta compensar imediatamente todos os entrypoints;
falha na compensação mantém lock/journal para recuperação supervisionada.
Não há remoção de releases, diretórios ou arquivos não geridos.

## Limites reais

A troca é por arquivo, não uma transação atômica de todo o portal. HTMLs novos
referenciam exclusivamente assets de sua versão, mas bookmarks de dois HTMLs
estáveis podem observar versões diferentes durante a troca/rollback. Nenhuma
garantia multinó/NFS ou de durabilidade após falha física é declarada.
MKD exclusivo coordena clientes FTP deste mecanismo; não coordena editores
externos. Antes de cada rename o hash anterior é conferido; um escritor externo
concomitante continua sendo risco residual. NFSv3 soft/nocto/nolock e caches do
provedor podem impedir observação imediata: verificação estrita falha e restaura.

FTP sem criptografia e a identidade que alcança PHP/chave HMAC permanecem riscos.
Este mecanismo limita o que seu cliente transfere; não confina a conta. Não usa
a chave e não altera `LOCAWEB_FTP_ISOLATION_APPROVED`. Sem confinamento comprovado,
os gates do publicador eleitoral continuam recusando esse transporte. Aprovação
operacional do front-end não certifica a arquitetura de resultados eleitorais.

Os workflows novos só ficam automáticos depois de integrarem a main. Commit/push
na branch de PR, mesmo com deploy inicial autorizado por CLI, não instala os
triggers da main. Nenhum merge automático está incluído nesta implementação.
