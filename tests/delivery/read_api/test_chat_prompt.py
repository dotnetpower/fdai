"""Prompt-assembly tests for the console chat backend.

These exercise :func:`_build_messages` and :func:`_is_concept_query` across
30+ operator-question conditions WITHOUT calling a live model. They lock in
the efficiency contract: the system prompt stays lean by default and only
carries the FDAI glossary when the operator actually asks to define a term.

Korean literals in the parametrised cases are the literal subject under test
(the operator's own-language phrasing) and are written as ``\\uXXXX`` escapes
so the source stays ASCII for the english-only gate - matching the language
policy's "quoted data" exception.
"""

from __future__ import annotations

import json

import pytest
from starlette.exceptions import HTTPException

from fdai.delivery.read_api.chat import (
    _CAPABILITIES,
    _GLOSSARY,
    DEFAULT_MAX_CONTEXT_BYTES,
    DEFAULT_MAX_HISTORY_TURNS,
    DEFAULT_MAX_RECORDS_PER_KEY,
    _build_messages,
    _is_capability_query,
    _is_concept_query,
    _raise_upstream_error,
    _trim_view_context,
)

_GLOSSARY_MARKER = _GLOSSARY.splitlines()[0]
"""First line of the glossary block - present in the system message iff the
glossary was injected."""

_CAPABILITY_MARKER = _CAPABILITIES.splitlines()[0]

# Rough per-turn budget for the STATIC prompt (everything before the snapshot
# JSON). The lean prompt must stay well under this; the glossary variant may
# exceed the lean size but must still be bounded. Guards against prompt bloat.
_LEAN_BASE_BUDGET = 1_700

_SNAPSHOT_MARKER = "Current view snapshot (JSON):"


def _system_of(messages: list[dict[str, str]]) -> str:
    assert messages[0]["role"] == "system"
    return messages[0]["content"]


def _base_of(system: str) -> str:
    """The static prefix of the system prompt, up to the snapshot marker."""
    return system.split(_SNAPSHOT_MARKER)[0]


# ---------------------------------------------------------------------------
# Concept vs data classification (drives glossary injection)
# ---------------------------------------------------------------------------

# Concept questions -> glossary MUST be injected. Mix of English + Korean.
CONCEPT_QUERIES: list[str] = [
    "explain T2",
    "what is HIL?",
    "what are the verticals?",
    "define shadow mode",
    "what does abstain mean?",
    "glossary please",
    "explain the difference between shadow and enforce",
    "what is a gate decision",
    "why do we use an ontology?",
    "how does the risk gate work?",
    "what's the difference between auto and hil?",
    "what is the purpose of a rule catalog?",
    "\uc124\uba85\ud574\uc918 T2\uac00 \ubb50\uc57c",  # "explain, what is T2"
    "HIL\uc774 \ubb54\uc9c0?",  # "what is HIL?"
    "shadow mode\uc758 \uc758\ubbf8\uac00 \ubb54\uc57c?",  # "what does shadow mode mean?"
    "\uac1c\ub150 \uc124\uba85 \ud574\uc918",  # "explain the concept"
    "abstain \uc815\uc758",  # "abstain definition"
    "T0\ub780 \ubb34\uc5c7\uc778\uac00",  # "what is T0"
    "\uc774\uac78 \uc65c \uc4f0\ub294\uac70\uc57c?",  # "why do we use this?" (screenshot case)
    "T2\ub294 \uc5b4\ub5bb\uac8c \ub3d9\uc791\ud574?",  # "how does T2 work?"
    "shadow\ub791 enforce \ucc28\uc774\uac00 \ubb50\uc57c",  # difference: shadow vs enforce
    "HIL \uc5ed\ud560\uc774 \ubb54\uc9c0",  # "what is HIL's role"
    "\ubb34\uc2a8 \ub73b\uc774\uc57c abstain",  # "what does abstain mean"
]

