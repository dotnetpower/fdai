"""Read-only Command Deck adapter for trusted runtime skill disclosure."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any

from fdai.core.conversation import (
    DescribeRuntimeSkillBundleTool,
    DescribeRuntimeSkillTool,
    ListRuntimeSkillBundlesTool,
    ListRuntimeSkillsTool,
    LoadRuntimeSkillBundleTool,
    LoadRuntimeSkillTool,
    Principal,
    ReadRuntimeSkillReferenceTool,
    Role,
)
from fdai.core.conversation.tools import SystemConsoleTool
from fdai.core.skills import RuntimeSkillDisclosure
from fdai.delivery.read_api.routes.chat_system_health import ChatToolResolver

_SKILL_VERBS = frozenset(
    {
        "list_skills",
        "describe_skill",
        "load_skill",
        "read_skill_reference",
        "list_skill_bundles",
        "describe_skill_bundle",
        "load_skill_bundle",
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeSkillChatTools:
    """Resolve explicit skill reads before narrator prompt assembly."""

    disclosure: RuntimeSkillDisclosure
    fallback: ChatToolResolver | None = None

    async def resolve(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        try:
            tokens = shlex.split(prompt)
        except ValueError as exc:
            head = prompt.lstrip().split(maxsplit=1)
            if not head or head[0] not in _SKILL_VERBS:
                return await self._fallback(prompt, principal_id=principal_id)
            return _invalid_arguments(str(exc))
        if not tokens or tokens[0] not in _SKILL_VERBS:
            return await self._fallback(prompt, principal_id=principal_id)
        verb = tokens[0]
        try:
            tool, arguments = self._tool_call(verb, tokens[1:])
            result = tool.call(
                arguments=arguments,
                principal=Principal(id=principal_id, role=Role.READER),
            )
        except ValueError as exc:
            return _invalid_arguments(str(exc), tool=verb)
        return {
            "tool": verb,
            "authority": "trusted_skill_catalog",
            "status": result.status,
            "result": result.data,
        }

    def _tool_call(
        self,
        verb: str,
        arguments: list[str],
    ) -> tuple[SystemConsoleTool, dict[str, object]]:
        if verb == "list_skills":
            limit = 20
            query_parts: list[str] = []
            for value in arguments:
                if value.startswith("limit="):
                    limit = int(value.removeprefix("limit="))
                else:
                    query_parts.append(value)
            return ListRuntimeSkillsTool(self.disclosure), {
                "query": " ".join(query_parts),
                "limit": limit,
            }
        if verb == "describe_skill" and len(arguments) == 1:
            return DescribeRuntimeSkillTool(self.disclosure), {"name": arguments[0]}
        if verb == "load_skill" and len(arguments) == 1:
            return LoadRuntimeSkillTool(self.disclosure), {"name": arguments[0]}
        if verb == "read_skill_reference" and len(arguments) == 2:
            return ReadRuntimeSkillReferenceTool(self.disclosure), {
                "name": arguments[0],
                "path": arguments[1],
            }
        if verb == "list_skill_bundles":
            limit = 20
            bundle_query_parts: list[str] = []
            for value in arguments:
                if value.startswith("limit="):
                    limit = int(value.removeprefix("limit="))
                else:
                    bundle_query_parts.append(value)
            return ListRuntimeSkillBundlesTool(self.disclosure), {
                "query": " ".join(bundle_query_parts),
                "limit": limit,
            }
        if verb == "describe_skill_bundle" and len(arguments) == 1:
            return DescribeRuntimeSkillBundleTool(self.disclosure), {"name": arguments[0]}
        if verb == "load_skill_bundle" and len(arguments) == 1:
            return LoadRuntimeSkillBundleTool(self.disclosure), {"name": arguments[0]}
        raise ValueError(f"invalid arguments for {verb}")

    async def _fallback(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
        if self.fallback is None:
            return None
        return await self.fallback.resolve(prompt, principal_id=principal_id)


def _invalid_arguments(message: str, *, tool: str | None = None) -> dict[str, Any]:
    return {
        "tool": tool or "skill_disclosure",
        "authority": "trusted_skill_catalog",
        "status": "error",
        "result": {
            "error": {
                "code": "invalid_skill_tool_arguments",
                "message": message,
            }
        },
    }


__all__ = ["RuntimeSkillChatTools"]
