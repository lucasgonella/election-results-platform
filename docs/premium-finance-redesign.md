# Raio-X Goiás: exploração financeira editorial

O redesign visual é um leitor estático isolado. Não altera ETL, dados, identidades,
credenciais, serviços, horários ou o mecanismo FTP. O JSON pertence exclusivamente
ao fluxo financeiro existente.

## Arquitetura e experiência

- `finance-core.js`: funções puras de validação, filtros, identidade, datas,
  agrupamento de registros e caminhos direcionados, sem dependências externas.
- `finance-app.js`: coordena um contexto único de filtros e seleção, URL
  compartilhável, grafo SVG, tabela paginada, evidências e preferências locais.
- `finance.css`: tokens próprios para navy, papel, teal e cores de entidades,
  tipografia editorial nativa, claro/escuro e controles responsivos. A preferência
  de tema usa `election-results:theme:v1`, compartilhada com o portal e
  sincronizada entre abas; a chave local anterior é aceita como fallback. O componente
  não importa assets do portal, preservando suas fronteiras de publicação.
- O dado é lido em `/eleicoes/goias/raio-x/data/go-2026.json`. O caminho estável
  funciona no entrypoint público e no HTML imutável de uma release, mesmo quando
  JavaScript e CSS estão em `frontend-releases/<SHA>/`.

A tela apresenta um panorama da base, um início guiado, filtros de candidatura e
transferência, uma área central de grafo e um painel de contexto. Em celular, os
filtros são recolhíveis e a tabela é uma alternativa ao grafo. A tabela pagina 30
registros, a lista de candidaturas 20 e os detalhes 15, sem despejar milhares de
itens no DOM. O grafo tem pan, zoom, ajuste, exportação SVG, seleção por teclado,
realce dos vizinhos e expansão/recolhimento de um segundo nível documentado.

## Semântica e limitações deliberadas

Identidades dependem exclusivamente de IDs. A candidatura declarada é o único
tipo de entidade inferível do contrato: as demais entidades são rotuladas como
**contrapartes, tipo não informado**. Não classificamos pessoas, empresas ou
partidos por nomes ou prefixos. Categorias de conexão vêm de `transfer.type`.

Registros são agrupados apenas pela combinação exata de origem, destino e
categoria. A direção permanece intacta. Cada grupo preserva todos os IDs, datas,
valores e fontes originais. Reciprocidade exige registros reais em ambas as
direções dentro dos filtros; a existência de uma relação não demonstra
irregularidade.

O raio dos nós segue a raiz quadrada de seu volume no contexto, e a espessura
segue a raiz quadrada da soma dos valores informados no grupo. Ausências usam um
mínimo visual. Categorias possuem padrões de traço; o tipo completo aparece ao
selecionar a relação. O desenho prioriza os maiores valores e limita-se a **70
entidades / 140 vínculos agregados**, declarando quantos ficaram fora do desenho.
A tabela contém todos os registros do contexto. O segundo nível segue relações
reais das entidades vizinhas, sem criar transferências entre os extremos.

A busca de caminhos segue somente o sentido dos registros e limita-se a **4
etapas / 5.000 entidades visitadas**. Cada etapa mostra valor, data, ID e evidência;
valores das etapas não são somados como se fossem um único repasse. O caminho
não comprova circulação do mesmo recurso. A base atual utiliza `donor:*` para
contrapartes e outro namespace para candidaturas. Mesmo nomes iguais não
estabelecem uma ligação entre namespaces. Essa incompatibilidade pode impedir
caminhos de várias etapas; o frontend explica o limite e não o contorna.

Valores `null` não viram zero. Somas incompletas são identificadas como subtotais;
dados sem data/valor são excluídos quando o usuário define os respectivos
intervalos. Datas aceitam DD/MM/YYYY e ISO com calendário validado. URLs de fonte
só recebem links quando são HTTPS em `tse.jus.br` ou seus subdomínios, sem
credenciais ou portas alternativas. Uma URL inválida é indicada, nunca aberta.

Scope GO, ano 2026, cargos permitidos, valores finitos e IDs únicos são validados
antes de desenhar a base. Contrato inválido, falha de rede, filtros vazios e
transferências ainda não publicadas têm estados explícitos sem dados fictícios.

## Verificação local

`python -m unittest tests.test_premium_finance_graph -v` cobre 12 cenários
sintéticos: escopo, IDs, identidade por ID, URL oficial, datas brasileiras,
calendário, null versus zero, filtros combinados, agregação, reciprocidade,
caminhos direcionados, limite de busca/desenho e round-trip da URL.

A base real usada no smoke local de 12/10/2026 continha 860 candidaturas, 5.791
registros e 3.807 entidades. Em Node 22 no app01, a construção do índice levou
aproximadamente 17 ms e o panorama limitado aproximadamente 52 ms, em uma medição
local. O carregamento do primeiro grafo em Chromium local levou 1,35 s. Esses
valores dependem do ambiente e não representam métricas de rede de produção.

O smoke em Chromium validou desktop (1600 px) e celular (390 px), troca grafo /
tabela, inspeção de registros, seleção e centralização de entidades, segundo
nível, filtros e modo escuro, sem erros JavaScript ou overflow horizontal.
Axe 4.14 não detectou violações nas regras WCAG 2 A/AA, 2.1 AA e 2.2 AA
no contexto inicial real, em claro/escuro a 1440 px e 390 px. Verificações por
teclado cobriram seleção de nós e arestas, restauração de foco na candidatura em
desktop e retorno ao título do grafo ao recolher os filtros em celular. Preferência
de tema compartilhada e sincronização entre abas foram exercitadas em Chromium.

A validação local do empacotador visual preservou apenas quatro arquivos visuais;
o JSON financeiro ficou fora do pacote. Artefatos de teste e screenshots ficam
fora do repositório. Publicação exige CI, merge, FTP e confirmação HTTPS no SHA
real; teste local não comprova publicação.