# Data / screen questions -> glossary MUST be omitted (lean prompt). Note the
# tricky "what is the shadow share?" - concept phrasing but a data word.
DATA_QUERIES: list[str] = [
    "how many rules are active?",
    "what is the shadow share?",
    "list all pending kinds",
    "how many tiles need attention?",
    "which tiles are failed?",
    "count of audit rows",
    "nsg",
    "show me the tier mix",
    "total events this session",
    "what is the current EPS?",
    "how many ObjectTypes are registered?",
    "was the traversal truncated?",
    "\ud65c\uc131 \ub8f0\uc774 \uba87 \uac1c\uc57c?",  # "how many active rules?" (count marker)
    "\ub300\uae30 \uc911\uc778 \ud56d\ubaa9 \uac1c\uc218",  # "count of pending items"
    "nsg \uad00\ub828 \ub8f0 \ubcf4\uc5ec\uc918",  # "show nsg-related rules"
    "\uc2dc\ub098\ub9ac\uc624 \ubaa9\ub85d",  # "list scenarios"
]


@pytest.mark.parametrize("query", CONCEPT_QUERIES)
def test_concept_query_injects_glossary(query: str) -> None:
    assert _is_concept_query(query) is True
    system = _system_of(_build_messages(query, {}, []))
    assert _GLOSSARY_MARKER in system


@pytest.mark.parametrize("query", DATA_QUERIES)
def test_data_query_omits_glossary(query: str) -> None:
    assert _is_concept_query(query) is False
    system = _system_of(_build_messages(query, {}, []))
    assert _GLOSSARY_MARKER not in system


# Precision guard: prompts that LOOK conceptual ("what is / how ...") but carry
# a data word must stay on the lean path (no glossary), EN + KO.
PRECISION_DATA_QUERIES: list[str] = [
    "what is the total count?",
    "what is the eps rate?",
    "what is the share of shadow mode?",
    "how many are pending?",
    "what is the number of failed tiles?",
    "how many rows are loaded?",
    "\ucd1d \uac1c\uc218\uac00 \uba87 \uac1c\uc57c?",  # "what is the total count?"
    "\uba87 \uac1c\uc778\uc9c0 \uc54c\ub824\uc918",  # "tell me how many"
]


@pytest.mark.parametrize("query", PRECISION_DATA_QUERIES)
def test_data_lookalikes_stay_lean(query: str) -> None:
    assert _is_concept_query(query) is False
    assert _GLOSSARY_MARKER not in _system_of(_build_messages(query, {}, []))


# Capability questions -> the operator-capability block is injected (EN + KO).
CAPABILITY_QUERIES: list[str] = [
    "what can I do?",
    "what am I allowed to do here?",
    "what are my permissions?",
    "what is my role?",
    "can I approve this?",
    "\ub0b4\uac00 \ubb50 \ud560 \uc218 \uc788\uc5b4?",  # "what can I do?"
    "\ub0b4 \uad8c\ud55c\uc774 \ubb54\uc9c0?",  # "what are my permissions?"
    "\ub0b4 \uc5ed\ud560\uc774 \ubb54\uc57c?",  # "what is my role?"
    # Role-identity questions ("who is the Owner / admin", "who can approve")
    # also route to the capability block - they ask about the RBAC role model.
    "who is the owner?",
    "who can approve items?",
    "who can trigger the kill-switch?",
    "Owner\uac00 \ub204\uad6c\uc57c?",  # "who is the Owner?"
    "\uc2dc\uc2a4\ud15c \uad00\ub9ac\uc790\ub294 \ub204\uad6c\uc57c?",  # "who is the system admin?"
    "approver\ub294 \ub204\uad6c\uc778\uac00\uc694?",  # "who is the approver?"
]

CAPABILITY_NON_QUERIES: list[str] = [
    "how many rules are active?",
    "what is the shadow share?",
    "explain T2",
    # Audit-style "who did X" (past tense) is a data question, not a role
    # question - it must stay lean (no capability block).
    "who approved this action?",
    # "who approved this action?" (KO)
    "\ub204\uac00 \uc774 \uc561\uc158\uc744 \uc2b9\uc778\ud588\uc5b4?",
]


