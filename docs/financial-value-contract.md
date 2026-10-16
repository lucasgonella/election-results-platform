# Valores financeiros do Raio-X Goiás

`revenue`, `expenses` e `transfers[].amount` continuam sendo números não negativos
finitos ou `null`. A extensão `financial_schema: 1` acrescenta cobertura por
candidatura, sem alterar o contrato de identidade e sem reclassificar o JSON
financeiro histórico. Nenhum dado financeiro versionado foi regenerado nesta
correção.

## Evidência e limites da origem

Fontes primárias consultadas em 16/10/2026:

- [Contas eleitorais 2026 no TSE](https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2026):
  identifica o SPCE como origem, a extração por arquivo e o recurso de contas de
  candidaturas. Isso não estabelece que uma candidatura ausente tenha valor zero.
- [Instruções do grupo de contas eleitorais](https://dadosabertos.tse.jus.br/group/about/prestacao-de-contas-eleitorais):
  orienta consultar o `leia-me.pdf` da respectiva eleição, pois o layout varia.

O ZIP público anteriormente documentado em `/tmp/tse-go/finance.zip` não estava
disponível neste ambiente. Não se baixaram arquivos, consultaram documentos
pessoais ou executaram coletores. A regra de declaração vazia foi preservada a
partir do importador, dos testes e da auditoria documentada em
[identidade no Raio-X](goias-person-identity.md); não se confirmou novamente a
extração bruta. Não há evidência para transformar todos os zeros históricos em
ausência, nem para interpretar ausência de linha como arrecadação/despesa zero.

## Regras do exportador

| Evidência no CSV do recorte | Valor exportado | Cobertura |
| --- | --- | --- |
| Registro com valor positivo ou zero explícito | Soma dos valores conhecidos | `known` se não há linhas com valor ausente |
| Receita com `VR_RECEITA=0` sem SQ, doador, data ou origem | `0`, se não existem outras receitas conhecidas | Declaração zero com arquivo/linha; não gera transferência |
| Receita com SQ oficial e valor ausente | `amount: null` na transferência | Preserva sequência, origem, data, categoria e fonte |
| Linhas com e sem valor na mesma candidatura | Escalar `null`; soma conhecida em `known_subtotal` | `partial` |
| Nenhuma linha ou somente valores ausentes | `null` | `missing` |

Os sentinelas já reconhecidos (`#NULO`, `#NE`, vazio e `-1`) são ausências. Números
inválidos, negativos não sentinela e não finitos interrompem a exportação.
Cabeçalhos monetários dos dois tipos de arquivo são validados independentemente
da existência de valores, evitando confundir coluna desconhecida com ausência.
Arquivos/categorias e critério de deduplicação existentes são preservados. O
fallback legado de `VR_DESPESA_PAGA` no arquivo contratado permanece compatível;
esta correção não reconcilia etapas contábeis.

Zero significa valor explícito encontrado nesta extração. Uma declaração sem
receita não prova ausência de movimentação futura, de outras contas ou de dados
ainda não disponíveis. Receita zero com SQ continua sendo um registro real.
Linha sem SQ e sem valor apenas sinaliza cobertura incompleta; não cria aresta.

Cada candidatura recebe `financial_coverage.revenue` e
`financial_coverage.expenses`, contendo:

```json
{
  "status": "partial",
  "known_records": 1,
  "missing_records": 1,
  "known_subtotal": 125.5,
  "zero_declarations": []
}
```

`known_records` e `missing_records` contam os registros após a deduplicação
existente; declarações sem sequência são contadas como linhas de cobertura.
`zero_declarations` guarda somente `source_file` e `source_row` das declarações
de receita zero, nunca documentos pessoais. A URL oficial e os SHA-256 dos ZIPs
continuam em `source`. Ausência de linha tem os dois contadores zerados e status
`missing`. Uma declaração zero somada a uma linha sem valor produz subtotal zero
`partial`, com escalar `null`, sem afirmar um total zero completo.

`known_subtotal` é a soma conhecida para `known` e `partial`, ou `null` para
`missing`. Em `known`, é igual ao escalar. Em `partial`, o escalar permanece
`null`: leitores anteriores, que ignoram os novos metadados, apresentam “Não
informado” em vez de rotular subtotal como total. O leitor novo recupera a soma
conhecida com o rótulo explícito. Isso evita introduzir um subtotal no escalar
da candidatura consumido pelo leitor anterior. Valores positivos/zero completos
e nulos mantêm seus tipos anteriores.

Há um limite adicional de compatibilidade: o leitor anterior já somava várias
candidaturas de uma pessoa sem conservar a ausência de outra candidatura. Pode,
portanto, apresentar o agregado misto conhecido/ausente como total. O leitor novo
corrige isso com `financial_summary`. Não se distorcem os escalares conhecidos
para contornar esse problema anterior. Publicar primeiro o leitor visual
compatível reduz esse risco antes de uma futura importação; um merge que dispare
simultaneamente as duas automações não garante essa ordem. O PR deve registrar
esse limite e o disparo automático do ETL.

`financial_audit` resume candidaturas `known`, `partial`, `missing`, zeros completos
e a soma conhecida (`subtotal`, `null` quando nenhum valor é conhecido).
Os campos legados `identity_audit.revenue_total` e `expense_total` continuam como
strings decimais, mas representam somente a soma conhecida se houver ausências.
Devem ser lidos junto da cobertura; não demonstram completude.

## Leitores, auditoria e publicação

O leitor e `financial_summary` na auditoria verificam coerência entre escalares,
status, contadores e evidências. Metadados são obrigatórios para a versão 1;
bases sem essa versão permanecem válidas. Zeros legados são preservados e o painel
informa que a versão não contém evidência de cobertura por candidatura.

`sumKnown` conserva `total: null` quando não há valor conhecido. `known` conta
itens com número ou subtotal conhecido, `missing` conta itens ausentes **ou parciais** e `count` conta
itens examinados: um subtotal participa de `known` e `missing`. Projeções por
pessoa guardam `financial_summary` separado; os metadados e evidências originais
permanecem em `candidacies`. Métricas, cartões, detalhes, grupos, tooltips e nós
mantêm o sinal de subtotal. Um autorepasse entra uma vez no volume do próprio
nó. Filtros monetários excluem valores `null`, inclusive no intervalo zero;
ordenação usa sentinela apenas para posicioná-los depois dos valores conhecidos.

O publicador permanece sem alterações. Testes sintéticos verificam que ele
aceita números/null e metadados aditivos em um dataset já publicável, preservando
bytes FTP/HTTPS. Seu gate existente ainda recusa dataset inteiramente sem
transferências. O ETL e o leitor aceitam esse caso sem fabricar atividade;
publicar uma base vazia exige decisão operacional separada.

**Atenção à integração:** o workflow existente `goias-finance-data.yml` observa
alterações em `tools/goias_finance_etl.py`. Fazer merge desta correção pode
disparar coleta e publicação financeira automáticas. Esta tarefa não executou
esse fluxo, não mudou workflows/horários e não autoriza merge ou publicação.
O deploy visual continua independente e exclui JSON financeiro.

Validação exclusivamente sintética: `tests/test_goias_finance_etl.py`,
`tests/test_goias_financial_contract.py`, `tests/test_goias_identity.py`,
`tests/test_premium_finance_graph.py`, `tests/test_goias_finance_publish.py` e
o cenário financeiro de `tests/test_raiox_navigation_browser.py`.
