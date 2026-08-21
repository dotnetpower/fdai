"""Narrator - the console LLM tier's *translator* role.

Sole responsibility: turn one natural-language utterance into ONE
Chat T0 verb string that the shipped
:class:`~fdai.core.conversation.coordinator.ConversationCoordinator`
exact-command parser will resolve, or abstain.

Design authority
----------------
[implementation-plan.md 2.2](../../../../docs/roadmap/fork-and-sequencing/implementation-plan.md)
R2 (ConsoleTool projection) and 2.3 R3 (LlmBinding role enum) fix the
narrator as a **translator, never a judge**:

- The narrator is NOT allowed to invent tool arguments, execute a
  side effect, or write to any store. It emits a *string*; the
    coordinator's exact-command parser converts it into ``(tool, args)`` under
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
The real Azure OpenAI-backed narrator is a delivery-layer adapter
(see :mod:`fdai.delivery.azure.llm.narrator`) - `core/` MUST
NOT import from `delivery/`.
"""

from __future__ import annotations

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
    installed command name). ``argument_hint`` is a free-form English hint an LLM
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

    Return the canonical verb line the coordinator's exact-command parser accepts
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


def default_tool_schemas() -> tuple[ToolSchema, ...]:
    """Ship the tool metadata the narrator sees.

    Lists canonical installed command names available for model translation.
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
    "GroundedAnswerNarrator",
    "Narrator",
    "ReadPlanNarrator",
    "ToolSchema",
    "default_tool_schemas",
    "format_prompt_tool_list",
]
