# Presidência por município: fonte própria e publicação isolada

O modo Municípios usa resultados municipais EA20 de 2026, cargo 1, do ambiente
oficial. Não distribui votação nacional/estadual entre cidades. A configuração
EA11 fornece eleição, turno, ciclo, pleito e templates de diretório. O EA12
fornece o inventário nacional e a correspondência exata TSE/IBGE (`cd`/`cdi`).
O campo IBGE observado na fonte possui sete dígitos; não se tenta completar
códigos por nome, município vizinho ou aproximação. Brasília e Fernando de
Noronha integram o inventário territorial; localidades do exterior ficam fora.

Referências primárias:

- [TSE: informações técnicas de 2026](https://www.tse.jus.br/eleicoes/informacoes-tecnicas-sobre-a-divulgacao-de-resultados).
- [EA12: municípios](https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/tse-ea12-arquivo-de-configuracao-de-municipios).
- [EA20: resultados unificados](https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/tse-ea20-arquivo-de-resultado-unificado).
- [IBGE: malha municipal de 2025](https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2025/Brasil/).

## Coleta e integridade

`municipal_collection` mantém cache HTTP e checkpoint exclusivos por turno,
sem usar PostgreSQL, cache/estado dos serviços eleitorais, financeiro ou Amazonas.
Quatro workers compartilham limite de quatro requisições por segundo, timeout,
três tentativas com backoff para falhas transitórias e ETag/Last-Modified.
404/204 abrem o circuito para evitar varrer milhares de URLs indisponíveis;
429 conserva cooldown de no mínimo dez minutos. Redirects e `f != o` são recusados.

EA15 informa as atualizações municipais. Um checkpoint de UF só é salvo após
concluir a partição e verificar que o acompanhamento não mudou. Registros são
reprocessados pelos mesmos validadores mesmo quando reutilizados do cache.
Cache não é fonte substituta para uma eleição diferente. Mesmo sem mudança no
EA15, os arquivos municipais são revalidados condicionalmente após seis horas;
mudança de cadastro ou divergência final força revalidação da UF. Falhas preservam a
publicação anterior e não produzem pacote nacional incompleto.

Cada município conserva ano/turno/eleição, UF, códigos oficiais, nome, cargo,
votos/percentuais/destinação por sequência oficial de candidato, seções,
eleitorado, estado de totalização, geração/captura, URL e SHA-256 da origem.
Nome/número/partido dos candidatos ficam no catálogo da mesma eleição.
O percentual descritivo é votos do candidato / votos válidos nominais (`vvc`).
`pvapn` oficial é preservado e validado contra esse denominador, com tolerância
de arredondamento de 0,02 p.p. Votos anulados não recebem liderança válida.
Empates, zero seções, ausência de denominador ou totais incoerentes não geram
vencedor. Final exige `tf=s` e todas as seções totalizadas; 100% arredondado não
é suficiente. Mais votado no município nunca significa eleito naquele município.

A reconciliação soma candidatos por UF, sem exterior. Igualdade é exigida quando
todos os municípios e a UF têm totalização final. Em dados parciais, diferenças
de timestamps CDN são identificadas; não se exigem somas nacionais contra
grandezas que incluem exterior. Cobertura conta esperados, processados,
disponíveis, aguardando, inconclusivos, pendentes, falhas e percentual por UF.

## Geometrias e visualização

A API simplificada do IBGE omite Boa Esperança do Norte/MT; por isso a fonte é o
ZIP nacional oficial de 2025, validado integralmente e associado pelos códigos.
Os dois registros geográficos não configurados como municípios pelo TSE não
ganham votação. Todas as 5.571 unidades do inventário observado foram associadas.
Polígonos são simplificados em duas resoluções por UF, preservando a topologia
de cada polígono. A malha original não satisfaz o critério GEOS mais estrito de
cobertura com arestas compartilhadas idênticas; não se inventam ou corrigem
limites. A simplificação serve à visualização, não à delimitação cadastral.

Canvas nativo desenha polígonos reais com preenchimento par/ímpar, incluindo
ilhas e buracos; nenhuma geometria é substituída por pontos/círculos. Paths são
construídos incrementalmente e resultados completos só são carregados por UF
quando necessários. Nacional usa malha reduzida; selecionar UF usa a resolução
detalhada. Geometrias têm URLs imutáveis próprias e podem ser reutilizadas entre
releases/turnos. Cache do leitor é limitado. Não há SDK cartográfico externo.

Busca normaliza acentos e mantém UF/código nos resultados para separar homônimos.
Mapa/tabela/painel usam a mesma publicação municipal fixada, com URL de seleção.
Tabela tem 30 linhas por página. Hover e zoom não selecionam; clique/toque/Enter
abrem dados. Pan tem tolerância de movimento; Ctrl/scroll preserva o ponto sob
o cursor por `t' = p - (p-t) × s'/s`. Touch aceita pan e pinch. A tabela e busca
são alternativas por teclado. Claro/escuro seguem o design system existente.
A comparação municipal/estadual usa a UF da própria release municipal.

## Publicação e operação

Namespace público exclusivo: `/public_html/municipal-2026`.
Marcadores: `turnos/1/version.json`, `turnos/2/version.json`.
Resultados imutáveis: `turnos/<turno>/releases/<sha256>/`.
Geometrias imutáveis: `geography/<sha256>/`.
Journal/backup privados: `/election-municipal-deploy/<turno>/`.
Não se escreve `/data`, primeiro/segundo turno existente, HTML do Raio-X,
financeiro, estudos ou publicações de outros projetos.

`municipal_release` exporta catálogo, resumo, cobertura e partições UF com
release ID, manifesto, tamanhos e SHA-256. Recalcula a identidade de conteúdo e
recusa arquivos extras, symlinks, códigos duplicados, geometrias ausentes e
cobertura incompleta. O transportador deriva do cliente FTP existente, com
allowlist própria. FTP convencional/passivo, porta 21; credenciais existentes,
sem TLS e sem segredo em argv/logs. A conta continua ampla: isso não comprova
isolamento no servidor nem aprova o protocolo eleitoral do PR #75.

O workflow `municipal-presidential-data.yml` coleta somente na main após CI,
conserva cache inclusive em interrupções e entrega artefato validado ao job FTP.
O job escritor usa concurrency global `locaweb-frontend-production`, MKD,
journal, backup do marcador, temporários exclusivos e leitura FTP/HTTPS dos
arquivos antes de ativar o marcador. O marcador é uma seleção por rename,
não uma transação atômica da hospedagem nem garantia multinó/NFS.
Não há deploy de PR. O frontend segue seu workflow visual original do portal.

Operações manuais oficiais: Actions → **Official municipal presidential data**,
main, turno, `run`, `status` ou `recover`. Lock conhecido com journal exige
recovery; lock desconhecido falha fechado. Nunca apagar locks manualmente.
Recuperação preserva o marcador anterior quando a preparação ficou incompleta,
ou conclui uma ativação já verificada; ativos antigos não são apagados.
Locks pendentes dos componentes visuais bloqueiam a publicação municipal.

O segundo turno usa caches, checkpoints, releases e journals próprios. Antes de
haver seções presidenciais totalizadas, o produtor registra espera e não ativa
dados municipais; o frontend mostra Aguardando dados municipais, sem reutilizar
o primeiro turno. Uma nova versão é fixada por inteiro, nunca UF a UF sobre um
snapshot anterior. Mudanças do marcador durante sua leitura falham fechado.

## Testes

`python -m unittest tests.test_municipal_pipeline -v` e
`python -m pytest -q tests/test_municipal_map.py` usam fixtures inventadas.
`municipal-ci.yml` exige Chromium real e axe A/AA em desktop/mobile,
claro/escuro, além de isolamento de turnos, zoom, navegação e URL. Ausência
das dependências não pode aprovar o job dedicado. O teste automático não é
certificação integral de acessibilidade. Evidências reais e métricas de produção
devem ser registradas após a confirmação pública da release.
