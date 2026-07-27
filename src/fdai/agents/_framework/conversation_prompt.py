"""Situational composition of a pantheon agent's conversational prompt.

The charter in :mod:`fdai.agents._framework.pantheon` carries the
**baseline** prompt: the eleven server-owned layers every agent always
runs with (identity, mandate, authority, grounding, epistemics, human
dialogue, peer protocol, disagreement, tiering, security, and the
agent's own role directive). One static string cannot serve every turn
though - an operator asking in Korean, a peer agent asking through the
A2A port, a critique round inside a bounded deliberation, and a
fact-scoped tool call are different situations that need different
instructions.

This module composes the prompt **per turn** from that baseline plus
situational layers.

Two invariants keep the dynamic path inside the conversational-port
contract (``agent-pantheon.md`` 6.2):

1. **Additive only.** A situation MAY add a constraint; it can never
   drop or rewrite a baseline layer. Every composed prompt is therefore
   a superset of the baseline, so no situation can weaken an authority,
   grounding, or security instruction, and the charter stays the
   immutable floor.
2. **Server-owned text.** :class:`ConversationSituation` is parsed from
   an untrusted turn context, but that context only *selects* layers -
   it never supplies prompt text. Free-form values are dropped or
   reduced to a bounded identifier before they reach a layer, so a
   forged context cannot inject instructions.

Composition is pure and deterministic: the same baseline plus the same
situation always yields the same text and the same ``prompt_sha256``, so
a recorded turn replays exactly.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

#: Hard bound on the immutable charter baseline - the contract every turn
#: starts from. Kept tight so the floor stays readable and cheap.
MAX_CHARTER_PROMPT_CHARS: Final[int] = 4_096

#: Hard bound on one composed prompt. Larger than the charter bound because
#: composition adds situational layers on top of it, but still fixed, so a
#: turn's prompt cost can never grow without limit.
MAX_COMPOSED_PROMPT_CHARS: Final[int] = 6_144

#: Budget the situational layers share. Deliberately tighter than the sum
#: of every layer: the same economy the escalation budget applies to model
#: calls applies to the prompt itself, so an unusual situation sheds
#: presentation framing rather than paying for all of it at once. The
#: priority order decides what survives; the baseline never pays.
MAX_SITUATIONAL_PROMPT_CHARS: Final[int] = 1_024

#: Bound on an agent's role directive (the eleventh baseline layer).
MAX_ROLE_DIRECTIVE_CHARS: Final[int] = 640

#: Ordered ids of the baseline layers built in ``pantheon.py``. Kept here
#: so a composed manifest can name every layer, not only the added ones.
BASELINE_LAYER_IDS: Final[tuple[str, ...]] = (
    "identity",
    "mandate",
    "authority",
    "grounding",
    "epistemics",
    "human_dialogue",
    "peer_protocol",
    "handoff",
    "disagreement",
    "tiering",
    "economy",
    "security_output",
    "role",
)

#: Locales the conversational port composes for. English is the default
#: and adds no layer; anything outside the allowlist degrades to English
#: rather than being echoed into the prompt.
SUPPORTED_LOCALES: Final[frozenset[str]] = frozenset({"en", "ko"})

_LOCALE_NAMES: Final[Mapping[str, str]] = {"ko": "Korean"}

_AUDIENCE_OPERATOR: Final[str] = "operator"
_AUDIENCE_PEER: Final[str] = "peer"

_PHASE_DIRECT: Final[str] = "direct"
_KNOWN_PHASES: Final[frozenset[str]] = frozenset({_PHASE_DIRECT, "position", "critique"})
_KNOWN_TIERS: Final[frozenset[str]] = frozenset({"T0", "T1", "T2"})

_AGENT_NAME = re.compile(r"^[A-Z][a-z]{1,15}$")
_TOOL_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_LOCALE_TAG = re.compile(r"^[A-Za-z]{2}(?:-[A-Za-z0-9]{2,8})?$")

#: Upper bound on the escalation counters a situation may carry, so a
#: malformed runtime value cannot render an unbounded number.
_MAX_ESCALATION_COUNT: Final[int] = 1_000_000


@dataclass(frozen=True, slots=True)
class PromptLayer:
    """One addressable prompt layer: a stable id plus server-owned text."""

    id: str
    text: str


@dataclass(frozen=True, slots=True)
class ConversationSituation:
    """The bounded, sanitized facts that select situational layers.

    Built with :meth:`from_context` from a turn context that may be
    partly caller-supplied. Every field is a closed enum, a boolean, or
    an identifier validated against a strict pattern, so the situation
    can never carry attacker-controlled prose into the prompt.
    """

    audience: str = _AUDIENCE_OPERATOR
    phase: str = _PHASE_DIRECT
    tier: str = "T0"
    locale: str = "en"
    requester: str | None = None
    tool_id: str | None = None
    tool_fact_keys: tuple[str, ...] = ()
    evidence_available: bool = True
    action_intent: bool = False
    escalation_available: bool = True
    escalation_spent: int = 0
    escalation_limit: int = 0
    handoff_owner: str | None = None

    def __post_init__(self) -> None:
        if self.audience not in {_AUDIENCE_OPERATOR, _AUDIENCE_PEER}:
            raise ValueError("conversation audience MUST be operator or peer")
        if self.phase not in _KNOWN_PHASES:
            raise ValueError("conversation phase MUST be direct, position, or critique")
        if self.tier not in _KNOWN_TIERS:
            raise ValueError("conversation tier MUST be T0, T1, or T2")
        if self.locale not in SUPPORTED_LOCALES:
            raise ValueError("conversation locale MUST be a supported locale")
        if self.requester is not None and _AGENT_NAME.fullmatch(self.requester) is None:
            raise ValueError("conversation requester MUST be a bounded agent name")
        if self.handoff_owner is not None and _AGENT_NAME.fullmatch(self.handoff_owner) is None:
            raise ValueError("conversation handoff owner MUST be a bounded agent name")
        if self.tool_id is not None and _TOOL_ID.fullmatch(self.tool_id) is None:
            raise ValueError("conversation tool id MUST be a bounded ASCII identifier")
        if not 0 <= self.escalation_spent <= _MAX_ESCALATION_COUNT:
            raise ValueError("conversation escalation_spent MUST be a bounded count")
        if not 0 <= self.escalation_limit <= _MAX_ESCALATION_COUNT:
            raise ValueError("conversation escalation_limit MUST be a bounded count")

    @classmethod
    def baseline(cls) -> ConversationSituation:
        """Return the situation whose composition equals the charter baseline."""
        return cls()

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
        *,
        allowed_tools: Sequence[str] = (),
        tool_fact_keys: Sequence[str] = (),
        action_intent: bool = False,
        evidence_available: bool = True,
    ) -> ConversationSituation:
        """Derive a situation from an untrusted turn context.

        Unknown, malformed, or oversized values fall back to the
        baseline value instead of raising: a conversational turn MUST
        NOT fail because a caller sent an odd hint, and the baseline is
        always the safe answer.
        """
        raw_phase = context.get("deliberation_phase")
        raw_tier = context.get("deliberation_tier")
        raw_requester = context.get("requester")
        raw_owner = context.get("handoff_owner")
        raw_tool = context.get("conversation_tool")
        tool_id = raw_tool if isinstance(raw_tool, str) and raw_tool in set(allowed_tools) else None
        return cls(
            audience=_AUDIENCE_PEER if context.get("a2a") is True else _AUDIENCE_OPERATOR,
            # A phase exists only inside a deliberation; a peer request
            # without one is a plain A2A introspection.
            phase=raw_phase
            if isinstance(raw_phase, str) and raw_phase in _KNOWN_PHASES
            else _PHASE_DIRECT,
            tier=raw_tier if isinstance(raw_tier, str) and raw_tier in _KNOWN_TIERS else "T0",
            locale=_normalize_locale(context.get("locale")),
            requester=(
                raw_requester
                if isinstance(raw_requester, str) and _AGENT_NAME.fullmatch(raw_requester)
                else None
            ),
            tool_id=tool_id,
            tool_fact_keys=tuple(tool_fact_keys) if tool_id is not None else (),
            evidence_available=evidence_available,
            action_intent=action_intent,
            # Absence means "not stated", which MUST NOT read as "denied":
            # only an explicit False from the runtime closes escalation.
            escalation_available=context.get("escalation_available") is not False,
            escalation_spent=_bounded_count(context.get("escalation_spent")),
            escalation_limit=_bounded_count(context.get("escalation_limit")),
            handoff_owner=(
                raw_owner
                if isinstance(raw_owner, str) and _AGENT_NAME.fullmatch(raw_owner)
                else None
            ),
        )

    @property
    def key(self) -> str:
        """Return a stable, bounded audit key for this situation."""
        parts = [
            f"audience={self.audience}",
            f"phase={self.phase}",
            f"tier={self.tier}",
            f"locale={self.locale}",
            f"evidence={'present' if self.evidence_available else 'absent'}",
            f"escalation={'available' if self.escalation_available else 'denied'}",
        ]
        if self.handoff_owner is not None:
            parts.append(f"handoff={self.handoff_owner}")
        if self.tool_id is not None:
            parts.append(f"tool={self.tool_id}")
        if self.action_intent:
            parts.append("intent=action")
        return ";".join(parts)


@dataclass(frozen=True, slots=True)
class ComposedConversationPrompt:
    """One composed prompt plus the provenance needed to replay it."""

    text: str
    layer_ids: tuple[str, ...]
    dropped_layer_ids: tuple[str, ...]
    situation_key: str

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def attribution(self) -> dict[str, Any]:
        """Return the public, text-free provenance for this composition.

        Mirrors the charter attribution rule in ``agent-pantheon.md``
        6.2: a caller learns which layers ran and their digest, never
        the instructions themselves.
        """
        return {
            "situation": self.situation_key,
            "layers": list(self.layer_ids),
            "dropped_layers": list(self.dropped_layer_ids),
            "prompt_sha256": self.prompt_sha256,
        }


def compose_conversation_prompt(
    *,
    baseline_prompt: str,
    situation: ConversationSituation,
) -> ComposedConversationPrompt:
    """Compose one turn's prompt from the baseline plus situational layers.

    The baseline is never rewritten or reordered; situational layers are
    appended in a fixed order. When the result would exceed
    :data:`MAX_COMPOSED_PROMPT_CHARS`, the least important situational
    layers are dropped - deterministically, and recorded in
    ``dropped_layer_ids``. The baseline is never trimmed, because that is
    where the authority, grounding, and security instructions live.
    """
    if not baseline_prompt.strip():
        raise ValueError("baseline conversation prompt MUST be non-empty")
    if len(baseline_prompt) > MAX_CHARTER_PROMPT_CHARS:
        raise ValueError("baseline conversation prompt MUST fit the charter budget")
    kept, dropped = _fit_budget(
        _situational_layers(situation),
        min(
            MAX_SITUATIONAL_PROMPT_CHARS,
            MAX_COMPOSED_PROMPT_CHARS - len(baseline_prompt),
        ),
    )
    return ComposedConversationPrompt(
        text="\n".join([baseline_prompt, *(layer.text for _, layer in kept)]),
        layer_ids=BASELINE_LAYER_IDS + tuple(layer.id for _, layer in kept),
        dropped_layer_ids=tuple(layer.id for _, layer in dropped),
        situation_key=situation.key,
    )


def _situational_layers(
    situation: ConversationSituation,
) -> tuple[tuple[int, PromptLayer], ...]:
    """Return ``(priority, layer)`` pairs in render order (1 = keep first)."""
    layers: list[tuple[int, PromptLayer]] = []
    if situation.audience == _AUDIENCE_PEER:
        requester = (
            f"agent {situation.requester}" if situation.requester else "another pantheon agent"
        )
        layers.append(
            (
                5,
                PromptLayer(
                    "audience_peer",
                    (
                        f"Peer request: {requester} is asking through the agent-to-agent port, "
                        "not a human operator. Lead with owned facts and evidence refs, drop "
                        "operator-facing narration, and keep the requester and correlation "
                        "trace intact."
                    ),
                ),
            )
        )
    if situation.phase == "position":
        layers.append(
            (
                6,
                PromptLayer(
                    "phase_position",
                    (
                        "Position round: state your own grounded position first. Do not "
                        "summarize, anticipate, or speak for the peers who answer after you."
                    ),
                ),
            )
        )
    elif situation.phase == "critique":
        layers.append(
            (
                6,
                PromptLayer(
                    "phase_critique",
                    (
                        "Critique round: address each peer claim explicitly, challenge it only "
                        "with owned counterevidence, concede when the peer evidence is stronger, "
                        "and leave unresolved disagreement standing instead of settling it."
                    ),
                ),
            )
        )
    if situation.tier == "T2":
        layers.append(
            (
                7,
                PromptLayer(
                    "tier_t2",
                    (
                        "T2 round: synthesis is bounded and presentation-only. Introduce no new "
                        "facts, restate no typed verdict as your own decision, and attribute "
                        "every synthesized claim to the agent that owns it."
                    ),
                ),
            )
        )
    if situation.tool_id is not None:
        fact_keys = ", ".join(situation.tool_fact_keys) or "the tool's declared facts"
        layers.append(
            (
                2,
                PromptLayer(
                    "tool_scope",
                    (
                        f"Tool scope: this turn runs through {situation.tool_id}. Answer only "
                        f"from these owned facts: {fact_keys}. Abstain with a scope reason when "
                        "the answer would need anything outside them."
                    ),
                ),
            )
        )
    if not situation.evidence_available:
        layers.append(
            (
                3,
                PromptLayer(
                    "evidence_gap",
                    (
                        "Evidence gap: no owned evidence is bound to this turn. Say so plainly, "
                        "name the evidence you would need, and abstain instead of reasoning "
                        "from general knowledge."
                    ),
                ),
            )
        )
    if situation.action_intent:
        layers.append(
            (
                1,
                PromptLayer(
                    "action_intent",
                    (
                        "Command intent: this request reads as an instruction to change "
                        "something. Do not act and do not promise to act. Explain the typed "
                        "pipeline path instead, and name the owning agent and the approval step."
                    ),
                ),
            )
        )
    if not situation.escalation_available:
        # The economy layer tells the agent to state the bound, so the bound
        # has to reach it. Rendered from the runtime's own counters when it
        # supplied them, never from a number the agent has to guess.
        bound = (
            f" ({situation.escalation_spent} of {situation.escalation_limit} "
            "model call(s) already spent for this correlation)"
            if situation.escalation_limit
            else ""
        )
        layers.append(
            (
                2,
                PromptLayer(
                    "budget_denied",
                    (
                        f"Escalation budget: the pre-declared budget leaves no model "
                        f"escalation for this turn{bound}. Answer from owned facts and "
                        "allowed tools only, and say plainly that the deeper pass was not "
                        "run rather than implying it was."
                    ),
                ),
            )
        )
    if situation.handoff_owner is not None:
        layers.append(
            (
                3,
                PromptLayer(
                    "handoff_pending",
                    (
                        f"Handoff in progress: {situation.handoff_owner} owns this request. "
                        "Contribute only your owned evidence and hand the conclusion back to "
                        "that owner; do not restate their answer as your own."
                    ),
                ),
            )
        )
    if situation.locale != "en":
        language = _LOCALE_NAMES.get(situation.locale, situation.locale)
        layers.append(
            (
                4,
                PromptLayer(
                    f"locale_{situation.locale}",
                    (
                        f"Locale: answer in {language}. Keep identifiers, resource ids, action "
                        "types, rule ids, and machine keys in ASCII exactly as stored."
                    ),
                ),
            )
        )
    return tuple(layers)


def _fit_budget(
    layers: Sequence[tuple[int, PromptLayer]],
    budget: int,
) -> tuple[tuple[tuple[int, PromptLayer], ...], tuple[tuple[int, PromptLayer], ...]]:
    """Drop the least important layers until the addition fits ``budget``.

    Deterministic: candidates are dropped by descending priority value,
    ties broken by reverse render order, so the same overflow always
    yields the same kept set.
    """
    kept = list(layers)
    dropped: list[tuple[int, PromptLayer]] = []
    while kept and _rendered_length(kept) > budget:
        victim = max(enumerate(kept), key=lambda item: (item[1][0], item[0]))[0]
        dropped.append(kept.pop(victim))
    return tuple(kept), tuple(dropped)


def _rendered_length(layers: Sequence[tuple[int, PromptLayer]]) -> int:
    """Return the characters a layer set adds, including its join newlines."""
    return sum(len(layer.text) + 1 for _, layer in layers)


def _normalize_locale(raw: Any) -> str:
    """Reduce an untrusted locale hint to a supported locale tag."""
    if not isinstance(raw, str) or _LOCALE_TAG.fullmatch(raw) is None:
        return "en"
    primary = raw.split("-", 1)[0].casefold()
    return primary if primary in SUPPORTED_LOCALES else "en"


def _bounded_count(raw: Any) -> int:
    """Reduce an untrusted counter to a bounded non-negative integer."""
    if not isinstance(raw, int) or isinstance(raw, bool):
        return 0
    return max(0, min(raw, _MAX_ESCALATION_COUNT))


__all__ = [
    "BASELINE_LAYER_IDS",
    "MAX_CHARTER_PROMPT_CHARS",
    "MAX_COMPOSED_PROMPT_CHARS",
    "MAX_ROLE_DIRECTIVE_CHARS",
    "MAX_SITUATIONAL_PROMPT_CHARS",
    "SUPPORTED_LOCALES",
    "ComposedConversationPrompt",
    "ConversationSituation",
    "PromptLayer",
    "compose_conversation_prompt",
]
