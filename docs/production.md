# Do notebook à produção: o que mudaria e o que não mudaria

Este projeto roda em um notebook, com SQLite e um modelo local. Isso foi uma **decisão**, não
uma limitação: a demonstração precisa ser reproduzível por qualquer pessoa sem conta em nuvem.
Mas a arquitetura foi desenhada para que o caminho até produção seja **trocar peças nas bordas**,
não reescrever o núcleo. Este documento explica esse caminho, o que ele custaria e onde estão
os riscos reais.

## O que não precisa mudar

As partes que carregam a lógica de negócio e as garantias de segurança já estão desacopladas
do ambiente:

| Componente | Por que já está pronto |
|---|---|
| `agents/` (grafo, planner, validação) | Não sabe onde roda. Recebe `Settings`, `User`, `Retriever` e `LLMProvider` por injeção. |
| `tools/contracts.py` | Contratos Pydantic são os mesmos em qualquer ambiente. |
| `approval.py` | Regras de hash, papel, prazo e idempotência são lógica pura sobre uma conexão; a conexão é parâmetro. |
| `providers/` | Interface `LLMProvider` com três implementações. Adicionar um endpoint corporativo (Azure OpenAI, Bedrock, vLLM) é uma classe nova, sem tocar no agente. |
| `auth.py` | O backend já recebe um objeto `User` com papel. Quem cria esse objeto é a única coisa que muda. |
| `evals/` | Os 33 casos e o runner rodam contra qualquer banco e qualquer provedor. Viram o teste de regressão do pipeline de deploy. |

## O que mudaria, em ordem de prioridade

### 1. Autenticação e identidade (bloqueante)

**Hoje:** menu de seleção de usuário; header `X-Demo-User` na API.
**Em produção:** OIDC/OAuth2 com o IdP da empresa (Entra ID, Okta, Keycloak). A dependência
`current_user()` em `api/app.py` passa a validar o JWT e montar o `User` a partir das claims
(`sub`, grupos → papel). A UI deixa de ter seletor e passa a usar o login do IdP.
**Esforço:** pequeno. É uma função. O resto do sistema já trata `User` como fonte de verdade.

### 2. Banco de dados

**Hoje:** SQLite local, um arquivo, lock por processo.
**Em produção:** PostgreSQL gerenciado (RDS, Cloud SQL, Azure Database).

- `data/db.py` troca `sqlite3` por um driver com pool (`psycopg` ou SQLAlchemy Core).
- As consultas em `tools/_ops_sql.py` são SQL padrão; `substr(created_at,1,7)` vira
  `to_char(created_at,'YYYY-MM')` ou, melhor, uma coluna `month` indexada.
- `action_proposals` e `tasks` ganham `SELECT … FOR UPDATE` no `execute()` para que dois
  gestores clicando ao mesmo tempo não corram. A chave `UNIQUE(idempotency_key)` já existe e
  continua sendo a última linha de defesa.
- Os dados operacionais reais provavelmente já vivem em um warehouse. Nesse caso
  `query_operations` aponta para **views materializadas** atualizadas por job, não para as
  tabelas transacionais — latência previsível e isolamento de carga.

### 3. Índice de documentos

**Hoje:** FTS5 em memória + FAISS em arquivo, reconstruídos a cada start (~segundos).
**Em produção:**

- Para dezenas de milhares de chunks, `pgvector` no mesmo Postgres resolve lexical (tsvector)
  e vetorial com **pré-filtro nativo** por `access_level` no `WHERE` — elimina o contorno de
  "pool × 4" que o retriever faz hoje por falta de pré-filtro no FAISS.
- Para milhões, OpenSearch/Elasticsearch com filtro de permissão na query, ou Qdrant/Weaviate
  com payload filtering.
- Ingestão vira um job (Airflow, Dagster, cron): detecta mudanças por hash (já implementado),
  reindexa só o delta, grava `index_version` — o rastreio já registra essa versão por execução.

### 4. LLM

**Hoje:** Ollama local, ~15 s por resposta na GPU do notebook.
**Em produção, duas rotas:**

| Rota | Quando | O que muda |
|---|---|---|
| **API gerenciada** (Azure OpenAI, Bedrock, Vertex) | Volume moderado, sem restrição de dados saindo | Nova classe em `providers/`, segredo no cofre, limite de taxa e orçamento por mês. Latência cai para 2–5 s. |
| **Inferência própria** (vLLM/TGI em GPU, modelo 8–70B) | Dados sensíveis, volume alto, custo previsível | Mesma interface. Exige GPU dedicada, autoscaling e observabilidade do servidor de inferência. |

