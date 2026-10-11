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
