"""Narrator - the console LLM tier's *translator* role.

Sole responsibility: turn one natural-language utterance into ONE
Chat T0 verb string that the shipped
:class:`~fdai.core.conversation.coordinator.ConversationCoordinator`
regex matcher will resolve, or abstain.

Design authority
----------------
[implementation-plan.md 2.2](../../../../docs/roadmap/fork-and-sequencing/implementation-plan.md)
R2 (ConsoleTool projection) and 2.3 R3 (LlmBinding role enum) fix the
narrator as a **translator, never a judge**:

- The narrator is NOT allowed to invent tool arguments, execute a
  side effect, or write to any store. It emits a *string*; the
  coordinator's T0 regex parses it back into ``(tool, args)`` under
  the same rules an operator typing the verb by hand would face.
- Narrator abstention (returning ``None`` / an unparseable string) is
  a fail-closed outcome - the coordinator abstains with the tool
  inventory, exactly as if the operator had typed a nonsense verb.
- The narrator MUST NOT bypass the RBAC floor. The coordinator gates
  the tool by role AFTER the T0 regex parse, so a Reader that asked
  for an Approver-only verb still gets a role refusal preview.

Upstream ships:

- :class:`Narrator` - the Protocol every adapter satisfies.
- :class:`ToolSchema` / :class:`NarratorArgumentSchema` - the tool
  metadata the coordinator hands to the narrator.
- :class:`DeterministicKeywordNarrator` - a fake / seed narrator used
  by tests and by ``tools/chat.py`` when no LLM binding is wired. It
  looks for keyword hints in the utterance (e.g. Korean 'audit'
  '감사 로그', English 'runbook' / 'audit log') and emits a
  matching verb, or abstains.

The real Azure OpenAI-backed narrator is a delivery-layer adapter
(see :mod:`fdai.delivery.azure.llm.narrator`) - `core/` MUST
NOT import from `delivery/`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from fdai.core.conversation.answer_plan import AnswerPlan
    from fdai.core.conversation.session import Turn
    from fdai.core.conversation.tools import ToolResult


@dataclass(frozen=True, slots=True)
class ToolSchema:
    """One tool description the narrator sees.

    ``verb`` is the canonical Chat T0 verb (matches the shipped
    :func:`~fdai.core.conversation.coordinator._VERB_PATTERNS`
    entry). ``argument_hint`` is a free-form English hint an LLM
    can lean on ("<resource_type> [substring]", "<approval_id>", ...).
    ``rbac_floor`` is the minimum role - narrator MAY omit tools
    above the current principal's role from the prompt, but the
    coordinator still enforces the floor after parsing.
    """

    verb: str
    tool_name: str
    argument_hint: str
    summary: str
    rbac_floor: str
    side_effect_class: str


@runtime_checkable
class Narrator(Protocol):
    """Translate one utterance into a Chat T0 verb string, or abstain.

    Return the canonical verb line the coordinator's regex accepts
    (e.g. ``"query_inventory resource-group"``), or :class:`None` to
    abstain (fail-closed - the coordinator emits an
    :class:`~fdai.core.conversation.tools.AbstainResult`).

    Sync by contract: the operator console REPL calls the narrator
    once per turn and blocks on the answer; an adapter that fronts
    async HTTP MAY wrap it internally (``asyncio.run(...)`` or
    :class:`httpx.Client`). Keeping the surface sync avoids forcing
    every coordinator caller to become an async function.
    """

    def translate(
        self,
        *,
        utterance: str,
        tools: Sequence[ToolSchema],
        principal_role: str,
    ) -> str | None: ...


@runtime_checkable
class ContextualNarrator(Protocol):
    """Translate a follow-up using bounded prior turns as untrusted context."""

    def translate_with_context(
        self,
        *,
        utterance: str,
        tools: Sequence[ToolSchema],
        prior_turns: Sequence[Turn],
        principal_role: str,
    ) -> str | None: ...


@runtime_checkable
class ClarificationNarrator(Protocol):
    """Ask one bounded question without selecting or invoking a tool."""

    def clarify(
        self,
        *,
        utterance: str,
        tools: Sequence[ToolSchema],
        prior_turns: Sequence[Turn],
        principal_role: str,
    ) -> str | None: ...


@runtime_checkable
class ReadPlanNarrator(Protocol):
    """Propose two or three canonical read commands without invoking them."""

    def propose_read_plan(
        self,
        *,
        utterance: str,
        tools: Sequence[ToolSchema],
        prior_turns: Sequence[Turn],
        principal_role: str,
    ) -> tuple[str, ...] | None: ...


@runtime_checkable
class GroundedAnswerNarrator(Protocol):
    """Render one successful tool result without changing its authority.

    The implementation receives only the operator utterance, the selected
    tool schema, the completed result, and the bounded session projection. It
    may improve presentation, but it cannot select another tool, alter the
    result payload, or grant execution eligibility.
    """

    def render_answer(
        self,
        *,
        utterance: str,
        tool: ToolSchema,
        result: ToolResult,
        answer_plan: AnswerPlan,
        prior_turns: Sequence[Turn],
        principal_role: str,
    ) -> str | None: ...


# ---------------------------------------------------------------------------
# Deterministic seed narrator (fake / tests)
# ---------------------------------------------------------------------------


# Bilingual keyword -> canonical verb prefix table. Deliberately small:
# the deterministic narrator is a fallback, not a substitute for an LLM.
# Every English keyword MUST also be a T0 verb prefix so the produced
# string is guaranteed to parse; Korean keywords are hand-picked from
# common operator prompts and MUST map to the same English verb.
_KEYWORD_TABLE: tuple[tuple[str, str], ...] = (
    # search_conversations
    ("search_conversations", "search_conversations"),
    ("conversation history", "search_conversations"),
    ("prior conversations", "search_conversations"),
    ("대화 검색", "search_conversations"),
    ("이전 대화", "search_conversations"),
    # explore_catalog
    ("explore_catalog", "explore_catalog"),
    ("list_rules", "explore_catalog"),
    ("카탈로그", "explore_catalog"),
    ("규칙 목록", "explore_catalog"),
    # query_inventory
    ("query_inventory", "query_inventory"),
    ("list_resources", "query_inventory"),
    ("인벤토리", "query_inventory"),
    ("리소스 그룹 목록", "query_inventory resource-group"),
    ("리소스 목록", "query_inventory"),
    # query_audit
    ("query_audit", "query_audit"),
    ("audit_log", "query_audit"),
    ("감사 로그", "query_audit"),
    ("감사 내역", "query_audit"),
    # list_hil
    ("list_hil", "list_hil"),
    ("pending_approvals", "list_hil"),
    ("승인 대기", "list_hil"),
    # query_operator_memory
    ("query_operator_memory", "query_operator_memory"),
    ("operator_memory", "query_operator_memory"),
    ("오퍼레이터 메모리", "query_operator_memory"),
    # query_log / metric / deployments / correlate
    ("query_log", "query_log"),
    ("로그 조회", "query_log"),
    ("query_metric", "query_metric"),
    ("메트릭", "query_metric"),
    ("query_deployments", "query_deployments"),
    ("배포 이력", "query_deployments"),
    ("correlate_incident", "correlate_incident"),
)


class DeterministicKeywordNarrator:
    """Keyword-lookup narrator used as a fallback / test seed.

    Never calls an LLM, never allocates memory beyond the input string.
    Matches on the FIRST English or Korean keyword the utterance
    contains (case-insensitive). Emits the corresponding verb prefix -
    the coordinator's regex will bind whatever argument text follows.

    A real LLM narrator (fork adapter) replaces this in production;
    upstream keeps this class so:

    - ``tools/chat.py`` works out of the box without an LLM binding
      for at least a curated bilingual keyword set.
    - Contract tests can assert coordinator + narrator wiring without
      pulling in an Azure adapter.
    """

    def __init__(self, table: Sequence[tuple[str, str]] | None = None) -> None:
        entries = tuple(table) if table is not None else _KEYWORD_TABLE
        if not entries:
            raise ValueError("DeterministicKeywordNarrator requires >= 1 keyword")
        self._entries: tuple[tuple[str, str], ...] = entries

    def translate(
        self,
        *,
        utterance: str,
        tools: Sequence[ToolSchema],
        principal_role: str,  # noqa: ARG002 - kept for Protocol parity
    ) -> str | None:
        del tools  # deterministic table ignores the schema
        stripped = utterance.strip()
        if not stripped:
            return None
        # Prefer the longest keyword match so a compound phrase like
        # "resource group list" wins over the shorter "resource list"
        # substring in the keyword table.
        matches = sorted(
            (
                (keyword, verb)
                for keyword, verb in self._entries
                if _keyword_present(stripped, keyword)
            ),
            key=lambda pair: -len(pair[0]),
        )
        if not matches:
            return None
        return matches[0][1]


def _keyword_present(haystack: str, needle: str) -> bool:
    """Case-insensitive substring test with word-boundary respect for ASCII.

    Korean (Hangul) never needs a word boundary; English keywords do
    so ``"list_rules"`` does NOT match ``"listen_rules"``.
    """
    if not needle:
        return False
    lowered_haystack = haystack.lower()
    lowered_needle = needle.lower()
    if needle.isascii() and re.fullmatch(r"[a-z0-9_]+", lowered_needle):
        pattern = rf"(?<![a-z0-9_]){re.escape(lowered_needle)}(?![a-z0-9_])"
        return re.search(pattern, lowered_haystack) is not None
    return lowered_needle in lowered_haystack


def default_tool_schemas() -> tuple[ToolSchema, ...]:
    """Ship the tool metadata the narrator sees.

    Mirrors the shipped :func:`~fdai.core.conversation.coordinator._VERB_PATTERNS`
    verb set. New verbs added to the coordinator MUST be reflected here
    (drift-guard tested).
    """
    return _DEFAULT_SCHEMAS


_DEFAULT_SCHEMAS: tuple[ToolSchema, ...] = (
    ToolSchema(
        verb="list_skills",
        tool_name="list_skills",
        argument_hint="<query> [limit=N]",
        summary="List eligible runtime skill metadata without loading content.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="describe_skill",
        tool_name="describe_skill",
        argument_hint="<skill_name>",
        summary="Describe one installed runtime skill without loading its body.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="load_skill",
        tool_name="load_skill",
        argument_hint="<skill_name>",
        summary="Load one complete eligible, trust-verified runtime skill body.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="read_skill_reference",
        tool_name="read_skill_reference",
        argument_hint="<skill_name> <reference_path>",
        summary="Read one complete declared runtime skill reference.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="list_skill_bundles",
        tool_name="list_skill_bundles",
        argument_hint="<query> [limit=N]",
        summary="List governed runtime skill bundle metadata without loading members.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="describe_skill_bundle",
        tool_name="describe_skill_bundle",
        argument_hint="<bundle_name>",
        summary="Describe one governed skill bundle and its compatibility metadata.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="load_skill_bundle",
        tool_name="load_skill_bundle",
        argument_hint="<bundle_name>",
        summary="Load one eligible bundle and all complete member bodies atomically.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="search_conversations",
        tool_name="search_conversations",
        argument_hint="<query> [mode=terms|phrase|prefix] [limit=N]",
        summary="Search prior authorized conversation turns without inference.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="search_tools",
        tool_name="search_tools",
        argument_hint="<capability query> [limit=N]",
        summary="Search installed tools visible to the current principal.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="describe_tool",
        tool_name="describe_tool",
        argument_hint="<tool_name>",
        summary="Describe one installed tool without invoking it.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="explore_catalog",
        tool_name="explore_catalog",
        argument_hint="<free-text query>",
        summary="Search shipped rules and ActionTypes by keyword.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="describe_event",
        tool_name="describe_event",
        argument_hint="<resource_type> <resource_id>",
        summary="Show what a normalized event looks like end-to-end.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="explain_verdict",
        tool_name="explain_verdict",
        argument_hint="<event_id>",
        summary="Show the tier + risk-gate decision for a past event.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="query_audit",
        tool_name="query_audit",
        argument_hint="[filters]",
        summary="Read the append-only audit log.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="query_inventory",
        tool_name="query_inventory",
        argument_hint="<resource_type> [substring]",
        summary="List resources of the given type (e.g. resource-group, object-storage).",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="query_operator_memory",
        tool_name="query_operator_memory",
        argument_hint="<scope_kind> <scope_ref>",
        summary="List active operator-memory entries scoped to a resource or resource-group.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="query_log",
        tool_name="query_log",
        argument_hint="<resource_ref> [query]",
        summary="Query recent log lines for a resource.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="query_metric",
        tool_name="query_metric",
        argument_hint="<resource_ref> <metric_name>",
        summary="Query a metric time-series for a resource.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="query_deployments",
        tool_name="query_deployments",
        argument_hint="<resource_ref>",
        summary="List recent deployments touching a resource.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="correlate_incident",
        tool_name="correlate_incident",
        argument_hint="<event_id>",
        summary="Correlate an event with prior resolved incidents.",
        rbac_floor="reader",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="simulate_change",
        tool_name="simulate_change",
        argument_hint="<event-json>",
        summary="Dry-run one event through the pipeline without side effects.",
        rbac_floor="contributor",
        side_effect_class="simulate",
    ),
    ToolSchema(
        verb="list_hil",
        tool_name="list_hil",
        argument_hint="",
        summary="List pending human-in-the-loop approval items.",
        rbac_floor="approver",
        side_effect_class="read",
    ),
    ToolSchema(
        verb="approve_hil",
        tool_name="approve_hil",
        argument_hint="<approval_id> [approve|reject]",
        summary="Approve or reject a pending HIL item.",
        rbac_floor="approver",
        side_effect_class="approve",
    ),
    ToolSchema(
        verb="run_runbook",
        tool_name="run_runbook",
        argument_hint="<name> [params_json] [--dry-run]",
        summary="Execute a runbook (dry-run only for Contributor; live requires Owner).",
        rbac_floor="contributor",
        side_effect_class="execute",
    ),
    ToolSchema(
        verb="activate_break_glass",
        tool_name="activate_break_glass",
        argument_hint="<reason (>=20 chars)>",
        summary="Grant a time-boxed emergency access; paged owners are notified.",
        rbac_floor="reader",
        side_effect_class="breakglass",
    ),
)


def format_prompt_tool_list(tools: Sequence[ToolSchema], principal_role: str) -> str:
    """Render a compact bullet list for LLM narrator prompts.

    Only tools whose ``rbac_floor`` the principal MEETS are exposed
    to the narrator - a Reader-role prompt never sees write verbs.
    RBAC ordering matches
    :class:`~fdai.core.rbac.roles.Role`.
    """
    order: Mapping[str, int] = {
        "reader": 0,
        "contributor": 1,
        "approver": 2,
        "owner": 3,
        "break_glass": 4,
    }
    principal_level = order.get(principal_role.lower(), 0)
    lines: list[str] = []
    for schema in tools:
        floor_level = order.get(schema.rbac_floor.lower(), 0)
        if floor_level > principal_level:
            continue
        arg = f" {schema.argument_hint}" if schema.argument_hint else ""
        lines.append(f"- {schema.verb}{arg} -- {schema.summary}")
    return "\n".join(lines)


__all__ = [
    "ClarificationNarrator",
    "ContextualNarrator",
    "DeterministicKeywordNarrator",
    "GroundedAnswerNarrator",
    "Narrator",
    "ReadPlanNarrator",
    "ToolSchema",
    "default_tool_schemas",
    "format_prompt_tool_list",
]
