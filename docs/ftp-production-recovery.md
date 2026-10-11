# Recuperação supervisionada da publicação — PR #75

Diagnóstico em 10/10/2026, horário de Brasília. **IMPLEMENTADO / preparado
localmente**, sem instalação, ativação ou reinício do timer. Este é o procedimento
único de corte proposto; suas operações remotas de escrita dependem de autorização
posterior e dos bloqueios abaixo. FTP convencional, porta 21, sem TLS; HTTPS
somente para controle autenticado e GET de verificação, nunca conteúdo de arquivos.

## Causa comprovada e correções

app01 `192.168.1.14`: revisão instalada `c273dfcaed764a7d04564b1d053e08f599dbbb10`,
timer `inactive/dead`, serviço com resultado `exit-code/1`. O wrapper chama
`publish-official-https.sh`. O helper instalado
`public_html/api/publish-official-snapshot.php`, 6.363 bytes, SHA-256
`a111b75168611138ec601b0360c563c10b17df60064a6dfc2fc7b935568b4d51`,
exige `is_file($src.'/'.$p)` para todas as entradas do manifest antes de escolher
os arquivos inalterados na baseline. Os três batches recentes examinados têm
**17 paths = 14 resultados + 3 metadados**, manifest com 137 resultados e **123
arquivos ausentes no batch**. É a condição concreta de `invalid_release`.

O helper corrigido valida os 137 paths fixos, seleciona delta/baseline antes de
verificar presença e usa o validador eleitoral e writer durável compartilhados.
Geração anterior, identidade divergente, reabertura e checksums continuam vetados.
A correção não autoriza retomar o upload HTTPS legado: o corte usa exclusivamente
o controlador FTP opt-in. O pacote de CI HTTPS inclui agora sua dependência PHP.

O wrapper legado passa a retomar pending/stage existentes, recusando estado
incompleto; não executa prepare destrutivo sobre publicação não confirmada.
`collector.src.ftp_recovery` monta uma candidata completa e um checkpoint seletivo,
sem rede ou chave. Queue é operação separada, protegida pelos gates existentes e
pelo SHA do plano revisado. O runner confere os 140 arquivos por GET antes de
confirmar esse checkpoint e mantém um hold para impedir novo prepare sobre os
deltas excluídos. Não chama o commit legado com o pending completo.

## Baseline e candidata verificáveis

Baseline pública, recuperada somente por FTP RETR:
`fd062ecbbafbe78ddfc240658e70525b6bf9e0cf28a8e21d64e0fb4b55d985ba`.
137 resultados + manifest/version/alerts: **140 arquivos / 11.174.461 bytes**.
Marcador: SHA-256
`69f3b4836d80927626980c5f3dd1d475ef3cde8036d0b1c9d1dcea352805d087`.
GETs de marcador, manifest e governador RJ conferiram com os bytes FTP. O manifest
do state coincide com as 137 entradas públicas. State e pending têm cinco arquivos
cada; stage tem 17. Nenhum arquivo remoto foi alterado.

Candidata local: **137 resultados + 3 metadados / 11.146.672 bytes**, 19.182
registros de candidatos. Substitui apenas `rj/governor.json`, `rj/senator.json`,
`rj/federal-deputy.json`, `rj/state-deputy.json`; mantém os outros 133 resultados
byte a byte. Manifest usa entradas dos arquivos efetivamente selecionados; alerts
são reconstruídos pelo código eleitoral existente. Não copia alerts do pending
que possam anunciar um delta excluído. Checkpoint mantém caches AM e outros alvos
inalterados; somente os quatro caches RJ vêm do pending.

ID determinístico da entrega completa, ainda **sem assinatura/transferência**:
`d229612eafaffe81b8a615f11bca0fc73aa981fb7d8c1906cb3535403d4642c8`.
SHA-256 do plano local:
`f76af8af4a342147ff649f321106883a06935165b6d1d37a09b2a1f74bc48c22`.
SHA-256 de `rj/governor.json` candidato:
`fad93916ce4cc6adcd41e021eb2b3d33bd4e1a599793e1ccf272a024d4a6ad9e`.

RJ governador: IDG **3441513**, fonte `2026-10-10T15:09:50-03:00`, Douglas Ruas,
**4.271.199 votos / 50,880152269% / Eleito**. A porcentagem recalculada sobre
8.394.627 votos válidos é 50,880152268826…%, compatível com o arredondamento.
Douglas passa de 2º turno a Eleito; Eduardo Paes passa de 2º turno a Não eleito.
O contrato existente marca candidatos ao 2º turno com elected=true; isso não
equivale a uma eleição já confirmada e foi respeitado na validação.

