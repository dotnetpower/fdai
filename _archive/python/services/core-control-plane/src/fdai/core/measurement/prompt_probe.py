"""Recognition-probe primitives for the T2 prompt (Wave 3 step D-1).

The composer emits an increasingly rich system prompt; long prompts
silently drop instructions. This module is the measurement half of the
"model actually reads what we sent" KPI documented in
``docs/roadmap/decisioning/prompt-composition.md § Recognition measurement``.

Wave 3 step D-1 ships **pure evaluator functions** on top of clean
dataclass inputs. Step D-2 wires them into the KPI dashboard, adds a
scenario-fixture runner, and teaches the composer to insert canary
tokens per layer. Splitting the work keeps step D-1 exercised in isolation
by unit tests without any I/O.

Design references:

- ``docs/roadmap/decisioning/prompt-composition.md § Recognition measurement``
- ``docs/roadmap/architecture/goals-and-metrics.md`` - measurement-first rule
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

# Violation codes surfaced by :func:`evaluate_adherence`. Structured
# strings so a downstream KPI can dispatch on them without regex
# matching the message.
_VIOLATION_NOT_JSON: Final[str] = "not-a-json-object"
_VIOLATION_MISSING_FIELD: Final[str] = "missing-field:"
_VIOLATION_WRONG_TYPE: Final[str] = "wrong-type:"
_VIOLATION_EMPTY_FIELD: Final[str] = "empty-field:"


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RequiredField:
    """One structural requirement the response MUST satisfy.

    ``expected_type`` is one of ``"string"`` / ``"object"`` /
    ``"array"`` - kept as strings so the check stays JSON-schema-shaped
    and does not require passing Python types across module
    boundaries. ``non_empty`` MUST be ``True`` for fields whose empty
    value would be an out-of-contract answer (e.g. ``action_type=""``
    should fail).
    """

    name: str
    expected_type: str
    non_empty: bool = True


@dataclass(frozen=True, slots=True)
class ExpectedResponse:
    """The ground truth the recognition probe scores a response against.

    ``expected_cited_rule_ids`` is the caller's authoritative list of
    rule ids that SHOULD appear in the model's ``cited_rule_ids``
    response field. Empty means the caller does not want to score
    citations (returns ``None`` for the F1 metric).

    ``canary_tokens`` is a mapping from a stable canary id (e.g.
    ``base.head``, ``pack.rca.tail``) to the exact token that was
    injected into the prompt. A response is scored as "echoed" when
    the token appears verbatim anywhere in the raw response text.
    Empty means canary probes are skipped.
    """

    required_fields: tuple[RequiredField, ...]
    expected_cited_rule_ids: tuple[str, ...] = ()
    canary_tokens: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class CitationScores:
    """Precision / recall / F1 for the ``cited_rule_ids`` field.

    Populated only when the caller supplied
    ``expected_cited_rule_ids``. Precision penalises hallucinated
    citations (ids not in the ground truth); recall penalises missed
    citations (ids the caller expected but the model omitted).
    """

    precision: float
    recall: float
    f1: float


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    """Per-sample recognition score.

    ``adherence_pass`` is ``True`` when every required field is
    present, has the expected type, and (when marked ``non_empty``)
    carries a non-empty value. Violations use structured codes so a
    KPI dashboard can bucket them without parsing free text.

    ``canary_echoes`` MAY be empty when the expected input carried no
    canary tokens; a ``True`` entry means the token appeared verbatim
    in the raw response, a ``False`` entry means it was dropped.

    ``citations`` is ``None`` when the caller passed no expected rule
    ids (citation scoring skipped).
    """

    adherence_pass: bool
    adherence_violations: tuple[str, ...]
    canary_echoes: Mapping[str, bool]
    citations: CitationScores | None


# ---------------------------------------------------------------------------
# Pure evaluators
# ---------------------------------------------------------------------------


def evaluate_adherence(
    response_json: Mapping[str, Any] | None,
    required_fields: Sequence[RequiredField],
) -> tuple[bool, tuple[str, ...]]:
    """Score whether the response satisfies the structural contract.

    ``response_json`` is ``None`` when the caller's JSON decode failed
    outright; that produces a single ``not-a-json-object`` violation
    rather than fanning out to per-field missing-field errors, which
    would double-count the same underlying defect.

    Returns ``(passed, violations)`` where ``violations`` is a tuple
    of structured codes (see the module-level ``_VIOLATION_*``
    constants). An empty tuple means every requirement was met.
    """

    if response_json is None:
        return False, (_VIOLATION_NOT_JSON,)

    violations: list[str] = []
    for field in required_fields:
        if field.name not in response_json:
            violations.append(f"{_VIOLATION_MISSING_FIELD}{field.name}")
            continue
        value = response_json[field.name]
        if not _matches_type(value, field.expected_type):
            violations.append(f"{_VIOLATION_WRONG_TYPE}{field.name}")
            continue
        if field.non_empty and _is_empty_value(value):
            violations.append(f"{_VIOLATION_EMPTY_FIELD}{field.name}")

    return not violations, tuple(violations)


def evaluate_canary_echoes(
    response_text: str,
    canary_tokens: Mapping[str, str] | None,
) -> Mapping[str, bool]:
    """Return which canary tokens the model echoed verbatim.

    ``canary_tokens`` may be ``None`` (no canaries injected for this
    sample), in which case the result is an empty mapping. Match is
    substring - a canary that lands inside a larger word still counts
    as echoed, matching the assumption that we generate long random
    tokens where accidental collisions are effectively impossible.
    """

    if not canary_tokens:
        return {}
    return {canary_id: token in response_text for canary_id, token in canary_tokens.items()}


def evaluate_citations(
    returned_ids: Sequence[str],
    expected_ids: Sequence[str],
) -> CitationScores | None:
    """Return precision/recall/F1 for the ``cited_rule_ids`` field.

    Returns ``None`` when ``expected_ids`` is empty - the caller
    explicitly opted out of citation scoring. The evaluator treats
    both inputs as **sets**; a caller who passes duplicates is scored
    on the distinct set, matching how rule ids surface in real audits.
    """

    if not expected_ids:
        return None
    expected_set = {rid for rid in expected_ids if rid}
    returned_set = {rid for rid in returned_ids if rid}
    if not expected_set:
        return None
    true_positives = len(expected_set & returned_set)
    precision = true_positives / len(returned_set) if returned_set else 0.0
    recall = true_positives / len(expected_set)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return CitationScores(precision=precision, recall=recall, f1=f1)


def score_recognition(
    *,
    expected: ExpectedResponse,
    response_json: Mapping[str, Any] | None,
    response_text: str,
) -> RecognitionResult:
    """Combine every recognition probe into one aggregate result.

    ``response_json`` is the parsed response object (or ``None`` when
    parsing failed); ``response_text`` is the raw string the canary
    probe scans. The caller keeps parsing and text separate because
    canary echoes MUST be measured against the untouched response,
    not against a re-serialized form that could reshape whitespace.
    """

    adherence_pass, violations = evaluate_adherence(response_json, expected.required_fields)
    canary_echoes = evaluate_canary_echoes(response_text, expected.canary_tokens)
    returned_ids = _extract_cited_ids(response_json) if response_json else ()
    citations = evaluate_citations(returned_ids, expected.expected_cited_rule_ids)
    return RecognitionResult(
        adherence_pass=adherence_pass,
        adherence_violations=violations,
        canary_echoes=canary_echoes,
        citations=citations,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _matches_type(value: object, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "object":
        return isinstance(value, Mapping)
    if expected_type == "array":
        return isinstance(value, list | tuple)
    raise ValueError(f"unsupported RequiredField.expected_type {expected_type!r}")


def _is_empty_value(value: object) -> bool:
    if isinstance(value, str):
        return not value
    if isinstance(value, Mapping | list | tuple):
        return len(value) == 0
    return False


def _extract_cited_ids(response_json: Mapping[str, Any]) -> tuple[str, ...]:
    """Read ``cited_rule_ids`` from a response, tolerating shape drift.

    A missing field, a non-list value, or non-string members surface
    as an empty tuple so citation F1 falls to zero recall without
    exceptions on partial responses.
    """

    raw = response_json.get("cited_rule_ids")
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(str(item) for item in raw if isinstance(item, str) and item)


# ---------------------------------------------------------------------------
# Canary token generation (Wave 3 step D-2a)
# ---------------------------------------------------------------------------


class CanaryGenerator(Protocol):
    """Produces one canary token per composer layer per compose call.

    The generator is called ONCE per layer while the composer is
    assembling a prompt; the returned token is prepended to that
    layer's body and stored on :class:`~fdai.core.prompts.types.ComposedPrompt.canary_tokens`
    so the recognition probe can score whether the model echoed each
    layer's marker back.

    Two upstream implementations ship:

    - :class:`SecretsCanaryGenerator` for production: opaque random
      tokens that will not accidentally collide with real content.
    - :class:`DeterministicCanaryGenerator` for tests / replayable
      recognition scenarios: canned tokens keyed by ``layer_id``.
    """

    def next_token(self, *, layer_id: str) -> str:
        """Return the canary token to inject at the head of ``layer_id``."""


class SecretsCanaryGenerator(CanaryGenerator):
    """Random per-call canary tokens, safe against accidental collisions.

    Uses :mod:`secrets` so the tokens are unpredictable to any layer
    the composer just injected. The ``CN_`` prefix keeps them
    grep-friendly during ad-hoc log inspection.
    """

    _PREFIX: Final[str] = "CN_"

    def next_token(self, *, layer_id: str) -> str:
        # ``layer_id`` is intentionally NOT hashed into the token so a
        # test writer inspecting a captured prompt cannot reverse-map
        # tokens to layers without the manifest, which is the audit
        # channel we already have.
        import secrets  # noqa: PLC0415 - deferred so callers who never build a real composer skip the import

        del layer_id
        return f"{self._PREFIX}{secrets.token_hex(6)}"


class DeterministicCanaryGenerator(CanaryGenerator):
    """Return a canned token per ``layer_id`` for tests and replay runs.

    Callers pre-seed a mapping of ``layer_id -> token``. An
    unregistered layer surfaces as ``f"CN_stub_{layer_id}"`` so a
    scenario that forgets to prime a layer still lands a
    grep-friendly marker rather than raising in the middle of a
    compose call.
    """

    def __init__(self, tokens: Mapping[str, str] | None = None) -> None:
        self._tokens: Mapping[str, str] = dict(tokens or {})

    def next_token(self, *, layer_id: str) -> str:
        return self._tokens.get(layer_id, f"CN_stub_{layer_id}")


# ---------------------------------------------------------------------------
# KPI aggregate (Wave 3 step D-2b-i)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecognitionKpiSummary:
    """Aggregate KPI over a batch of :class:`RecognitionResult` samples.

    Populated by :func:`summarize_recognition`. Everything downstream
    (dashboard row emitter, scenario runner CLI, promotion gate)
    consumes this dataclass rather than iterating over
    :class:`RecognitionResult` directly, so the KPI contract stays
    stable even when the sample-level type gains fields.

    ``adherence_pass_rate`` and ``per_layer_canary_echo_rate`` are
    floats in ``[0.0, 1.0]``; the caller is responsible for
    dividing by zero: with ``sample_count == 0`` both are ``0.0`` and
    ``mean_citation_f1`` is ``None`` so a downstream metric emitter
    can skip the row rather than publish a misleading zero.
    """

    sample_count: int
    adherence_pass_rate: float
    adherence_violation_counts: Mapping[str, int]
    per_layer_canary_echo_rate: Mapping[str, float]
    mean_citation_f1: float | None


def summarize_recognition(
    results: Sequence[RecognitionResult],
) -> RecognitionKpiSummary:
    """Aggregate per-sample results into one :class:`RecognitionKpiSummary`.

    Only samples where the caller supplied ``expected_cited_rule_ids``
    contribute to ``mean_citation_f1``; samples without expected ids
    have ``result.citations is None`` and are excluded from the
    average so citation coverage is not silently diluted by
    non-scored runs.

    ``per_layer_canary_echo_rate`` reports one rate per layer id that
    appeared in **any** sample's ``canary_echoes``, so a layer that
    was measured in only a subset of the batch still surfaces with
    the correct denominator. Layers that never had a canary injected
    do not appear at all.
    """

    if not results:
        return RecognitionKpiSummary(
            sample_count=0,
            adherence_pass_rate=0.0,
            adherence_violation_counts={},
            per_layer_canary_echo_rate={},
            mean_citation_f1=None,
        )

    sample_count = len(results)
    adherence_passes = sum(1 for r in results if r.adherence_pass)
    adherence_pass_rate = adherence_passes / sample_count

    violation_counts: dict[str, int] = {}
    for result in results:
        for code in result.adherence_violations:
            violation_counts[code] = violation_counts.get(code, 0) + 1

    # For each layer id observed anywhere in the batch, count how many
    # samples measured it (its id was present in ``canary_echoes``)
    # and how many of those echoed. A layer that no sample measured
    # never enters the mapping - a zero-denominator entry would
    # publish 0.0 and be indistinguishable from "measured but never
    # echoed".
    echo_totals: dict[str, int] = {}
    echo_denominators: dict[str, int] = {}
    for result in results:
        for layer_id, echoed in result.canary_echoes.items():
            echo_denominators[layer_id] = echo_denominators.get(layer_id, 0) + 1
            if echoed:
                echo_totals[layer_id] = echo_totals.get(layer_id, 0) + 1
    per_layer_echo_rate = {
        layer_id: echo_totals.get(layer_id, 0) / denominator
        for layer_id, denominator in echo_denominators.items()
    }

    scored_citations = [r.citations for r in results if r.citations is not None]
    if scored_citations:
        mean_f1: float | None = sum(c.f1 for c in scored_citations) / len(scored_citations)
    else:
        mean_f1 = None

    return RecognitionKpiSummary(
        sample_count=sample_count,
        adherence_pass_rate=adherence_pass_rate,
        adherence_violation_counts=violation_counts,
        per_layer_canary_echo_rate=per_layer_echo_rate,
        mean_citation_f1=mean_f1,
    )


__all__ = [
    "CanaryGenerator",
    "CitationScores",
    "DeterministicCanaryGenerator",
    "ExpectedResponse",
    "RecognitionKpiSummary",
    "RecognitionResult",
    "RequiredField",
    "SecretsCanaryGenerator",
    "evaluate_adherence",
    "evaluate_canary_echoes",
    "evaluate_citations",
    "score_recognition",
    "summarize_recognition",
]
