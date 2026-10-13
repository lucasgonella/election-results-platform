# Exploração geográfica eleitoral

O mapa do portal é uma visualização descritiva dos resultados presidenciais por
unidade da federação. O mapa e a tabela usam o mesmo contexto da página:
turno, publicação, UF e candidatura. Não há coleta, projeção, publicação de dados
ou alteração de serviços neste componente.

## Limites e procedência

A auditoria do exportador (`collector/src/static_site_builder.py`) confirma o
contrato atual: Presidência no Brasil, nas 27 UFs e no Exterior. Não existem
resultados municipais neste inventário estadual. O modo **Municípios** usa o
[pipeline municipal isolado](municipal-presidential-map.md), com coleta EA12/EA15/EA20,
malha IBGE de 2025 e publicação própria. Não associa códigos por semelhança de
nome nem distribui votos estaduais entre municípios.

As geometrias foram obtidas em 12/10/2026 diretamente da
[API oficial de malhas do IBGE](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3):

```
https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?intrarregiao=UF&formato=application/vnd.geo+json&qualidade=minima
```

O IBGE documenta essas malhas simplificadas como adequadas a aplicações web.
A geometria é ilustrativa; não serve para medição cadastral, delimitação legal
ou análise de área. O endpoint foi consultado sem `periodo`, e o arquivo local
registra o hash dos bytes recebidos; a data da consulta não significa que a
malha tenha ano de referência 2026.