Em qualquer rota: o agente já faz **duas** chamadas por pergunta com proposta. Em produção, a
proposta deveria ser gerada só sob demanda (botão "propor ação"), cortando custo pela metade
nas perguntas exploratórias.


### 5. Serviço e escala

**Hoje:** `uvicorn` em um processo; Streamlit chama o núcleo direto.
**Em produção:**

```
[IdP] ──► [API Gateway / WAF] ──► [FastAPI × N réplicas] ──► Postgres (+pgvector)
                                        │                       │
                                   [fila de jobs]          [LLM endpoint]
                                        │
                                  [worker × M]  ← execução do agente
```

- **API e UI separadas.** A UI (Streamlit ou um front React) fala só com a API; o núcleo
  roda nos workers.
- **Execução assíncrona.** Uma pergunta com LLM leva segundos. `POST /ask` enfileira e devolve
  `run_id`; a UI faz polling em `GET /runs/{id}` ou recebe por WebSocket. O `Tracer` já gera o
  `run_id` e grava estado por etapa — é o que a UI consome.
- **Stateless.** Nenhum estado de sessão no processo; tudo em banco ou cache. Permite
  escalar horizontalmente em Kubernetes, ECS ou Cloud Run.
- **Dimensionamento inicial:** 2 réplicas de API, 2–4 workers, autoscale por profundidade da
  fila. Com LLM gerenciado, o gargalo é a cota do provedor, não o serviço.

### 6. Observabilidade

**Hoje:** JSONL local com `run_id`, etapas, tokens, erros, redaction.
**Em produção:** os mesmos registros vão para OpenTelemetry → Grafana/Datadog/Honeycomb.
Alertas em: taxa de `failed`, p95 de latência, citações removidas por execução (sinal de
degradação do modelo), tentativas de aprovação negadas (sinal de abuso). O `audit_log` vai
para armazenamento imutável (WORM) por exigência de auditoria.

### 7. Segurança adicional

- Segredos em cofre (Vault, Key Vault, Secrets Manager), nunca em `.env`.
- Rate limit por usuário na API.
- Lista de ferramentas continua fechada; adicionar uma ferramenta exige PR + revisão.
- A quarentena por padrão de injeção é complementada por um classificador dedicado
  (ex.: Llama Guard ou Prompt Guard) na entrada e nos chunks — o ponto de encaixe já existe
  em `planner.detect_injection`.
- Revisão de LGPD: dados reais de clientes exigem base legal, minimização (o agente só
  recebe agregados, nunca linhas individuais — já é assim) e política de retenção dos logs.

### 8. CI/CD — o que já existe e o que falta

**Já implementado neste repositório:**

- [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) roda a cada push e PR, em
  Python 3.11 e 3.12: `ruff` → `pylint --fail-under=10` → `pytest` → `copiloto eval` em modo
  determinístico → **gate** (`scripts/ci_gate.py`): o build falha se qualquer um dos 33 casos
  regredir ou se houver uma violação de autorização ou execução sem aprovação. O relatório
  JSON é publicado como artefato.
- Em seguida, a imagem Docker é construída (sem push) para garantir que o `Dockerfile` não
  quebrou.
- [`Dockerfile`](../Dockerfile): imagem única, usuário sem privilégios, banco sintético gerado
  na build, healthcheck em `/health`. [`docker-compose.yml`](../docker-compose.yml) sobe API +
  UI com um comando e Ollama como perfil opcional.

**O que faltaria para CD de verdade:**

- Push da imagem para um registry (GHCR, ECR, ACR) com tag = SHA do commit, em `main`.
- Deploy por ambiente (dev → staging → prod) disparado por tag ou aprovação manual no
  workflow (`environment:` com *required reviewers* no GitHub).
- Migrações de banco versionadas (Alembic) rodando antes do deploy.
- Avaliação **com LLM** em workflow noturno (`schedule:`), não no PR — custo e tempo. O
  relatório vai para um bucket e um job compara com o anterior; queda em "citações
  inventadas" ou "eco malicioso" abre issue automaticamente.
