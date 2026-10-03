# Election Results Platform

![CI](https://github.com/lucasgonella/election-results-platform/actions/workflows/ci.yml/badge.svg)

Plataforma para coleta, persistência e publicação de resultados eleitorais a partir dos arquivos disponibilizados pelo Tribunal Superior Eleitoral (TSE).

**Demo:** https://gonella.com.br/eleicoes/

> Projeto independente. Não é um serviço oficial do TSE. A interface apenas apresenta os dados publicados pela Justiça Eleitoral e não realiza projeções, estimativas ou declarações próprias de resultado.

## Visão geral

O projeto foi construído como uma pipeline completa de dados eleitorais:

```text
TSE
 |
 v
Python Collector
 |
 v
PostgreSQL
 |
 v
Static JSON Builder
 |
 v
Atomic SSH Publisher
 |
 v
Locaweb /data/*.json
 |
 v
HTML + CSS + JavaScript
```

O collector identifica alterações nos arquivos de acompanhamento do TSE, processa os resultados em lotes, persiste snapshots no PostgreSQL e, quando o conjunto está consistente, gera um bundle estático de JSON e o publica no servidor web.

A documentação técnica oficial do TSE para divulgação dos resultados de 2026 está disponível em:

https://www.tse.jus.br/eleicoes/informacoes-tecnicas-sobre-a-divulgacao-de-resultados

## Funcionalidades

- coleta de arquivos de resultados do TSE;
- descoberta dinâmica das eleições suportadas;
- detecção de mudanças antes de processar novos resultados;
- ingestão stateful em batches;
- persistência histórica de snapshots no PostgreSQL;
- observabilidade do estado dos batches;
- geração de JSONs estáticos para o frontend;
- publicação remota com staging, validação e troca atômica;
- atualização automática do frontend;
- busca de candidatos por nome, número ou partido;
- favoritos persistidos no navegador com `localStorage`, atualização automática a cada 10 segundos e indicador de sincronização com o bundle publicado;
- suporte a deep links por localidade e cargo;
- CI com GitHub Actions e pytest.

## Escopo atual

O bundle publicado atualmente cobre 85 combinações de localidade e cargo:

- Presidente: Brasil, 27 UFs e Exterior;
- Governador: 27 UFs;
- Senador: 27 UFs;
- Deputado Federal: Goiás;
- Deputado Estadual: Goiás.

Códigos de cargo utilizados pela aplicação:

| Código | Cargo |
| ---: | --- |
| 1 | Presidente |
| 3 | Governador |
| 5 | Senador |
| 6 | Deputado Federal |
| 7 | Deputado Estadual |

## Arquitetura

### Collector

O collector em Python é responsável por:

1. carregar a configuração da eleição;
2. descobrir os targets suportados;
3. consultar o estado de acompanhamento;
4. detectar mudanças;
5. criar e retomar batches persistentes;
6. buscar e interpretar os resultados;
7. persistir snapshots e candidatos;
8. atualizar checkpoints somente após o processamento consistente.

Principais módulos:

```text
collector/src/
├── collector_runner.py
├── runtime.py
├── discovery.py
├── stateful_planner.py
├── change_detection.py
├── batch_ingest.py
├── ingest.py
├── parser.py
├── repository.py
├── observability.py
├── static_exporter.py
├── static_site_builder.py
└── tse_client.py
```

### Banco de dados

O projeto utiliza PostgreSQL e mantém as migrations em:

```text
database/migrations/
```

A persistência inclui eleições, localidades, cargos, candidatos, snapshots de apuração, estado dos arquivos de acompanhamento e batches de ingestão.

### Publicação estática

Depois que a coleta termina sem pendências ou erros, a pipeline pode gerar os arquivos consumidos pelo frontend:

```text
data/
├── manifest.json
├── br/
│   └── president.json
├── go/
│   ├── president.json
│   ├── governor.json
│   ├── senator.json
│   ├── federal-deputy.json
│   └── state-deputy.json
└── ...
```

O publisher envia o bundle para uma área temporária no servidor remoto, valida a quantidade de arquivos e só então ativa a nova versão.

### Frontend

O frontend é estático e fica em:

```text
web/public/eleicoes/
```

Ele utiliza HTML, CSS e JavaScript sem framework e consome apenas os JSONs publicados em `/data/`.

Os favoritos são armazenados localmente no navegador. Nenhuma preferência de candidato é enviada ao backend.

## Stack

- Python
- PostgreSQL
- psycopg
- Requests
- pytest
- Docker Compose para PostgreSQL local
- systemd service + timer
- Bash
- SSH
- HTML
- CSS
- JavaScript
- GitHub Actions

## Desenvolvimento local

### Requisitos

- Python 3.13+
- Docker / Docker Compose
- Git

Clone o repositório:

```bash
git clone https://github.com/lucasgonella/election-results-platform.git
cd election-results-platform
```

Crie o ambiente virtual:

```bash
python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Instale as dependências:

```bash
pip install -r collector/requirements-dev.txt
```

Suba o PostgreSQL local:

```bash
docker compose up -d
```

As variáveis básicas para desenvolvimento estão documentadas em:

```text
.env.example
deploy/env/collector.env.example
```

## Testes

Execute:

```bash
python -m pytest -q
```

O pipeline de CI também compila os módulos Python e executa os testes a cada pull request e push para a `main`.

## Execução como serviço

Os arquivos de systemd ficam em:

```text
deploy/systemd/
├── election-collector.service
└── election-collector.timer
```

Os scripts operacionais ficam em:

```text
deploy/scripts/
├── run-collector.sh
└── publish-results.sh
```

A configuração de produção deve ser fornecida externamente por arquivo de ambiente. Credenciais de banco, chaves SSH e outros segredos não devem ser versionados.

## Segurança operacional

O projeto possui uma trava explícita para impedir o uso acidental do ambiente oficial:

```text
COLLECTOR_ALLOW_OFFICIAL=false
```

Para uma execução oficial, a alteração desse valor deve ser intencional e acompanhada da configuração correta do ambiente.

O publisher também valida o bundle local e remoto antes de ativar uma nova versão.

## Fonte dos dados

Os resultados exibidos pela aplicação são obtidos dos arquivos disponibilizados pelo Tribunal Superior Eleitoral.

- TSE: https://www.tse.jus.br/
- Informações técnicas de divulgação: https://www.tse.jus.br/eleicoes/informacoes-tecnicas-sobre-a-divulgacao-de-resultados
- Ambiente de resultados: https://resultados.tse.jus.br/

## Autor

Desenvolvido por **Lucas Gonella**.

- GitHub: https://github.com/lucasgonella
- Repositório: https://github.com/lucasgonella/election-results-platform
- Aplicação: https://gonella.com.br/eleicoes/