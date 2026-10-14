# Limitações e o que este projeto NÃO é

## Não é um sistema em produção

- **Autenticação de demonstração.** A seleção de usuário na interface e o header `X-Demo-User`
  na API identificam o papel, mas não autenticam ninguém. Para uso externo é necessário
  autenticação real (OIDC, sessão, etc.) e o backend já recebe o `User` de forma desacoplada.
- **Sem multiusuário real.** SQLite local, sem controle de concorrência além do lock do FTS5.
- **Sem conformidade declarada.** Não há alegação de conformidade com LGPD ou outro regime.
  Os dados são sintéticos; os controles implementados estão listados no README.

## Dados e cenário

- O aumento de cancelamentos foi **introduzido artificialmente** (assinante × RapidoLog ×
  atraso). O sistema encontra o padrão porque ele existe nos dados, não por inteligência
  analítica geral.
- Três meses de dados; perguntas sobre outros períodos retornam limitação.
- Correlação ≠ causa: as respostas usam "concentra-se em" e "hipótese a investigar". O LLM
  pode ainda assim escorregar na redação; o caso M01 verifica termos proibidos.

## Agente

- **Planner por regras.** Perguntas fora dos padrões caem em `insufficient` mesmo quando um
  humano saberia qual consulta fazer.
- **Validação de citações** só garante que o ID citado existe entre os chunks recuperados —
  não que o trecho sustenta a afirmação (fidelidade). Fidelidade exige rubrica humana.
- **Detecção de prompt injection por padrões** é complementar. A defesa principal é
  estrutural: o LLM não tem ferramenta de escrita, a aprovação está fora dele e a autorização
  é pré-filtro.
- Resposta com LLM não é determinística entre execuções (temperatura 0.1, modelo local).

## Recuperação

- Corpus pequeno (12 documentos, ~50 chunks). Resultados de lexical vs híbrido **não
  generalizam** para corpora grandes.
- Modelo de embeddings multilíngue genérico; sem fine-tuning.
- Reranking não implementado.
- Sem cache de respostas (decisão: evitar compartilhamento indevido entre papéis).

## Avaliação

- 33 casos é uma amostra pequena. Percentis só são reportados com n ≥ 5 e não devem ser
  lidos como SLA.
- Checks automáticos cobrem exatidão numérica, recall de documentos, precisão de citações,
  autorização, aprovação e injeção. **Utilidade e fidelidade** exigem rubrica humana e não
  estão automatizadas.
- LLM-as-judge não foi usado.
- Uma repetição por variante; sem intervalo de confiança.

## Custos

- Não há tabela de preços; exibimos tokens, não dinheiro.
- Rodar local custa hardware e energia, não medidos.

## Achados da avaliação com LLM

Após a iteração v1.3 → v1.4 (ver `evaluation.md`):

- **Resolvido**: eco de texto de documento malicioso — chunks sinalizados agora ficam em
  quarentena e não chegam ao LLM (0 ocorrências em 66 execuções).
- **Reduzido, não eliminado**: o modelo `qwen3.5:9b` ainda **inventa IDs de chunk**
  ocasionalmente (12 → 2 em 66 execuções) mesmo com a lista explícita de citações permitidas.
  A validação remove, mas a afirmação fica sem referência. Próximas opções: citação por índice
  numérico, modelo maior, ou segunda passagem de reparo (com limite de 1).
- **Omissão** de rótulos presentes no contexto ocorre esporadicamente (1 em 66).
- A detecção de injeção continua baseada em padrões; a quarentena só protege contra o que
  o detector reconhece. A defesa estrutural (sem ferramenta de escrita, aprovação fora do LLM)
  é o que vale para o resto.

## Planejado, não implementado

- Reranking local com medição de latência.
- Exposição das ferramentas via MCP.
- Ingestão de PDF/OCR.
- Tool calling pelo LLM com os mesmos contratos.
