# Correções prioritárias da auditoria multiagente

Base verificada antes das alterações: `main` no GitHub em
`7eb2ae9cc1a03a86033fce8a34c1c56772ef67eb`, o mesmo SHA da auditoria.
Não havia commits posteriores na `main` contendo essas correções. A branch
`fix/multiagent-audit-p1` foi criada em clone independente, preservando a branch
da auditoria e as alterações preexistentes do checkout operacional.

Durante a implementação, a `main` recebeu outros trabalhos de transporte e
métricas e uma atualização financeira. A comparação posterior também não
encontrou essas três correções; os três commits foram reaplicados sobre
`98cd223446acd79b4f30a115c77a2673f1c9f495`, sem conflitos, conservando as alterações
concorrentes. A validação final precisa corresponder a essa base integrada.

## Resultados compatíveis com a seleção

Uma troca de localidade ou cargo invalida imediatamente resultado, cartões,
resumo, tabela e exportação da seleção anterior. O contexto publicado aos
consumidores informa carregamento ou falha sem reaproveitar um resultado
incompatível. O turno continua definido pela URL e pelo namespace da página;
não há fallback entre turnos.

Cada tentativa tem uma revisão e identidade de seleção. Sucesso, rejeição de
rede, erro HTTP, erro de JSON e falha de validação só podem afetar a tentativa
ainda atual. Falhas da consulta apresentam mensagem e ação de tentar novamente.

A atualização em segundo plano prepara a publicação candidata antes de aplicar
o conjunto completo. Falhas conservam a publicação anterior íntegra e deixam
o marcador elegível para nova tentativa. Uma atualização pendente não pode
reverter navegação iniciada depois dela. Isso não promete transação global no
TSE ou no servidor FTP.

## Ausência, zero e cobertura financeira

O contrato continua aceitando valores numéricos e `null`. O exportador deixa de
fabricar zero quando uma candidatura não aparece nas linhas financeiras.
Metadados aditivos identificam cobertura conhecida, parcial ou ausente e
referenciam as linhas de declaração explicitamente zerada. Somas incompletas
permanecem identificadas como subtotais nos consumidores.

Dados legados sem esses metadados continuam aceitos. Seus zeros não são
reclassificados retrospectivamente. Esta alteração não regenera nem modifica
o JSON financeiro versionado. Em valores parciais, o campo escalar antigo fica
`null` e o subtotal conhecido acompanha os metadados: leitores anteriores mostram
ausência de informação em vez de um total incorreto. Os critérios de evidência e
os limites da investigação estão no
[contrato financeiro](financial-value-contract.md).

O publicador financeiro mantém seus gates e transporte existentes. Em especial,
o suporte do leitor a uma base sem transferências não autoriza sua publicação
automática pelo gate atual.

## Leitor HTTP dos dois turnos

O portal, favoritos, composição e comparação estadual entre turnos encaminham
leituras eleitorais permitidas ao mesmo leitor. `/data` e `/data/turnos/2`
conservam marcadores, dados, caches e
estado de polling separados. URLs financeiras e municipais não entram nessa
lista de caminhos; a coleta e os escritores permanecem intactos.

As requisições têm timeout de cabeçalhos e corpo, limite de tamanho, deduplicação,
serialização e até três tentativas. HTTP 429 e falhas transitórias usam backoff
limitado com jitter; `Retry-After` em segundos ou data nunca é antecipado.
Uma pausa longa é reavaliada em intervalos limitados para evitar overflow do timer.
O prazo é registrado já nos cabeçalhos de erro, antes de ler o corpo: um timeout
posterior do corpo não pode apagar o `Retry-After` recebido.

Web Locks coordenam requisições entre abas participantes da mesma origem.
Somente o prazo de pausa é compartilhado em storage; isso não compartilha os
dados dos turnos. A pausa expira por timestamp. Sem Web Locks ou storage,
persistem as proteções locais, mas a coordenação entre abas fica limitada.
O cancelamento de um consumidor não cancela a requisição compartilhada de outro.

## Validação e publicação

Os testes novos usam dados inventados, transportes controlados, relógios
sintéticos e cenários de abas independentes. A regressão inclui os leitores,
favoritos, contrato financeiro e testes existentes do mecanismo visual.
Resultados executados e limitações devem constar na PR; testes locais não
comprovam implantação nem capacidade dos endpoints públicos.

Nenhum deploy, merge, coleta oficial, alteração de banco, timer ou configuração
operacional faz parte desta entrega. O workflow financeiro existente observa
alterações no ETL: um eventual merge pode executar esse fluxo e publicar uma
nova exportação. A PR é o limite autorizado desta sessão; o merge e seus efeitos
precisam de decisão posterior.

O [preflight final](goias-finance-publication-preflight.md) acrescenta uma trava
de compatibilidade à job financeira, sob a mesma exclusão dos workflows visuais.
Ela impede coleta/publicação prematura sem antecipar nem executar deploy nesta
sessão. Os horários, transportes e writers existentes permanecem preservados.
