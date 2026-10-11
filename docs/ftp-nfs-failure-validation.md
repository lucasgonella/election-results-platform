# Etapa 16 — falhas sintéticas, topologia e requisitos de armazenamento

## Evidência remota e limite da observação

Após a Etapa 15, foram executadas somente 12 consultas autenticadas runtime
e 3 read, em conexões HTTPS novas, sem cookies e sem concorrência. Origem:
cliente CLI na Locaweb via SSH, chave fixture lida apenas no servidor.
Todas observaram `dinesh8169`, dois PIDs (336322/355000), fpm-fcgi e PHP 8.5.7.
DNS/TLS observaram um endereço público. Nenhum cookie foi emitido na amostra.
Isso não comprova quantidade total de backends, afinidade de origem, política
de failover, host permanentemente fixo ou armazenamento compartilhado por todos.
O probe não impõe host para runtime/read: outro nó pode ser observado sem
habilitar mutações, desde que consiga ler a mesma fixture privada.

O mount observado no host SSH é NFSv3 em `/home/storage`, `nolock`,
`local_lock=all`, `nocto`, `soft`, acregmin/acdirmin 60 segundos. Identidade
do export foi registrada apenas como SHA-256 no relatório local. Não foram
consultados outros servidores internos, painel, root ou configurações privadas
de outros clientes. A amostra saiu de uma única origem e janela de tempo.

## Garantias de protocolo não são garantias do contrato

