# Observador e histórico de parciais do segundo turno

`election-round2.service` mantém um processo contínuo. Ele consulta, com ETag,
os índices oficiais nacionais das eleições descobertas na prova da publicação
ativa e a configuração oficial, a cada dois segundos quando está ocioso. O TSE
distribui arquivos HTTP; isso é observação condicional, não uma assinatura push
oferecida pelo TSE. Mudança no conteúdo aciona o mesmo `cycle` e publicador.

Há um único escritor, com o mesmo flock, recovery, journals e validações completas.
Sinais recebidos durante uma publicação são verificados novamente ao seu término,
capturando a versão mais recente. Não há fila de publicações concorrentes. O
intervalo de 30 segundos fica como reconciliação periódica, sem esperar esse
prazo quando um índice muda. Falhas e Retry-After continuam sendo respeitados.
SIGTERM aguarda o ciclo em andamento terminar; TimeoutStopSec mantém 20 minutos.

O instalador existente habilita o serviço contínuo e desabilita somente o antigo
timer desse turno. Os drop-ins existentes conservam transporte, identidades e
credenciais. Antes de instalar, parar o timer dedicado e aguardar a execução
atual; em futuras atualizações, parar o observador e aguardar sua saída graciosa.
O primeiro turno permanece separado.

O monitor existente, a cada 30 segundos, constrói `vote-history.json` privado a
partir de receipts completos, pacotes locais e prova oficial verificada. O
histórico público é um campo permitido de `status.json`, publicado pelo mesmo
fluxo auxiliar de journal, transferência, readback e HTTPS já existente. Não há
novo writer de releases eleitorais. Falha no histórico não interrompe a coleta.

O gráfico mostra votos observados de cada candidatura, sem projeções, juízos ou
declaração de resultado. O eixo horizontal usa o horário de publicação no portal,
em Brasília; a geração oficial também fica registrada. Não se inventam pontos
anteriores. Apenas pacotes já publicados entram no histórico; dados de staging,
pré-coleta ou transações pendentes são excluídos. Há limites de 4096 observações
e 2 MiB, além do cache durável privado e dos registros originais conservados.

O frontend consulta o documento compartilhado a cada 30 segundos e após mudança
de contexto, com cache/deduplicação/backoff existentes. O primeiro turno oculta
o gráfico. As séries nacionais são explicitamente identificadas como Brasil,
Presidência e segundo turno, inclusive ao explorar filtros estaduais.

Referência oficial: https://www.tse.jus.br/eleicoes/informacoes-tecnicas-sobre-a-divulgacao-de-resultados
