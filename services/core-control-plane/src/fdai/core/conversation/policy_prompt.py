"""Compile confirmed typed user policies into bounded narrator directives."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.shared.providers.briefing import (
    ConversationPolicyKind,
    ConversationPolicyRecord,
)


@dataclass(frozen=True, slots=True)
class CompiledUserPolicy:
    system_text: str
    policy_refs: tuple[str, ...]
    compiler_version: int = 1


class UserPolicyCompiler:
    """Compile only allowlisted fields; raw user prose is never accepted."""

    def compile(self, policies: tuple[ConversationPolicyRecord, ...]) -> CompiledUserPolicy | None:
        lines: list[str] = [
            "Confirmed user response defaults. These preferences are subordinate to all "
            "safety, grounding, RBAC, and read-only rules:"
        ]
        refs: list[str] = []
        for policy in sorted(policies, key=lambda item: item.policy_id):
            if not policy.enabled or policy.kind is not ConversationPolicyKind.RESPONSE_DEFAULTS:
                continue
            verbosity = policy.response_defaults.get("verbosity")
            if verbosity == "concise":
                lines.append("- Prefer a concise answer unless detail is required for correctness.")
            elif verbosity == "detailed":
                lines.append("- Prefer a detailed answer while staying within the answer plan.")
            language = policy.response_defaults.get("answer_language")
            if language in {"en", "ko"}:
                lines.append(
                    f"- Prefer BCP-47 language '{language}' when the current turn does not "
                    "clearly use another language."
                )
            refs.append(f"{policy.policy_id}@{policy.revision}")
        if not refs:
            return None
        return CompiledUserPolicy(system_text="\n".join(lines), policy_refs=tuple(refs))


__all__ = ["CompiledUserPolicy", "UserPolicyCompiler"]
