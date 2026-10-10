# Etapa 15 — ensaio limitado, ainda não autorizado

As escritas abaixo exigem aprovação específica. A configuração instalada
continua runtime/read e activation_host vazio. O código preparado não foi
instalado na Locaweb nesta etapa. Não é plano de produção.

## Baseline reconfirmada em 10/10/2026

Home `/home/storage/4/b7/e0/afgnet1`; host FPM `dinesh8169`, PHP 8.5.7,
SAPI fpm-fcgi, UID/GID 542178/542178. Runtime/read HTTP 200, no-store/nosniff.
Privados 0700 e config de 338 bytes 0600, sem exportação da chave.
Config SHA-256: `a9248d8f819ec13c91d2c6c7b50cfd853897c4dac8549ea3801eb5fc1f5ed29c`.
Marcador original, 23 bytes de JSON canônico, sem newline:
`23ab6436c98a78840a9bb8dd9b06b564c990525e3606e32ae84883ea0c642c9a`.
Probe/helper instalados continuam nos hashes da etapa 14; baseline local
e seis hashes públicos registrados em `.stage15-validation/baseline-ftp.json`.

NFSv3: nolock, local_lock=all, nocto, soft, acregmin=60, acdirmin=60.
Não há evidência de exclusão entre hosts. O ensaio será de um host, dois
clientes e duas transições. Nenhuma conclusão de NFS multinó, perda de energia
ou durabilidade do diretório poderá ser derivada desses testes.

## Revisão e correções preparadas

- A allowlist do probe agora aceita somente a configuração readonly original
  ou a lista exata runtime/read/lock/replace_a/replace_b. Escritas exigem host
  explícito coincidente antes de abrir lock ou escrever. Unknown actions falham.
- Links em config/helper/lock/marker/private são recusados. Mutações possuem
  destinos fixos na fixture, sem path enviado no corpo HTTP.
- Lock e replace compartilham probe.lock, criado 0600. Lock dura dois segundos
  e tenta LOCK_EX|LOCK_NB. O host pin não transforma um lock local em distribuído.
- fp_write usa temporário exclusivo no mesmo diretório, fwrite/fflush/fsync e
  rename. A correção remove somente seu temporário quando ocorre falha.
  Não se afirma fsync de diretório ou garantia contra falha completa do NFS.
- Read retorna JSON, bytes e SHA-256 obtidos da mesma leitura do marcador.
- O cliente Python recusa status inesperados e campos desconhecidos. Para
  essa rota, exercise é bloqueado: sua restauração semântica não garante
  bytes originais em variações de formatação, e a chave não deve estar no Windows.
  No marcador canônico atual, a restauração semântica daria o mesmo hash.
- O cliente CLI [ftp-staging-exercise.php](../deploy/scripts/ftp-staging-exercise.php)
  usa a chave somente no servidor, cURL com verificação TLS, sem redirect,
  respostas limitadas, dois handles no máximo e recuperação em finally.
  Nenhum cliente/endpoint novo precisa ser instalado remotamente.

## Escopo exato proposto

Somente após aprovação, instalar por FTP 21 sem TLS dois arquivos atualizados:

| Origem na branch | Destino FTP | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| deploy/locaweb/ftp-staging-probe.php | /public_html/eleicoes/__staging_pr75/probe.php | 7574 | `54ab592ff32e41ef60687359de03b609f6657ebd11ae167bcb4209e02af203cc` |
| deploy/locaweb/ftp-publication.php | /ftp-staging-pr75/private/ftp-publication.php | 16951 | `ebf21001b50783c281cfa3cb15c5ca54fce562daef5e76a4fe0516b1f9f5c460` |

Total dos dois novos arquivos: 24.525 bytes. Destinos físicos: home acima
mais destino FTP. Helper 0600; probe 0644. .htaccess e marcador não recebem
upload nesta etapa. Não transferir config, chave, resultados ou a árvore inteira.

Antes de substituir código, criar `/ftp-staging-pr75/private/etapa15-code-backup`
0700, contendo `probe.original.php` (5953 bytes, hash
`fce0c188132e32f7d761b130d56bb4f32b14e90dfbf66610e7a4534bc65d7b32`)
e `helper.original.php` (16729 bytes, hash
`b29a1a093a78caee4170eb80769373586de6334001286a6cc48efef19f6c039a`),
ambos 0600 e obtidos do pacote original verificado. Esses dois backups de
código também usam FTP; nunca incluem configuração/chave.

O ensaio CLI criará exclusivamente o diretório privado
`/ftp-staging-pr75/private/etapa15-backup` 0700, com arquivos 0600:
`marker.original` (23 bytes), `config-template.json` e `manifest.json`.
O template remove integralmente o valor da chave; guarda somente prefixo,
sufixo e checksum necessários para recuperar os bytes originais com a chave
que continua no config do servidor. Não existe backup/cópia persistente da chave.
O manifest contém host, hash do marcador e seis hashes públicos, sem segredos.
Tamanhos máximos: template 2048 bytes, manifest 2048 bytes.

Outras modificações permitidas no escopo proposto:

- `private/staging-config.json`: somente habilitação temporária das cinco ações
  e activation_host=`dinesh8169`; depois restauração exata dos 338 bytes originais.
  Chave e os outros valores permanecem iguais, sem transferência pelo FTP.