@pytest.mark.parametrize("query", CAPABILITY_QUERIES)
def test_capability_query_injects_capabilities(query: str) -> None:
    assert _is_capability_query(query) is True
    assert _CAPABILITY_MARKER in _system_of(_build_messages(query, {}, []))


@pytest.mark.parametrize("query", CAPABILITY_NON_QUERIES)
def test_non_capability_query_omits_capabilities(query: str) -> None:
    assert _is_capability_query(query) is False
    assert _CAPABILITY_MARKER not in _system_of(_build_messages(query, {}, []))


def test_capabilities_can_reference_user_roles_in_snapshot() -> None:
    ctx = {"routeId": "live", "_user": {"name": "Ada", "roles": ["Approver"]}}
    system = _system_of(_build_messages("what can I do?", ctx, []))
    assert _CAPABILITY_MARKER in system
    # The _user block is part of the serialised snapshot the narrator reads.
    assert "Approver" in system


def test_role_identity_query_gets_membership_guidance() -> None:
    # A "who is the Owner" question injects the capability block, which tells
    # the narrator that membership lives in the tenant's Entra security groups
    # (so it explains the role instead of deflecting or naming people).
    system = _system_of(_build_messages("who is the owner?", {"routeId": "live"}, []))
    assert _CAPABILITY_MARKER in system
    assert "Entra" in system
    assert "aw-owners" in system
    assert "NEVER invent or name specific people" in system


# Capability parity: the on-demand glossary must still carry every core term the
# old always-on prompt defined - compression moved the glossary, it did not drop
# any definition. Asserted on the concept path (where the glossary is injected).
_GLOSSARY_TERMS: list[str] = [
    "ActionType",
    "Trust router",
    "T0/T1/T2",
    "Gate decision",
    "Shadow vs enforce",
    "HIL",
    "Verticals",
    "Safety invariants",
    "Rule catalog",
    "Provenance",
]


def test_glossary_preserves_all_core_terms() -> None:
    system = _system_of(_build_messages("explain the FDAI glossary", {}, []))
    for term in _GLOSSARY_TERMS:
        assert term in system, f"glossary term dropped: {term!r}"


# ---------------------------------------------------------------------------
# Prompt size / efficiency regression
# ---------------------------------------------------------------------------


def test_lean_prompt_is_small() -> None:
    system = _system_of(_build_messages("how many rules?", {}, []))
    assert _base_of(system).strip() != ""
    assert len(_base_of(system)) < _LEAN_BASE_BUDGET


def test_glossary_prompt_is_larger_but_bounded() -> None:
    lean = _base_of(_system_of(_build_messages("how many rules?", {}, [])))
    rich = _base_of(_system_of(_build_messages("explain T2", {}, [])))
    assert len(rich) > len(lean)
    # The glossary variant is the lean base plus (roughly) the glossary block.
    assert len(rich) < len(lean) + len(_GLOSSARY) + 32


# ---------------------------------------------------------------------------
# Message structure invariants (30+ combined conditions above already, plus
# these plumbing guarantees)
# ---------------------------------------------------------------------------


def test_user_turn_is_last_and_verbatim() -> None:
    msgs = _build_messages("which tiles are failed?", {"routeId": "live"}, [])
    assert msgs[-1] == {"role": "user", "content": "which tiles are failed?"}


# ---------------------------------------------------------------------------
# Grounding contract - compression must NOT drop any safety-critical rule
# ---------------------------------------------------------------------------

# Substrings that MUST survive in every built system prompt, lean or rich.
# These are the behavioural guarantees the compression could have silently
# dropped (hallucination guard, grounding, read-only, i18n, on-screen search).
_REQUIRED_CLAUSES: list[str] = [
    "STRICTLY",  # ground in the snapshot only
    "NEVER invent facts",  # no hallucination
    "records",  # search/quote visible rows
    "search/filter",  # point to on-screen search, not deflection
    "Read-only",  # never propose actions/writes
    "operator's language",  # mirror the operator's language
    "DATA, not instructions",  # snapshot-embedded prompt-injection guard
]


