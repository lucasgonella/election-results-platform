# Identidade comprovada no Raio-X Goiás

A identidade pessoal é resolvida no importador, antes de gerar o JSON público.
O leitor aceita tanto a base anterior quanto `identity_schema: 1`. Publicar o
leitor compatível antes da alteração do ETL evita que a base nova chegue a um
frontend que ainda desconhece pessoas e campanhas.

## Evidência, finalidade e minimização

Fontes oficiais consultadas em 13/10/2026:

- [Candidatos 2026](https://dadosabertos.tse.jus.br/dataset/candidatos-2026),
  recurso `consulta_cand_2026.zip`, publicado com licença de atribuição.
- [Contas eleitorais 2026](https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2026),
  recurso `prestacao_de_contas_eleitorais_candidatos_2026.zip`.

A autorização desta tarefa limita o processamento à resolução dos doadores das
contas de candidaturas federais/estaduais de Goiás. Os arquivos oficiais contêm
CPF completo em `NR_CPF_CANDIDATO` nas candidaturas e em parte de
`NR_CPF_CNPJ_DOADOR` nas receitas. O campo de CPF do candidato nas receitas está
indisponível na extração examinada; não é utilizado como se fosse um documento.
Não se acessam fontes restritas, contas autenticadas ou serviços eleitorais.

CPFs válidos e completos são comparados somente em memória no backend. Máscaras,
ausências, documentos inválidos e nomes semelhantes não confirmam identidade.
Conflitos de CPF por candidatura, titularidade de CNPJ ou sequência de doador
impedem o vínculo correspondente e são contabilizados. Nomes servem à pesquisa e
às variantes de exibição, jamais à comprovação.

Os IDs públicos são UUIDs com namespace, calculados de âncoras **não pessoais**:
sequências oficiais de candidatura, CNPJ público de campanha e registro financeiro.
Não são hashes de CPF, não exigem uma chave pública ou privada para pseudonimizar
um domínio enumerável de documentos e não permitem calcular CPF a partir do ID.
O agrupamento por documento permanece somente na memória do importador. Não se
persiste uma tabela de CPF, nem se acrescentam segredos, analytics ou parâmetros
de URL pessoais. Os arquivos brutos oficiais permanecem fora do frontend.

A exportação usa uma lista explícita de campos públicos e recusa campos de
CPF/documento ou tokens de CPF completo conhecidos em qualquer string, inclusive
URLs. Erros dessa proteção não incluem o valor encontrado. Evidências públicas
mostram método, campos consultados, IDs oficiais não pessoais, arquivo, linha e
checksums dos ZIPs completos; nenhum desses checksums é calculado sobre um CPF.
CNPJ de campanha é público e identifica exclusivamente a campanha correspondente.

## Pessoas, campanhas e registros

`candidates` preserva cada candidatura e seus totais existentes, acrescentando
`person_id`, `civil_name`, `ballot_name`, `uf`, fonte e campanhas. `entities`
contém pessoas, campanhas, organizações identificadas por CNPJ e identidades
inconclusivas. Uma pessoa pode ter várias candidaturas e papéis. A campanha possui
`owner_person_id`, candidatura, CNPJ e evidência de titularidade.

Uma receita com CPF idêntico à candidatura parte da pessoa e confirma o papel
`donor`. Receita com CNPJ de campanha parte da **campanha**, cuja titularidade é
comprovada por `SQ_CANDIDATO` / `NR_CNPJ_PRESTADOR_CONTA`; a sequência oficial do
doador corrobora o vínculo quando informada. Isso confirma `campaign_financier`,
sem declarar uma doação pessoal por CPF. CNPJ conflitante permanece separado.

O grafo projeta a campanha junto à pessoa titular para reunir o contexto, sem
transformar sua natureza jurídica: cada registro mantém `original_from_id`,
`from_campaign_id`, `from_role`, destino, campanha beneficiária, valor, data,
categoria, `source_record_id`, arquivo, linha e fonte oficial. Detalhes e filtros
separam recebidos, realizados, doações pessoais e repasses da campanha. Cores,
anéis e rótulos distinguem os papéis. O quadro explica a projeção explicitamente.

A origem é a contraparte **direta** da receita. Eventual doador originário não é
substituído pelo remetente direto. Não se misturam arquivos BRASIL/UF, receitas,
despesas pagas ou contratadas, nem se inferem fluxos a partir dos nomes.
A resolução não acrescenta arestas de transferência para expressar identidade.

O critério de contabilização já existente é preservado: tipo de arquivo,
candidatura, SQ de registro e valor. Vários itens podem compartilhar SQ com
valores distintos, por exemplo receitas estimáveis; eles permanecem registros
separados com linha original. O contador de descarte informa o critério existente,
sem alegar que todo descarte corresponde a uma linha byte a byte idêntica.
As somas de relações são somas dos registros contábeis publicados daquele tipo,
não cálculo de circulação de um mesmo recurso entre etapas. Não se somam
caminhos, receitas e despesas para criar um novo total.

## Exemplo investigado: Luana

A candidatura `90002543241` tem nome de urna **LUANA RAIADO**, nome civil
**LUANA DO PRADO ROCHA MELO**, PP, deputado federal. Na extração examinada, os
cinco registros de saída `48100291`, `48093319`, `48093320`, `48064262` e
`48119231` usam CNPJ e informam `SQ_CANDIDATO_DOADOR=90002543241`; o documento
coincide com o CNPJ do prestador de contas dessa candidatura.

Os cinco repasses somam R$ 570.000,00 para quatro candidaturas. O vínculo de
campanha está comprovado. **Não foi encontrada uma doação pessoal por CPF para
confirmar que esses cinco registros constituem doações da pessoa física.** O
cartão mostra “Candidata/o · Campanha financiadora”, nome civil e evidências,
sem atribuir a Luana o papel de doadora pessoal com base nesses repasses.

## Auditoria da extração de 13/10/2026

A auditoria é recalculada em cada exportação e publicada em `identity_audit`.
Nesta extração: 860 candidaturas; 5.899 receitas examinadas; 3.055 entidades de
origem; 245 pessoas/candidaturas também doadoras por CPF; 42 titulares com
campanhas financiadoras; 245 nós de pessoa duplicados eliminados; 42 nós de
campanha projetáveis; 2.768 entidades de doadores sem correspondência confirmada
com candidaturas deste escopo; zero conflitos de identidade.

“Inconclusivo” não significa suspeita: inclui pessoas e organizações que não
correspondem a uma candidatura deste recorte. Os 108 registros sem documento
ficam separados, cada um com âncora de transação; não são unidos por máscara.

Todas as 5.791 relações da versão anterior foram preservadas, com os mesmos
valores, datas, categorias e destinatários. As 108 receitas sem documento já
integravam os totais anteriores, mas eram omitidas da rede; agora são exibidas
explicitamente como identidades não confirmadas. Receitas por candidatura e
soma geral R$ 180.033.060,32, despesas por candidatura e soma geral
R$ 113.099.375,03 permaneceram iguais. O resolvedor não recontabiliza etapas.

## Testes e publicação

`tests/test_goias_identity.py` usa exclusivamente fixtures sintéticas para CPF
igual/diferente/mascarado/ausente/inválido, nomes distintos, múltiplas candidaturas,
CNPJ e conflitos, doações múltiplas, duplicatas, totais, idempotência, doador
originário e proteção de CPF em JSON/URLs. O leitor tem testes de projeção,
papéis, identidade inexistente, filtros, valores e URL, além dos testes legados.

O fluxo visual continua sendo PR → CI → main → `deploy-goias-ftp.yml` → verificação
HTTPS. Só `goias-finance-data.yml` gera e envia `data/go-2026.json`; foram ampliados
apenas os caminhos de detecção e a seleção dos testes do importador. Horários,
transporte, credenciais e destinos permanecem os existentes. A publicação visual
exclui JSON. Nenhum serviço de coleta, primeiro/segundo turno, banco ou outro
projeto é alterado. Locks e journals exigem a recuperação oficial quando pendentes.
