# Raio-X Eleitoral de Goiás (2026)

Frontend: `web/public/eleicoes/goias/raio-x/index.html`

## Escopo

- Todas as candidaturas para **deputado estadual e federal**, UF da candidatura **GO**, em 2026.
- Incluir candidaturas não eleitas.
- Apenas fatos documentados pelo TSE; não inferir identidade de pessoas por nome.
- Fluxos financeiros envolvendo campanhas de GO podem ter contrapartes de outra UF.
- Os vínculos precisam preservar ID da transação e URL/identificador da fonte do TSE.

## Contrato da base a ser publicada

`web/public/eleicoes/goias/raio-x/data/go-2026.json`

```json
{
  "scope": "GO",
  "year": 2026,
  "generated_at": "2026-10-09T17:00:00Z",
  "candidates": [
    {
      "id": "TSE_SQ_CANDIDATO_REAL",
      "name": "NOME_CONFORME_TSE",
      "party": "SIGLA",
      "number": "00000",
      "office": "deputado estadual",
      "status": "situação eleitoral conforme fonte",
      "votes": null,
      "revenue": null,
      "expenses": null
    }
  ],
  "transfers": [
    {
      "id": "ID_UNICO_DO_REGISTRO_ORIGINAL",
      "from_id": "ID_ENTIDADE_ORIGEM",
      "from_name": "NOME_PUBLICO_ORIGEM",
      "to_id": "TSE_SQ_CANDIDATO_REAL",
      "to_name": "NOME_PUBLICO_DESTINO",
      "amount": 0,
      "date": "2026-09-01",
      "type": "DOACAO_OU_TRANSFERENCIA",
      "source_url": "https://dadosabertos.tse.jus.br/..."
    }
  ]
}
```

**Não publicar este exemplo como se fossem registros reais.** Não gerar o JSON quando os arquivos originais não tiverem sido baixados, analisados e reconciliados.

## Fontes oficiais

- https://dadosabertos.tse.jus.br/dataset/candidatos-2026
- https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2026

A página mostra uma mensagem de indisponibilidade honesta quando ainda não existe base validada.

## Publicação

O visual segue PR → CI → merge na `main` → deploy FTP automático → verificação
HTTPS por SHA-256. `.github/workflows/deploy-goias-ftp.yml` chama o mecanismo
reutilizável, com assets versionados, backup e rollback. Ele envia somente arquivos
visuais permitidos e nunca `data/go-2026.json`. O workflow financeiro
`goias-finance-data.yml` continua proprietário desse JSON, sem alterações de ETL
ou horários. Mudanças apenas em dados não disparam o deploy visual.

O destino FTP já confirmado é `/public_html/eleicoes/goias/raio-x`; a variável
`LOCAWEB_FTP_GOIAS_DIR` deve continuar `public_html/eleicoes/goias/raio-x`. São
reutilizados os três secrets FTP existentes, porta 21, passivo, sem TLS. A conta
tem acesso amplo e o transporte não oferece criptografia.

Deploy manual, consulta de status, rollback de versão verificada e recuperação
estão no Actions, workflow **Manual frontend deploy status rollback recovery**,
branch `main`, componente `raio-x`. Não usar o receptor eleitoral ou um segundo
workflow para copiar HTMLs/JSONs deste módulo.

Procedimento central: [CI/CD visual da Locaweb](../../../../../docs/frontend-ftp-deployment.md).

## Exploração visual premium

O módulo usa assets independentes `finance-core.js`, `finance-app.js` e
`finance.css`, com filtros compartilhados pela URL, claro/escuro, grafo SVG
navegável, tabela paginada e painel de evidências. O fetch usa o caminho estável
`/eleicoes/goias/raio-x/data/go-2026.json`, compatível também com o HTML imutável
das releases. O arquivo financeiro continua sob responsabilidade exclusiva do ETL.

IDs de candidatura e de contraparte não são unidos por nome. Tipos de
contrapartes ausentes são indicados explicitamente. Caminhos seguem transferências
reais em seu sentido declarado; relações indiretas não são apresentadas como
repasses diretos. Valores ausentes permanecem distintos de zero. O grafo é
limitado e a tabela preserva o conjunto completo do contexto.