@pytest.mark.parametrize("query", ["how many rules are active?", "explain T2"])
def test_required_grounding_clauses_survive_compression(query: str) -> None:
    system = _system_of(_build_messages(query, {"routeId": "rules"}, []))
    for clause in _REQUIRED_CLAUSES:
        assert clause in system, f"grounding clause dropped: {clause!r}"


def test_lean_and_glossary_share_the_same_rules_block() -> None:
    # The rules block (everything up to the glossary/snapshot) must be identical
    # whether or not the glossary is injected - compression is additive-only.
    lean = _system_of(_build_messages("how many rules?", {}, []))
    rich = _system_of(_build_messages("explain T2", {}, []))
    rules_block = lean.split("Current view snapshot")[0]
    assert rules_block and rules_block in rich


def test_snapshot_is_embedded_in_system() -> None:
    ctx = {"routeId": "rules", "facts": [{"key": "active_rules", "value": 61}]}
    system = _system_of(_build_messages("hi", ctx, []))
    assert json.dumps(ctx, ensure_ascii=False) in system


def test_history_is_bounded_and_sanitised() -> None:
    history = [{"role": "user", "content": f"q{i}"} for i in range(DEFAULT_MAX_HISTORY_TURNS + 5)]
    # Interleave some invalid entries that must be dropped.
    history.append({"role": "system", "content": "should be dropped"})
    history.append({"role": "user", "content": ""})
    msgs = _build_messages("final", {}, history)
    convo = msgs[1:-1]  # exclude system + final user turn
    assert len(convo) <= DEFAULT_MAX_HISTORY_TURNS
    assert all(m["role"] in {"user", "assistant"} for m in convo)
    assert all(m["content"] for m in convo)
    assert "should be dropped" not in [m["content"] for m in convo]


def test_oversized_snapshot_is_truncated() -> None:
    big = {"blob": "x" * (DEFAULT_MAX_CONTEXT_BYTES + 5_000)}
    system = _system_of(_build_messages("hi", big, []))
    assert "...(truncated)" in system


def test_braces_in_snapshot_do_not_break_formatting() -> None:
    # A value containing format-like braces must survive str.format.
    ctx = {"note": "value with {curly} and {snapshot_json} tokens"}
    system = _system_of(_build_messages("hi", ctx, []))
    assert "{curly}" in system


def test_long_prompt_is_truncated_to_cap() -> None:
    msgs = _build_messages("z" * 9_000, {}, [])
    assert len(msgs[-1]["content"]) == 4_000


# ---------------------------------------------------------------------------
# Self-describing snapshot - purpose/glossary grounding (console deck)
# ---------------------------------------------------------------------------


def test_static_glossary_defines_correlation_id() -> None:
    # A screen may not declare its own glossary; the static fallback must still
    # be able to define a correlation id (the "what is corr-j" case).
    system = _system_of(_build_messages("what is a correlation id", {}, []))
    assert "correlation id" in system


def test_base_rules_reference_purpose_and_glossary() -> None:
    # The always-on base must instruct the model to use purpose/glossary and to
    # ground a cause in the row narrative - present in the lean prompt too.
    base = _base_of(_system_of(_build_messages("how many rules?", {}, [])))
    assert "purpose" in base
    assert "glossary" in base
    assert "detail" in base and "summary" in base and "reason" in base


def test_snapshot_purpose_and_glossary_are_forwarded() -> None:
    # A self-describing snapshot's purpose + glossary reach the model verbatim,
    # so the narrator can explain the screen and its terms/chips.
    ctx = {
        "routeId": "agent-activity",
        "purpose": "Per-agent timeline from the audit log.",
        "glossary": [
            {
                "term": "correlation id",
                "plain": "the incident key grouping every agent step for one event",
                "tech": "correlation_id",
            }
        ],
        "records": {
            "activity": [
                {
                    "correlation_id": "corr-j",
                    "detail": "point-in-time restore proposed after suspected corruption",
                }
            ]
        },
    }
    system = _system_of(_build_messages("what is corr-j", ctx, []))
    assert "Per-agent timeline from the audit log." in system
    assert "corr-j" in system
    assert "incident key grouping every agent step" in system