Revisão humana pré-ativação obrigatória do conjunto de candidatos: desaparecem
Garotinho (seq 190002550196, 274.411 votos, Anulado sub judice/Não eleito) do
governador e quatro candidatos do estadual (seq 190002543011, 190002542991,
190002538831, 190002538603). O plano registra removidos, votos/status anteriores
e transições; preparação não equivale a aprovação dessas mudanças.

Os quatro deltas AM atuais são posteriores à baseline e agora têm final=true:
IDGs 3385241 governador, 3391134 senador, 3387214 federal, 3387215 estadual.
O histórico anterior de reabertura permanece sem explicação oficial confirmada.
**Não afirmar que o stage atual reabre a totalização.** Manter esses quatro
deltas para revisão, sem promover ou certificar o pending como baseline. Os seis
outros deltas são semanticamente iguais à geração pública, com nova captura;
também ficam preservados. O hold registra os dez alvos não selecionados.

## Bloqueios de corte, separados da correção de código

1. FTP PWD `/` mapeia a home, mas MLST de `.election-publisher/hmac.key` e
   `public_html/api/election-publish.php` continua respondendo 250. O gate real
   retorna `ftp_control_exposed`. **Não configurar isolamento=true.** Requer prova
   de confinamento efetivo da conta existente pelo provedor, incluindo acesso por
   outras interfaces, sem criar conta/hospedagem. Chmod 0700/0600 com o mesmo UID
   não resolve. Enquanto persistir, nenhum upload eleitoral deve ser tentado.
2. `public_html/api/election-ftp-control.php` e inbox de produção respondem 550;
   controlador, baseline certificada, configuração e override ainda precisam de
   instalação autorizada. 550 isoladamente não prova ausência ou ACL segura.
3. `app.js` público já referencia releases; `favorites.js` público não referencia
   snapshot_id nem `/data/releases/`. Ambos recebem cache `max-age=315360000`.
   Ativar assets imutáveis com URL nova antes dos dados; não sobrescrever favoritos
   antigos e esperar invalidação de cache. Corrigido também o plano de portal para
   trocar o entrypoint real `composicao.html`, além de index.html.
4. NFSv3 nolock/nocto/soft: ensaios provaram lock em um host e aceitação de barreiras
   CLI, não exclusão multinó nem persistência após falha física. Provedor precisa
   confirmar topologia/fencing, cache e stable storage. Pin dinesh8169 e lock
   compartilhado com legado são necessários, mas não suficientes por si sós.
5. Revisão das remoções RJ, revisão AM, quota/backups e ausência de outro escritor
   devem ser concluídas. O hold impede retomada automática até reconciliação
   residual expressamente revisada. Não remover o hold apenas para iniciar timer.

## Procedimento único, na janela posteriormente autorizada

Os caminhos abaixo são **destinos propostos**, não diretórios criados. Revalidar
FTP/home após confinamento; divergência de mapa interrompe o corte. Usar somente
um código do PR com CI integral aprovado. Definir `CUTOVER_ID` único e registrar
SHA, IDs e hashes sem valores de credenciais. Timer continua parado durante tudo.

1. **Preflight e backups.** Confirmar timer inativo, serviço sem processo e ausência
   de escritores legados/novos, publicar após coleta=false. Não executar prepare.
   Conferir marcador, 140 hashes, state/pending/stage e plano local. Guardar cópias
   verificáveis completas do live e das configurações em
   `/var/backups/election-results-platform/pr75-recovery/<CUTOVER_ID>` no app01;
   na Locaweb, backup privado em
   `/home/storage/4/b7/e0/afgnet1/.election-publisher/backups/pr75-recovery/<CUTOVER_ID>`
   dos entrypoints, marcador, configuração, certificado/watermarks/journals se
   existentes. Nunca incluir chaves/ambiente em artefatos públicos, nem imprimir.
   Preservar release ativa e backups anteriores; não apagar qualquer estado.

