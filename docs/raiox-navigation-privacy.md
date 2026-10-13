# Pesquisa de pessoas e avaliação de consulta por CPF — Raio-X Goiás

Avaliação técnica inicial em 13/10/2026. **Consulta pública por CPF bloqueada.**
Este documento registra a decisão de produto e as pendências para o controlador;
não é parecer jurídico nem certificação de conformidade. Nenhum endpoint privado
ou índice de documentos foi criado nesta alteração.

## Avaliação antes de implementar consulta por documento

1. **Fonte exata.** O importador existente lê `NR_CPF_CNPJ_DOADOR` em
   `receitas_candidatos_2026_GO.csv`, no
   [ZIP oficial de prestação de contas de candidatos](https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2026.zip).
   A identidade de candidatura usa `NR_CPF_CANDIDATO` em
   `consulta_cand_2026_GO.csv`, do [conjunto de candidaturas do TSE](https://dadosabertos.tse.jus.br/dataset/candidatos-2026).
   Disponibilidade varia por arquivo/registro; CPF ausente ou mascarado não confirma
   pessoa. Esta tarefa não baixa, copia ou registra esses documentos. Usa apenas
   o JSON público já minimizado e IDs canônicos opacos.
2. **Disponibilização.** O [conjunto de contas de 2026](https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2026)
   identifica o SPCE como fonte, a ASEPA como gestora e disponibiliza CSVs de
   candidatos e CNPJs de campanha. Divulgação eleitoral não equivale a autorização
   específica para oferecer um localizador reverso de pessoas.
3. **Condições e termos.** O metadado indica “Creative Commons Atribuição”, sem
   especificar ali uma versão. Manter crédito, origem e limites dos registros.
   Consultadas as [perguntas frequentes](https://dadosabertos.tse.jus.br/pages/perguntasfrequentes)
   e a [política do TSE](https://www.tse.jus.br/transparencia-e-prestacao-de-contas/politica-de-privacidade-dos-sites-do-tribunal-superior-eleitoral),
   acessível pelo link de termos do conjunto. A política descreve serviços e
   tratamento pelo Tribunal, não autoriza o portal independente a indexar CPFs.
   Não foi identificada autorização específica para essa nova finalidade.
4. **Finalidade.** A funcionalidade pública entregue localiza nomes oficiais e
   permite examinar receitas eleitorais documentadas no escopo GO/2026. Uma
   consulta privada por CPF exigiria finalidade concreta distinta, público
   autorizado e justificativa para cada uso. “Transparência” genérica não basta.
5. **Hipótese legal.** Nenhuma base foi aprovada para a nova pesquisa reversa.
   O acesso público continua sujeito aos arts. 6 e 7, §§3–7, da
   [LGPD consolidada](https://planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm).
   Obrigação eleitoral do declarante/TSE não se transfere automaticamente ao
   portal. Consentimento deve provir do titular, não do visitante que consulta
   terceiros. Não presumir exceção jornalística ou condição de órgão de pesquisa.
6. **Necessidade e proporcionalidade.** Nomes, nomes de urna, aliases oficiais,
   candidatura e IDs opacos bastam para navegar. CPF completo pode ser necessário
   à resolução interna já existente, mas isso não demonstra necessidade de
   publicá-lo ou torná-lo pesquisável. Para eventual legítimo interesse em dados
   não sensíveis, realizar teste separado de finalidade, necessidade e
   balanceamento/salvaguardas, conforme o
   [guia da ANPD](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/guia_legitimo_interesse.pdf/@@display-file/file).
7. **Reidentificação e exposição.** CPF é dado pessoal; associações financeiras
   e partidárias podem produzir perfil político, dano reputacional e discriminação.
   Não inferir opinião política da doação. Se houver tratamento de dados sensíveis,
   avaliar o art. 11: legítimo interesse não ampara essa categoria. IDs opacos
   ligados a nomes são pseudônimos, não anonimização da base inteira.
8. **Enumeração.** Consulta livre pode confirmar existência, cruzar bases e
   coletar relações em massa. Hash simples de CPF é enumerável. Mascaramento parcial
   não elimina riscos nem serve como chave única. Não oferecer confirmação binária
   de um documento consultado sem controles e finalidade comprovados.
9. **Proteções atuais e projeto condicionado.** O frontend não possui campo,
   endpoint, índice, hash nem armazenamento de CPF. Entradas no formato de documento
   são recusadas nos campos de nome, origem, destino e caminho antes de serializar
   a URL; nenhum dado digitado é enviado à API ou analytics. A aplicação não usa
   terceiros para busca. O caminho de dados e o mecanismo de publicação existentes
   são preservados. URLs arbitrárias digitadas antes do carregamento já podem
   chegar ao servidor: higienização no cliente não apaga logs anteriores nem
   substitui proteção no servidor. Se uma consulta **privada** for juridicamente
   autorizada, usar backend autenticado, autorização por finalidade, proteção das
   chaves, rate limiting por conta e origem, resposta resistente à enumeração,
   auditoria sem documentos em claro e nenhum documento em URL.
10. **Retenção e descarte.** A nova busca não retém documentos. Para eventual
    tratamento privado, o controlador deve aprovar prazo por finalidade, acesso
    mínimo, expiração de caches e descarte verificável de temporários/backups,
    preservando evidências legitimamente necessárias. Prazos dos arquivos brutos
    existentes precisam de revisão própria; esta tarefa não apaga arquivos
    financeiros nem muda sua retenção. Art. 16 deve orientar a decisão, não um
    prazo arbitrário definido pelo frontend.
11. **Transparência e direitos.** Antes de abrir consulta privada, identificar
    controlador, encarregado quando aplicável, destinatários e canal efetivo para
    os direitos do art. 18, com aviso de privacidade (art. 9). O repositório não
    demonstra aprovação desse canal para a nova função; a Ouvidoria do TSE atende
    o Tribunal e não substitui o canal do portal. Termos de uso regulam o serviço;
    aviso explica tratamento; consentimento é manifestação do titular para
    finalidade específica. Aceitar um popup não reúne esses três requisitos.
12. **Revisão jurídica e RIPD.** Solicitar parecer especializado antes de qualquer
    implementação privada ou pública por CPF. Avaliar perfil político, escala,
    expectativas e impactos. A [orientação da ANPD sobre RIPD](https://www.gov.br/anpd/pt-br/canais_atendimento/agente-de-tratamento/relatorio-de-impacto-a-protecao-de-dados-pessoais-ripd)
    recomenda avaliação prévia em tratamento de alto risco e identifica a
    responsabilidade do controlador. Pode haver exigência da Autoridade; não há
    aprovação genérica pelo simples envio do relatório. Este documento inicial
    não substitui RIPD, decisão do controlador ou parecer.

## Decisão e condições para eventual revisão

**Entregar busca pública por nomes oficiais; não entregar busca por CPF.** O
controlador deverá revisar também o tratamento existente, inclusive condições
para divulgação dos nomes, sem presumir conformidade plena pela ausência de
CPF. Não criar relações entre homônimos, inferir opiniões ou irregularidades.

Qualquer revisão da decisão depende de autorização jurídico-técnica documentada,
fonte e finalidade delimitadas, hipótese legal fundamentada, teste de necessidade,
RIPD quando cabível, canal de direitos e controles de servidor demonstrados.
Controles técnicos isolados não resolvem as pendências jurídicas.
