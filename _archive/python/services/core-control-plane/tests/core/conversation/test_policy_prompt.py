from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.conversation.policy_prompt import UserPolicyCompiler
from fdai.shared.providers.briefing import (
    BriefingSpec,
    ConversationPolicyKind,
    ConversationPolicyRecord,
)

NOW = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)


def _policy(
    policy_id: str,
    *,
    kind: ConversationPolicyKind,
    defaults: dict[str, str] | None = None,
    briefing: BriefingSpec | None = None,
) -> ConversationPolicyRecord:
    return ConversationPolicyRecord(
        policy_id=policy_id,
        principal_id="principal-a",
        kind=kind,
        enabled=True,
        revision=2,
        confirmed_at=NOW,
        source_turn_id="turn-1",
        response_defaults=defaults or {},
        briefing_spec=briefing,
    )


def test_compiler_emits_only_allowlisted_fixed_directives() -> None:
    compiled = UserPolicyCompiler().compile(
        (
            _policy(
                "response-defaults",
                kind=ConversationPolicyKind.RESPONSE_DEFAULTS,
                defaults={"verbosity": "concise", "answer_language": "ko"},
            ),
        )
    )
    assert compiled is not None
    assert "concise" in compiled.system_text
    assert "BCP-47 language 'ko'" in compiled.system_text
    assert compiled.policy_refs == ("response-defaults@2",)


def test_opening_briefing_is_not_compiled_into_system_prompt() -> None:
    compiled = UserPolicyCompiler().compile(
        (
            _policy(
                "opening",
                kind=ConversationPolicyKind.OPENING_BRIEFING,
                briefing=BriefingSpec(),
            ),
        )
    )
    assert compiled is None
