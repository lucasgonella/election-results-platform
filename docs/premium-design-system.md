# Sistema visual do Portal Eleitoral

A identidade combina papel quente (`#f5f4ef`), tinta azul (`#102334`) e teal
(`#087f8c`). Tipografia sem serifa mantém navegação e números nítidos; a serifa
editorial aparece nos títulos de exploração. Fontes são locais/do sistema: não
há dependência de CDN nem de download de fontes. Numerais tabulares evitam que
contadores mudem de largura durante atualizações.

## Organização e contrato

`design-system.css` contém os tokens de cores, tipografia responsiva,
espaçamento, largura, superfícies, foco, movimento e primitives de interface.
`styles.css` aplica esses tokens à central eleitoral, cartões presidenciais,
resultados, tabelas, favoritos e descoberta. `composition.css` organiza a
comparação do Congresso. O Raio-X possui seu próprio pacote de publicação.

As duas entradas do portal carregam os mesmos arquivos compartilhados. O script
`design-system.js` é pequeno e síncrono no cabeçalho para aplicar o tema antes
da pintura; ele não consulta dados, marcadores de publicação ou serviços.

| Contrato | Comportamento |
| --- | --- |
| `.site-header`, `.site-header-inner`, `.brand`, `.main-nav` | Navegação persistente e identidade comum |
| `[data-nav-toggle][aria-controls]` | Menu móvel; Escape fecha e devolve foco |
| `[data-theme-toggle]` | Alterna claro/escuro e identifica a ação pelo nome acessível |
| `[data-dialog-open="id"]`, `[data-dialog-close]` | Abre/fecha `dialog` nativo, com Escape e foco geridos pelo navegador |
| `.masthead`, `.eyebrow`, `.editorial`, `.section-heading` | Hierarquia editorial de apresentação e exploração |
| `.surface`, `.button`, `.segmented`, `.badge`, `.legend` | Componentes reutilizáveis |
| `.empty-state`, `.error-state`, `.skeleton` | Espera, ausência e erro distintos |
| `.table-scroll` | Região nomeada e foco por teclado para rolagem horizontal |
| `.sr-only`, `.skip-link`, `:focus-visible` | Leitura assistiva, salto para o conteúdo e foco visível |

O tema segue `prefers-color-scheme` até uma escolha explícita, guardada em
`election-results:theme:v1`. Acesso ao armazenamento é protegido por `try/catch`:
navegação privada ou armazenamento negado não interrompem o portal. Eventos
`storage` sincronizam a preferência entre abas; a chave dos favoritos permanece
independente. `window.PortalDesign.applyTheme` permite aplicar um tema visual;
não modifica os filtros eleitorais.

## Acessibilidade e visualização

Controles principais usam área de toque de pelo menos 44 px. Os inputs possuem
labels, tabelas podem receber foco para rolagem, a navegação tem localização e
página atual, e avisos de carregamento são anunciados sem movimentar o foco.
O menu oferece fechamento por teclado. O drawer de favoritos mantém a leitura
original, acrescentando foco inicial, confinamento de Tab, conteúdo de fundo
`inert` e restauração do foco ao fechar. Diálogos usam a implementação nativa.
`prefers-reduced-motion` reduz transições e desativa rolagem animada.

A paleta das candidaturas dispõe de seis tokens, mas cores não são o único
identificador: nomes, partido, valores e legendas continuam explícitos. O código
de visualização deve associar uma cor estável à identidade da candidatura.
Fotografias ausentes não são substituídas por pessoas inventadas.

