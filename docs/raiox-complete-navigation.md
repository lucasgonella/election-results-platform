# Raio-X: exploração pelo índice completo

## Causa e separação dos estados

O pacote financeiro já contém todas as transações publicadas. O leitor anterior
mantinha `q=CHARLES BENTO` ao clicar na doadora e reaplicava esse nome às
transferências. Isso escondia as outras campanhas. Além disso, o contexto de
primeiro grau incluía vínculos entre vizinhos, em vez de somente os registros
diretos do nó principal. A abertura sem URL escolhida selecionava a primeira
candidatura com receitas na ordem de arrecadação.

O leitor agora separa base validada, adjacências globais, identidade canônica,
filtros financeiros explícitos, busca de nomes, subgrafo limitado e histórico.
`getCompleteDirectConnections` consulta `incoming`/`outgoing` globais, elimina
apenas a dupla ocorrência da mesma linha nas duas adjacências e aplica os filtros
explícitos. `q` é somente localizador de entidades. A quantidade excluída pelos
filtros e a quantidade fora do desenho são informadas separadamente.

Clique, pesquisa, URL e navegação abrem o mesmo primeiro grau. Novos nós começam
nas diretas; segundo/terceiro graus exigem expansão explícita. Campanhas continuam
na projeção documentada junto ao titular. O endpoint legal e o papel permanecem
nos registros; repasse de campanha não vira doação pessoal. Não houve alteração
no ETL, financeiro, identidades, banco ou serviços.

## Câmera e interação

A abertura padrão mostra Visão geral; `selected` válido é canônico, e inválido
volta ao geral com aviso. A escolha por arrecadação foi removida. Não há seleção
armazenada entre sessões. Limpar filtros também retorna ao geral.

No SVG, `p = t + s*q`. Para preservar o ponto sob o cursor, `s'` é limitado a
35–800% e `t' = p - (p - t) * (s'/s)`. O ponto de tela é convertido com a inversa
real de `getScreenCTM`, incluindo letterboxing e viewport responsivo. Rolagem de
trackpad é proporcional à distância e ao `deltaMode`; pan e pinch compartilham
essas coordenadas. Atualizações da câmera são agrupadas por animation frame.

Hover/foco realçam vizinhos e mostram resumo sem seleção, painel ou URL. Clique,
toque e Enter/Espaço abrem a rede própria, preservando escala e centrando o novo
nó, conforme o pedido de expansão dinâmica. Arrasto com deslocamento acima de
5px suprime clique posterior, inclusive quando retorna ao ponto de partida.
Fundo vazio e Visão geral removem seleção sem limpar filtros ou reenquadrar.

`pushState` é reservado a mudança de entidade. Filtros e câmera usam
`replaceState`; selecionar novamente o mesmo ID não cria entrada. Voltar,
avançar e a trilha restauram URL, filtros, câmera e posições. Apenas o tema é
persistido em localStorage.

## Legibilidade e limites

Layout de forças determinístico, cache de 24 contextos e posição central fixada
em coordenadas do mundo durante a troca. Colisões recebem repulsão; nenhum
agrupamento visual altera relações. A câmera conserva sua posição em mudanças
de filtro. Rótulos respeitam colisões e ficam mais detalhados ao aproximar;
valores de arestas aparecem progressivamente. Cores, contornos, texto e setas
complementam a legenda.

Até 70 entidades/140 vínculos agregados em desktop, 36/65 em mobile. O limite é
de desenho, não de consulta. Todas as relações do contexto permanecem na tabela
(30 por página) e nos registros do painel (15 por página). Busca incremental em
todas as identidades (20 por página), acentos normalizados e tokens de nomes
compostos. Homônimos têm IDs/resultados distintos. Nomes e CNPJs de campanhas
já autorizados pelo contrato localizam sua pessoa titular; documento pessoal
não é indexado nem pesquisável. Avaliação jurídica: [privacidade](raiox-navigation-privacy.md).

## Evidências locais de 13/10/2026

As fixtures automatizadas são inventadas e não são publicadas como finanças.
O teste bloqueante Charles → Izaura compara IDs, valores, evidências e grafo
entre clique, pesquisa, URL e vários saltos, além de filtros, histórico e
preservação de registros distintos de mesmo valor.

Separadamente, Chromium com o JSON real do commit `cd709b8` confirmou 40 registros
diretos, 30 campanhas e R$ 1.016.000 para o ID publicado da doadora localizado pela
busca Izaura. Charles permaneceu entre os beneficiários. As duas páginas da
tabela foram comparadas integralmente nas três rotas de seleção. Não se trata
de prova de identidade por semelhança de nome: a navegação usa o ID do registro
já resolvido no pacote oficial.

- Suíte Python: 435 testes + 17 subtestes aprovados; o ambiente sem Playwright
  pula o módulo de navegador, que é executado separadamente e obrigatoriamente
  no CI de Goiás.
- Chromium real: 8 testes de integração aprovados, incluindo falha/retry,
  geral, alias/URL inválida, isolamento de hover/pan, invariância do cursor,
  pinch, filtros explícitos, homônimos, CPF bloqueado e 1.200 doadores sintéticos.
- axe-core: zero violações automatizadas WCAG A/AA nos dois temas, em 1440×1000
  e 390×844, também com a base real. A auditoria automática não substitui toda
  avaliação humana de acessibilidade.
- Transporte/publicação: 54 testes offline de isolamento, falhas, recuperação,
  backup e validação aprovados. Empacotamento oficial validou HTML/CSS/JS e
  excluiu financeiro.
- Benchmark local Node 22, mediana de 5 execuções: índice anterior 98,15ms,
  índice novo 62,83ms. Consulta direta de Izaura: média 0,18ms em 1.000 execuções.
  Fixture de 10.000 doadores recupera todos e mantém desenho limitado, abaixo
  do orçamento de 4s do teste. São medidas locais, não latência de produção.
- Assets fonte: 102.558 → 131.263 bytes sem compressão, sem biblioteca nova de
  runtime. O JSON de 6.522.707 bytes permanece no ciclo de publicação financeiro.
- SHA-256 financeiro preservado:
  `706e933df5079771532cd06aa406a0e5f3e0935cd00fb3aa003a035cbe25a693`.

Integração/publicação devem ser comprovadas no relatório de execução por PR,
SHA efetivo, Actions, recibo e HTTPS. Este documento descreve implementação e
validação local; não declara por si uma implantação concluída.
