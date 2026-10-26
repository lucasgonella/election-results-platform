# Biometria nacional — Presidência, segundo turno de 2026

Painel: `/eleicoes/?turno=2#biometria`. Escopo fixo: ambiente oficial,
eleição 6258, pleito 3221, cargo 1. Inclui as 27 UFs e exterior (ZZ).
O inventário de seções principais é conferido com `s.ts` do resumo presidencial
nacional. Seções agregadas entram somente pelo BU da seção principal.

## Contagens e cobertura

Os três inteiros do campo de identificação no BU ASN.1/BER oficial são,
na ordem: identificação biográfica, biometria reconhecida, sem cadastro
biométrico. Identificação biográfica e ausência de cadastro são exibidas
também somadas como “sem uso da biometria”. Cadastro biométrico e utilização
efetiva da biometria são conceitos diferentes.

O coletor exige cabeçalho oficial, pleito, fase, município/zona/seção, eleição
presidencial e cargo corretos; comparecimento presidencial compatível com o
BU; soma dos votos presidencial igual ao comparecimento; soma das categorias
igual ao comparecimento. Sem os contadores, o comparecimento vai para
“não informado”. Em BUs de seção de apuração manual/SA, o comparecimento
global pode estar ausente/zero; utiliza-se o comparecimento presidencial,
com identificação não informada. Não se infere “documento em mão”.

São acumuladas somente as seções efetivamente validadas. Percentuais usam o
comparecimento dessas seções; não constituem estimativa nacional. O painel
exibe cobertura, contagens não informadas e último sucesso de coleta. A marca
de completo exige todas as seções e igualdade com o comparecimento nacional.
Os contadores são do BU, sem identificação pessoal ou associação ao candidato.

Fonte: `https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221/`.
Configurações `config/{uf}/{uf}-p003221-cs.json`; AUX da seção seleciona um
único BU totalizado. O hash do diretório TSE não é tratado como hash do BU.
O checkpoint privado conserva BU comprimido, URL, SHA-256 dos bytes e data
de captura. Esses hashes conferem integridade de transporte/armazenamento;
o coletor não afirma validar a assinatura digital da urna.

## Operação separada

Código `collector/src/biometry*.py`, sem PostgreSQL. SQLite WAL com chave única
UF/município/zona/seção; mudanças no inventário invalidam o BU anterior até
nova leitura. Fila intercala as 28 localidades; quatro workers e limite global
de quatro requisições por segundo. AUX e BU são duas requisições por seção:
a consolidação inicial pode levar dias. Retomada aproveita o checkpoint;
429 impõe pausa compartilhada e persistida. Reserva de disco 2 GiB, limite de
checkpoint 1 GiB, serviço com 384 MiB de memória e 20% de CPU.

Instalação somente de main revisada e com todos os checks aprovados:
`sudo deploy/scripts/install-biometry.sh CHECKOUT SHA40`.
Cria apenas usuário `electionbiometry`, release root-owned em
`/opt/election-biometry/releases/SHA`, venv próprio e state privado
`/var/lib/election-biometry`. Usa `LoadCredential` sobre a identidade SSH já
existente, host pinado e seleção explícita SSH; sem fallback de transporte.
Não modifica outros serviços, dados eleitorais, financeiro ou credenciais.

`systemctl status election-biometry.service` e
`journalctl -u election-biometry.service` mostram ciclos e falhas sanitizadas.
Para exportar/diagnosticar com o CLI `biometry_runner`, parar apenas esse
serviço antes; todas as operações CLI usam flock exclusivo no state.
O serviço tenta publicar no máximo a cada dez minutos, inclusive após falha
ou reinício, e a página consulta a versão a cada dois minutos quando visível.
Falhas de publicação são registradas separadamente e não impõem a pausa de
falha de coleta: o download dos BUs continua entre as tentativas. O horário da
última publicação só avança após confirmação; o journal pendente é preservado
para recuperação pelo mesmo publicador. Exportações/publicações supervisionadas
continuam mostrando a falha ao operador. Se não houver mudança, verifica a
release anterior sem reenviar. A taxa global do TSE permanece quatro requisições
por segundo; não multiplicar coletores sobre o mesmo checkpoint.

Namespace exclusivo: `/public_html/biometria-2026/presidente/turno-2`.
Release imutável `releases/SHA256/panel.json`, vinculada por hash/tamanho e
escopo ao `version.json`. Leitor e publicador exigem os mesmos totais por
município, UF e Brasil. A publicação verifica bytes por SSH e HTTPS antes e
depois da ativação. Estado privado remoto `/election-biometry-deploy/2`.
MKD/owner remoto e journal local precedem as mutações; backups de marcadores
anteriores são conservados. Não há garantia de transação distribuída/NFS.

Falha conserva o journal. O mesmo coletor tenta recuperar a transação conhecida
antes de publicar outra versão, verificando baseline, owner e arquivos. Locks,
temporários ou mudanças externas desconhecidos interrompem; não remover por
timeout. Após commit confirmado, a limpeza do lock é retomável mesmo se a
resposta de delete/rmdir for perdida. Para reverter, parar apenas este serviço,
investigar o journal, validar a release anterior e publicar seu agregado pelo
mesmo Publisher; nunca trocar o marcador manualmente ou apagar releases.

O HTML/CSS/JS segue o deploy visual existente PR → CI → main → Actions →
verificação HTTPS. Dados não entram no artefato visual. Testes são sintéticos
e locais: `tests/test_biometry.py`, `tests/test_biometry_browser.py`. O job de
navegação municipal existente também carrega a suíte de biometria via
`load_tests`, com Chromium e axe em claro/escuro, filtros, CSV, falhas e
isolamento de turno. Nenhum novo workflow ou segredo é necessário.