[RFC 1813, RENAME/COMMIT](https://www.rfc-editor.org/rfc/rfc1813.html)
exige rename atômico para o cliente e descreve persistência em stable storage.
Isso não equivale a invalidar imediatamente caches de outros clientes, nem
comprova a implementação, export sync/async ou proteção elétrica do provedor.
[nfs(5)](https://man7.org/linux/man-pages/man5/nfs.5.html) documenta que nolock
e local_lock deixam a exclusão no cliente local; nocto desabilita close-to-open;
soft pode produzir falhas e corrupção em certas condições. Os parâmetros reais
não foram alterados. Locks locais testados na Etapa 15 não certificam multinó.
[fsync(2)](https://www.man7.org/linux/man-pages/man2/fsync.2.html) distingue
persistência do conteúdo e da entrada do diretório. Sucesso de fsync não é
prova de recuperação após perda de energia ou indisponibilidade do servidor NFS.

## Defeitos reproduzidos e correções na branch

- Ausência/vazio/incompletude de watermarks permitia validação sem o histórico
  anterior; um mapa antigo podia permitir dados menores que a release corrente.
  Agora um marcador existente exige 137 watermarks completos, tipos válidos e
  limites coerentes com a baseline. Ausência/inconsistência exige revisão; não
  se reconstrói silenciosamente o histórico usando a release após rollback.
- Dados selados, 140 arquivos de release e assinatura de inventário usavam
  file_put_contents sem fsync. O writer único agora grava temporário exclusivo,
  exige fwrite/fflush/fsync, rename e fsync do diretório. Assinaturas da preparação
  de baseline usam o mesmo writer. fsync ausente/sem suporte é erro, sem fallback.
- Falha na barreira do diretório depois de trocar o marcador é resultado ambíguo.
  Status valida a release assinada e exige barreira bem-sucedida antes do recibo;
  enquanto o erro persistir, não confirma. Não repete automaticamente a ativação.
- Recibo histórico com identidade/snapshot inconsistente era aceito pelo servidor.
  Agora exige schema/ID/snapshot coerentes e inventário válido antes de confirmar.
- Marcador perdido com histórico de recibos poderia parecer instalação vazia ou
  permitir confirmação histórica apesar da perda da seleção pública. Agora exige
  revisão, sem criar marcador ou reiniciar automaticamente a história da fonte.

Essas verificações detectam perdas/inconsistências observáveis. Uma restauração
antiga, internamente coerente, de todo o armazenamento pode ser indistinguível
localmente do passado; deve ser confrontada com checkpoint independente do app01
e backups verificados. Nenhuma recuperação silenciosa ou reset foi adicionado.

Helper preparado é revisão 3; cliente CLI preparado exige helper_revision=3
para futuras mutações. A hospedagem continua com helper revisão 2 da Etapa 15,
config runtime/read e activation_host vazio. Nenhum PHP novo foi instalado.
O suporte do PHP/NFS a fsync de diretórios precisa de ensaio separado: falhar
essa capacidade bloqueia a adoção; não há flag para ignorar a barreira.

## Testes e interpretação

`tests/test_ftp_fault_recovery.py` usa uploader real com FTP em memória e
interceptação de syscalls em namespace PHP, exclusivamente em árvores temporárias:
upload interrompido, RETR incompleto, rename recusado, retry do mesmo ID,
perda de resposta/status, falha de confirmação local, leitura de baseline,
gravação/fsync recusados, ausência de fsync, diretório recusado, interrupção
após marcador e antes do recibo, saída abrupta do processo fixture antes/depois
do rename do marcador (sem finally), retomada em processo novo, tipos de
watermarks inválidos, rollback, recibo inconsistente, outro host
antes de qualquer escrita e ordem das barreiras antes do commit.
O teste confirma 140 syncs de dados selados e 142 da release/inventário,
além da barreira após rename da release, antes de trocar o marcador.

Regressões foram enviadas primeiro para demonstrar defeitos no CI Linux,
sem tocar serviços reais. O primeiro simulador também tinha import de exceção
incompleto; foi corrigido. PHP local permanece bloqueado por Application Control.
Falhas simuladas não representam crash real, EIO de NFS real ou power-loss.
Não se usa kill, umount, alteração de mount, carga ou falha induzida na hospedagem.

## Menor alteração arquitetural verificável

Um marcador por rename seleciona uma release por observação; isso não constitui
transação global entre caches, água máxima histórica, journal e recibo. O fluxo
consegue serializar escritores cooperativos somente se todo mutador usar o mesmo
host validado, lock e estado consistente. O gate de host já existe; sticky session
sozinha não assegura essa condição. Outro nó deve recusar escrita, sem promover
automaticamente um substituto após falha do host. Troca de host requer fencing,
quiescência e reconciliação explícitos, não apenas editar activation_host.

A conta existente ainda alcança chave/verificador/saída pública. O mesmo principal
pode retirar as verificações ou forjar assinaturas; código PHP e chmod pelo mesmo
UID não criam essa separação. Portanto a arquitetura atual **não garante segurança
de publicação eleitoral** na fronteira comprovada; isolamento/corte continuam false.

Menor proposta, mantendo conta e hospedagem: provedor aplicar confinamento real
da identidade de transporte à inbox autorizada e preservar Goiás; proteger chave,
verificador, estado e saída de alteração pelo transporte/SSH equivalente; assegurar
um único host mutador e política explícita de failover; demonstrar barreiras de
persistência e visibilidade nas rotas leitoras. Não se recomenda conta/hospedagem
nova, eleição de líder com mkdir no NFS ou lock distribuído simulado com flock.
Se o contrato não permitir essas propriedades, o impedimento permanece comprovado
pela identidade ampla atual e pelo lock local, independentemente dos testes.

O provedor precisa confirmar: lista de backends e afinidade/failover, export comum
e namespace por nó, política de cache, export sync/async, comportamento COMMIT e
fsync/rename, garantias de storage/backup e meios autorizados de acessar cada nó.
Páginas de balanceamento para Cloud/Dedicados não comprovam este contrato compartilhado.
Nenhum chamado foi enviado em nome do responsável.

## Próximo ensaio remoto proposto, sem autorização de escrita

Antes de montar ensaio de falhas do publicador, medir a capacidade nova de barreira,
sem repetir locks/trocas da Etapa 15. Destino único novo:
`/home/storage/4/b7/e0/afgnet1/ftp-staging-pr75/private/etapa16-barrier` 0700.
Somente `sample.json` (23 bytes `{"fixture":"replace_a"}`), seu temporário
`sample.json.<16 hex>.tmp` e `expected.json` privado contendo hash/tamanho/host,
até 512 bytes; arquivos 0600. Nenhum upload, endpoint, config ou marcador existente
será alterado. Um cliente PHP CLI por SSH gera a fixture sintética no servidor,
grava/flush/fsync, rename, sync de diretório e leitura/checksum, uma execução serial.
É geração de fixture, não transferência de artefato por SSH ou ativação de release.

Backup: não há arquivo preexistente a substituir; colisão interrompe antes de mkdir.
Critério: todos os retornos de gravação/barreira e hash esperados. Em falha, parar
e conservar os artefatos; não renomear marcador ou retry cego. Limpeza futura somente
após comparar hashes/inventário de seus próprios arquivos, com escopo aprovado.
Esse ensaio prova somente aceitação da API e leitura no cliente observado. Outro
host/recuperação após reinício do storage depende de ambiente seguro e rota por nó
fornecidos pelo provedor; nenhuma indisponibilidade será induzida no serviço compartilhado.
Escopo executável final, hashes do cliente e autorização específica são necessários
antes de qualquer mkdir/escrita/fsync/rename remoto. Nenhuma operação deste plano
foi executada. Não reutilizar automaticamente a aprovação da Etapa 15.

## Classificação

IMPLEMENTADO: correções na branch e regressões sintéticas.
TESTADO LOCALMENTE: seis testes Python de FTP/estado; PHP depende do CI Linux.
TESTADO NA LOCAWEB: amostra autenticada de topologia, mount e hashes somente leitura.
VALIDADO EM STAGING: Etapa 15 em um host; nenhuma falha/NFS multinó/durabilidade nova.
ATIVO EM PRODUÇÃO: nenhuma mudança; Goiás/Amazonas/pending/watermarks preservados.
