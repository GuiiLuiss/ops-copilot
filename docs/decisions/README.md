# Decisões de arquitetura

Registros curtos no formato contexto → decisão → consequências.

## ADR-001: Dados estruturados *e* RAG, com papéis distintos

**Contexto.** A pergunta principal mistura números ("aumentaram?") e normas ("quais ações?").
**Decisão.** Números vêm **somente** de consultas SQL fixas (`query_operations`); documentos
vêm de recuperação (`search_policies`). O LLM não calcula nem consulta: recebe evidências
prontas, com taxas já formatadas (`*_pct`).
**Consequências.** Exatidão numérica verificável (6/6 nos casos); o LLM pode errar formatação
ou omitir, mas não inventar números que não existem no contexto. Custo: perguntas que exigiriam
uma consulta não prevista caem em "insuficiente".

## ADR-002: Um agente com ferramentas, não multiagentes

**Contexto.** Multiagentes aumentam superfície de erro, latência e dificuldade de auditoria.
**Decisão.** Um grafo linear com cinco nós e lista fechada de três ferramentas.
**Consequências.** Rastreio simples (uma linha JSON por execução), limites fáceis de impor.
Extensões (ex.: MCP) ficam fora do MVP.

## ADR-003: Aprovação fora da autoridade do LLM

**Contexto.** Documentos recuperados podem conter instruções para "aprovar automaticamente".
**Decisão.** `approval.py` é uma operação da aplicação: exige papel gestor, hash exato do
conteúdo exibido e prazo; edição revoga; execução é idempotente por `proposal_id + hash`.
O grafo do agente não tem acesso a essas funções.
**Consequências.** Mesmo que o modelo "decida" aprovar, nada acontece. Testado em
`tests/test_approval.py` e nos casos F01–F04, S03.

## ADR-004: Autorização como pré-filtro, não pós-filtro

**Contexto.** Filtrar depois do ranking pode vazar trechos restritos via ranking/trecho.
**Decisão.** O conjunto pesquisável é restrito ao nível do usuário **antes** de qualquer busca;
`get_chunk` também valida. FAISS não tem pré-filtro nativo, então o retriever busca um pool
maior (`top_k × 4`) e descarta IDs não autorizados antes da fusão.
**Consequências.** Zero vazamentos nos casos S01/S02 e testes. Custo: o pool pode ser pequeno
demais em corpora grandes (mitigação: particionar índices por nível).

## ADR-005: Busca híbrida com RRF; reranking adiado

**Contexto.** Documentos curtos em português; lexical já resolve a maior parte.
**Decisão.** Lexical (FTS5) é o baseline obrigatório sem downloads. Vetorial e híbrido (RRF,
k=60) são variantes medidas com os mesmos casos. Reranking fica para depois de haver ganho
demonstrado nas variantes.
**Consequências.** Ver `docs/evaluation.md` para resultados reais, incluindo onde a variante
não ajudou.

## ADR-006: Ollama local como provedor principal; Gemini opcional

**Contexto.** Hardware disponível (RTX 4070 Laptop, 32 GB) suporta um modelo de 9B; cotas
gratuitas de API mudam sem aviso.
**Decisão.** Interface `LLMProvider` com três implementações. Ollama é o padrão quando o
usuário ativa LLM; Gemini via REST sem SDK extra; `none` é sempre funcional.
**Consequências.** Sem chave para rodar a demo; latência local medida (~18 s resposta +
~11 s proposta no smoke test com `qwen3.5:9b`). Todos os resultados publicados usam Ollama;
o provedor Gemini existe como alternativa de configuração.

## ADR-007: Planner por regras

**Contexto.** Deixar o LLM escolher ferramentas exigiria validação extra e inviabilizaria o
modo determinístico.
**Decisão.** Intenção e plano por expressões regulares sobre a pergunta normalizada.
**Consequências.** Previsível e barato; menos flexível. Registrado como limitação e possível
extensão (tool calling com os mesmos contratos Pydantic).
