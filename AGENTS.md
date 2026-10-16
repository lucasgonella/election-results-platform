# Instruções operacionais

Leia `README.md`, a documentação do componente e
`docs/frontend-ftp-deployment.md` antes de alterar publicação visual. Confira
`git status --short`, preserve alterações preexistentes e diferencie código,
testes locais, staging e produção. Confirme o estado real dos servidores e
Actions; documentação não é prova de implantação.

## CI/CD visual definitivo

Melhorias no portal e no Raio-X seguem PR → CI → merge na main → deploy FTP
automático → verificação HTTPS → relatório. Não redesenhar esse fluxo nem pedir
comandos manuais na Locaweb para alterações comuns. O merge/publicação deve
respeitar o escopo autorizado na sessão. PRs não publicam.

- Cliente independente: `deploy/frontend.py`; configuração:
  `deploy/frontend-targets.json`; testes: `tests/test_frontend_deploy.py` e
  `tests/test_frontend_readers.py`.
- Portal: visuais de `web/public/eleicoes`, excluindo `goias` e `data`. Raio-X:
  visuais de `web/public/eleicoes/goias/raio-x`, excluindo seus dados financeiros.
- Destinos reais: `/public_html/eleicoes` e
  `/public_html/eleicoes/goias/raio-x`; FTP `/` é a home da hospedagem.
- Todo escritor visual deve usar `deploy-frontend-ftp.yml`, concurrency global
  `locaweb-frontend-production`, MKD remoto por componente, backups e verificações.
  Não acrescentar upload direto.
- `deploy-goias-ftp.yml` é o único deploy visual de Goiás. Preservar o ETL
  `goias-finance-data.yml`, audit, importador e JSON financeiro.
- Ações manuais na main: deploy, status, rollback de versão publicada e recover.
  Documentação central contém caminhos, diagnósticos e recuperação.
- Conferir CI no SHA efetivo, artefatos, Step Summary e hashes públicos. Upload
  sem confirmação por HTTPS não significa publicação concluída.

## Política permanente da Locaweb

FTP convencional, porta 21, passivo, sem TLS, permanece disponível para rollback.
A missão explícita de 16/10/2026 autoriza SSH + rsync por seleção configurada,
seguindo `docs/ssh-rsync-migration.md`, com identidades dedicadas, host pinado e
os mesmos locks, journals, gates eleitorais e verificação HTTPS. Não alternar
automaticamente transportes nem efetuar corte com transação pendente. Não usar
FTPS, SFTP, SCP ou upload HTTP/HTTPS para arquivos. Para FTP, reutilizar
`LOCAWEB_FTP_HOST`, `LOCAWEB_FTP_USER`, `LOCAWEB_FTP_PASSWORD`; não criar contas
nem duplicar credenciais. `LOCAWEB_FTP_GOIAS_DIR` pertence ao Raio-X e deve ser
`public_html/eleicoes/goias/raio-x`. Nunca imprimir credenciais, HMAC ou `.env`.

FTP não fornece ativação consistente. Preservar backups e checksums, enviar
assets versionados antes dos HTMLs e recuperar falhas pelo journal. Não apagar
arquivos remotos fora do inventário gerido. Não declarar atomicidade global,
durabilidade após falha física nem segurança NFS multinó sem evidência.

A conta existente tem acesso amplo, inclusive PHP/chave HMAC; não afirmar
isolamento, alterar `LOCAWEB_FTP_ISOLATION_APPROVED` ou reutilizar aprovação visual
para contornar gates eleitorais. O PR #75 permanece separado, aberto e em
rascunho para o protocolo TSE. Não fazer merge integral desse PR.

## Preservação e validação

Não alterar resultados, `/data`, financeiro, banco, credenciais,
`.election-publisher`, state, pending, stage, proteções do Amazonas ou serviços/
timers em tarefa visual. Deploy visual não autoriza coleta TSE nem ativação do
publicador. Infraestrutura e banco exigem autorização correspondente.

Use fixtures sintéticas e testes adequados. Validar transporte, caminhos,
concorrência, rollback e falhas antes de mudar o mecanismo. Referências:

```sh
python -m unittest tests.test_frontend_deploy -v
python -m pytest -q tests/test_frontend_readers.py tests/test_web_favorites.py
python -m pytest -q
```

Node e `deploy/frontend-requirements.txt` são necessários à validação visual;
o deploy usa `curl` nativo para STOR/RETR FTP, sem credenciais em argv, dentro
do mesmo módulo. Locks pendentes de qualquer componente bloqueiam novo deploy.
o CI Linux executa os testes. Não desabilitar controles de segurança do Windows
para executar testes locais. Revise o diff, confirme compatibilidade financeira
e relate limitações reais; não versionar relatórios com segredos nem fixtures
operacionais privadas.
