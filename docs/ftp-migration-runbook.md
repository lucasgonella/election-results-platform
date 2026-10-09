# Preparação da migração FTP — etapas 7 e 8 / PR #75

Este documento registra diagnóstico somente leitura de **09/10/2026, aproximadamente 18h15–18h35, America/Sao_Paulo**. Nenhum serviço, timer, endpoint, configuração, banco ou arquivo remoto foi modificado. Os procedimentos de escrita abaixo dependem de autorização posterior; não são comandos para executar nesta etapa.

## Evidências reais e limites

| Item | Evidência | Classificação |
| --- | --- | --- |
| Home SSH | `/home/storage/4/b7/e0/afgnet1`, UID/GID 542178, usuário `afgnet1`. | CONFIRMADO |
| Raiz pública operacional | `public_html` resolve para `/home/storage/4/b7/e0/afgnet1/public_html`; marcador e 140 JSONs servidos por HTTPS conferem byte a byte com essa árvore. Configuração do virtualhost não foi obtida. | CONFIRMADO: árvore servida; INFERIDO: document root do virtualhost. |
| Dados e API | `public_html/data`, `data/releases`, `public_html/api`; mesmo device 33. Dados 0755, marcador 0644, API 0775. | CONFIRMADO |
| Área privada existente | `.election-publisher` 0700; chave 0600; staging, backups, batches e test-public existentes fora de public_html. `includes` também está fora da área pública, com modo 0755. | CONFIRMADO |
| Identidade PHP | `ps` mostrou processos php-fpm com UID 542178, o mesmo usuário SSH. `/proc/.../exe` não pôde confirmar o executável do processo web. | CONFIRMADO: UID observado; PENDENTE: versão/configuração web. |
| CLI PHP | `/usr/bin/php8.4`, PHP 8.4.22; JSON/hash/PCRE/date disponíveis. Validação somente leitura do helper novo passou nos 137 arquivos reais; flock, fsync e rename existem. | CONFIRMADO para CLI `-n`; não comprova restrições do FPM. |
| Filesystem | NFS; df mostrou 464.336.512 KiB livres na montagem compartilhada e 3% de inodes usados. | CONFIRMADO; não representa quota da conta. |
| Uso da conta | `data` 35.720 KiB; `.election-publisher` 553.424 KiB; portal 2.160 KiB. Somente resultados da baseline: 11.087.245 bytes. `quota` não informou limite utilizável. | CONFIRMADO: uso; PENDENTE: quota. |
| FTP 21 | Conexão sem login e FEAT disponíveis; servidor anuncia EPSV/EPRT, MLST, REST, SIZE e UTF8. | CONFIRMADO: conectividade/capacidades anunciadas. |
| FTP PWD, raiz e usuário | Credenciais não estão nesta sessão nem no collector.env do app01. GitHub confirmou somente a existência dos três secrets. `LOCAWEB_FTP_GOIAS_DIR=public_html/eleicoes/goias/raio-x`. | NÃO VERIFICADO: PWD/identidade; INFERIDO: raiz provavelmente equivalente à home. |
| GitHub environments | Somente `https-staging` encontrado; staging/production e respectivas inbox vars não estavam configurados. | CONFIRMADO no momento da consulta. |
| app01 | HEAD `c273dfcaed764a7d04564b1d053e08f599dbbb10`; serviço como electioncollector; timers ativos; override HTTPS; publicação após coleta false. Chave existente 0600, UID 999/GID 982. | CONFIRMADO |
| Outros agendadores | Sem crontab para root, gonella e electioncollector; nenhuma referência eleitoral encontrada nos cinco diretórios cron examinados. Runner self-hosted instalado. | CONFIRMADO nesse escopo; não prova exclusividade global. |

Não foram executados STOR, MKD, RNFR/RNTO, DELE, ativação, testes de escrita ou testes de lock no servidor. A conta FTP ainda precisa de login para determinar PWD, MLSD/UID/perms e se alcança a área privada. A mesma identidade Unix de SSH e PHP **não** prova isolamento contra FTP. Se FTP tiver o mesmo UID e acesso à home, 0700/0600 não protegem a chave/estado contra essa conta; chroot/permissões da hospedagem precisam impedir esse alcance. Não criar credenciais duplicadas para contornar essa verificação.

## Baseline e estado confirmado

Release selecionada:

```text
fd062ecbbafbe78ddfc240658e70525b6bf9e0cf28a8e21d64e0fb4b55d985ba
environment: oficial
generated_at: 2026-10-09T16:27:48.601711+00:00
SHA-256 do marcador público: 69f3b4836d80927626980c5f3dd1d475ef3cde8036d0b1c9d1dcea352805d087
```

Os 137 resultados, manifest, version e alerts conferem com os arquivos SSH. O manifest do state tem os mesmos 137 registros e idgs; conteúdo semântico dos alertas coincide. A geração de metadados no state é posterior à geração do bundle público, sem mudança dos resultados. Portanto igualdade dos timestamps de bundle não é requisito da adoção; hashes exatos do checkpoint local são registrados separadamente.

`pending`/`stage` têm alterações em `to/governor.json`, `am/federal-deputy.json` e `am/state-deputy.json`. O governador tem a mesma geração/idg/fingerprint de fonte, com nova captura. No Amazonas:

| Target | Baseline: idg / geração | Pending: idg / geração | Alteração adicional |
| --- | --- | --- | --- |
| Deputado federal AM | 2799854 / 05/10 06:08:17 -03 | 3374388 / 09/10 15:11:57 -03 | final true → false; totalized_at recua. |
| Deputado estadual AM | 2791077 / 05/10 06:08:17 -03 | 3376197 / 09/10 15:11:59 -03 | final true → false; totalized_at recua. |

Esses são dados persistidos pelo serviço, não uma nova consulta TSE desta sessão. Timestamp posterior identifica uma geração nova, mas não autoriza ignorar a reabertura. A trava `totalization_reopened_requires_review` conserva a última release e bloqueia esse delta. Confirmar a semântica com o responsável e evidências oficiais antes de qualquer corte; não limpar watermarks ou trocar baseline pelo pending para contornar.

## Adoção assistida implementada e testada

O helper `prepare-ftp-baseline.php` usa **o mesmo validador** da publicação normal. Produz plano assinado com ID, hash do marcador, inventário dos 140 arquivos, watermarks dos 137 targets e hashes dos cinco arquivos do state. Verifica manifest, targets/idgs e alertas do state contra a release. Detecta mudança do marcador/checkpoint durante a leitura. Não modifica os dados públicos.