Os 27 `codarea` foram comparados integralmente com os IDs, siglas, nomes e
regiões da [API oficial de localidades](https://servicodados.ibge.gov.br/api/docs/localidades),
consultada em `https://servicodados.ibge.gov.br/api/v1/localidades/estados`.
Os códigos UF possuem dois dígitos; não são códigos de municípios ou códigos
municipais do TSE. Correspondência verificada:

| Região | UF e código IBGE |
| --- | --- |
| Norte | RO 11; AC 12; AM 13; RR 14; PA 15; AP 16; TO 17 |
| Nordeste | MA 21; PI 22; CE 23; RN 24; PB 25; PE 26; AL 27; SE 28; BA 29 |
| Sudeste | MG 31; ES 32; RJ 33; SP 35 |
| Sul | PR 41; SC 42; RS 43 |
| Centro-Oeste | MS 50; MT 51; GO 52; DF 53 |

O asset `web/public/eleicoes/brazil-states.js` contém exclusivamente geometrias,
metadados do IBGE e caminhos SVG. JSON eleitoral não é incorporado nesse asset.
A transformação usa Albers equivalente, com paralelos −5°/−42° e centro
−54°/−16°, ajustada a uma janela 820 × 740. Coordenadas projetadas são
arredondadas a 0,1 unidade, vértices consecutivos idênticos são removidos e todos
os anéis são preservados. Cada UF registra centro, limites, sigla e código IBGE.
Não há API cartográfica externa durante a navegação.

SHA-256 do GeoJSON simplificado original:
`07c671aa87aa1ab296c446de6294df9827112782537b996c0a160284907e7c0f`.
O hash da resposta de localidades está no metadado `localitiesSha256` do asset.

## Contrato de integração

Carregar `brazil-states.js`, `electoral-map.js` e `electoral-map.css` na release
visual do portal. Montar em `#electoral-map-root`. O componente usa:

```js
window.ElectionPortal.getContext()
// {round, manifest, version, dataBase, scope, office, result, candidate}
window.ElectionPortal.loadResult(scope, 1, {signal})
window.ElectionPortal.selectScope(scope, 1)
window.ElectionPortal.setCandidate(ballot_number)
```

Mudanças completas de contexto disparam `election:context` no `document`, com o
mesmo objeto em `event.detail`. O mapa fixa as linhas do manifest ao iniciar
uma leitura. Verifica turno, UF, cargo presidencial, eleição, `tse_idg` e
`captured_at` do resultado. A candidatura selecionada usa o número de urna
para compartilhar o filtro entre UFs; identidade na comparação entre turnos
requer também sequência TSE igual ou nome e partido correspondentes.
`window.ElectoralMap.candidateColor(ballot_number)` fornece cores determinísticas
compartilháveis com os cards, com contraste mínimo 4,5:1 para labels brancos.

O cache é reiniciado ao mudar turno, marcador, diretório de dados ou geração do
manifest. São feitas no máximo quatro leituras simultâneas. Troca de contexto
aborta solicitações anteriores e descarta respostas atrasadas mesmo que o
transporte ignore cancelamento. Falhas não ficam definitivamente em cache;
**Tentar novamente** repete a leitura da publicação selecionada.

Parâmetros compartilháveis adicionais: `mapa` (leitura), `regiao`, `candidate`
e `vista=table`. `scope`, `office` e `turno` continuam pertencendo ao roteamento
existente da página. Filtros incompatíveis de candidatos são limpos após a
leitura do novo elenco oficial.

## Critérios e cálculos

- **Mais votado:** maior quantidade de votos nominais válidos na UF. Votação
  zerada, candidaturas com votos inválidos, totais contraditórios e empate
  recebem cor neutra. Essa classificação nunca significa candidato eleito.
- **Consolidação:** somente `snapshot.totalization_final === true`,
  `sections.total > 0` e `sections.totalized === sections.total`.
  Percentual arredondado a 100% ou todas as seções com confirmação final
  ausente/falsa não são suficientes. Contorno tracejado e texto identificam
  apuração ou totalização ainda parcial. O mapa não infere finalidade para
  formatos legados que omitem esse campo.
- **Percentual do candidato:** `candidate.votes / snapshot.votes.candidate_valid
  × 100`; usa `snapshot.votes.valid` apenas quando o primeiro campo está
  ausente. Se não houver denominador válido, pode exibir exclusivamente
  `candidate.vote_percentage` informado pelo TSE. Não soma candidaturas para
  inventar o denominador.
- **Diferença entre líderes:** `(primeiro.votes − segundo.votes) / votos válidos
  nominais × 100`, em pontos percentuais. Requer dois candidatos e denominador
  oficial coerente. A diferença absoluta em votos aparece no painel.
- **Abstenção:** `snapshot.abstentions.total / snapshot.electorate.totalized × 100`.
  Descreve o eleitorado das seções já totalizadas; não extrapola para o
  eleitorado das seções pendentes.
- **Comparação entre turnos:** percentual da mesma candidatura e UF no turno
  selecionado menos percentual no outro turno. Ausência de candidatura não
  equivale a zero. Requer votos disponíveis nos dois conjuntos. A escala de
  cor satura em ±30 p.p.; o painel e a tabela conservam o valor exato.

A comparação é uma ação explícita. Cada turno possui seu próprio marcador
(`/data/version.json` e `/data/turnos/2/version.json`) e seu próprio diretório
imutável `releases/<snapshot_id>`. O marcador do outro turno é lido novamente
após o manifest; mudança de ativação interrompe a comparação. Marcadores
legados sem snapshot verificado, manifest misto, caminho inesperado e resultado
de outra publicação falham fechados. Nunca há fallback do segundo para o
primeiro turno. Se pelo menos um dos resultados comparados estiver parcial,
o contorno permanece tracejado. As fórmulas também aparecem na interface.

## Interação, acessibilidade e desempenho

Zoom por botões e Ctrl/⌘ + roda; pan por arraste; redefinição da visão; seleção
por estado; filtro regional; pesquisa por nome/sigla; legenda clicável; painel
contextual; alternativa tabular equivalente. O mapa possui navegação por setas
entre centros das UFs, seleção por Enter/Espaço e um ponto de entrada de Tab.
Na leitura por liderança, candidaturas que lideram ao menos uma UF aparecem
primeiro, ordenadas pelo número de UFs; as demais permanecem selecionáveis em
**Outras candidaturas (sem liderança)**. Se não houver lideranças classificáveis,
o elenco completo continua visível, com zero UFs e indicação explícita de
aguardando apuração, falta de dados ou ausência de liderança.
Todos os valores relevantes têm texto, sem depender apenas da cor. Em mobile,
filtros são recolhíveis, o painel aparece abaixo do mapa e tooltips não cobrem a
visualização. `prefers-reduced-motion` elimina animações e transições.

A malha contém 4.985 vértices simplificados em 27 paths. O arquivo visual ocupa
61.720 bytes; compressão gzip de referência: 21.860 bytes. Essa medição local
não presume compressão habilitada na hospedagem. Renderização usa SVG nativo,
sem WebGL, tiles, SDKs ou bibliotecas cartográficas adicionais. As 27 linhas da
tabela dispensam virtualização; não se carregam milhares de polígonos municipais
sem resultados oficiais. O desempenho observado em fixtures locais e em HTTPS
é relatado separadamente das estimativas de tamanho.

## Validação offline

```sh
node --test tests/electoral_map.test.js
python -m pytest -q tests/test_electoral_map.py
```

As fixtures são explicitamente sintéticas. Os testes verificam as 27
correspondências UF/IBGE, geometria finita, empate, votação zerada, consolidação,
denominadores, valores inválidos, mesma candidatura entre turnos, identidade
do resultado, separação de namespaces, mudança de ativação, cache, repetição de
falhas, cancelamento, respostas atrasadas e contraste dos labels.
A validação de browser deve incluir filtros, teclado, zoom, tabela, mobile,
modo escuro, console e auditoria de acessibilidade, sem tratar fixtures como
resultados de produção.
