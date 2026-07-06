"""Conversation coordinator - Layer 2 orchestrator.

Implements the deterministic Chat T0 layer described in
[operator-console.md § 4.1](../../../../docs/roadmap/operator-console.md).
A regex / keyword intent matcher that dispatches direct-hit tool calls
without invoking an LLM. The narrator (Chat T1 / T2) is a follow-up
wave; a fork that binds a :class:`ConversationalModel` gets the
escalation path per operator-console.md § 4.2.

Design invariants enforced here:

- **The coordinator NEVER fabricates a tool call.** When no Chat T0
  pattern matches with confidence >= threshold, ``handle_turn`` returns
  an :class:`AbstainResult` and the CLI prints the tool inventory.
- **RBAC floor is applied before the tool is invoked.** A principal
  under the tool's ``rbac_floor`` receives an abstain reason naming
  the missing role, not the tool's failure surface.
- **Sync now, async-ready.** Every tool is called synchronously at
  Day 1 because :class:`ExploreCatalogTool` is pure Python over an
  in-memory catalog. Live-provider tools that need an event loop (T0
  in-memory execution, StateStore query) land with an async variant of
  the Protocol; the coordinator gains a parallel ``handle_turn_async``.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from aiopspilot.core.conversation.session import (
    ConversationSession,
    Principal,
    Turn,
    principal_has_role_at_least,
)
from aiopspilot.core.conversation.tools import (
    AbstainResult,
    SystemConsoleTool,
    ToolResult,
)


@dataclass(frozen=True)
class CoordinatorConfig:
    """Coordinator tuning knobs.

    ``chat_t0_confidence_threshold`` is the score below which an
    intent match is treated as a miss and the turn abstains. Defaults
    to 0.75 - a compromise: exact-verb matches score 1.0, keyword
    hits ~0.85, fuzzy hits ~0.6 and are rejected.
    """

    chat_t0_confidence_threshold: float = 0.75


@dataclass(frozen=True)
class _IntentMatch:
    """Result of the Chat T0 intent matcher."""

    tool_name: str
    arguments: dict[str, Any]
    confidence: float


_VERB_PATTERNS: tuple[tuple[str, str], ...] = (
    # Explicit verb + argument. Anchored so an accidental substring
    # never triggers the tool (e.g. "explore_catalogue" would not match
    # "explore_catalog" without the word boundary).
    (r"^\s*(?P<verb>explore[_\s-]?catalog(?:ue)?)\b\s*(?P<rest>.*)$", "explore_catalog"),
    (r"^\s*(?P<verb>search[_\s-]?catalog)\b\s*(?P<rest>.*)$", "explore_catalog"),
    (r"^\s*(?P<verb>list[_\s-]?rules?)\b\s*(?P<rest>.*)$", "explore_catalog"),
    # describe_event: describe_event <resource_type> <resource_id>
    (r"^\s*(?P<verb>describe[_\s-]?event)\b\s*(?P<rest>.*)$", "describe_event"),
    # explain_verdict: explain_verdict <event_id>
    (r"^\s*(?P<verb>explain[_\s-]?verdict)\b\s*(?P<rest>.*)$", "explain_verdict"),
    (r"^\s*(?P<verb>why[_\s-]?abstained?)\b\s*(?P<rest>.*)$", "explain_verdict"),
    # query_audit: query_audit key=value ...
    (r"^\s*(?P<verb>query[_\s-]?audit)\b\s*(?P<rest>.*)$", "query_audit"),
    (r"^\s*(?P<verb>audit[_\s-]?log)\b\s*(?P<rest>.*)$", "query_audit"),
    # query_inventory: query_inventory <resource_type> [substring]
    (r"^\s*(?P<verb>query[_\s-]?inventory)\b\s*(?P<rest>.*)$", "query_inventory"),
    (r"^\s*(?P<verb>list[_\s-]?resources)\b\s*(?P<rest>.*)$", "query_inventory"),
    # simulate_change: simulate_change <JSON scenario>
    #   Anchored BEFORE the more specific approve_hil so a stray
    #   "simulate" verb never falls through.
    (r"^\s*(?P<verb>simulate[_\s-]?change)\b\s*(?P<rest>.*)$", "simulate_change"),
    (r"^\s*(?P<verb>what[_\s-]?if)\b\s*(?P<rest>.*)$", "simulate_change"),
    # list_hil: list_hil [limit=N]
    (r"^\s*(?P<verb>list[_\s-]?hil)\b\s*(?P<rest>.*)$", "list_hil"),
    (r"^\s*(?P<verb>pending[_\s-]?approvals)\b\s*(?P<rest>.*)$", "list_hil"),
    # approve_hil: approve_hil idempotency_key=... decision=approve|reject
    (r"^\s*(?P<verb>approve[_\s-]?hil)\b\s*(?P<rest>.*)$", "approve_hil"),
    (r"^\s*(?P<verb>resolve[_\s-]?hil)\b\s*(?P<rest>.*)$", "approve_hil"),
    # run_runbook: run_runbook name=... [dry_run=true|false] [params_json=...]
    (r"^\s*(?P<verb>run[_\s-]?runbook)\b\s*(?P<rest>.*)$", "run_runbook"),
    # activate_break_glass: activate_break_glass reason="..." expiry_seconds=N
    (
        r"^\s*(?P<verb>activate[_\s-]?break[_\s-]?glass)\b\s*(?P<rest>.*)$",
        "activate_break_glass",
    ),
    (r"^\s*(?P<verb>break[_\s-]?glass)\b\s*(?P<rest>.*)$", "activate_break_glass"),
)


def _extract_query(rest: str) -> str:
    """Trim quotes, punctuation, and boilerplate stopwords."""

    text = rest.strip()
    if not text:
        return ""
    # Common leading tokens the user might type: for / about / matching.
    text = re.sub(r"^(?:for|about|matching|by|containing)\s+", "", text, flags=re.I)
    # Strip surrounding quotes.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1]
    return text.strip()


class ConversationCoordinator:
    """Route one conversation turn to zero or one tool call.

    The coordinator is stateless with respect to conversation memory;
    per-turn append onto :class:`ConversationSession.turns` is
    performed by ``handle_turn``. All tool lookups are O(N) over the
    installed tool set - a few dozen entries is the expected upper
    bound.
    """

    def __init__(
        self,
        *,
        tools: Sequence[SystemConsoleTool],
        config: CoordinatorConfig | None = None,
    ) -> None:
        self._tools: dict[str, SystemConsoleTool] = {tool.name: tool for tool in tools}
        if not self._tools:
            raise ValueError("ConversationCoordinator MUST have at least one tool")
        self._config = config or CoordinatorConfig()

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def list_tools_for(self, principal: Principal) -> tuple[str, ...]:
        """Tool names the ``principal``'s role satisfies the floor for."""

        return tuple(
            name
            for name, tool in sorted(self._tools.items())
            if principal_has_role_at_least(principal.role, tool.rbac_floor)
        )

    def handle_turn(
        self,
        *,
        session: ConversationSession,
        message: str,
    ) -> ToolResult | AbstainResult:
        """Handle one operator utterance.

        Appends inbound + result turns onto ``session.turns`` regardless
        of outcome. Never raises for a user-caused mistake (unknown
        verb, bad argument shape); returns a structured
        :class:`ToolResult` or :class:`AbstainResult` instead.
        """

        inbound = Turn(
            turn_id=str(uuid.uuid4()),
            direction="inbound",
            content=message,
            tier="T0",
        )
        session.append(inbound)

        match = self._match_intent(message)
        if match is None or match.confidence < self._config.chat_t0_confidence_threshold:
            visible = self.list_tools_for(session.principal)
            abstain = AbstainResult(
                reason=(
                    "no chat_t0 intent match; try one of the listed verbs"
                    if match is None
                    else f"chat_t0 intent match confidence={match.confidence:.2f} below threshold"
                ),
                tool_inventory=visible,
            )
            session.append(
                Turn(
                    turn_id=str(uuid.uuid4()),
                    direction="system",
                    content=abstain.reason,
                    tier="T0",
                )
            )
            return abstain

        tool = self._tools.get(match.tool_name)
        if tool is None:
            # Should not happen - intent matcher can only name registered tools.
            raise KeyError(f"intent matched an unregistered tool: {match.tool_name!r}")

        if not principal_has_role_at_least(session.principal.role, tool.rbac_floor):
            preview = (
                f"role {session.principal.role.value!r} is below tool "
                f"{tool.name!r} floor {tool.rbac_floor.value!r}"
            )
            session.append(
                Turn(
                    turn_id=str(uuid.uuid4()),
                    direction="system",
                    content=preview,
                    tier="T0",
                )
            )
            return ToolResult(status="error", preview=preview)

        tool_call_turn = Turn(
            turn_id=str(uuid.uuid4()),
            direction="tool_call",
            content=tool.name,
            tool_name=tool.name,
            arguments=match.arguments,
            tier="T0",
        )
        session.append(tool_call_turn)

        try:
            result = tool.call(arguments=match.arguments, principal=session.principal)
        except (TypeError, ValueError) as exc:
            preview = f"tool {tool.name!r} rejected arguments: {exc}"
            session.append(
                Turn(
                    turn_id=str(uuid.uuid4()),
                    direction="tool_result",
                    content=preview,
                    tool_name=tool.name,
                    tier="T0",
                )
            )
            return ToolResult(status="error", preview=preview)

        session.append(
            Turn(
                turn_id=str(uuid.uuid4()),
                direction="tool_result",
                content=result.preview,
                tool_name=tool.name,
                result_preview=result.preview,
                tier="T0",
            )
        )
        return result

    def _match_intent(self, message: str) -> _IntentMatch | None:
        """Regex-first, case-insensitive.

        Confidence heuristic:

        - exact verb prefix + non-empty argument -> 1.0
        - exact verb prefix, empty argument -> 0.85
        - fuzzy verb (missing hyphen / space) -> 0.8
        """

        text = message.strip()
        if not text:
            return None

        for pattern, tool_name in _VERB_PATTERNS:
            m = re.match(pattern, text, flags=re.IGNORECASE)
            if not m:
                continue
            verb = m.group("verb")
            rest = m.group("rest") if "rest" in (m.groupdict() or {}) else ""
            query = _extract_query(rest)
            arguments: dict[str, Any] = _extract_tool_arguments(tool_name, query)
            confidence = 1.0 if query else 0.85
            if _has_fuzzy_verb(verb):
                confidence = min(confidence, 0.8)
            return _IntentMatch(
                tool_name=tool_name,
                arguments=arguments,
                confidence=confidence,
            )

        return None