Inventário legado fica em `FTP_STATE/adopted-baselines/<snapshot_id>/inventory.json` e `inventory.sig`, fora da release. `fp_inventory` só usa esse certificado quando ambos os arquivos internos estão ausentes; nunca encobre um inventário interno corrompido. Releases novas continuam com seu inventário próprio.

O módulo `collector.src.ftp_baseline` verifica assinatura do plano, marcador recém-obtido e hashes exatos do state, sob o mesmo lock do runner FTP. Cria apenas `ftp-queue/confirmed.json`, sem fabricar recibo de publicação. Recusa entrega em voo ou checkpoint conflitante; repetição do mesmo plano é idempotente. Preserva state, pending, stage e caches.

Sequência futura, com escritores suspensos e gates desabilitados:

1. Congelar um checkpoint verificável de state/pending/stage, unidade/override/ambiente e release selecionada. Backups de ambiente/chaves permanecem protegidos, fora dos artefatos públicos, sem imprimir conteúdo. Registrar SHA do código e hash dos arquivos.
2. Comparar novamente os 140 hashes públicos/SSH e os 137 entries do state. Guardar cópia privada dos cinco arquivos **selecionados** de state para a validação cruzada; não transportar .env, chave, banco ou o diretório live completo. Se for necessário enviá-los à hospedagem, usar FTP para staging privado autorizado e manter permissões restritas. Não usar pending como estado confirmado.
3. Preparar o plano com PHP 8.4 e a chave já existente, em diretório privado novo. Exemplo de referência, com caminhos aprovados ainda a definir:

```text
/usr/bin/php8.4 <artefato-control>/files/tools/prepare-ftp-baseline.php <ftp-config.json> <copia-privada-do-state> <chave-existente> <novo-diretorio-do-plano>
```

4. Revisar o plano. Sob locks novo e oficial legado, verificar novamente hash do marcador, dos 140 arquivos e do checkpoint. Instalar apenas os certificados em `adopted-baselines/<id>` e o watermarks.json privado por arquivo temporário/rename. Não sobrescrever watermarks existentes de outra adoção; não editar a release legada nem o marcador. Só prosseguir com plano autenticado e hashes coincidentes; divergência exige novo plano/revisão.
5. Obter marcador fresco e plano assinado no app01 por leitura autenticada. A confirmação local futura é:

```text
<python-aprovado> -m collector.src.ftp_baseline --root /var/lib/election-results-platform/live --plan <plano-assinado> --marker <marcador-fresco> --key-file /etc/election-results-platform/secrets/hmac.key
```

6. Verificar que somente o novo confirmed.json mudou e que state/pending/stage continuam íntegros. Guardar o plano/certificado/backups. Preparação de plano e simulação de instalação passaram em fixtures locais; **nenhum desses passos foi executado em produção**. A instalação do certificado no servidor permanece assistida, sem endpoint genérico de adoção.

## Ativação de código, separada dos dados

Reutilizar `ftp-code-delivery.yml` → `deploy-locaweb-ftp.yml`. O workflow exige environment previamente existente; produção precisa de reviewers. O ID aprovado aparece no resumo do Actions e no artefato arquivado. Não confiar somente no READY recebido por FTP. `LOCAWEB_FTP_GOIAS_DIR` não é usado.

Para o controlador, o pacote contém um **único PHP público autossuficiente**, reunindo endpoint e helper. Isso evita uma requisição observar arquivos PHP de versões diferentes. Os dois helpers de adoção ficam em `tools/`, somente na inbox privada. Lint é aplicado aos PHPs efetivamente empacotados.

Para o portal, manter o diretório físico existente e Goiás. Colocar assets em `/eleicoes/releases/<artifact_id>/`; gerar HTMLs cujos recursos e navegação interna selecionam esse ID. Os links GO preservam `/eleicoes/goias/...`. Depois instalar entrypoints HTML por rename de arquivo temporário no mesmo diretório, com assets já completos. Não copiar manifest/checkpoint/ferramentas para a área pública. Root assets antigos permanecem para recuperação e caches.

`prepare-ftp-code-activation.py` prepara apenas um diretório novo de plano/arquivos. Confere ID aprovado, READY, allowlist, paths, tamanhos/hashes; registra hashes prévios dos entrypoints e a ordem assets → entrypoints. Não altera public_root. Exemplo futuro:

```text
python3 deploy/scripts/prepare-ftp-code-activation.py --artifact <inbox>/<id-aprovado> --expected-id <id-do-Actions> --public-root /home/storage/4/b7/e0/afgnet1/public_html --output <novo-diretorio-privado-do-plano>
```

Após revisão/autorização: adquirir lock de código por destino, comparar os hashes prévios ao plano, copiar e verificar backups privados, instalar assets sem alterar releases anteriores, copiar entrypoint para arquivo temporário no próprio diretório, verificar hash/modo 0644 e usar rename sem DELE. Registrar fase/ID e manter backups. Os entrypoints são trocados individualmente; HTMLs têm recursos fixos na própria release, sem depender de troca global simultânea de arquivos. PHP permanece com `enabled=false` até o corte de dados.

Rollback de código: validar backups e restaurar somente entrypoints por temporário/rename; assets versionados e originais são conservados. A antiga interface de favoritos não é compatível com o contrato novo: antes do corte, manter um artefato anterior de frontend **já validado com releases**, para recuperação após publicação FTP. Restauração da interface original exige revisão da compatibilidade e pode exigir rollback de dados primeiro.

Esse plano evita depender de symlinks, .htaccess ou troca de document root não comprovadas na hospedagem. Preparação e simulação de ativação/recuperação passaram localmente. Teste de escrita, rename/lock, permissões web e cache em staging da hospedagem **ainda não executado**.

## Corte HTTPS → FTP: referência para janela autorizada

