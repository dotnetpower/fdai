"""Read-only console tools (Day 1 - operator-console.md 3.1).

Every shipped tool has ``side_effect_class = 'read'`` and is exercised
in the module tests to prove it never touches an executor, PR adapter,
or state-store write. Tools consume already-loaded catalogs (rule +
ActionType) in memory; they do not open external connections.

Wave scope:

- **Day 1 (this module)** - ``explore_catalog``, plus the shape shared by
  the other four read-only tools. ``describe_event``, ``explain_verdict``,
  ``query_audit``, and ``query_inventory`` will land as separate
  implementations that plug into the same Protocol; they need live
  providers (StateStore, Inventory) whose composition happens at the
  CLI layer.
- **Wave W1** - write-class tools (``simulate_change``, ``approve_hil``,
  ...) land in a separate module and are ActionType-catalog projections
  per R2 in
  [implementation-plan.md](../../../../docs/roadmap/fork-and-sequencing/implementation-plan.md).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from fdai.core.conversation.session import Principal, Role
from fdai.shared.contracts.models import OntologyActionType, Rule
from fdai.shared.providers.conversation_channel import ConversationActivity

SideEffectClass = Literal["read", "simulate", "approve", "execute", "breakglass"]


@dataclass(frozen=True)
class ToolResult:
    """Structured tool output.

    ``data`` is a JSON-serialisable payload the CLI or narrator can
    render verbatim. ``preview`` is the short human-readable line
    written into the audit trail. ``evidence_refs`` are audit ids /
    rule ids / PR urls the caller MUST cite verbatim.
    """

    status: Literal["ok", "error", "abstain"]
    data: Mapping[str, Any] = field(default_factory=dict)
    preview: str = ""
    evidence_refs: tuple[str, ...] = ()
    activities: tuple[ConversationActivity, ...] = ()


@dataclass(frozen=True)
class AbstainResult:
    """Sentinel: the intent matcher did not resolve to a tool.

    The coordinator MUST return this rather than fabricate a call. The
    CLI renders the tool inventory so the user can retry with an
    explicit verb.
    """

    reason: str
    tool_inventory: tuple[str, ...]


@runtime_checkable
class SystemConsoleTool(Protocol):
    """Read-only console tool contract.

    ``name`` is the verb the intent matcher looks for. ``rbac_floor`` is
    the lowest role that MAY invoke the tool (all five shipped tools
    default to :attr:`Role.READER`). ``call`` receives already-validated
    arguments and returns a :class:`ToolResult`.

    Kept **sync** on Day 1 because the shipped tools operate on
    in-memory catalogs; live-provider tools that ship in later waves
    will introduce an async variant of the Protocol so ``core/`` still
    holds only Protocols per the coding-conventions safety rules
    (see .github/instructions/coding-conventions.instructions.md).
    """

    name: str
    description: str
    rbac_floor: Role
    side_effect_class: SideEffectClass

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> ToolResult: ...


class ExploreCatalogTool:
    """Search the shipped rule + ActionType catalogs by keyword.

    Pure read: consumes the already-loaded ``rules`` and
    ``action_types`` tuples handed to it at construction. No I/O.

    Arguments (``arguments`` mapping):

    - ``query`` (str, required) - case-insensitive substring matched
      against rule id, ActionType id, category (severity /
      resource-type / operation), and description.
    - ``kind`` (str, optional) - one of ``rule`` / ``action_type`` /
      ``any``; default ``any``.
    - ``limit`` (int, optional) - default 10, capped at 50.

    Returns a :class:`ToolResult` whose ``data`` has two lists,
    ``rules`` and ``action_types``, each containing lightweight
    projections (id, category, resource_type, one-line summary).
    """

    name = "explore_catalog"
    description = (
        "Search the shipped rule catalog and action-type ontology by keyword; "
        "returns matched ids with severity, resource type, and a short summary."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(
        self,
        *,
        rules: Sequence[Rule],
        action_types: Sequence[OntologyActionType],
    ) -> None:
        self._rules = tuple(rules)
        self._action_types = tuple(action_types)

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> ToolResult:
        query = _require_str(arguments, "query").strip().lower()
        if not query:
            return ToolResult(
                status="error",
                preview="explore_catalog requires a non-empty 'query'.",
            )
        kind = _optional_str(arguments, "kind", default="any").lower()
        if kind not in ("rule", "action_type", "any"):
            return ToolResult(
                status="error",
                preview=f"explore_catalog 'kind' must be rule|action_type|any, got {kind!r}.",
            )
        limit = _optional_int(arguments, "limit", default=10, minimum=1, maximum=50)

        matched_rules: list[dict[str, Any]] = []
        if kind in ("rule", "any"):
            for rule in self._rules:
                if _rule_matches(rule, query):
                    matched_rules.append(
                        {
                            "id": rule.id,
                            "severity": _enum_value(rule.severity),
                            "resource_type": rule.resource_type,
                            "category": _enum_value(rule.category),
                            "remediates": getattr(rule, "remediates", ""),
                            "summary": _summary(_rule_summary(rule)),
                        }
                    )
                    if len(matched_rules) >= limit:
                        break

        matched_actions: list[dict[str, Any]] = []
        if kind in ("action_type", "any"):
            for at in self._action_types:
                if _action_matches(at, query):
                    matched_actions.append(
                        {
                            "id": at.name,
                            "category": (
                                at.category.value
                                if at.category and hasattr(at.category, "value")
                                else "remediation"
                            ),
                            "operation": (
                                at.operation.value
                                if hasattr(at.operation, "value")
                                else str(at.operation)
                            ),
                            "trigger_kind": (
                                at.trigger_kind.kind.value
                                if at.trigger_kind and hasattr(at.trigger_kind.kind, "value")
                                else "rule_violation"
                            ),
                            "summary": _summary(at.description or ""),
                        }
                    )
                    if len(matched_actions) >= limit:
                        break

        total = len(matched_rules) + len(matched_actions)
        preview = (
            f"explore_catalog[{query}]: {len(matched_rules)} rule(s), "
            f"{len(matched_actions)} action_type(s)"
        )
        evidence = tuple(f"rule:{r['id']}" for r in matched_rules) + tuple(
            f"action_type:{a['id']}" for a in matched_actions
        )
        return ToolResult(
            status="ok" if total > 0 else "abstain",
            data={
                "query": query,
                "kind": kind,
                "rules": matched_rules,
                "action_types": matched_actions,
            },
            preview=preview,
            evidence_refs=evidence,
        )


# ---------------------------------------------------------------------------
# argument-shape helpers - schema validation lands with the argument_schema
# projection in Wave W1; these give the Day-1 CLI a typed door without a
# JSON Schema evaluator dependency.
# ---------------------------------------------------------------------------


def _require_str(args: Mapping[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str):
        raise TypeError(f"argument {name!r} MUST be a string; got {type(value).__name__}")
    return value


def _optional_str(args: Mapping[str, Any], name: str, *, default: str) -> str:
    value = args.get(name, default)
    if not isinstance(value, str):
        raise TypeError(f"argument {name!r} MUST be a string; got {type(value).__name__}")
    return value


def _optional_int(
    args: Mapping[str, Any],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = args.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError(f"argument {name!r} MUST be an int; got {type(raw).__name__}")
    value = int(raw)
    if value < minimum or value > maximum:
        raise ValueError(f"argument {name!r} outside [{minimum},{maximum}]: {value}")
    return value


def _summary(text: str) -> str:
    line = " ".join((text or "").split())
    return line if len(line) <= 160 else line[:157] + "..."


def _rule_matches(rule: Rule, needle: str) -> bool:
    haystack_parts = [
        getattr(rule, "id", "") or "",
        getattr(rule, "resource_type", "") or "",
        _enum_value(getattr(rule, "category", "")),
        _enum_value(getattr(rule, "severity", "")),
        getattr(rule, "remediates", "") or "",
        _rule_summary(rule),
    ]
    return any(needle in part.lower() for part in haystack_parts)


def _action_matches(at: OntologyActionType, needle: str) -> bool:
    haystack_parts = [
        at.name or "",
        _enum_value(getattr(at, "operation", "")),
        at.description or "",
    ]
    return any(needle in part.lower() for part in haystack_parts)


def _rule_summary(rule: Rule) -> str:
    """Best-effort one-liner summary of a rule.

    :class:`Rule` has no `description` field of its own (see
    ``shared.contracts.models``); the closest human-readable hint is
    the ``remediation.template_ref`` name and the ``check_logic``
    reference. Both are safe to expose - they're catalog metadata,
    never secrets.
    """

    rem = getattr(rule, "remediation", None)
    template_ref = getattr(rem, "template_ref", "") if rem is not None else ""
    check = getattr(rule, "check_logic", None)
    check_ref = getattr(check, "reference", "") if check is not None else ""
    parts: list[str] = []
    if template_ref:
        parts.append(f"remediation={template_ref}")
    if check_ref:
        parts.append(f"policy={check_ref}")
    return " ".join(parts)


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


__all__ = [
    "AbstainResult",
    "ExploreCatalogTool",
    "SideEffectClass",
    "SystemConsoleTool",
    "ToolResult",
]