Arquitetura, método, limites e evidências locais:
[Redesign do leitor financeiro](../../../../../docs/premium-finance-redesign.md).
Testes sintéticos: `python -m unittest tests.test_premium_finance_graph -v`.

## Identidades comprovadas e campanhas

Para pessoas exclusivamente doadoras, o nome exibido usa a grafia mais frequente
nas transferências do mesmo ID, considerando apenas nomes e variações já
publicados para essa identidade. Maiúsculas/minúsculas e espaços equivalentes
contam juntos; empates e ausência de evidências mantêm o nome principal da fonte.
O critério é global, independente dos filtros e da ordem das linhas, e aparece
nas variações do painel. Nomes de candidatura não são substituídos. Nomes
originais, IDs, valores, evidências e JSON financeiro permanecem intactos.
Essa escolha de rótulo não confirma nome civil nem associa pessoas pelo nome.

O leitor aceita `identity_schema: 1`, com pessoas e campanhas associadas por
evidências oficiais, sem CPFs públicos. Repasses de campanha permanecem distintos
de doações pessoais. O ETL é o único responsável pela resolução e pelo JSON.
Método, auditoria e investigação de Luana: [identidade no Raio-X](../../../../../docs/goias-person-identity.md).

O contrato aditivo `financial_schema: 1` diferencia valor conhecido, subtotal e
ausência por candidatura. Zero exige valor explícito na fonte; versões legadas
continuam exibidas sem reclassificar zeros históricos. O leitor mantém a
completude ao consolidar candidaturas de uma pessoa e nos volumes do grafo.
Evidências, compatibilidade e limites de publicação:
[contrato dos valores financeiros](../../../../../docs/financial-value-contract.md).

## Navegação pelo índice completo

A página sem seleção explícita abre em **Visão geral**. `selected` válido é
resolvido ao ID canônico; ID indisponível retorna ao geral com aviso. Não há
persistência de seleção em storage, escolha automática ou ordenação por receita
para definir a pessoa inicial.

`getCompleteDirectConnections(index, entityId, explicitFilters)` usa somente os
índices globais `incoming`/`outgoing` do pacote validado. `q` localiza nomes e
campanhas; não restringe transações. Cargo, partido, categoria, origem, destino,
intervalos e papel são filtros explícitos, preservados entre entidades. Clique,
busca, URL e histórico abrem o mesmo conjunto direto para o mesmo ID/filtros.
Repasses próprios encontrados nas duas adjacências são contados uma vez pelo ID
da linha. Registros de mesmo valor/data não são deduplicados.

O clique centra o novo nó e conserva a escala; voltar/avançar restaura câmera e
filtros. Hover, pan e zoom não selecionam. Ctrl/Meta + scroll utiliza a inversa da
matriz SVG para preservar o ponto sob o cursor: `t' = p - (p - t) * (s' / s)`.
O modo touch aceita pinch e arrasto. Ajustar à tela calcula limites reais dos nós;
o zoom é limitado a 35–800%. Limpar filtros retorna ao geral. Clique no fundo ou
Visão geral mantém os filtros e a câmera.

O desenho usa layout determinístico e mostra até 70 nós/140 vínculos (36/65 em
mobile), com rótulos graduais e contagem explícita do que não foi desenhado. A
busca consulta todas as identidades, 20 por página; a tabela inclui todos os
registros do contexto, 30 por página. Segundo/terceiro graus são expansões
limitadas de relações documentadas. Cada nova pessoa começa em conexões diretas;
proximidade geométrica não cria relações. Campanhas são projetadas junto ao
titular comprovado, preservando o tipo e os endpoints legais em cada registro.

Aceite bloqueante com fixture inventada Charles → Izaura (sem simular dados
públicos): `python -m unittest tests.test_raiox_navigation -v`. Chromium real:
instalar `tests/raiox-browser-requirements.txt` e executar
`python -m unittest tests.test_raiox_navigation_browser -v`. O CI de Goiás exige
Playwright e axe-core; a ausência dessas dependências não pode aprovar esse job.
A avaliação jurídico-técnica em [pesquisa e privacidade](../../../../../docs/raiox-navigation-privacy.md)
mantém busca por CPF bloqueada; não foi criado índice, campo ou endpoint.

Causa, câmera, critérios de equivalência e medidas locais:
[navegação completa](../../../../../docs/raiox-complete-navigation.md).
