"""Shared runtime skill disclosure defaults for read API composition."""

from __future__ import annotations

from fdai.core.conversation import default_tool_schemas
from fdai.core.skills import RuntimeSkill, RuntimeSkillDisclosure, SkillCatalog

READ_API_SKILL_TOOL_IDS = frozenset(
    {
        *(schema.tool_name for schema in default_tool_schemas()),
        "describe_skill",
        "list_skills",
        "load_skill",
        "read_skill_reference",
    }
)


class RejectingSkillTrustVerifier:
    """Fail closed until startup publishes a verified durable snapshot."""

    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        del skill, raw_markdown
        return False


def empty_runtime_skill_disclosure() -> RuntimeSkillDisclosure:
    """Build an empty Bragi projection that grants no runtime capability."""
    return RuntimeSkillDisclosure(
        catalog=SkillCatalog(),
        verifier=RejectingSkillTrustVerifier(),
        agent="Bragi",
        available_tools=READ_API_SKILL_TOOL_IDS,
    )


__all__ = [
    "READ_API_SKILL_TOOL_IDS",
    "RejectingSkillTrustVerifier",
    "empty_runtime_skill_disclosure",
]
