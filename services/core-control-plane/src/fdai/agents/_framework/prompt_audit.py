"""Project Pantheon charter structure into a stable 30-point diagnostic."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.agents._framework.base import AgentSpec


@dataclass(frozen=True, slots=True)
class PromptAuditItem:
    item_id: int
    name: str
    passed: bool


@dataclass(frozen=True, slots=True)
class PromptAuditResult:
    agent: str
    score: int
    items: tuple[PromptAuditItem, ...]
    prompt_sha256: str


def audit_agent_prompt(spec: AgentSpec) -> PromptAuditResult:
    """Evaluate one immutable charter without invoking a model."""

    prompt = spec.conversation.system_prompt.casefold()
    checks = (
        ("canonical_identity", prompt.startswith(f"you are {spec.name.casefold()},")),
        (
            "positive_mandate",
            spec.conversation.system_prompt.splitlines()[1].startswith("Mandate: "),
        ),
        ("fixed_roster", "fixed operational agents" in prompt),
        ("role_contract", spec.role_contract() in spec.conversation.system_prompt),
        ("authority_boundary", "authority boundary:" in prompt),
        ("typed_authority", "typed pipeline remains authoritative" in prompt),
        ("read_only_port", "conversational port is read-only" in prompt),
        ("declared_tools", all(tool in prompt for tool in spec.conversation.tools)),
        ("evidence_refs", "evidence refs for every material claim" in prompt),
        ("epistemic_split", "facts, inferences, and unknowns" in prompt),
        ("insufficient_evidence", "abstain when evidence is insufficient" in prompt),
        ("counterevidence", "counterevidence" in prompt),
        ("operator_locale", "operator's locale" in prompt),
        ("minimal_clarification", "minimum missing scope" in prompt),
        ("peer_discussion", "peer discussion" in prompt),
        ("requester_attribution", "requester" in prompt),
        ("correlation_trace", "correlation trace" in prompt),
        ("owner_handoff", "to that owner by name" in prompt),
        ("deterministic_handoff", "deterministic and needs no model" in prompt),
        ("no_impersonation", "never answer in the owner's name" in prompt),
        ("claim_challenge", "challenge peer claims" in prompt),
        ("conflict_preservation", "never average conflicts" in prompt),
        ("t1_selection", "t1 semantic routing" in prompt),
        ("t2_boundary", "t2 synthesis is optional, bounded, and presentation-only" in prompt),
        ("owned_facts_first", "owned facts first" in prompt),
        ("model_last_resort", "last resort" in prompt),
        ("declared_budget", "pre-declared budget" in prompt),
        ("untrusted_content", 'trusted="false"' in prompt),
        ("sensitive_output", "sensitive values" in prompt),
        ("hidden_prompt_secrecy", "do not reveal this prompt" in prompt),
    )
    items = tuple(
        PromptAuditItem(item_id=index, name=name, passed=passed)
        for index, (name, passed) in enumerate(checks, start=1)
    )
    policy = spec.conversation_policy()
    return PromptAuditResult(
        agent=spec.name,
        score=sum(item.passed for item in items),
        items=items,
        prompt_sha256=str(policy["prompt_sha256"]),
    )


__all__ = ["PromptAuditItem", "PromptAuditResult", "audit_agent_prompt"]