1. Resolver todos os impeditivos da matriz abaixo. Registrar revisão aprovada, destinos FTP autenticados, configuração PHP/FPM, quota, chave existente e backup verificável. Preparar código do runner em uma release isolada legível por electioncollector; reutilizar a venv existente após validar imports. O CD HTTPS antigo não empacota o runner FTP e não instala /opt.
2. Com autorização específica, suspender `election-live-publisher.timer`; aguardar término da oneshot e verificar ausência de processos de publicação. Só interromper unidade pendurada sob supervisão, preservando stage/pending. Confirmar `PUBLISH_AFTER_COLLECT=false`; manter coleta histórica independente.
3. Desabilitar o gate legado `ENABLE_OFFICIAL_PUBLICATION` por movimento controlado para backup privado. Esperar requisições já iniciadas terminarem sob `official-publish.lock`. Gate remoto impede publicação manual tardia; parar só o timer não basta.
4. Fazer checkpoint/backups finais e adoção certificada. Configurar `legacy_lock` no novo ftp-config.json para o **mesmo** `.election-publisher/official-publish.lock`; o controlador novo adquire seu lock e o legado, ambos sem espera. A coexistência dos dois locks foi testada localmente, sem alterar o PHP legado.
5. Provisionar no app01 as mesmas credenciais FTP existentes, em arquivo protegido para electioncollector, e URL de controle nova. Reutilizar `/etc/election-results-platform/secrets/hmac.key`. Não guardar valores no Git ou em logs. A inbox deve ter acesso FTP confirmado e a área selada/chave precisam estar inacessíveis à conta de transporte.
6. Preparar override distinto, revisado, sem instalar agora. Exemplo:

```ini
[Service]
WorkingDirectory=/opt/election-results-platform-ftp/releases/<sha-aprovado>
EnvironmentFile=/etc/election-results-platform/ftp.env
ExecStart=
ExecStart=/opt/election-results-platform/.venv/bin/python -m collector.src.ftp_live_runner
```

7. Autorizar instalação do override e daemon-reload somente na janela de corte. Timer permanece suspenso. Configuração do novo endpoint habilitada só após baseline/certificado/locks verificados.
8. Primeira execução manual supervisionada do runner, só após resolver a reabertura do Amazonas. Esperar recibo e conferir por GET marcador, 140 hashes e leitores. Se falhar, preservar release e fila; não chamar commit nem coletar novamente para apagar a entrega. Reconciliar ID por status antes de retentar.
9. Sucesso exige 137 targets, todos os hashes corretos, baseline/journal coerentes, state correspondente ao recibo, nenhuma execução/gate legado habilitado e ausência de erros/fila crescente. Somente então retomar o timer autorizado e observar vários ciclos com freshness, erro de transporte, espaço e reabertura monitorados. Não alterar sua frequência sem necessidade/revisão.

## Reversão

- Antes da primeira ativação: dados públicos e state permanecem intactos. Suspender o novo runner, manter gates fechados, restaurar configuração/entrypoints revisados a partir dos backups. Não reativar uploads HTTPS como fallback automático contra a política FTP.
- Depois da primeira ativação: suspender acionadores FTP e reconciliar entrega em voo; usar rollback autenticado da entrega corrente para a baseline certificada. Verificar 140 hashes. O helper aceita inventário privado da baseline legada e conserva watermarks, inclusive a barreira de finalização.
- Restaurar o checkpoint local correspondente ao marcador sob supervisão, a partir do backup ou `ftp-queue/previous-<delivery_id>`. Preservar fila, recibos e estados posteriores para auditoria; não apagar state nem reduzir watermarks. Reconciliar confirmed.json somente com plano/estado correspondente. Não permitir que um recibo histórico seja confundido com o marcador corrente após rollback.
- Reverter código só para artefato compatível com o marcador selecionado. Se não houver alvo íntegro, conservar a release atual e suspender publicação; não fazer uploads individuais para compensar. Mudança de política para retomar HTTPS exigiria autorização explícita própria.

## Matriz de bloqueios e checklist de liberação

| Bloqueio | Estado | Condição de liberação |
| --- | --- | --- |
| Layout SSH, árvore servida e 140 hashes | RESOLVIDO | Revalidar checkpoint na janela. |
| State confirmado vs baseline/alertas | RESOLVIDO | Congelar escritores antes de emitir plano final. |
| idg real numérico | RESOLVIDO | Validador corrigido; CLI validou 137 dados reais sem escrita. |
| Procedimento de adoção | RESOLVIDO no código/testes locais | Instalação privada permanece não executada e assistida. |
| Exclusão com lock oficial legado | RESOLVIDO no código/testes locais | Configurar path real e testar no staging; suspensão/gate ainda não realizados. |
| Ativação recuperável de código | RESOLVIDO como plano/teste local | Execução na hospedagem e teste de cache/permissões pendentes. |
| FTP PWD/UID, destinos e inbox privada | IMPEDITIVO | Login de leitura com credenciais existentes; confirmar mapeamento e acesso. |
| Isolamento de chave/estado/código contra FTP | IMPEDITIVO | Provar restrição efetiva; mesmo UID com acesso à home é insuficiente. |
| Reabertura dos resultados AM | IMPEDITIVO para primeira entrega | Revisão oficial/operacional e regra explícita, testada; não remover a trava. |
| PHP web e NFS real: escrita/lock/rename/cache | IMPEDITIVO para corte | Staging autorizado no runtime web e filesystem reais. CLI não substitui essa prova. |
| Quota da conta, retenção e espaço de segurança | PENDENTE | Confirmar quota; reservar builds, sealed, releases e backups; definir alertas/limpeza supervisionada. |
| Environments staging/production e vars novas | PENDENTE | Configurar destinations separados, reviewers de produção e acesso API do preflight. |
| Credenciais no app01 e runner instalado | PENDENTE | Provisionar credenciais existentes e release aprovada sem mudar serviços fora da janela. |
| Backup/restauração real e leitores no navegador | PENDENTE | Ensaio de staging com artefato anterior compatível e testes de recuperação. |

**Conclusão:** apto a continuar a preparação e o ensaio local; **não apto ao corte de produção**, mesmo supervisionado, enquanto os quatro impeditivos permanecerem. Nenhum deles deve ser interpretado como autorização implícita para modificar a hospedagem.

Diagnóstico reproduzível (somente leitura remota, relatório local sem segredos):

```text
python deploy/scripts/audit-ftp-migration.py --report <arquivo-local-novo.json> --ftp --public-hashes --validate-php
```

O FTP lê somente variáveis já provisionadas no ambiente; sem elas, informa indisponibilidade e consulta apenas FEAT sem login. O relatório não deve ser commitado: contém metadados operacionais datados. Testes de adoção/ativação usam fixtures; nenhuma coleta oficial ou publicação real foi executada nesta etapa.

Validação final local da etapa 7: **226 testes aprovados e 1 excluído**, o teste Bash legado bloqueado pelo Windows. PHP lint aprovado; pacote público autossuficiente validado com PHP CLI. Testes novos cobrem adoção/idempotência, marcador/state/assinatura alterados, pending incompatível, certificado sobre release corrompida, rollback para baseline legada, lock oficial concorrente, idg inteiro/string e ordem de chaves, reabertura bloqueada, artefato aprovado/corrompido, staging fora de public_root e recuperação dos entrypoints preservando data/Goiás. `git diff --check` aprovado. Teste real de transferência/ativação na hospedagem não foi executado.