- Canary: nova versão de prompt ou modelo recebe 10% do tráfego com comparação de métricas
  antes de 100%. `PROMPT_VERSION` e `index_version` já ficam no rastreio de cada execução,
  então a comparação é um `GROUP BY`.

### 9. Nuvem — onde rodar

A aplicação é um container stateless + Postgres + endpoint de LLM. Isso cabe em qualquer
nuvem; a escolha é de operação, não de arquitetura.

| Opção | Quando escolher | O que o projeto já tem para isso |
|---|---|---|
| **Serverless de containers** — Cloud Run, Azure Container Apps, AWS App Runner | Começar rápido, volume variável, time pequeno. Escala a zero fora do horário. | `Dockerfile` pronto; healthcheck; config 100% por variável de ambiente. |
| **ECS Fargate / Azure Container Instances** | Já há padrão corporativo em AWS/Azure; precisa de VPC privada e IAM fino. | Idem; adicionar task definition / bicep. |
| **Kubernetes** (EKS, AKS, GKE) | Já existe cluster e plataforma interna; precisa de GPU para inferência própria (vLLM). | Imagem + compose servem de base para Helm chart; workers e API são deployments separados. |

Peças gerenciadas ao redor, em qualquer opção:

- **Banco:** RDS/Cloud SQL/Azure Database for PostgreSQL com extensão `pgvector`.
- **Segredos:** Secrets Manager / Key Vault / Secret Manager, injetados como env vars.
- **Fila:** SQS / Service Bus / Pub/Sub para desacoplar `POST /ask` dos workers.
- **LLM:** Bedrock / Azure OpenAI / Vertex AI, ou vLLM em nó GPU no cluster.
- **Observabilidade:** CloudWatch / Azure Monitor / Cloud Logging recebendo OpenTelemetry.
- **Rede:** API atrás de gateway com WAF; banco e LLM em sub-rede privada; UI só fala com a API.

Se eu tivesse que escolher hoje para um piloto interno: **Cloud Run ou Container Apps + Postgres
gerenciado + LLM gerenciado**. Menor custo fixo, deploy em minutos, e nada do núcleo muda. Migrar
para Kubernetes depois é mover o mesmo container.

**Infraestrutura como código:** Terraform ou Bicep para os recursos acima, no mesmo
repositório, em `infra/`. Não está incluído aqui porque exigiria uma conta em nuvem para
validar — e o critério deste projeto foi não publicar nada que não tenha sido executado.

## O que eu faria primeiro

Se tivesse uma semana para colocar isso diante de usuários internos reais:

1. Autenticação com o IdP (1 dia).
2. Postgres + pgvector, migrar schema e consultas (1–2 dias).
3. API assíncrona com fila e worker; UI consumindo `run_id` (2 dias).
4. LLM gerenciado com cota e orçamento; Ollama fica como fallback de desenvolvimento (0,5 dia).
5. CI com os 33 casos; deploy em staging (1 dia).

Nada disso toca o grafo do agente, as regras de aprovação ou os contratos das ferramentas.

## O que eu não faria

- **Multiagentes.** Nenhum problema atual pede isso; só aumentaria superfície e custo.
- **Deixar o LLM escolher ferramentas** antes de ter telemetria suficiente para medir se a
  flexibilidade compensa a perda de previsibilidade.
- **Cache de respostas** compartilhado entre usuários — o filtro de permissão invalidaria a
  maior parte dos acertos e o risco de vazamento não compensa.
- **Prometer que elimina alucinação.** O desenho reduz a superfície e torna o erro visível;
  a avaliação contínua é o que mantém isso verdadeiro.

## Custo estimado (ordem de grandeza, não orçamento)

Para 200 usuários internos, ~2.000 perguntas/dia, LLM gerenciado:

| Item | Faixa mensal |
|---|---|
| Postgres gerenciado (pequeno, com réplica) | US$ 100–300 |
| API + workers (3–6 instâncias pequenas) | US$ 150–400 |
| LLM (≈2.000/dia × ~6k tokens de prompt + ~600 de resposta) | depende do modelo e do provedor; US$ 100–1.000 |
| Observabilidade | US$ 50–200 |

Os volumes de tokens vêm das execuções reais em `evals/results/`; os preços variam por
provedor e região e devem ser cotados na hora. Inferência própria em GPU troca custo variável
por fixo e faz sentido acima de algumas dezenas de milhares de perguntas por mês ou quando os
dados não podem sair do ambiente.
