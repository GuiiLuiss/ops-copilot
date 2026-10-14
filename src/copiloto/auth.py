"""Identidade e autorização de demonstração.

ATENÇÃO: a seleção de usuário na interface é um MODO DE DEMONSTRAÇÃO LOCAL.
Não é autenticação segura. Para implantação externa, substituir por autenticação real.
A autorização (papel → nível de acesso) é aplicada no backend, nunca pelo LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Role = Literal["analista", "gestor"]

# Níveis de acesso em ordem crescente. Um papel acessa seu nível e os inferiores.
ACCESS_LEVELS: dict[str, int] = {"analista": 1, "gestor": 2}


@dataclass(frozen=True)
class User:
    user_id: str
    name: str
    role: Role

    @property
    def access_level(self) -> int:
        return ACCESS_LEVELS[self.role]

    def can_access(self, doc_access_level: str) -> bool:
        return self.access_level >= ACCESS_LEVELS.get(doc_access_level, 99)

    @property
    def can_approve(self) -> bool:
        return self.role == "gestor"


DEMO_USERS: dict[str, User] = {
    "ana.analista": User("ana.analista", "Ana (analista)", "analista"),
    "gui.gestor": User("gui.gestor", "Gui (gestor)", "gestor"),
}


def get_user(user_id: str) -> User:
    try:
        return DEMO_USERS[user_id]
    except KeyError as e:
        raise PermissionError(f"usuário desconhecido: {user_id}") from e
