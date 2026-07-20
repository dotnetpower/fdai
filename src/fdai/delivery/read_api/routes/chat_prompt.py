"""Prompt assembly, concept detection, and locale helpers for chat."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any, Final

from fdai.core.conversation.answer_plan import (
    AnswerIntent,
    AnswerPlan,
    DetailLevel,
    build_answer_plan,
)
from fdai.delivery.read_api.routes.chat_prompt_content import (
    _AGENT_EVIDENCE_DIRECTIVE,
    _BEHAVIOR_EVIDENCE_DIRECTIVE,
    _CAPABILITIES,
    _CONCEPT_EVIDENCE_DIRECTIVE,
    _EXPLANATION_DIRECTIVE,
    _GLOSSARY,
    _OPERATIONAL_EVIDENCE_DIRECTIVE,
    _SCREEN_EXPLANATION_DIRECTIVE,
    _SYSTEM_PROMPT,
    _TOOL_EVIDENCE_DIRECTIVE,
    _WEB_EVIDENCE_DIRECTIVE,
)

_LOG = logging.getLogger(__name__)


"""Prompt assembly, concept glossary, and locale helpers for chat."""


_LOG = logging.getLogger(__name__)


DEFAULT_MAX_CONTEXT_BYTES: Final[int] = 60_000


DEFAULT_MAX_HISTORY_TURNS: Final[int] = 8


DEFAULT_MAX_RECORDS_PER_KEY: Final[int] = 40


DEFAULT_MAX_EXPLANATION_ITEMS: Final[int] = 24


DEFAULT_MAX_LIFECYCLE_CRITERIA: Final[int] = 12


_COMPILED_USER_POLICY_KEY: Final[str] = "_compiled_user_policy"


_CONCEPT_INTENT: Final = re.compile(
    r"\b(explain|define|definition|glossary|mean|meaning|purpose|difference"
    r"|overview|compare|comparison|example|examples|summari[sz]e|summary"
    r"|describe|walk (me|us) through|tell me about)\b"
    r"|\bwhy\b|\brole of\b"
    r"|\bwhen (should|do i|to)\b"
    "|\uc124\uba85|\uc758\ubbf8|\ub73b|\uac1c\ub150|\uc815\uc758"
    "|\uc5ed\ud560|\ucc28\uc774|\uc6a9\ub3c4|\uc65c"
    "|\uc608\uc2dc|\ube44\uad50|\uc694\uc57d|\uc815\ub9ac|\uc5b8\uc81c",
    re.IGNORECASE,
)


_CONCEPT_PHRASING: Final = re.compile(
    r"\bwhat\s+(is|are|does|do|kind|type)\b|\bwhats\b|\bwhat's\b"
    r"|\bhow\s+(does|do|is|are|to)\b"
    "|\ubb34\uc5c7|\ubb50|\ubb54|\uc5b4\ub5bb\uac8c|\ubb34\uc2a8|\uc544\ub2cc\uac00|\uc544\ub2c8\uc57c",
    re.IGNORECASE,
)


_DATA_WORD: Final = re.compile(
    # Trailing escapes decode to Korean count markers: how-many / count.
    r"how many|number of|count|share|total|pending|rate|eps|mix"
    r"|distribution|many|loaded|affected|depth|step"
    "|\uba87|\uac1c\uc218",
    re.IGNORECASE,
)


_CONCEPT_DOMAIN: Final = re.compile(
    r"(?<![A-Za-z0-9_])(?:actiontype|abstain|blast radius|correlation id|exemption|grounding|hil|"
    r"idempotency|kill-switch|ontology|override|pantheon|promotion gate|quality gate|"
    r"remediation pr|rollback contract|safety invariants?|shadow|trust router|"
    r"two-port|agent autonomy|autonomous agents?|t0|t1|t2|verifier|verticals?|what-if)"
    r"(?![A-Za-z0-9_])|\uc2a4\uc2a4\ub85c|\uc790\uc728|\ud310\ud14c\uc628",
    re.IGNORECASE,
)


_AGENT_NAME_TOKEN: Final = re.compile(r"[A-Za-z][A-Za-z0-9-]*")


_GLOSSARY_STOP: Final = frozenset(
    {"a", "an", "and", "do", "does", "explain", "is", "of", "the", "what", "why"}
)


_GLOSSARY_ALIASES: Final = {
    "two-port model": re.compile(
        r"\bagents?\b.*\b(?:autonom\w*|convers\w*|operate|run|work)\b"
        r"|\b(?:autonom\w*|convers\w*)\b.*\bagents?\b"
        "|\uc5d0\uc774\uc804\ud2b8.*(?:\ub300\ud654|\uc2a4\uc2a4\ub85c|\uc790\uc728|\ub3d9\uc791)"
        "|(?:\ub300\ud654|\uc2a4\uc2a4\ub85c|\uc790\uc728|\ub3d9\uc791).*\uc5d0\uc774\uc804\ud2b8",
        re.IGNORECASE,
    ),
}


def _is_concept_query(prompt: str) -> bool:
    """True when the prompt asks to define/explain a term (glossary needed).

    Data-metric phrasings ("how many", "share", "count") are excluded so
    routine screen questions get the lean prompt without the glossary block.
    """
    if _CONCEPT_INTENT.search(prompt):
        return True
    return bool(_CONCEPT_PHRASING.search(prompt) and not _DATA_WORD.search(prompt))


def _glossary_matches(prompt: str) -> list[dict[str, str]]:
    prompt_tokens = {
        token.lower()
        for token in _AGENT_NAME_TOKEN.findall(prompt)
        if token.lower() not in _GLOSSARY_STOP
    }
    ranked: list[tuple[int, int, str, str]] = []
    for index, line in enumerate(_GLOSSARY.splitlines()):
        if not line.startswith("- ") or ":" not in line:
            continue
        term, definition = line[2:].split(":", 1)
        term_tokens = {
            token.lower()
            for token in _AGENT_NAME_TOKEN.findall(term)
            if token.lower() not in _GLOSSARY_STOP
        }
        alias = _GLOSSARY_ALIASES.get(term.strip().lower())
        score = len(prompt_tokens & term_tokens) + (4 if alias and alias.search(prompt) else 0)
        if score:
            ranked.append((score, -index, term.strip(), definition.strip()))
    if not ranked:
        return []
    best = max(score for score, _, _, _ in ranked)
    return [
        {"term": term, "definition": definition}
        for score, _, term, definition in ranked
        if score == best
    ][:3]


def _with_concept_evidence(prompt: str, view_context: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(view_context)
    enriched.pop("_concept_evidence", None)
    if any(
        key in enriched
        for key in (
            "_behavior_evidence",
            "_operational_evidence",
            "_tool_evidence",
            "_agent_evidence",
        )
    ):
        return enriched
    if not _is_concept_query(prompt):
        return enriched
    entries = _glossary_matches(prompt)
    if entries:
        enriched["_concept_evidence"] = {
            "authority": "fdai_glossary",
            "entries": entries,
        }
    return enriched


def _concept_answer(view_context: Mapping[str, Any], plan: AnswerPlan) -> str | None:
    raw = view_context.get("_concept_evidence")
    if not isinstance(raw, Mapping):
        return None
    entries = raw.get("entries")
    if not isinstance(entries, list):
        return None
    parts = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        term = entry.get("term")
        definition = entry.get("definition")
        if isinstance(term, str) and isinstance(definition, str):
            parts.append(f"{term}: {definition}")
    if not parts:
        return None
    if plan.intent is not AnswerIntent.DEFINITION or plan.detail_level is DetailLevel.BRIEF:
        return "\n".join(parts)
    definition = "\n".join(parts)
    return (
        f"## Definition\n{definition}\n\n"
        f"## Why it exists\n{definition}\n\n"
        f"## Control-loop position\n{definition}\n\n"
        f"## Core parts\n{definition}\n\n"
        f"## Example\n{definition}"
    )


_CAPABILITY_INTENT: Final = re.compile(
    r"\bwhat (can|could) i do\b|\bwhat am i allowed\b|\bam i allowed\b"
    r"|\bmy (permission|role|access|capabilit)\w*\b"
    r"|\bcan i (do|approve|edit|change|write|execute|promote|run)\b"
    r"|\bwhat can i\b"
    r"|\bwho (can|could|may) (approve|reject|edit|change|write|execute|promote|deploy|run|do|"
    r"trigger|manage)\b"
    r"|\bwhat (does|do) (a |an |the )?(owner|admin(istrator)?|approver|reader|"
    r"contributor|break.?glass)s? do\b"
    r"|\bhow (do|can) i (get|obtain|request|earn|receive) (a |an |the )?"
    r"(role|permission|access|capabilit\w+)\b"
    r"|\blist (my |the |all )?(role|permission|capabilit\w+)s?\b"
    r"|\bwhat (roles?|permissions?|capabilit\w+) (are|exist|do|does)\b"
    "|\uad8c\ud55c|\uc5ed\ud560|\ud560 \uc218 \uc788"
    "|\uc5ed\ud560 \ubaa9\ub85d|\uad8c\ud55c \ubaa9\ub85d"
    "|\uad8c\ud55c\uc744 \uc5b4\ub5bb\uac8c|\uad8c\ud55c \uc5b4\ub5bb\uac8c",
    re.IGNORECASE,
)


_ROLE_TOKEN: Final = re.compile(
    r"\bowner|\badmin(istrator)?|\bapprover|\breader|\bcontributor|\bbreak.?glass"
    r"|\brbac\b|\brole (matrix|model|list)\b"
    "|\uc624\ub108|\uc18c\uc720\uc790|\uad00\ub9ac\uc790|\uc6b4\uc601\uc790"
    "|\uc2b9\uc778\uc790|\uc2b9\uc778 \uad8c\ud55c",
    re.IGNORECASE,
)


_WHO_TOKEN: Final = re.compile(
    r"\bwho (is|are|can|has|have|holds?)\b|\ub204\uad6c|\ub204\uac00",
    re.IGNORECASE,
)


_ROLE_EXPLAIN_INTENT: Final = re.compile(
    r"\b(explain|describe|what does|what do|what is|what are"
    r"|role of|purpose of|kind of)\b"
    "|\ubb50 \ud574|\ubb50 \ud558\ub294|\uc5b4\ub5a4 \uc77c|\uc124\uba85",
    re.IGNORECASE,
)


_HOW_TO_GET_INTENT: Final = re.compile(
    r"\bhow (do|can) i (get|obtain|request|earn|receive|become)\b"
    "|\uc5b4\ub5bb\uac8c \uc5bb|\uc5b4\ub5bb\uac8c \ubc1b",
    re.IGNORECASE,
)


def _is_capability_query(prompt: str) -> bool:
    """True when the operator asks about the RBAC role model.

    Three shapes route to the capability block:
    1. a direct "what can I do / my permissions / list roles" question,
    2. a role-identity question ("who is the Owner") - role token + who token,
    3. a role-description question ("what does an Owner do", "explain the
       Approver") - role token + role-explain intent,
    4. a "how do I get X" question paired with a role token
       ("how can I obtain owner permission?").
    Audit-style "who approved this?" data questions stay lean because
    _WHO_TOKEN excludes past-tense "who approved" and _ROLE_EXPLAIN_INTENT
    requires an explanatory verb (not a bare past action).
    """
    if _CAPABILITY_INTENT.search(prompt):
        return True
    if _ROLE_TOKEN.search(prompt) and (
        _WHO_TOKEN.search(prompt)
        or _ROLE_EXPLAIN_INTENT.search(prompt)
        or _HOW_TO_GET_INTENT.search(prompt)
    ):
        return True
    return False


def _trim_view_context(
    view_context: dict[str, Any], *, max_records: int = DEFAULT_MAX_RECORDS_PER_KEY
) -> dict[str, Any]:
    """Cap each ``records`` array to a representative sample.

    The rendered page can publish hundreds of rows; forwarding them all lets
    the snapshot JSON dominate the prompt. Trim each array to ``max_records``
    and flag ``_records_truncated`` (plus per-key ``_records_meta`` giving the
    shown/total counts) so the model knows the sample size honestly - never
    "there are only N" when N is the sample cap. Returns the input unchanged
    when no array exceeds the cap (no needless copy).
    """
    records = view_context.get("records")
    context = view_context
    if isinstance(records, dict):
        trimmed: dict[str, Any] = {}
        meta: dict[str, dict[str, int]] = {}
        changed = False
        for key, rows in records.items():
            if isinstance(rows, list) and len(rows) > max_records:
                trimmed[key] = rows[:max_records]
                meta[key] = {"shown": max_records, "total": len(rows)}
                changed = True
            else:
                trimmed[key] = rows
                if isinstance(rows, list):
                    meta[key] = {"shown": len(rows), "total": len(rows)}
        if changed:
            context = dict(view_context)
            context["records"] = trimmed
            context["_records_truncated"] = True
            context["_records_meta"] = meta
    return _trim_explanations(context)


def _trim_explanations(view_context: dict[str, Any]) -> dict[str, Any]:
    explanations = view_context.get("explanations")
    if not isinstance(explanations, dict):
        return view_context
    bounded = dict(explanations)
    changed = False
    meta: dict[str, dict[str, int]] = {}

    for key in ("relationships", "lifecycles"):
        values = explanations.get(key)
        if isinstance(values, list) and len(values) > DEFAULT_MAX_EXPLANATION_ITEMS:
            bounded[key] = values[:DEFAULT_MAX_EXPLANATION_ITEMS]
            meta[key] = {"shown": DEFAULT_MAX_EXPLANATION_ITEMS, "total": len(values)}
            changed = True

    lifecycles = bounded.get("lifecycles")
    if isinstance(lifecycles, list):
        bounded_lifecycles: list[Any] = []
        for lifecycle in lifecycles:
            if not isinstance(lifecycle, dict):
                bounded_lifecycles.append(lifecycle)
                continue
            bounded_lifecycle = dict(lifecycle)
            for key in ("creation", "closure", "authority_refs"):
                values = lifecycle.get(key)
                if isinstance(values, list) and len(values) > DEFAULT_MAX_LIFECYCLE_CRITERIA:
                    bounded_lifecycle[key] = values[:DEFAULT_MAX_LIFECYCLE_CRITERIA]
                    changed = True
            deduplication = lifecycle.get("deduplication")
            if isinstance(deduplication, dict):
                fields = deduplication.get("fields")
                if isinstance(fields, list) and len(fields) > DEFAULT_MAX_LIFECYCLE_CRITERIA:
                    bounded_lifecycle["deduplication"] = {
                        **deduplication,
                        "fields": fields[:DEFAULT_MAX_LIFECYCLE_CRITERIA],
                    }
                    changed = True
            bounded_lifecycles.append(bounded_lifecycle)
        bounded["lifecycles"] = bounded_lifecycles

    provenance = explanations.get("provenance")
    if isinstance(provenance, dict):
        refs = provenance.get("refs")
        if isinstance(refs, list) and len(refs) > DEFAULT_MAX_EXPLANATION_ITEMS:
            bounded["provenance"] = {
                **provenance,
                "refs": refs[:DEFAULT_MAX_EXPLANATION_ITEMS],
            }
            meta["provenance.refs"] = {
                "shown": DEFAULT_MAX_EXPLANATION_ITEMS,
                "total": len(refs),
            }
            changed = True

    if not changed:
        return view_context
    context = dict(view_context)
    context["explanations"] = bounded
    context["_explanations_truncated"] = True
    context["_explanations_meta"] = meta
    return context


def _snapshot_json_capped(view_context: dict[str, Any], cap: int) -> str:
    """Serialise ``view_context`` and cap at ``cap`` bytes without breaking JSON.

    Three failure modes to avoid: (1) a mid-record string cut yields invalid
    JSON that a lenient model may still try to parse as legitimate data;
    (2) a silent slice hides the fact that the operator's page is too
    large; (3) a value the caller passed that isn't JSON-serialisable
    (a ``datetime``, a ``set``, a circular ref) crashes the whole chat
    request. On overflow, replace the whole payload with a valid, tiny
    JSON stub carrying the size + a ``...(truncated)`` sentinel the
    grounding rules watch for. On a serialisation error, fall back to a
    ``default=str`` pass so the model at least sees stringified values,
    and on a still-fatal error emit a matching ``_snapshot_unserialisable``
    stub - never propagate the exception into the request path.
    """
    try:
        raw = json.dumps(view_context, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        try:
            raw = json.dumps(view_context, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            _LOG.warning("chat snapshot not serialisable: %s", type(exc).__name__)
            stub = {
                "_snapshot_unserialisable": True,
                "_error_type": type(exc).__name__,
                "_note": (
                    "The rendered page published a value the deck cannot serialise; "
                    "ask the operator to reload the page. ...(truncated)"
                ),
            }
            return json.dumps(stub, ensure_ascii=False)
    if len(raw) <= cap:
        return raw
    route = str(view_context.get("routeId") or view_context.get("routeLabel") or "-")
    stub = {
        "_snapshot_truncated": True,
        "_original_bytes": len(raw),
        "_cap_bytes": cap,
        "_route": route,
        "_note": (
            "Snapshot too large to send; ask the operator to narrow the page "
            "(search / filter / open one row) and re-ask. ...(truncated)"
        ),
    }
    return json.dumps(stub, ensure_ascii=False)


_LOCALE_TAG: Final = re.compile(r"^[A-Za-z]{2}(?:[-_][A-Za-z0-9]{2,8})*$")


_KOREAN_TEXT: Final = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]")


def _extract_locale(view_context: dict[str, Any]) -> str | None:
    """Read the operator locale from ``_locale`` or ``_user.locale``.

    Returns ``None`` when the value is absent, not a string, malformed, or
    already ``en`` (so no directive is prepended on the default path).
    """
    raw = view_context.get("_locale")
    if not isinstance(raw, str):
        user = view_context.get("_user")
        if isinstance(user, dict):
            raw = user.get("locale")
    if not isinstance(raw, str) or not raw:
        return None
    tag = raw.strip()
    if not _LOCALE_TAG.match(tag):
        return None
    primary = tag.split("-", 1)[0].split("_", 1)[0].lower()
    if primary == "en":
        return None
    return tag


def _locale_directive(locale: str) -> str:
    """Build the single-line locale directive for a non-English operator.

    Render the final answer in the operator's language, but keep every
    identifier, code fragment, and numeric value verbatim so grounding stays
    exact.
    """
    return (
        f"L3 rendering: answer in the operator's language (BCP-47 '{locale}'). "
        "Keep every id, number, tool output, code fragment, and column name "
        "verbatim in English - only the surrounding prose is localised."
    )


def _response_locale(prompt: str, view_context: dict[str, Any]) -> str | None:
    """Resolve the final-answer locale for the current turn.

    A Korean current prompt always renders in Korean, even when the console UI
    locale is English. Otherwise the explicit operator locale remains the L3
    override. Conversation history never decides the current turn's language.
    """
    if _KOREAN_TEXT.search(prompt):
        return "ko"
    return _extract_locale(view_context)


def _build_messages(
    prompt: str,
    view_context: dict[str, Any],
    history: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Assemble the chat messages shared by every backend.

    One grounded system message (size-capped snapshot + glossary only when the
    prompt is a concept question) followed by the bounded conversation history
    and the user turn. Centralised so all three backends
    (:class:`OpenAiCompatibleChatBackend`, :class:`AzureAdChatBackend`, and the
    streaming path) build byte-identical, minimal prompts.
    """
    view_context = dict(view_context)
    compiled_policy = view_context.pop(_COMPILED_USER_POLICY_KEY, None)
    view_context = _trim_view_context(view_context)
    if not isinstance(view_context.get("_answer_plan"), dict):
        plan = build_answer_plan(prompt, route_id=str(view_context.get("routeId") or "") or None)
        view_context = {**view_context, "_answer_plan": plan.to_dict()}
    locale = _response_locale(prompt, view_context)
    snapshot_json = _snapshot_json_capped(view_context, DEFAULT_MAX_CONTEXT_BYTES)
    glossary = _GLOSSARY if _is_concept_query(prompt) else ""
    capabilities = _CAPABILITIES if _is_capability_query(prompt) else ""
    records = view_context.get("records")
    screen_explanation = (
        _SCREEN_EXPLANATION_DIRECTIVE
        if isinstance(records, Mapping)
        and any(key in records for key in ("sections", "controls", "constraints"))
        else ""
    )
    explanation_rules = (
        _EXPLANATION_DIRECTIVE if isinstance(view_context.get("explanations"), Mapping) else ""
    )
    system = _SYSTEM_PROMPT.format(
        screen_explanation=screen_explanation,
        explanation_rules=explanation_rules,
        capabilities=capabilities,
        glossary=glossary,
        snapshot_json=snapshot_json,
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    if isinstance(compiled_policy, dict) and isinstance(compiled_policy.get("text"), str):
        messages.append({"role": "system", "content": compiled_policy["text"]})
    if "_behavior_evidence" in view_context:
        messages.append({"role": "system", "content": _BEHAVIOR_EVIDENCE_DIRECTIVE})
    if "_operational_evidence" in view_context:
        messages.append({"role": "system", "content": _OPERATIONAL_EVIDENCE_DIRECTIVE})
    if "_agent_evidence" in view_context:
        messages.append({"role": "system", "content": _AGENT_EVIDENCE_DIRECTIVE})
    if "_tool_evidence" in view_context:
        messages.append({"role": "system", "content": _TOOL_EVIDENCE_DIRECTIVE})
    if "_concept_evidence" in view_context:
        messages.append({"role": "system", "content": _CONCEPT_EVIDENCE_DIRECTIVE})
    if "_web_evidence" in view_context:
        messages.append({"role": "system", "content": _WEB_EVIDENCE_DIRECTIVE})
    # Locale directive is a separate second system message so the base prompt
    # stays byte-identical for English operators (matches the CLI narrator's
    # two-message shape when locale != "en"). Skipped when locale is absent
    # or already English.
    if locale is not None:
        messages.append({"role": "system", "content": _locale_directive(locale)})
    for turn in history[-DEFAULT_MAX_HISTORY_TURNS:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content:
            messages.append({"role": role, "content": content[:4000]})
    messages.append({"role": "user", "content": prompt[:4000]})
    return messages


__all__ = [
    "DEFAULT_MAX_EXPLANATION_ITEMS",
    "DEFAULT_MAX_CONTEXT_BYTES",
    "DEFAULT_MAX_HISTORY_TURNS",
    "DEFAULT_MAX_RECORDS_PER_KEY",
    "_AGENT_EVIDENCE_DIRECTIVE",
    "_BEHAVIOR_EVIDENCE_DIRECTIVE",
    "_CAPABILITIES",
    "_CONCEPT_EVIDENCE_DIRECTIVE",
    "_EXPLANATION_DIRECTIVE",
    "_GLOSSARY",
    "_OPERATIONAL_EVIDENCE_DIRECTIVE",
    "_SCREEN_EXPLANATION_DIRECTIVE",
    "_SYSTEM_PROMPT",
    "_TOOL_EVIDENCE_DIRECTIVE",
    "_WEB_EVIDENCE_DIRECTIVE",
]
