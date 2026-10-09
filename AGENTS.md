# Manual técnico e operacional para agentes

## Objetivo e fontes

Este repositório coleta resultados eleitorais do TSE, mantém histórico em PostgreSQL e publica JSONs para um frontend estático. Consulte [ARCHITECTURE.md](ARCHITECTURE.md) para componentes, fluxos, contratos, riscos e informações de produção ainda não confirmadas. Consulte também `README.md`, `docs/` e `web/public/eleicoes/goias/raio-x/README.md`.

Este manual descreve o código inspecionado; não comprova o estado de servidores, banco ou GitHub Actions. Quando documentação e implementação divergirem, confirme no código e registre a divergência. Diferencie fatos verificados, inferências e informações desconhecidas. Não apresente funcionalidades planejadas como entregues.

## Política permanente de transferência para a Locaweb

Decisão explícita do responsável: todo upload para a hospedagem deve usar **FTP convencional na porta 21, sem TLS**. Não substituir por SFTP, FTPS, SCP ou upload HTTPS. O responsável reconhece os riscos do transporte sem criptografia; não reabrir a escolha de transporte em cada tarefa.

- Reutilizar `secrets.LOCAWEB_FTP_HOST`, `secrets.LOCAWEB_FTP_USER` e `secrets.LOCAWEB_FTP_PASSWORD` existentes no GitHub Actions. Não duplicar credenciais.
- `vars.LOCAWEB_FTP_GOIAS_DIR` pertence somente ao Raio-X Goiás. Confirmar a raiz FTP e o destino dos demais componentes antes de implementar deploy; caminho SSH absoluto não determina caminho relativo FTP.
- Centralizar transporte e validação em workflows reutilizáveis quando possível, com destinos permitidos por componente, artefatos explícitos e coordenação entre todos os escritores do mesmo destino.
- Toda publicação exige análise de impacto, validação e testes; identificar papel e dependências de cada arquivo antes de substituir produção. Não transferir `.env`, segredos, `.git`, estado interno ou arquivos sem inclusão explícita no artefato. Não imprimir credenciais nem colocá-las nas URLs/logs.
- Preservar os diretórios existentes e implementar backup, checksums, recuperação e prevenção de publicação parcial. FTP é transporte; não constitui sozinho um protocolo de ativação consistente.
- Para apuração, preservar releases imutáveis, 137 resultados coerentes, troca atômica do marcador, idempotência e prevenção de regressão. É proibido substituir o publicador por uploads individuais diretamente nos JSONs públicos.
- O novo protocolo usa HTTPS autenticado apenas para controle/consulta/ativação **sem conteúdo de arquivos**; não usá-lo para transferir arquivos. A implementação opt-in e seus bloqueios de implantação estão em `docs/ftp-publication.md`.
- Esta decisão não autoriza modificar imediatamente o fluxo operacional existente. O live HTTPS observado na auditoria permanece como está até uma migração expressamente autorizada, projetada e testada. Não usar os scripts SSH/HTTPS legados para novos uploads.

## Regras de trabalho

1. Antes de qualquer alteração, leia as instruções aplicáveis, confira `git status --short` e analise o impacto em dados, compatibilidade dos JSONs, frontend, segurança, concorrência e recuperação de falhas.
2. Respeite o escopo autorizado pelo usuário. Não altere arquivos ou componentes fora dele; preserve alterações preexistentes. Não faça commits ou pushes sem autorização.
3. Alterações em infraestrutura, banco, migrations aplicadas, serviços/timers, credenciais, deploy ou publicação remota exigem autorização correspondente. Uma solicitação de edição local não autoriza executar essas operações.
4. Não execute coleta contra o TSE, bootstrap, módulos operacionais ou chamadas ao receptor HTTPS durante uma tarefa de inspeção. Mesmo modos chamados de dry-run podem consultar rede e banco.
5. Não revele valores de `.env`, arquivos de ambiente operacionais, chaves SSH, HMAC, tokens ou senhas. Não os inclua em logs, patches ou documentação. Use nomes de variáveis e exemplos sem credenciais reais.
6. Não apague estado live, checkpoints, snapshots, volumes ou diretórios de publicação para resolver falhas sem analisar preservação e recuperação dos dados e obter autorização.
7. Qualquer alteração futura deve ser seguida de testes adequados ao impacto. Antes de executar testes, confira se usam serviços reais, subprocessos ou arquivos persistentes. Informe o que passou, o que não foi executado e por quê.
8. Não altere o transporte de publicação nem habilite escritores concorrentes por conveniência. Confirme quem possui `/data` e como restaurar o estado antes de uma mudança operacional.

## Navegação rápida

| Caminho | Uso |
| --- | --- |
| `collector/src/` | Cliente TSE, parser, planejamento, ingestão, persistência, observabilidade e builders/publicador live. |
| `database/migrations/` | Schema SQL e evolução; aplicação é uma operação separada. |
| `web/public/eleicoes/` | Portal, favoritos e composição parlamentar. |
| `web/public/eleicoes/goias/raio-x/` | Interface financeira de Goiás e contrato de dados. |
| `deploy/scripts/` | Scripts com efeitos operacionais; ler antes de executar. |
| `deploy/locaweb/` | Receptor PHP HTTPS e helpers de ativação. |
| `deploy/systemd/`, `deploy/env/` | Serviços, timers e exemplo de ambiente Linux. |
| `.github/workflows/`, `tests/`, `docs/` | CI/CD, validações e documentação operacional. |

