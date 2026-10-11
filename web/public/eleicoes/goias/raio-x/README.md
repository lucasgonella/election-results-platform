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

A pipeline `https-staging-cd.yml` é isolada na app01 e **não publica automaticamente o conteúdo web da Locaweb**. O publicador autenticado atual trata apenas JSONs de apuração eleitoral sob `/data/`. Não usá-lo para enviar arquivos arbitrários da interface.

Para entrar em produção é necessário um mecanismo de deploy para arquivos estáticos da Locaweb ou uma única instalação manual supervisionada. Proteger com revisão e testes antes de ativar publicamente.

## CI/CD FTP porta 21

Workflow: `.github/workflows/deploy-goias-ftp.yml`. O novo fluxo publica somente
front-end/assets por FTP 21, com release versionada, backup e verificação SHA-256
por FTP e HTTPS. O JSON `data/go-2026.json` permanece exclusivamente com o
importador financeiro da main. Deploy visual não o substitui.

Operação e rollback: [CI/CD visual FTP](../../../../../docs/frontend-ftp-deployment.md).
Nenhum componente visual escreve `/data/` eleitoral nem habilita o coletor.

Configure em GitHub Actions Secrets: `LOCAWEB_FTP_HOST`, `LOCAWEB_FTP_USER`, `LOCAWEB_FTP_PASSWORD`; e Actions Variable: `LOCAWEB_FTP_GOIAS_DIR`, caminho relativo à raiz FTP (por exemplo `public_html/eleicoes/goias/raio-x` **somente se** a raiz FTP for a home da hospedagem; ou `eleicoes/goias/raio-x` se a raiz FTP já for `public_html`).

FTP tradicional transmite senha e arquivos sem criptografia. O workflow testa a URL pública depois de publicar e falha se o conteúdo não for encontrado. O workflow não configura secrets automaticamente: essa configuração depende do proprietário da conta.

Deploy FTP autorizado e configurado para primeira execução em outubro de 2026.