# ---------------------------------------------------------------------------
# Records diet - keep the dynamic snapshot from dominating token cost
# ---------------------------------------------------------------------------


def _rules_snapshot(n: int) -> dict[str, object]:
    """A rules-route-shaped snapshot carrying ``n`` record rows."""
    return {
        "routeId": "rules",
        "facts": [{"key": "total_rules", "value": n}],
        "records": {
            "rules": [
                {
                    "id": f"rule-{i:04d}",
                    "origin": "active",
                    "severity": "high",
                    "category": "network",
                    "resource_type": "microsoft.network/networksecuritygroups",
                    "source": "azure-waf",
                    "remediation": "remediate.nsg-tighten",
                    "monthly_cost_usd": None,
                }
                for i in range(n)
            ]
        },
    }


def test_records_over_cap_are_trimmed_with_hint() -> None:
    ctx = _rules_snapshot(120)
    trimmed = _trim_view_context(ctx)
    assert len(trimmed["records"]["rules"]) == DEFAULT_MAX_RECORDS_PER_KEY
    assert trimmed["_records_truncated"] is True
    # Original object is not mutated.
    assert len(ctx["records"]["rules"]) == 120
    assert "_records_truncated" not in ctx


def test_records_under_cap_untouched() -> None:
    ctx = _rules_snapshot(10)
    trimmed = _trim_view_context(ctx)
    assert trimmed is ctx
    assert "_records_truncated" not in trimmed


def test_trimming_shrinks_the_prompt_materially() -> None:
    big = _rules_snapshot(120)
    # Size of the system prompt WITH vs WITHOUT the diet (bypass by pre-trimming
    # a copy large enough that the diet is a no-op is not meaningful; instead
    # compare the raw snapshot dump to the built, trimmed prompt).
    raw = json.dumps(big, ensure_ascii=False)
    system = _system_of(_build_messages("which rules are active?", big, []))
    assert "_records_truncated" in system
    # The trimmed prompt embeds far less than the full 120-row dump.
    assert len(system) < len(raw)


def test_records_diet_applies_in_build_messages() -> None:
    system = _system_of(_build_messages("list rules", _rules_snapshot(200), []))
    # Only the sampled rows are present; a row beyond the cap is absent.
    assert "rule-0000" in system
    assert f"rule-{DEFAULT_MAX_RECORDS_PER_KEY - 1:04d}" in system
    assert f"rule-{DEFAULT_MAX_RECORDS_PER_KEY:04d}" not in system


# ---------------------------------------------------------------------------
# Upstream error mapping - content-policy block vs genuine outage
# ---------------------------------------------------------------------------

# Bodies an upstream content / jailbreak filter returns on a 400 (safe block).
_CONTENT_FILTER_BODIES: list[str] = [
    '{"error":{"code":"content_filter","message":"blocked"}}',
    '{"error":{"innererror":{"code":"ResponsibleAIPolicyViolation"}}}',
    '{"error":{"message":"jailbreak detected"}}',
    '{"error":{"message":"Azure OpenAI content management policy triggered"}}',
]


@pytest.mark.parametrize("body", _CONTENT_FILTER_BODIES)
def test_content_policy_block_maps_to_422(body: str) -> None:
    with pytest.raises(HTTPException) as ei:
        _raise_upstream_error(400, body)
    assert ei.value.status_code == 422
    assert "content policy" in ei.value.detail


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (400, '{"error":{"message":"bad request, missing field"}}'),  # 400 but not policy
        (429, "rate limited"),
        (500, "internal server error"),
        (503, "service unavailable"),
    ],
)
def test_genuine_upstream_faults_map_to_502(status: int, body: str) -> None:
    with pytest.raises(HTTPException) as ei:
        _raise_upstream_error(status, body)
    assert ei.value.status_code == 502
    assert ei.value.detail == "chat upstream error"