- `private/probe.lock`: arquivo novo vazio, 0600, dentro do staging.
- `public/probe-marker.json`: replace_b, replace_a e restauração exata do backup.
- Temporários `.part` dos quatro uploads e `<arquivo>.<16 hex>.tmp` dos writers,
  no mesmo diretório de cada destino, sempre explicitamente delimitados.

## Sequência e critérios

1. Revalidar host, namespace, modo, seis hashes públicos, config/marker/código
   e ausência das duas pastas de backup. Qualquer divergência interrompe.
2. Criar/verificar backups de código, instalar helper e probe por .part/hash/rename.
   Validar lint com PHP 8.5 e confirmar probe_version=2/helper_revision=2 por
   runtime readonly. Cache antigo ou outro host impede habilitação de escrita;
   não resetar OPcache global.
3. Executar cliente CLI no servidor, como comando PHP, sem instalar arquivo.
   Default plan é inerte. Run exige namespace, host e cinco digests aprovados:
   probe, helper, marcador, config e fingerprint dos seis arquivos públicos.
4. Antes de habilitar ações, criar/verificar backup exato do marcador e template
   sem chave. Habilitar somente a lista fixa e o host confirmado, modo 0600.
5. Disparar exatamente dois lock simultâneos. Sucesso exige um HTTP 200
   lock_acquired e um HTTP 409 publication_busy. Serialização pelo FPM, dois
   sucessos, host divergente ou timeout não comprovam exclusão: recuperar.
6. Replace_b e replace_a, uma vez cada, com um GET sintético concorrente a cada
   transição. O GET só pode observar um dos hashes A/B íntegros ou o A original.
   Após cada replace, confirmar hash via read autenticado e GET normal/cache-bust.
   Uma amostra por transição não certifica atomicidade sob carga ou entre nós.
7. Em finally, desabilitar mutações primeiro, adquirir o lock com espera máxima
   de seis segundos e restaurar os bytes originais do marcador. Conferir ambos
   os hashes originais e os seis arquivos públicos. Validar visibilidade HTTPS.
8. Confirmar por config e três requests autenticados que lock/replace_a/replace_b
   recebem fixture_action_not_approved sem escrita. Nenhuma chave registrada.

Rede: timeout 10s/request, par concorrente até 12s, orçamento lógico do run 90s,
recuperação 60s; no máximo dois requests ativos. Aproximadamente 21 requests no
run e recuperação normal, sem carga contínua. Chamadas de filesystem podem
exceder orçamento em falha NFS: timeout SSH não será tratado como recuperação.

Após desconexão/terminação, **não repetir run**. Usar recover com o mesmo
namespace/host, lendo os backups persistentes; não recriar chave nem apagar lock
ativo. Se recuperação não puder ser confirmada, manter backups e interromper
novas mutações. Não tocar no portal para compensar uma falha da fixture.

Modelo de execução no servidor (cliente disponível ao operador; o wrapper
local pode executá-lo com `php -r`, sem upload do cliente):

```text
/usr/bin/php8.5 -d opcache.enable_cli=0 <cliente-local-ao-operador> plan
/usr/bin/php8.5 -d opcache.enable_cli=0 <cliente> run <namespace> <host> <probe-sha> <helper-sha> <marker-sha> <config-sha> <public-fingerprint>
/usr/bin/php8.5 -d opcache.enable_cli=0 <cliente> recover <namespace> <host>
```

Limpeza: remover somente .part verificados e temporários próprios abandonados,
se seus hashes/inventários forem conhecidos e nenhum writer estiver ativo.
O writer corrigido limpa seu temporário em falha normal. Conservar os dois
diretórios de backup e o inode probe.lock ao final para recuperação/revisão;
não há limpeza recursiva ou remoção automática do config. Retirada posterior
desses artefatos exige escopo delimitado. O código atualizado permanece só no
staging; uma falha de instalação pode restaurar os dois arquivos originais pelos
backups de código verificados. Nada disso habilita a publicação eleitoral.

## PHP CLI 139

Lint padrão de `/dev/null` reproduziu 139, excluindo defeito do probe como causa.
php.ini principal sozinho funciona; scan de php.d reproduz; dentre os INIs
testados isoladamente, `10-opcache.ini` reproduziu 139. Ele define
`opcache.enable_cli=1`. IonCube sozinho, incluindo seu OPcache, passou.
Com INI completo e `-d opcache.enable_cli=0`, /dev/null, probe e helper passaram
no lint. Esse workaround aplica-se somente ao comando CLI; nenhum INI,
extensão da hospedagem, OPcache web ou serviço foi alterado. O defeito interno
da distribuição deve ser corrigido pelo provedor; não declarar isso corrigido.

## Classificação

IMPLEMENTADO: correções e cliente de recuperação na branch do PR.
TESTADO LOCALMENTE: regressões Python; PHP Windows bloqueado por Application Control.
TESTADO NA LOCAWEB: baseline readonly, runtime/read, NFS mount e diagnóstico CLI;
lint dos PHP preparados por stdin, sem instalação.
VALIDADO EM STAGING: somente diagnóstico readonly da etapa 14/15. Locks,
rename/recuperação real e NFS multinó continuam não validados.
ATIVO EM PRODUÇÃO: nenhuma mudança desta etapa. Isolamento FTP continua false.