## Etapa 8 — evidências adicionais de 09/10/2026

Diagnóstico remoto exclusivamente de leitura, aproximadamente 18h59–19h10 America/Sao_Paulo. SSH executou Python por stdin para `stat`, `os.access`, leitura de `/proc/mounts` e comparação dos resultados eleitorais. Não foram lidos conteúdos de chaves, configurações privadas ou estado selado. Nenhum endpoint foi ativado; não houve comandos FTP de escrita, alteração de serviços ou testes remotos com arquivos temporários. As leituras do estado live não congelam o serviço: são observações datadas, não um checkpoint de adoção.

### Identidade FTP e separação de transporte/controle

Nesta sessão, `LOCAWEB_FTP_HOST`, `LOCAWEB_FTP_USER` e `LOCAWEB_FTP_PASSWORD` estão ausentes do ambiente do processo. A etapa 7 confirmou a existência dos secrets no GitHub, mas seus valores não são recuperáveis pela API de secrets. Não foram solicitadas novas senhas nem iniciado workflow para extrair credenciais. A conexão sem login a `ftp.afgnet.com.br:21` respondeu a FEAT, anunciando MLST, SIZE, EPSV e UTF8. **Não houve autenticação FTP**: login, PWD, UID, chroot, mapeamento FTP→SSH e direitos da conta continuam NÃO VERIFICADOS.

Metadados revalidados por SSH, sem leitura dos arquivos:

| Caminho relativo à home SSH | Existência / modo / proprietário | Limite da evidência |
| --- | --- | --- |
| `.election-publisher` | Existe, 0700, UID/GID 542178. | SSH tem acesso de leitura/escrita segundo `os.access`; FTP desconhecido. |
| `.election-publisher/hmac.key` | Existe, 0600, UID/GID 542178. | Somente stat/access; conteúdo não lido. FTP desconhecido. |
| `.election-publisher/official-publish.lock` | Existe, 0644, UID/GID 542178. | Não aberto nem adquirido. |
| `public_html/api/election-publish.php` | Existe, 0644, UID/GID 542178. | SSH tem acesso segundo `os.access`; conteúdo remoto não lido. FTP desconhecido. |
| `.election-publisher/ftp-config.json` | Ausente nesse caminho fixo do endpoint novo. | Não comprova ausência de outras configurações privadas. |
| `public_html/api/election-ftp-control.php` | Ausente no destino esperado. | Controlador FTP não instalado nesse caminho. |
| `.election-publisher/ftp-state` e `.election-publisher/sealed` | Ausentes nesses dois caminhos examinados. | `cfg.private` é configurável; não são prova de ausência global de estado selado. |

A ausência de `ftp-config.json` impede determinar o destino efetivo de `cfg.private/sealed` do novo protocolo. Não se deve inventar um path operacional a partir do exemplo de configuração. O PHP-FPM observado na etapa 7 compartilha o UID SSH; identidade FTP continua desconhecida.

**Menor ajuste recomendado, condicionado ao diagnóstico autenticado:** restringir a conta FTP existente a um namespace de transporte que exponha somente inboxes aprovadas e os destinos legados necessários a Goiás. A restrição deve excluir chave, configuração, estado selado, locks e PHP executável, incluindo caminhos absolutos, `..` e links simbólicos. Preferir configuração de raiz virtual/chroot/allowlist suportada pelo provedor, preservando secrets e destinos existentes. Não mover a chave para um diretório dentro da mesma raiz FTP nem usar chmod mais permissivo. Se a hospedagem não puder impor essa fronteira à conta existente, a separação de identidade/conta pelo provedor exige decisão e autorização posteriores; não duplicar credenciais por iniciativa do agente.

Para liberar: em uma sessão autorizada que já receba os secrets existentes, executar login, PWD, SYST e MLST/MLSD seletivos. Comparar UID/mode/paths com a tabela SSH. Não listar conteúdo privado indiscriminadamente, não usar RETR de arquivos sensíveis e não imprimir usuário/senha. Listagem negada isoladamente não prova impossibilidade de escrita: confirmar também a política de confinamento/allowlist do provedor, já que testes de escrita estão proibidos nesta etapa.

### Amazonas: origem oficial confirmada, causa ainda não confirmada

Os URLs foram obtidos das chaves do `target-state.json` no app01, sem adivinhar caminhos. Foram feitos dois GETs diretos, ambos HTTP 200, em **21:58:58–21:58:59 UTC**:

