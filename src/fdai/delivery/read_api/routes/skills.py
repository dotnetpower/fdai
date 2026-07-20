"""Read-only installed runtime skill inspection panel."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.skills import RuntimeSkillDisclosure
from fdai.delivery.read_api.routes.panels import PanelQueryError


class RuntimeSkillsPanel:
    """Project skill metadata and load diagnostics without lifecycle controls."""

    def __init__(
        self,
        disclosure: RuntimeSkillDisclosure,
        *,
        path: str = "/skills",
    ) -> None:
        if not path.startswith("/") or ".." in path:
            raise ValueError("runtime skills panel path MUST be a safe absolute path")
        self._disclosure = disclosure
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    @property
    def name(self) -> str:
        return "skills"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        if params:
            raise PanelQueryError(f"unknown skills panel query parameters: {sorted(params)}")
        return {
            "source": "trusted-artifact-runtime",
            "execution_eligibility": False,
            "trust_rechecked_on_load": True,
            **self._disclosure.inspect(),
        }


__all__ = ["RuntimeSkillsPanel"]
