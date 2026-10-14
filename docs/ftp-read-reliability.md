# Retomada de leituras e uploads FTP

Incidentes de 14/10/2026: o segundo turno registrou timeouts/reset; o primeiro
turno manteve uma candidata PI não selecionada e exigiu reconciliação; o ETL
Goiás recebeu curl 56 depois de entregar um JSON completo. FTP/HTTPS confirmaram
os mesmos 6.620.789 bytes financeiros. Uma repetição do job antigo ainda tentou
push a partir de um commit superado. Não há prova de qual equipamento ou trecho
de rede causou os resets. Corrigir o tratamento dessas falhas não certifica a rede.

O segundo turno substitui a sessão e descarta bytes parciais antes de repetir
somente leituras, com três tentativas para MLST+RETR. O primeiro turno continua
exigindo recover oficial e writer parado, e agora reconcilia também a baseline
completa que permaneceu selecionada. Nenhum desses casos repete ativação incerta,
ignora lock, afrouxa revisão do Amazonas ou elimina o pacote interrompido.

O único escritor financeiro continua `goias-finance-data.yml`, com a mesma agenda,
concorrência, credenciais, destino e importador. Seu checkout fixa a main atual.
`tools.goias_finance_publish` usa curl nativo, FTP passivo 21 sem TLS, credenciais
em netrc temporário 0600 e erros sanitizados. Dados já idênticos por FTP/HTTPS
não são reenviados. STOR tem uma tentativa. Respostas transitórias incertas
só são consideradas concluídas após conferir integralmente os bytes esperados
por FTP **e** HTTPS. Não basta JSON válido ou quantidade de candidatos.

Leituras têm retentativas limitadas; uploads não são repetidos às cegas. O upload
financeiro existente substitui um único JSON no mesmo caminho e **não oferece
ativação transacional**: falha parcial continua sendo erro e exige nova execução
oficial com um dataset validado. Esse patch não declara atomicidade, isolamento
da conta ou durabilidade física. Portal, Raio-X visual e estudos não são enviados.

Testes usam FTP simulado, bytes sintéticos e callbacks: RETR parcial, resets,
421/permissões, orçamento de tentativas, preservação da candidata/checkpoint,
baseline/restauração, alterações externas, corrupções, upload incerto completo,
upload parcial, igualdade FTP/HTTPS, idempotência e proteção de credenciais.

## Instalação do código aprovado

O PR118 passou todos os checks; a suíte completa executou 500 testes e 27
subtestes, com 17 skips da infraestrutura local. A execução financeira
[38607350746](https://github.com/lucasgonella/election-results-platform/actions/runs/38607350746)
concluiu FTP/HTTPS com 860 candidaturas e 5.899 transferências, sem alterar o
importador. Seu commit automático contém exclusivamente o JSON financeiro.

O instalador do segundo turno continua exigindo o SHA aprovado da main atual.
Se o ETL avançar a main após os checks, não contornar essa recusa: concluir os
checks no SHA efetivo, por PR de documentação quando necessário, e só depois
executar o instalador oficial. Parar apenas os timers dos escritores envolvidos,
confirmar inatividade, preservar estado e executar recover/reconcile oficiais.
Reativar e confirmar ciclos reais; exit 0 de backoff não comprova nova coleta.

O primeiro turno preserva `TimeoutError`/`OSError`/`EOFError` ao esgotar leituras.
Isso permite ao transporte existente reconciliar um STOR já concluído por
releitura, sem repetir o upload. MLST e RETR compartilham um orçamento de três
tentativas, inclusive na limpeza de um temporário conhecido. O histórico local
`reconciliations/<candidate-id>.json` guarda o job e a conclusão antes que outra
coleta reutilize `in-flight.json`; candidata e arquivos continuam retidos.
Uma falha nova não herda o código de erro antigo do health.