| Cargo / URL oficial | IDG | Geração (`dg`/`hg`) | Totalização (`dt`/`ht`) | `tf` | SHA-256 dos bytes recebidos |
| --- | --- | --- | --- | --- | --- |
| [Federal AM](https://resultados.tse.jus.br/oficial/ele2026/6259/dados/am/am-c0006-e006259-u.json) | 3374388 | 09/10/2026 15:11:57 | 05/10/2026 05:05:12 | n | `43148bcdb03d765b640ec7d154a475b2b44efa949471d77aba96a8eb747681a4` |
| [Estadual AM](https://resultados.tse.jus.br/oficial/ele2026/6259/dados/am/am-c0007-e006259-u.json) | 3376197 | 09/10/2026 15:11:59 | 05/10/2026 05:05:12 | n | `f9aea70e97c6b479b969bdc8a20407deca70d056cc174df788c7a093f29eeb2e` |

Last-Modified: respectivamente `09/10/2026 18:13:42 GMT` e `18:13:44 GMT`. Ambos indicam 8157/8157 seções totalizadas (100%). Os IDs e horários coincidem com o pending observado na etapa 7 e com os resultados em stage revalidados nesta etapa. Os resultados incrementais estavam em stage; a inspeção de `pending/<uf>/<cargo>.json` não encontrou esses arquivos, portanto não se atribui ao pending uma estrutura de arquivos igual à de stage.

A release pública selecionada continua `fd062ecbbafbe78ddfc240658e70525b6bf9e0cf28a8e21d64e0fb4b55d985ba`. Os dois resultados nela mantêm IDGs 2799854/2791077, geração 05/10 06:08:17, totalização 05/10 05:07:34 e `totalization_final=true`.

Comparação baseline→stage por **identidade `tse_candidate_seq`**, não por posição: mesmos conjuntos de 135 candidatos federais e 278 estaduais; totais de votos e seções iguais. Não foram encontradas mudanças nos campos de votos dos candidatos. Mudaram `result_status` de todos, `elected` de 8 federais/24 estaduais, `display_order` de 102/219 candidatos, `seat_allocations` dos dois cargos e `candidate_status` de um candidato estadual. Portanto não é apenas atualização de captura e não basta comparar total de votos para liberar a entrega.

**CONFIRMADO PELO CÓDIGO:** `collector/src/parser.py`, `as_bool`, converte `s→true` e `n→false`; `parse_ea20` usa `tf`, `dg/hg` e `dt/ht` diretamente. O false observado corresponde ao campo original do TSE, não a erro dessa conversão. A origem oficial atual dos dados está confirmada por HTTPS; isso não prova a causa administrativa/judicial da mudança.

A [FAQ técnica do TSE 2026](https://www.tse.jus.br/eleicoes/informacoes-tecnicas-sobre-a-divulgacao-de-resultados/) descreve IDG como identificador único de geração; não oferece nessa resposta garantia de ordenação monotônica. Também alerta para geração paralela e diferenças de sincronização na CDN. Isso permite considerar sincronização ou reprocessamento como hipóteses, não concluir que explicam este caso. O [TRE-AM publicou a conclusão do primeiro turno em 05/10 às 12h36](https://www.tre-am.jus.br/comunicacao/noticias/2026/Outubro/eleicoes-2026-justica-eleitoral-divulga-relatorio-de-conclusao-do-primeiro-turno), com bancada federal e 24 cadeiras estaduais definidas; a notícia antecede os arquivos de 09/10 e não certifica sua situação atual.

**NÃO VERIFICADO:** reabertura/retotalização oficialmente autorizada para esses dois cargos, causa da retirada das indicações de eleito/alocações e significado operacional do recuo do horário. A pesquisa oficial consultada não forneceu ato que explique essas gerações; isso não prova inexistência do ato. O link EA20 foi localizado na documentação oficial, mas o PDF não pôde ser obtido/validado nesta sessão. Para liberar, obter esclarecimento técnico do TSE/TRE-AM ou relatório/ato oficial referente à eleição 6259, abrangência AM, cargos 6/7 e essas gerações, acompanhado de dados oficiais coerentes. Qualquer eventual regra de exceção exige análise e testes próprios, revisão e autorização. **Preservar `totalization_reopened_requires_review`, baseline, watermarks e pending; não adotar stage como baseline para contornar o gate.**

### NFS e staging real: risco adicional comprovado

Leitura de `/proc/mounts` confirmou `/home/storage` em **NFS v3**, com opções relevantes `rw,noexec,acregmin=60,acdirmin=60,soft,nocto,nolock,noacl,local_lock=all`. A etapa 7 já confirmou device 33 comum à home/áreas pública e privada.

**CONFIRMADO:** a montagem anuncia locks locais, sem coordenação NFS de locks. **INFERIDO:** `flock` pode serializar processos no mesmo host, mas não oferece a garantia necessária entre hosts diferentes usando essa montagem. **NÃO VERIFICADO:** quantidade de nós PHP/web, afinidade do endpoint, montagens nos outros nós e visibilidade de rename/cache entre clientes. A existência de flock/rename/fsync no CLI não resolve esse bloqueio. Cache de atributos e `nocto` exigem verificar visibilidade entre processos/nós; não se presume atraso exato de 60 segundos para todas as leituras HTTP.

| Ensaio mínimo | Categoria | Evidência / critério de aprovação |
| --- | --- | --- |
| Metadados de paths, UID/modes/device, mount options, quota, versão CLI | Somente leitura | Confinamento, destinos e capacidade documentados; não confundir CLI com FPM nem df com quota. |
| Topologia PHP/web, pool/UID, restrições FPM, OPcache e política de cache | Somente leitura do painel/configuração sanitizada pelo operador | Identificar todos os hosts que podem ativar/servir e as restrições efetivas. Não instalar phpinfo nem chamar endpoint mutável para diagnosticar. |
| HEAD/GET de marcador e arquivos estáticos já existentes | Somente leitura | Registrar Cache-Control, ETag, Age/Last-Modified e hashes; demonstra configuração observada, não atomicidade. |
| Harness PHP-FPM com fixtures em namespace staging dedicado | **Cria arquivos; autorização específica necessária** | Runtime web efetivo, mesma montagem e permissões equivalentes, sem caminhos/key/dados de produção; UID, fsync e limites verificados. Não ativar endpoint nesta etapa. |
| Lock concorrente e recuperação após saída de worker | **Cria/abre lock de teste; autorização necessária** | Dois workers no mesmo host e em hosts distintos disputam o mesmo lock; nunca há dois ativadores. Testar também lock compartilhado com harness do legado. Se multihost + lock local, reprovar e exigir confinamento de execução ou solução de locks do provedor, com autorização. |
| Rename de marcador de fixture sob leitores concorrentes | **Escrita temporária; autorização necessária** | Leitores locais/FPM/HTTP em todos os nós observam somente JSON antigo ou novo íntegro; nenhum 404/JSON parcial. Registrar latência de visibilidade; mesmo filesystem para temporário/destino. |
| Cache/OPcache e troca/rollback de PHP fixture | **Escrita temporária; autorização necessária** | Código/HTML/JSON correspondem à versão ativada em todos os nós; rollback recupera versão coerente, respeitando caches. |
| FTP interrompido, hash incorreto, ativação/resposta perdida e rollback | **Uploads e escrita; autorização necessária** | Somente conta/destinos staging aprovados e fixtures locais de 137 targets; release anterior preservada, idempotência e reconciliação demonstradas. Nunca arquivos eleitorais reais. |

Preparar staging privado separado para inbox/controle e uma árvore pública de teste com acesso restrito e fixtures, sem reutilizar `/data`, chave ou estado real. Sua criação, eventual harness/endpoint temporário, uploads e limpeza são mudanças a autorizar separadamente. Antes do ensaio registrar paths/hosts/limites, responsáveis e plano de remoção exclusivo desse namespace; após autorização, guardar evidências e repetir rollback. Nada dessa sequência foi executado nesta etapa.

### Matriz atualizada dos quatro impeditivos

| Impeditivo | Evidência e diagnóstico | Risco | Solução recomendada | Estado | Ação para liberação |
| --- | --- | --- | --- | --- | --- |
| Identidade/raiz FTP | Porta 21/FEAT funcionam; três variáveis ausentes na sessão; nenhum login. PWD/UID/destinos desconhecidos. | Entrega em diretório incorreto ou público; isolamento presumido. | Usar sessão autorizada com os secrets existentes; diagnóstico seletivo de leitura. | IMPEDITIVO | Comprovar autenticação/PWD/mapeamento e paths permitidos, sem solicitar novas senhas. |
| Fronteira transporte/controle | Chave 0600 e PHP 0644 pertencem ao UID SSH 542178; alcance FTP desconhecido; config FTP fixa ainda ausente. | Mesmo UID e home irrestrita podem permitir adulteração do controle/estado e acesso à chave. | Restrição efetiva da conta existente por raiz virtual/chroot/allowlist; decisão do provedor se isso for impossível. | IMPEDITIVO | Evidência de confinamento incluindo traversal/symlinks e exclusão de chave, configuração, sealed e PHP; não enfraquecer modos. |
| Amazonas final→não final | GET oficial confirma IDGs do pending, tf=n, horário recuado e 100% de seções; stage perde marcações de eleito/alocações, sem mudança de votos. Causa oficial não demonstrada. | Publicar estado não final/regressivo ou perder eleitos apesar de votos iguais. | Esclarecimento/ato oficial e revisão da situação, preservando o gate. | IMPEDITIVO para primeira entrega | Evidência oficial específica e payload coerente; eventual tratamento autorizado e testado, sem apagar estado. |
| PHP-FPM/NFS/cache/rollback | NFS v3 `nolock,local_lock=all,nocto` e caches; CLI testado na etapa 7; topologia web desconhecida. | Ativadores multihost concorrentes; marcador/código divergente em caches; recuperação não comprovada. | Confirmar topologia/garantia de lock e executar plano staging isolado após autorização. | IMPEDITIVO para corte | Ensaio em todos os nós relevantes, lock exclusivo, rename/visibilidade e rollback aprovados; se locks multihost não forem garantidos, manter bloqueio. |

Nenhum dos quatro impeditivos foi resolvido por completo. Diagnóstico da origem dos dados AM e opções NFS avançou; solução operacional permanece pendente. O projeto **não está apto ao corte de produção**, inclusive supervisionado, até essas condições serem atendidas. Alteração desta etapa: somente este runbook; arquitetura/código/serviços permanecem preservados. Não se repete a suíte local da etapa 7 por mudança exclusivamente documental; validar diff e fontes.

## Missão final — preparação com credenciais existentes

Evidências de 09/10/2026, aproximadamente 19h15–19h40 America/Sao_Paulo. Esta seção substitui as lacunas de autenticação anteriores, sem transformar observações antigas em fatos atuais. Não houve escrita remota, deploy, instalação de endpoint, mudança de unidade/timer, upload ou coleta pelo agente.

### FTP autenticado e risco de controle confirmado

O arquivo Windows `.secrets/ftp.env` existe e contém os nomes `LOCAWEB_FTP_HOST`, `LOCAWEB_FTP_USER`, `LOCAWEB_FTP_PASSWORD`, `LOCAWEB_FTP_PORT`. Está ignorado pelo Git; nenhum valor foi impresso. Autenticação via FTP 21 bem-sucedida, **PWD inicial `/`**. Operações utilizadas: login, PWD, FEAT/OPTS MLST e MLST/MLSD de metadados; nenhum RETR de conteúdo sensível, STOR, MKD, DELE ou rename.

| Caminho FTP | Caminho SSH / evidência de correspondência |
| --- | --- |
| `/` | `/home/storage/4/b7/e0/afgnet1`; MLST UID 542178; `../../` resolve novamente para `/`. |
| `/public_html` | `.../afgnet1/public_html`; MLST unique `21g7a4c0c`, inode SSH 8014860 (`0x7a4c0c`), device 33, UID 542178. |
| `/.election-publisher/hmac.key` | `.../afgnet1/.election-publisher/hmac.key`; MLST unique `21gb11d68`, inode SSH 11607400 (`0xb11d68`), UID/GID 542178, modo 0600, 65 bytes. Conteúdo não lido. |
| `/public_html/api/election-publish.php` | Mesmo inode correspondente ao SSH; arquivo PHP legado alcançável pela conta. Conteúdo remoto não lido. |

MLST da chave e do PHP anuncia `perm=radfwMT`, incluindo capacidade anunciada de leitura/escrita; `.election-publisher` também é alcançável. **Isolamento insuficiente confirmado**, independentemente de chmod. Não foi testado STOR para provar escrita: o alcance da chave já invalida a fronteira exigida. O UID dos objetos não prova sozinho o UID efetivo do daemon FTP, mas o acesso anunciado aos mesmos objetos demonstra o problema operacional.

`/etc/passwd` e o caminho SSH absoluto responderam 550; nenhuma symlink foi anunciada na listagem da raiz. Isso sugere confinamento à home, não isolamento de controle dentro dela, nem prova ausência de links/traversal em toda a árvore. Não houve tentativa de explorar ou ler arquivos externos.

Não existem `ftp-inbox`, `ftp-inbox/elections` ou `ftp-inbox/code` na home SSH; nenhum diretório de transporte com nome ftp/inbox/staging foi encontrado na raiz. `.election-publisher/staging` existe, mas **não usar** como inbox nova: pertence à área de controle exposta. Destinos propostos, ainda não provisionados:

```text
SSH: /home/storage/4/b7/e0/afgnet1/ftp-inbox/elections/{staging,production}
SSH: /home/storage/4/b7/e0/afgnet1/ftp-inbox/code/{staging,production}/{portal,control}
FTP atual: /ftp-inbox/... (mapeamento após restrição da conta deve ser revalidado)
```

O provedor deve restringir a conta existente a destinos de transporte e Goiás aprovados, excluindo chave/configuração/estado/inventários/journals/recibos/PHP. Preservar `public_html/eleicoes/goias/raio-x` e os secrets existentes. Se chroot/allowlist com namespace virtual não for suportado, exigir decisão de separação de identidade pelo provedor; nenhuma conta ou senha duplicada foi criada. Não criar inbox dentro de public_html nem enfraquecer modos. A configuração do confinamento e criação dos destinos exigem autorização de infraestrutura e não foram executadas.

### app01 preparado, sem instalação

`/etc/election-results-platform/secrets/ftp.env`: **0600, UID 999/GID 982**, legível por `electioncollector`; contém exatamente os quatro nomes FTP acima. Virtualenv `/opt/election-results-platform/.venv/bin/python`: Python **3.14.4**, requests/dotenv/psycopg disponíveis. Unidade existente continua como electioncollector, usando o wrapper legado; timer ativo/habilitado. HEAD instalado continua `c273dfcaed764a7d04564b1d053e08f599dbbb10`. `live_publisher.py`, `parser.py` e `discovery.py` conferem byte a byte com a branch; os componentes FTP novos exigem instalação futura da revisão aprovada.

State/pending/stage existem; `ftp-queue/confirmed.json` e `ftp-queue/current.json` não existem. Isso exige adoção assistida antes da primeira execução, sem descartar pending. Não repetir instalação do virtualenv indiscriminadamente: validar a revisão aprovada em Python 3.14 e preservar a instalação/rollback anterior.

Preparados localmente:

- `run-ftp-live-publisher.sh`: executa diretamente o runner novo, sem source/eval de credenciais e sem prepare/commit legado adicional.
- `ftp-live-publisher.override.conf.example`: acrescenta EnvironmentFile protegido FTP e configuração operacional, limpa/substitui ExecStart da **mesma unidade**, conserva timer e identidade, usa UMask 0077. Instalar somente na janela autorizada, com ordem de drop-ins revisada frente a https.conf.
- `ftp-publisher.env.example`: dois gates false, paths/URL/chave existente, porta 21. Aprovação de corte e isolamento é operacional, não uma forma de ignorar gates automáticos.
- Pré-validação do runner antes de qualquer state/TSE: configuração obrigatória, porta 21, destino privado, arquivo regular sem symlink, ownership pelo UID efetivo e ausência de permissões de grupo/outros em POSIX.

O transporte inspeciona MLST de caminhos de controle relativos e absolutos após login e **antes de MKD/STOR**. Caminho sensível visível ou comando inconclusivo bloqueia. Negação 550 é requisito necessário, não prova suficiente de confinamento; aprovação do provedor permanece indispensável.

### Amazonas: semântica oficial obtida, causa ainda bloqueada

O [leiaute EA20 de 10/07/2026](https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/tse-ea20-arquivo-de-resultado-unificado) foi acessado nesta missão. Páginas 9–10: `tf=s` significa totalização final e `tf=n` significa ausência dela; finalização é o processo de encerramento da eleição com atribuição ou não de eleitos e não equivale somente a 100% das seções. Página 13: `e` indica eleito/segundo turno; página 14: `st` é preenchido quando existe totalização final. Página 12: `vag` representa vagas da agremiação, sujeitas a atualização durante totalizações.

Isso confirma a interpretação do parser e a relevância das indicações removidas no delta AM. Não explica a razão de `s→n` nem fornece autorização oficial para reabertura dessas gerações. A pesquisa oficial nesta missão não trouxe justificativa específica suficiente. Registrar solicitação humana ao TSE/TRE-AM com eleição/UF/cargos/IDGs/horários/hashes já documentados; não enviar credenciais ou estado interno. O formulário oficial indicado na página técnica do TSE é `https://30308800.tse.jus.br/`; nenhum chamado/mensagem foi enviado pelo agente. Nova fixture cobre 100% de seções com perda de eleito e `tf=false`: a ativação é rejeitada e a release anterior preservada.

### PHP/NFS: mitigação local e ensaio preparado

`activation_host` agora é obrigatório no controlador/helper. Ausente ou diferente de `gethostname()`, falha antes de nonce, lock ou escrita. A restrição protege contra ativadores em hosts diferentes sobre NFS com locks locais; ainda exige provar que o hostname identifica um host único e que o endpoint pode ser roteado/servido nesse host. **Não resolve** por si só topologia, disponibilidade, caches, durabilidade ou coordenação com um legado ativo em outro nó. Manter o corte bloqueado e o legado suspenso durante o futuro ensaio/corte autorizado.

`prepare-ftp-staging.py` gera **somente localmente**, em diretório novo `ftp-staging-*`, fixtures completas/delta de 137 targets, chave aleatória descartável e probe privado/público isolado. O probe não é incluído no pacote da aplicação. Na interface web exige HTTPS POST autenticado com chave de fixture; permite somente runtime, lock, troca A/B de marcador e leitura, sem paths/comandos arbitrários. Namespace/configuração de fixture obrigatórios; duração de lock limitada a dois segundos. Não usar chave ou dados de produção.

Ensaio futuro autorizado: configurar namespace remoto exclusivo e root correto; confirmar FPM/host/OPcache via runtime; disparar locks concorrentes de workers/nós; executar trocas A/B sob leitores locais/web de todos os nós; medir hashes/cache/visibilidade; testar código de fixture anterior/novo e recuperação; depois protocolo completo/delta, FTP interrompido, resposta perdida e rollback usando fixtures e configuração privada separada. Registrar nó atendente e nunca deduzir multinó de muitas requisições ao mesmo nó. Não resetar OPcache global ou cache de produção. Instalação/provisionamento, todas as escritas e limpeza continuam dependentes de autorização específica.

### CI/CD e divergência com main

Na leitura inicial, PR #75 estava em rascunho com os três checks anteriores aprovados. Branch 7 commits atrás e 3 à frente de main; os sete commits exclusivos da main são financeiros de Goiás. Não foram incorporados nem alterados; não houve merge. Revalidar divergência e conflitos na revisão final.

Workflows novos preservam secrets existentes e não alteram workflows financeiros. O reutilizável falha em ref/componente/ambiente inválidos; exige environment existente, reviewers em production, aprovação de isolamento e inbox terminada em `code/<ambiente>`. Concurrency conserva um grupo por destino de ambiente, sem cancelamento de entregas em curso. Staging/production têm namespaces distintos; portal/control são serializados no mesmo ambiente. Checkout fixa github.sha, valida toda a suíte, empacota allowlist e registra/archive o ID do artefato; antes de upload verifica novamente ID/READY/allowlist/bytes/symlinks/arquivos extras. Nenhuma ativação pública é feita pelo workflow.

CI FTP executa a suíte em Python 3.13 e 3.14, incluindo PHP e harness; aprovação do CI não resolve infraestrutura. Os environments/vars e o acesso do GITHUB_TOKEN ao preflight de environment ainda exigem validação na configuração real; falha de leitura interrompe o workflow. Não foi disparado workflow de entrega para testar esse acesso.

O caller e o reutilizável declaram `actions: read`, permissão mínima documentada para [Get an environment](https://docs.github.com/en/rest/deployments/environments#get-an-environment). Isso corrige a omissão local de permissão sem criar token ou conceder escrita administrativa. A validação do acesso/configuração no ambiente real permanece necessária.

### Checklist exato de implantação — somente após liberação

1. **Provedor:** restringir FTP e criar destinos privados staging/production aprovados; comprovar ausência de acesso a todo controle e código, inclusive traversal/links. Revalidar PWD/mapeamento; definir quota/retensão e reservas de espaço.
2. **Staging autorizado:** instalar somente harness/fixtures no namespace exclusivo, com configuração adaptada; executar todos os ensaios FPM/hosts/lock/NFS/rename/cache/rollback acima. Guardar evidências e remover somente o namespace de teste conforme autorização.
3. **Dados oficiais:** obter esclarecimento suficiente sobre AM e revisão humana. Não liberar a primeira entrega enquanto o gate rejeitar o pending. Nenhuma exceção automática está prevista.
4. **Revisão:** CI verde da revisão exata, revisão do PR e integração supervisionada com main; environments/vars/reviewers/inboxes distintos e leitura do preflight confirmados. Nenhum merge automático.
5. **Entrega de código:** workflow manual, main aprovada e componente/ambiente correto; arquivar artifact_id/checksum. Preparar plano privado com `prepare-ftp-code-activation.py`; revisar allowlist, hashes prévios e backups. Ativação é uma operação separada autorizada; arquivos offline de tools ficam privados.
6. **Checkpoint de corte:** autorização explícita, suspender timer/escritor legado controladamente e aguardar serviço inativo; provar ausência de outros escritores. Guardar override/unidade/revisão instalada, configuração protegida, cinco arquivos state, pending/stage, marcador, 140 hashes, chave existente e releases em backup privado. Nunca imprimir ou empacotar esses segredos.
7. **Adoção:** executar o procedimento assistido anterior com release selecionada/state congelados; instalar certificados/watermarks sob locks aprovados, verificar novamente hashes e criar confirmed.json autenticado. Preservar state/pending/stage. Não certificar pending como baseline.
8. **Instalação app01:** instalar revisão/virtualenv aprovados de modo recuperável, configurar ftp-publisher.env com paths/host/URL/gates revisados, instalar drop-in de corte em ordem que substitua ExecStart legado. Não alterar intervalo do timer. `daemon-reload`/acionamento somente na janela autorizada. Timeout atual de 2min deve ser medido em staging; alteração futura exige revisão/autorizaçao e não contornar erro com uploads públicos.
9. **Primeira entrega:** acionar runner supervisionado somente depois dos gates; verificar recibo, snapshot_id, marcador público e 140 hashes/137 targets, portal/favoritos na mesma release e estado confirmado exato. Estado local só muda após recibo válido; pending rejeitado continua preservado.
10. **Observação:** confirmar vários ciclos sem concorrência, fila/latência/logs/retensão/backup e rollback verificáveis; então retomar agendamento autorizado. Falha em qualquer gate interrompe o corte e mantém/restaura a última release íntegra.

### Rollback verificável

1. Autorizar e suspender o novo runner/timer; aguardar inatividade. Congelar fila/current.json/recibo/confirmed/state e coletar marcador/hashes; não apagar fila nem watermarks.
2. **Dados:** controle HMAC `rollback` com delivery_id corrente seleciona apenas a anterior registrada no journal, após inventário/hashes válidos. Verificar nova activation_revision, alvo, 137 resultados, metadados e leitores. Watermarks permanecem altos; alvo corrompido não é ativado. Repetição é idempotente.
3. **Código:** usar backup privado/artefato anterior aprovado e plano recuperável; comparar hashes atuais contra os previstos, instalar recursos anteriores íntegros e trocar entrypoints por temporário+rename no mesmo filesystem. Verificar código/HTML/assets e caches em todos os nós. Não sobrescrever arquivo público durante FTP.
4. **app01:** restaurar revisão/virtualenv e drop-in anterior verificados. Remover/restaurar somente o override FTP criado na janela, preservando https.conf original; daemon-reload e eventual retomada exigem autorização. Não iniciar o wrapper legado com state FTP divergente da release restaurada: reconciliar checkpoint/fila/baseline assistidamente primeiro.
5. Revalidar marker/140 hashes/state e exclusividade. Se AM/isolamento ainda bloquearem, conservar a release íntegra sem tentar publicar o pending. O legado não é fallback automático autorizado para novos uploads; uma retomada operacional exige decisão explícita.

Publicação/rollback e recuperação de baseline legada continuam cobertos pela suíte existente. Os novos testes exercitam veto antes de upload, gates antes de coleta, host divergente sem escrita, integridade/extra de artefato, cenário AM não final com 100% de seções e harness local de lock/rename/recuperação. Ensaios remotos não executados.

### Situação final dos quatro impeditivos

| Item | Estado atualizado | Liberação restante |
| --- | --- | --- |
| A — autenticação/identidade/mapeamento | **RESOLVIDO** para leitura; **PENDENTE** provisionamento dos destinos | Criar inboxes privadas autorizadas e revalidar mapa após confinamento. |
| B — isolamento de controle | **IMPEDITIVO**, exposição confirmada | Provedor restringir conta existente/namespace; prova de separação da chave/estado/código. Gate local implementado não altera ACL. |
| C — Amazonas | **IMPEDITIVO para primeira entrega** | Semântica EA20 confirmada; causa/legitimidade da mudança exige evidência oficial e validação humana. |
| D — PHP/NFS/cache | **IMPEDITIVO para corte** | Pin de host e harness implementados/testados localmente; topologia e ensaios remotos de escrita não autorizados. |

**BLOQUEADO para implantação de produção.** Preparação local pode ser revisada no PR; impedimentos restantes exigem autorização/configuração da hospedagem, ensaio real ou esclarecimento oficial. Nenhum deles pode ser eliminado com chmod mais permissivo, remoção de gates ou descarte de pending.

Validação final local desta missão: **254 testes aprovados, 1 excluído** (sintaxe Bash legado indisponível no Windows); lint dos dez arquivos PHP aprovado e `git diff --check` aprovado. Harness local comprovou runtime CLI, exclusão de dois processos concorrentes, troca A/B e recuperação do marcador em fixtures. Essas evidências não representam PHP-FPM, multinó ou NFS reais. CI Linux valida a suíte completa e sintaxe do wrapper novo em Python 3.13/3.14; consultar os checks da revisão exata no PR #75 antes de aprovar. Nenhuma alteração de produção foi realizada.
