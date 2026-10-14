"""Ferramenta `search_policies`. O `User` vem do backend; o modelo só escolhe a query."""

from __future__ import annotations

from copiloto.auth import User
from copiloto.retrieval.retriever import Retriever, get_retriever
from copiloto.tools.contracts import SearchPoliciesInput, SearchPoliciesOutput


def search_policies(inp: SearchPoliciesInput, user: User,
                    retriever: Retriever | None = None,
                    mode: str | None = None) -> SearchPoliciesOutput:
    r = retriever or get_retriever()
    res = r.search(inp.query, user=user, reference_date=inp.reference_date,
                   top_k=inp.top_k, mode=mode)
    return SearchPoliciesOutput(
        query=inp.query, retrieval_mode=res.mode, hits=res.hits,
        filtered_out_count=res.filtered_out_count,
    )