Ignore `.venv`, caches e arquivos gerados na navegação usual. Prefira `rg` para buscas. Não confunda o histórico no banco com o estado do publicador live: são caminhos independentes.

## Ambientes

- **Desenvolvimento:** Python local e PostgreSQL do `docker-compose.yml`. Defaults do runtime apontam para o simulado do TSE. O exemplo `.env.example` usa `POSTGRES_HOST=db`, adequado à rede Compose; para Python no host, confira o endereço e a porta publicados. O exemplo operacional usa `localhost`.
- **Staging:** o CD HTTPS prepara código em releases isoladas no runner app01, sem instalar PHP na Locaweb nem mudar a aplicação em `/opt`. Os testes de ativação PHP usam armazenamento privado. Não equipare esse staging à produção.
- **Produção:** na auditoria de 09/10/2026, os timers do app01 estavam habilitados e o live usava HTTPS oficial por override; a publicação após coleta estava desabilitada. Isso é evidência datada, não garantia do estado futuro. FTP é obrigatório para novos uploads e alvo da migração, ainda não realizada. Coleta histórica oficial exige `--allow-official`; o live não tem a mesma trava. Detalhes e lacunas estão em `ARCHITECTURE.md`.

## Preparação local: comandos de referência

Os comandos abaixo não devem ser executados automaticamente em uma sessão de reconhecimento. Criação de ambiente, instalação e inicialização de serviços dependem do escopo autorizado.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r collector/requirements-dev.txt
docker compose up -d
```

Em Linux/macOS, a ativação é `source .venv/bin/activate`. O CI usa Python 3.13. Bash, PHP CLI e Node são necessários para as validações correspondentes; não presuma sua disponibilidade no Windows. O parser requer dados de fuso para `America/Sao_Paulo`; a disponibilidade deve ser conferida no ambiente.

Configure as variáveis a partir dos exemplos, sem sobrescrever configuração existente. O Compose não aplica as migrations automaticamente. Não execute SQL de migration sem plano, revisão de impacto e autorização para o banco de destino.

## Validação

Com ambiente preparado e execução autorizada:

```text
python -m pytest -q
python -m compileall -q collector
python -m unittest discover -s tests -p 'test_https_*.py' -v
bash tests/test_https_release.sh
node --check web/public/eleicoes/app.js
node --check web/public/eleicoes/favorites.js
node --check web/public/eleicoes/composition.js
```

Para PHP, use `php -l <arquivo>` em cada arquivo de `deploy/locaweb/`. A validação JavaScript do Raio-X extrai o script inline; seu procedimento está em `.github/workflows/goias-finance-ci.yml`.

`compileall` escreve bytecode. Os testes podem criar arquivos temporários e executar helpers PHP/Bash; o teste de releases promove e restaura ponteiros dentro de uma árvore temporária. Não execute esses comandos sob uma exigência de leitura estrita. A suíte não substitui validação em banco real, navegador ou produção.

Selecione testes conforme o impacto: parser/cliente para formatos e HTTP; planner/batches para checkpoints; repositórios e schema para persistência; builders e leitores para contratos JSON; testes de falhas e recuperação para publicação. Mudanças operacionais exigem confirmar também limites, concorrência, idempotência e rollback.

## Cuidados específicos

- O live publisher deve ser o único escritor de dados públicos quando esse modo estiver ativo; o exemplo recomenda `PUBLISH_AFTER_COLLECT=false` nessa situação.
- `collector.src.live_publisher prepare/commit`, collectors, bootstrap e scripts de publicação não são comandos neutros de diagnóstico.
- O checkout local auditado não contém a base/pipeline financeira; a main remota já possuía importador e workflows financeiros na auditoria de 09/10/2026. Conferir a revisão de trabalho antes de concluir ausência. Não fabrique candidatos, valores ou vínculos.
- Os riscos registrados em `ARCHITECTURE.md` continuam pendentes até correção e validação explícitas. Não transforme a documentação desses riscos em alegação de correção.

Ao entregar trabalho, resuma os arquivos alterados, impacto, validações e limitações, e confira o diff. Para mudanças exclusivamente documentais, revisão dos links, consistência das fontes e `git diff --check` são suficientes, salvo necessidade adicional identificada.

## Implementação FTP opt-in — etapa 6

Antes de alterar o protocolo, leia [docs/ftp-publication.md](docs/ftp-publication.md). `collector.src.ftp_live_runner` é entrada nova, não instalada nos serviços existentes; `ftp_delivery` congela/assina/transfere e reconcilia. `election-ftp-control.php` e `ftp-publication.php` ativam somente entregas eleitorais verificadas, com 137 resultados, baseline assinada e lock próprio.

Não contorne as travas de baseline legada ou estado live existente apagando arquivos. Adoção inicial em produção requer reconciliação e autorização. O workflow reutilizável novo entrega código em inbox privada; não ativa código em execução. Não descreva essa entrega como deploy de aplicação já ativada. Fluxos GO/SSH/HTTPS antigos continuam preservados e não compartilham o lock novo. Não habilite dois escritores.

Testes obrigatórios do protocolo: `python -m pytest -q tests/test_ftp_publication.py`, PHP lint e validação dos leitores JavaScript; depois suíte adequada ao impacto. Use fixtures locais. Retenção atual conserva tudo; nenhuma limpeza automática deve ser acrescentada sem proteger releases e entregas em voo.
