# Preparação da migração FTP — etapa 7 / PR #75

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
