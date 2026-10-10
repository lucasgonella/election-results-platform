# Fronteira de confiança da conta FTP existente

## Evidências e limite

Na retomada de 09/10/2026, o diagnóstico autenticado somente leitura confirmou
PWD `/` e acesso MLST a `.election-publisher/hmac.key`, `/includes` e
`/public_html/api/election-publish.php`. Os fatos anunciados pelo servidor
incluem escrita/rename/delete no arquivo PHP e na chave; nenhuma dessas
operações foi executada. Isso comprova exposição e capacidades anunciadas,
mas não substitui um ensaio de escrita autorizado.

O protocolo em `collector/src/ftp_delivery.py` e
`deploy/locaweb/ftp-publication.php` verifica assinaturas e hashes. Se o mesmo
principal puder ler a chave, poderá fabricar entregas autenticadas. Se puder
substituir o PHP que verifica a assinatura, poderá retirar a verificação.
Se puder substituir os JSONs e o marcador públicos, poderá adulterar o que
o navegador lê sem passar pelo controlador. Portanto retirar a chave da
inbox, adicionar outra assinatura ou conferir hashes no app01, isoladamente,
não protege a aplicação quando o verificador e sua saída continuam mutáveis
pelo transporte. Essa conclusão decorre das capacidades observadas; não foi
realizado ataque ou substituição de arquivos.

## Menor mudança necessária, preservando a conta

É necessária uma restrição aplicada pelo provedor ao principal de transporte
da **conta existente**, independente do código PHP e de gates declarativos:

- Permitir entrega somente nas inboxes aprovadas por componente e preservar
  o destino financeiro Goiás autorizado, sem ampliar seu escopo.
- Impedir leitura de chave/configuração privada e impedir escrita, exclusão
  e rename de verificadores PHP, frontend, resultados, marcadores, estado,
  journal e backups fora das inboxes.
- Impedir escape por links, aliases, traversal e rename entre namespaces.
  Arquivos PHP enviados às inboxes não podem ser executados pelo servidor web.
- Confirmar que a mesma credencial não permite contornar essa fronteira por
  outro protocolo, especialmente um shell SSH irrestrito.

A documentação oficial de
[SSH da Locaweb](https://www.locaweb.com.br/ajuda/wiki/como-utilizar-o-ssh-hospedagem-de-sites/)
informa reutilização de usuário e senha FTP no SSH. Isso não comprova a
configuração atual da conta: autenticação por senha e restrições de shell
precisam ser confirmadas pelo provedor. Confinar somente FTP seria insuficiente
se a mesma senha desse acesso irrestrito aos arquivos por SSH. Não houve teste
de autenticação SSH nem alteração de políticas nesta sessão.

A capacidade de aplicar essa política à conta principal e aos acessos
existentes é desconhecida. A documentação de FTP multiusuário não demonstra
essa capacidade para a conta principal. Não se propõe outra conta, serviço,
plano ou arquitetura. Se o provedor não puder aplicar a restrição acima à
infraestrutura atual, a fronteira exigida não pode ser garantida nela.
Permissões Unix ajustadas pelo mesmo UID e aprovações configuradas como true
não fornecem essa garantia. Os gates permanecem fechados.

## Avanço independente

Fixtures isoladas podem medir transporte e runtime após aprovação específica,
mas não certificam isolamento nem autorizam dados reais. O cliente
`probe-ftp-staging.py reconcile` consulta inventário e hashes após interrupção
sem escrever; `probe-ftp-web.py` verifica FPM, exclusão de lock, visibilidade
HTTP normal e sem cache e restauração da fixture. Ensaios no mesmo host não
comprovam coerência multinó NFS. Consulte [o plano](ftp-staging-plan.md).

Na etapa 14, a rota proposta em `/eleicoes/__staging_pr75/` expõe somente
probe e marcador sintético. Configuração, chave fixture e helper ficam em
`/ftp-staging-pr75/private`, fora de `public_html`; autenticação HMAC e ações
runtime/read limitam o diagnóstico. Isso resolve o posicionamento HTTP do
harness, **não** o acesso amplo do principal FTP: ele continua alcançando
controle/código. Não habilitar LOCAWEB_FTP_ISOLATION_APPROVED. A transferência
separadamente aprovada de uma chave descartável de teste ao diretório privado
não envolve a chave HMAC real e não autoriza publicação eleitoral.