def _extract_tool_arguments(tool_name: str, query: str) -> dict[str, Any]:
    """Map the raw ``query`` string onto per-tool argument shape.

    Every branch takes the same ``query`` (already trimmed) and turns
    it into the argument dict the tool expects. Missing pieces are
    left absent; the tool returns an ``error`` :class:`ToolResult`
    when a required argument is empty.
    """

    if tool_name == "explore_catalog":
        return {"query": query} if query else {"query": ""}
    if tool_name == "describe_event":
        # Two positional tokens: resource_type resource_id (rest is
        # ignored). "key=value" tokens override.
        args: dict[str, Any] = _parse_kv_tokens(query)
        positional = [tok for tok in query.split() if "=" not in tok]
        if "resource_type" not in args and len(positional) >= 1:
            args["resource_type"] = positional[0]
        if "resource_id" not in args and len(positional) >= 2:
            args["resource_id"] = positional[1]
        # An operator can pass '{...}' JSON as resource_props.
        return args
    if tool_name == "explain_verdict":
        return {"event_id": query}
    if tool_name == "query_audit":
        return _parse_kv_tokens(query)
    if tool_name == "query_inventory":
        args = _parse_kv_tokens(query)
        positional = [tok for tok in query.split() if "=" not in tok]
        if "resource_type" not in args and positional:
            args["resource_type"] = positional[0]
        if "id_substring" not in args and len(positional) >= 2:
            args["id_substring"] = positional[1]
        return args
    if tool_name == "simulate_change":
        # Accept a JSON-shaped scenario ("simulate_change {...}") OR
        # key=value tokens whose values compose into ``scenario``
        # (e.g. ``resource_type=object-storage resource_id=x``).
        args = {}
        stripped = query.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            import json as _json

            try:
                scenario = _json.loads(stripped)
                if isinstance(scenario, dict):
                    return {"scenario": scenario}
            except _json.JSONDecodeError:
                # Fall through to the kv-token path so the tool's own
                # validator surfaces a useful error.
                pass
        kv = _parse_kv_tokens(query)
        if kv:
            scenario_dict: dict[str, Any] = {
                k: v for k, v in kv.items() if k not in ("signal_type",)
            }
            if scenario_dict:
                args["scenario"] = scenario_dict
            if "signal_type" in kv:
                args["signal_type"] = kv["signal_type"]
        return args
    if tool_name == "list_hil":
        args = _parse_kv_tokens(query)
        # Coerce limit to int; tool clamps [1, 100].
        if "limit" in args:
            try:
                args["limit"] = int(args["limit"])
            except (TypeError, ValueError):
                # Leave as-is; the tool returns error.
                pass
        return args
    if tool_name == "approve_hil":
        args = _parse_kv_tokens(query)
        positional = [tok for tok in query.split() if "=" not in tok]
        # Positional shorthand: "approve_hil <ik> approve|reject [justification words...]".
        if "idempotency_key" not in args and positional:
            args["idempotency_key"] = positional[0]
        if "decision" not in args and len(positional) >= 2:
            args["decision"] = positional[1]
        if "justification" not in args and len(positional) >= 3:
            args["justification"] = " ".join(positional[2:])
        return args
    if tool_name == "run_runbook":
        args = _parse_kv_tokens(query)
        positional = [tok for tok in query.split() if "=" not in tok]
        if "name" not in args and positional:
            args["name"] = positional[0]
        if "dry_run" in args:
            raw = str(args["dry_run"]).lower()
            args["dry_run"] = raw in ("true", "1", "yes", "y")
        if "params_json" in args:
            import json as _json

            try:
                loaded = _json.loads(args.pop("params_json"))
                if isinstance(loaded, dict):
                    args["params"] = loaded
            except _json.JSONDecodeError:
                # Leave params absent; tool will accept default {}.
                pass
        return args
    if tool_name == "activate_break_glass":
        args = _parse_kv_tokens(query)
        if "expiry_seconds" in args:
            try:
                args["expiry_seconds"] = int(args["expiry_seconds"])
            except (TypeError, ValueError):
                pass
        # If no reason came through kv-tokens, accept the whole query
        # as the reason (natural-language friendly).
        if "reason" not in args and query.strip():
            # Strip any k=v tokens so we do not double-count them.
            leftover = " ".join(tok for tok in query.split() if "=" not in tok)
            if leftover:
                args["reason"] = leftover
        return args
    return {}


def _parse_kv_tokens(query: str) -> dict[str, Any]:
    """Parse whitespace-separated ``key=value`` tokens.

    Values may be quoted. Unknown escapes are preserved verbatim. Only
    the first '=' in a token is used as the separator so a value can
    contain '='.
    """

    result: dict[str, Any] = {}
    for tok in query.split():
        if "=" not in tok:
            continue
        key, _, value = tok.partition("=")
        key = key.strip()
        if not key:
            continue
        v = value.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in {'"', "'"}:
            v = v[1:-1]
        result[key] = v
    return result


def _has_fuzzy_verb(verb: str) -> bool:
    """True if the verb needed normalisation (missing hyphen / space).

    The verb 'explore_catalog' is canonical; 'explore catalog' and
    'explore-catalog' are accepted with slightly lower confidence.
    """

    return "_" not in verb


__all__ = [
    "ConversationCoordinator",
    "CoordinatorConfig",
]