A [WCAG 2.2 do W3C](https://www.w3.org/TR/WCAG22/) fundamenta as decisões de
reflow, teclado, foco, contraste, tamanho de alvos e identificação de estados.
Testes automáticos e inspeção visual ajudam a validar esses critérios, mas não
representam uma certificação completa de conformidade ou teste com todas as
tecnologias assistivas.

## Congresso

A página troca uma apresentação isolada por um percurso com identidade comum,
resumo das casas, comparação visual, tabelas pesquisáveis e metodologia
recolhível. Os filtros escolhem Câmara/Senado e buscam partidos nas tabelas; o
texto explica que os semicírculos sempre mostram todas as cadeiras. A visão
“Tabelas” oferece uma leitura numérica direta, especialmente em telas menores.
Cada gráfico possui alternativa tabular com cabeçalhos e nome acessível.

A lógica `composition.js` foi preservada. Ela consulta somente o primeiro turno
e o snapshot indicado por seu marcador. Não reutiliza dados do segundo turno.
O texto identifica a origem das bancadas “Atual” e explica que essa base é
incorporada ao frontend, sem consulta parlamentar em tempo real. A posição no
semicírculo não representa ideologia nem localização física. A variação conta
cadeiras, não interpreta tendências. Cadeiras ainda não definidas permanecem
pendentes. Falha HTTP encerra o skeleton e exibe o estado indisponível.

## Validação local e peso dos assets

`tests/test_web_design_system.py` executa o JavaScript real em Node para validar
a persistência do tema, armazenamento negado, alterações do sistema, sincronização
entre abas e fechamento do menu por Escape. Testes existentes da composição e
leitores continuam verificando os contratos eleitorais.

O teste de navegador local usa exclusivamente fixtures sintéticas: dois
candidatos de Câmara, sendo apenas um oficialmente eleito, e um senador eleito.
Ele confirmou larguras 1440, 768, 390 e 320 px sem rolagem horizontal, filtros,
visão de tabelas, vazio, tema persistido e movimento reduzido. Os controles
visuais não emitiram requisições eleitorais adicionais. Axe-core não apontou violações automáticas WCAG A/AA em 1440 e 390 px, nos
dois temas. Esse resultado não substitui a avaliação com leitores de tela.
Um fixture HTTP 503
confirmou o aviso de erro e a interrupção da animação de carregamento.
Os screenshots e o relatório local ficam fora do repositório em
`/opt/election-delta-staging/premium-composition-*.png` e
`/opt/election-delta-staging/premium-composition-qa.json` e
`/opt/election-delta-staging/premium-composition-accessibility.json`.

Medição antes da publicação, em bytes; gzip calculado localmente e não uma
alegação sobre a compressão efetivamente configurada na hospedagem:

| Asset | Bytes | Gzip local |
| --- | ---: | ---: |
| `design-system.css` | 14.450 | 3.789 |
| `design-system.js` | 10.364 | 2.903 |
| `styles.css` | 37.163 | 6.268 |
| `composition.css` | 10.732 | 2.376 |
| `composicao.html` | 12.569 | 3.852 |

A auditoria integrada da home utilizou o preview local de GET dos JSONs públicos
atualmente publicados. Em 1440 e 390 px, nos temas claro e escuro, não houve
overflow horizontal, erros de página/console nem violações automáticas WCAG A/AA
no axe-core. Fontes, busca, comparação de turnos e favoritos também foram
avaliados abertos em 390 px: todos couberam na tela e tiveram zero violações
automáticas. Foram validados Escape, foco da busca, foco/inert/restauração dos
favoritos e navegação nos dois turnos. O cabeçalho móvel passou de duas linhas
(90 px) para uma linha (69 px), com alvos de 44 px e contador de favoritos em
badge. O reflow da home também foi confirmado em 320 px. Relatórios locais:
`premium-home-visual-audit.json`, `premium-home-dialog-audit.json` e screenshots
`premium-home-*-visual.png`, sob `/opt/election-delta-staging/`.

A toolbar de resultados mantém busca flexível, seletor de apresentação e CSV na
mesma linha em desktop; em mobile a busca ocupa sua própria linha. As tabelas
usam numerais tabulares, cabeçalhos com hierarquia visual e uma região nomeada
com foco para rolagem horizontal por teclado. A visão tabular foi auditada em
1440 e 390 px, sem overflow da página e sem violações automáticas WCAG A/AA.
Evidência local adicional: `premium-toolbar-table-audit.json`.

A validação local não comprova publicação. CI, SHA integrado, estado FTP, hashes
HTTPS e resultados de navegador na URL pública pertencem ao relatório final
operacional do redesign.