2. **Instalar código e leitores por FTP.** Gerar pelo packager existente os
   componentes control/portal. Artefatos preparados nesta sessão:
   control `8311dcef91da1f466d18483ec64cb428027b727467bd60a9d1a40b4dba937ed6`,
   portal `f6a27966e3a29b4ffbc47d99c99b87a82042cef439c5a086f4a7a4080ab0dd11`.
   FTP somente para `/ftp-inbox/code/production/<component>/<artifact_id>`
   (físico: home + esse caminho), por .part/RETR/checksum/rename/READY.
   Revalidar IDs ao empacotar o SHA final; se mudarem, atualizar o plano aprovado.
   Tools ficam privados em `.election-publisher/ftp-runtime/<control_id>/tools`.
   Instalar o endpoint control autossuficiente em
   `public_html/api/election-ftp-control.php` por temporário/rename supervisionado.
   Não instalar o receiver de upload HTTPS como alternativa.
   Portal: assets novos em `public_html/eleicoes/releases/<portal_id>`; trocar
   somente index.html e composicao.html depois de todos os hashes conferirem.
   O plano de ativação reescreve URLs dos assets e preserva `/eleicoes/goias/`.
   Não transferir `/data`, Goiás, `.env`, state ou chave como código do portal.
   Conferir GETs das URLs imutáveis/favoritos e comportamento no navegador antes
   de continuar. Restaurar entrypoints pelo backup se houver divergência.

