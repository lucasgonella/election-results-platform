# Central Eleitoral 2026: direção, contratos e aceitação

O redesign reconstrói a exploração visual com um percurso panorama → território
→ candidatura → registro. Portal, Congresso e Raio-X compartilham a linguagem
editorial de papel quente, tinta azul e teal, mantendo os dois pacotes de deploy
independentes. A hierarquia prioriza contexto, números, comparação e procedência.
Não houve alteração do coletor, banco, publicadores eleitorais, ETL financeiro,
credenciais, serviços, estados transacionais ou configuração de FTP.

## Pesquisa de referências

As fontes abaixo foram consultadas como referência de qualidade e interação,
sem copiar um layout. A aplicação das ideias ao portal é uma decisão própria:

| Fonte primária | Observação e decisão aplicada |
| --- | --- |
| [Bloomberg, resultados eleitorais](https://www.bloomberg.com/graphics/2024-us-election-results/) | Contexto eleitoral e geografia: resumo inicial, mapa e comparação com leitura numérica. |
| [Reuters Graphics, arquivo](https://graphics.thomsonreuters.com/) | Descoberta editorial por assunto: uma entrada guiada antecede a exploração detalhada. O arquivo consultado contém exemplos de 2024, não foi tratado como catálogo completo de 2026. |
| [Our World in Data, redesign](https://ourworldindata.org/redesigning-our-interactive-data-visualizations) e [mapas](https://ourworldindata.org/new-features-better-maps) | Controles próximos à visualização e alternativa tabular: filtros explícitos, métodos e números acessíveis. |
| [Observable, choropleth](https://observablehq.com/@observablehq/plot-choropleth) | Cor ligada a uma variável documentada: cada modo informa seu critério e mantém ausências neutras. |
| [Mapbox, mapas eleitorais](https://www.mapbox.com/elections) | Exploração em várias escalas: zoom, pan e seleção contextual, limitada às escalas presentes no contrato oficial. |
| [Flourish, network graph](https://helpcenter.flourish.studio/hc/en-us/articles/8761553784719-Network-graph-an-overview) | Redes direcionadas e pesos: setas, escalas por raiz quadrada e detalhe de cada registro. |
| [ArcGIS, seletores](https://doc.arcgis.com/en/dashboards/latest/create-and-share/selectors.htm) e [acessibilidade](https://doc.arcgis.com/en/dashboards/latest/reference/accessibility-features.htm) | Seleção contextual e teclado: URL compartilhável, foco visível e alternativa tabular. |
| [WCAG 2.2](https://www.w3.org/TR/WCAG22/) | Reflow, contraste, teclado, movimento reduzido, nomes acessíveis e estados compreensíveis. |

Financial Times Visual Journalism (`ig.ft.com`) e páginas interativas do New
York Times foram pesquisados, mas os acessos disponíveis retornaram erro ou
bloqueio de robots. Não se afirma uma inspeção desses layouts inacessíveis.

## Portal: contexto único e leitura verificada

`portal-bridge.js` expõe `ElectionPortal`: turno, publicação fixada, localidade,
cargo e candidato. O mapa e a área presidencial escutam `election:context`.
O leitor memoiza consultas da mesma publicação e invalida o cache quando muda o
marcador. Escopo, cargo, eleição, turno, ambiente, IDG, captura, IDs e valores
são conferidos contra o manifesto. Respostas atrasadas da seleção anterior são
descartadas; falha na atualização conserva o contexto publicado anterior.

O primeiro turno lê `/data/version.json`. O segundo lê somente
`/data/turnos/2/version.json`, sem fallback para o primeiro. A comparação entre
turnos é uma ação explícita que valida os dois conjuntos independentemente.
Turno, UF, cargo, candidato, região e leitura do mapa ficam na URL. A troca de
turno conserva filtros compatíveis e descarta seleções sem correspondência.

O panorama dos cargos conta localidades presentes no manifesto; não estima
eleitos. Presidência mostra totalização, candidaturas, partido, número, votos,
percentual e situação TSE. Cadastro sem apuração mostra espera, sem percentuais
artificiais. Resultados preservam favoritos e apresentam cards, tabela paginada,
busca e CSV filtrado com proteção contra fórmulas. Valores ausentes não viram zero.

O mapa usa 27 geometrias oficiais IBGE com códigos conferidos, simplificadas e
incorporadas em um asset visual. Há seleção, regiões, busca, zoom, pan, legenda,
painel contextual, tabela, liderança, percentual, margem, abstenção e comparação
entre turnos. Empate e ausência de votos não recebem uma liderança inventada.
Totalização final exige o sinal explícito da fonte e todas as seções totalizadas;
liderança geográfica não significa candidatura eleita.

Contratos, fórmulas, geometria, origem e limites: [mapa](geographic-data.md).
Tokens, teclado, tema e Congresso: [design system](premium-design-system.md).
Identidades, evidências, filtros e caminhos: [Raio-X](premium-finance-redesign.md).

## Limites da fonte entregues como estados confiáveis

- O manifesto atual contém Brasil, UFs e Exterior. Municípios ficam desabilitados
  com explicação; não se inferem resultados municipais a partir de uma UF.
- Fotografias autorizadas e catálogo verificável de snapshots históricos não
  estão presentes. São usados monogramas e uma explicação de indisponibilidade.
- No segundo turno, o cadastro oficial publicado contém 34 alvos e 68 linhas de
  candidaturas, com zero seções totalizadas na auditoria. A interface mostra os
  nomes oficiais e espera pela apuração.
- O Raio-X une entidades apenas pelo ID. Namespaces de contrapartes e candidaturas
  não são reconciliados por nome; caminhos indiretos podem não existir na base.
- O Congresso preserva sua lógica de primeiro turno e identifica a referência
  incorporada das bancadas atuais, sem apresentá-la como consulta em tempo real.

## Desempenho e validação

Não foi adicionada biblioteca de mapa, grafo ou framework em runtime. Fontes são
do sistema. A geometria tem 4.985 vértices, aproximadamente 61,7 kB e 21,9 kB
com gzip local. O mapa limita consultas simultâneas a quatro, reutiliza a
publicação fixada e só busca o outro turno por solicitação explícita.

O Raio-X limita o desenho a 70 entidades e 140 vínculos agrupados, informando
o corte; todos os registros permanecem na tabela. Listas, tabelas e evidências
são paginadas. Caminhos limitam-se a quatro etapas e 5.000 entidades visitadas.

Fixtures sintéticas verificam isolamento de turno, publicação, fórmulas,
identidade, ausências, erros, caminhos direcionados e limites de renderização.
A navegação integrada usa somente GET dos JSONs públicos reais no preview local.
Há inspeção visual, teclado, temas e reflow de 320 a 1.440 px, além de Axe-core
WCAG A/AA. Os testes automáticos não constituem uma certificação completa ou
substituem avaliação com leitores de tela.

Aceitação local final: **402 testes e 15 subtests aprovados**, além dos 48 casos
do cliente FTP executados separadamente. O navegador verificou os dois turnos,
27 UFs, seleção compartilhada de candidato/UF, filtros, tabela, CSV, favoritos,
busca e comparação independente. Foram verificadas 30 combinações de página,
largura e tema (home, Raio-X e Congresso; 1.440, 1.024, 768, 390 e 320 px;
claro/escuro), sem overflow horizontal nem exceções de página.

Benchmark descritivo em Chromium no app01, três contextos novos por versão,
preview local com proxy GET e JSONs em cache, sem simulação de rede: a mediana
para os cards de resultados passou de **316,3 ms para 473,1 ms** (+156,8 ms),
com o novo mapa completo em aproximadamente **743 ms**. O DOM passou de 733
para 1.344 elementos ao adicionar mapa, contexto e comparação. Não são Web
Vitals de produção, nem se afirma melhoria da velocidade em relação à home
anterior; o custo medido acompanha a ampliação funcional. Compressões citadas
são gzip local, não uma garantia sobre os headers da hospedagem.

## Publicação e preservação

Seguem vigentes [os procedimentos oficiais de FTP](frontend-ftp-deployment.md):
PR, CI no SHA efetivo, merge, Actions hospedado, FTP passivo sem TLS na porta21,
assets antes dos HTMLs, backups, journal e verificação HTTPS de hashes.
Os JSONs financeiros e eleitorais são excluídos de ambos os pacotes visuais.
Antes da publicação foram confirmados os dois componentes íntegros, locks
ausentes, journals concluídos e os três timers ativos. A atualização financeira
automática da main foi incorporada sem modificar seu conteúdo.

Relatórios operacionais e screenshots ficam fora do Git, sem segredos. O relatório
final da sessão identifica commits, PR, CI, deploy, métricas e URLs efetivamente
verificadas em produção.