3. **Configurar e certificar baseline, sem ativar dados.** Inbox FTP:
   `/ftp-inbox/elections/production`; físico:
   `/home/storage/4/b7/e0/afgnet1/ftp-inbox/elections/production`.
   Estado protegido do ativador:
   `/home/storage/4/b7/e0/afgnet1/.election-publisher/ftp-state`.
   Configuração fixa `.election-publisher/ftp-config.json`: public_root =
   `/home/storage/4/b7/e0/afgnet1/public_html`, site = public_root/data,
   inbox/private acima, environment=oficial, round=1, enabled=false,
   activation_host=host FPM revalidado, legacy_lock =
   `.election-publisher/official-publish.lock` absoluto. Gerar config no servidor,
   sem chave embutida; não exportar HMAC. Reutilizar a chave real existente somente
   nas ferramentas de produção no servidor, nunca no staging.
   Enviar os cinco arquivos selecionados do **state confirmado** por FTP para
   `/ftp-inbox/elections/production/adoption-<CUTOVER_ID>/state`, fora do público.
   Executar o helper privado `tools/prepare-ftp-baseline.php` com config, state,
   caminho da chave existente e novo diretório privado do plano. Seguir instalação
   verificada do inventário privado e watermarks do
   [runbook](ftp-migration-runbook.md#adoção-assistida-implementada-e-testada), sob
   ambos os locks e marcador inalterado. Não alterar a release legada. Adotar
   confirmed.json no app01 com `collector.src.ftp_baseline`, assinatura e hashes
   coincidentes; state/pending/stage permanecem intactos.

4. **Revalidar o pacote seletivo no app01.** Materializar candidata/checkpoint/
   recovery-plan.json no diretório novo
   `/var/lib/election-results-platform/recovery/<CUTOVER_ID>` por preparação
   offline a partir da baseline íntegra e cópias congeladas, usando a revisão
   aprovada. Comando (não coleta, publica nem carrega chave):

   ```sh
   python -m collector.src.ftp_recovery prepare \
     --baseline BASELINE_LOCAL --marker MARCADOR_FRESCO_LOCAL \
     --stage STAGE_CONGELADO --state STATE_CONGELADO --pending PENDING_CONGELADO \
     --output /var/lib/election-results-platform/recovery/CUTOVER_ID \
     --include rj/governor.json --include rj/senator.json \
     --include rj/federal-deputy.json --include rj/state-deputy.json
   python -m collector.src.ftp_recovery verify \
     --package /var/lib/election-results-platform/recovery/CUTOVER_ID
   ```

   Conferir o SHA do plano, 140 hashes, 137 identidades/gerações, candidatos,
   remoções e checkpoint. Se qualquer entrada live mudou desde a cópia desta
   sessão, gerar/revisar novo plano; não reutilizar os IDs acima por conveniência.
   Aprovação deve nomear o SHA do plano e aceitar explicitamente as mudanças RJ.

5. **Corte de escritor, com timer ainda parado.** Provisionar código aprovado em
   release isolada do app01; credenciais FTP existentes via EnvironmentFile 0600
   já existente. Instalar somente o override FTP revisado, com WorkingDirectory
   apontando à revisão aprovada e ExecStart do runner FTP. Preservar https.conf no
   backup; não envolver o runner no prepare/commit legado. Desabilitar o gate
   legado de publicação por alteração supervisionada reversível, esperar
   quiescência e provar que ele não pode escrever de outro host. Configurar URL
   `https://afgnet.com.br/api/election-ftp-control.php`. Somente após todas as
   provas externas e autorização: habilitar config/control e os gates de corte.
   Nenhum gate passa a true como parte da correção ou deste documento.

6. **Enfileirar exatamente o checkpoint revisado.** No contexto do runner com os
   EnvironmentFiles protegidos já carregados (não source/eval nem senhas em argv):

   ```sh
   python -m collector.src.ftp_recovery queue \
     --root /var/lib/election-results-platform/live \
     --package /var/lib/election-results-platform/recovery/CUTOVER_ID \
     --reviewed-plan-sha256 SHA_DO_PLANO_APROVADO
   ```

   Recusa gates falsos, baseline não adotada, entrega em voo, hashes live alterados
   e hold anterior. Congela/assina **140 arquivos**, estado seletivo separado,
   current.json e hold dos dez alvos restantes. Não altera os três diretórios live.

7. **Uma execução supervisionada.** Iniciar somente o serviço revisado, não o
   timer. Retoma essa fila sem prepare; consulta status, FTP 21 entrega somente
   `/ftp-inbox/elections/production/<delivery_id>/files` e descriptor/sig/READY.
   Ativador verifica HMAC/hashes/baseline, sela, monta os 137 e renomeia marcador
   sob host/locks aprovados. Reconciliação usa o mesmo ID se a resposta se perder;
   não criar outra entrega nem fazer commit manual. A confirmação seletiva só
   ocorre depois de GET do marcador, **140 arquivos comparados ao descriptor**
   e novo GET do marcador idêntico, com redirecionamentos recusados. Erro mantém
   fila/recibo e estado anterior para recuperação; não retornar ao HTTPS upload.

8. **Aceitação e rollback.** Conferir por URLs estáveis normais e cache-busting
   marcador/manifest/137 JSONs, incluindo os votos/status RJ e baseline AM,
   favoritos, composição e Goiás. Conferir state seletivo, pending/stage intactos,
   previous-<id>, receipt/journal e hold. Se houver falha após seleção, manter
   timer parado e usar `Control(...).request("rollback", delivery_id)` com chave
   lida no app01. O rollback só pode selecionar a anterior verificada registrada
   no journal; watermarks permanecem altos. Conferir os 140 hashes da baseline e
   nova activation_revision. Reconciliar confirmed/state seletivamente sob lock
   usando previous-<id>/backups e marcador fresco; não aceitar recibo histórico
   como confirmação da seleção atual. Falha/corrupção no alvo: não ativar outro
   conteúdo; preservar evidências e última seleção íntegra. Restaurar código só
   por plano com hashes e artefato compatível, usando FTP; não editar JSONs avulsos.

9. **Automação, somente em autorização posterior.** Hold residual permanece e
   bloqueia novo prepare antes de tocar pending/stage/TSE. Revisar os AM específicos
   e reconciliar os dez alvos com fonte/gerações/checkpoint, guardando as cópias
   originais. Uma resolução assinada/revisada do hold e validação de ciclos
   posteriores são pré-condições de retomada do timer; esta sessão não implementa
   autorização automática para AM nem remove o hold. Se a revisão não puder ser
   concluída, RJ pode estar publicado após o corte autorizado, mas publicação
   automática continua suspensa. Não declarar o incidente operacional encerrado.

## Evidências e classificação

Os datasets reais, planos, snapshots de leitura e artefatos ficam locais em
`.incident-validation/`, fora do Git. Testes usam exclusivamente fixtures; CI deve
aprovar o HEAD efetivamente enviado. Nenhum workflow de deploy foi disparado.
Correções: **IMPLEMENTADO**. Builder/validação da candidata: **TESTADO LOCALMENTE**.
Inspeções FTP/SSH/GET e lint: **TESTADO NA LOCAWEB**, sem aplicação instalada.
Nova recuperação/controle em produção: **não VALIDADO EM STAGING nem ATIVO EM
PRODUÇÃO**. Os ensaios anteriores de staging têm escopo próprio e não liberam o
corte. Preservar o PR em rascunho e Goiás/AM/pending/watermarks existentes.
