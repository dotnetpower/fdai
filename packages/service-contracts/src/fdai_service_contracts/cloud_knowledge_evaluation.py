"""Offline, authority-free accounting for paired cloud-document RAG observations.

Responsibility: bind a frozen question set and reduce supplied numeric observations.
Boundary: no retrieval, model call, source authentication, or human-review verification.
Authority and state: immutable diagnostics only; never qualify or promote production.
Dependencies: the shared knowledge codec, Pydantic, and the standard library.
Deployment: an in-process contract library, not an additional runtime service.
"""

from __future__ import annotations

import math
import unicodedata
from collections import Counter
from typing import Annotated, Final, Literal, Self, cast

from pydantic import (
    AfterValidator,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    computed_field,
    field_validator,
    model_validator,
)

from fdai_service_contracts.baseline_cohort import CommitRevision
from fdai_service_contracts.cloud_knowledge import (
    Digest,
    Identifier,
    KnowledgeContract,
    canonical_bytes,
    content_digest,
)

Language = Literal["en", "ko"]
CaseSplit = Literal["development", "held_out"]
CaseKind = Literal["single", "dependency", "negative"]
EvidenceVenue = Literal["synthetic", "local-integration", "operational"]
EvaluationStatus = Literal["pass", "fail", "hold", "no_evidence"]

MAX_SEMANTIC_CASES: Final = 1000
MAX_OBSERVATIONS: Final = MAX_SEMANTIC_CASES * 2
MAX_CLAIMS: Final = 10_000
TOP_K: Final = 8
LANGUAGES: Final[tuple[Language, Language]] = ("en", "ko")
CASE_FLOORS: Final[tuple[tuple[CaseKind, int, int], ...]] = (
    ("single", 40, 20),
    ("dependency", 20, 10),
    ("negative", 20, 10),
)

EvaluationId = Annotated[Identifier, Field(strict=True, min_length=1, max_length=128)]
EvaluationDigest = Annotated[Digest, Field(strict=True, min_length=64, max_length=64)]
ClaimCount = Annotated[StrictInt, Field(ge=0, le=MAX_CLAIMS)]
Count = Annotated[StrictInt, Field(ge=0, le=MAX_OBSERVATIONS * 100_000)]
BasisPoints = Annotated[StrictInt, Field(ge=0, le=10_000)]


def _number(value: object) -> float:
    """Reject booleans, numeric strings, overflow, and non-finite numeric assertions."""
    if type(value) not in (int, float):
        raise ValueError("evaluation metrics MUST be finite nonnegative numbers")
    try:
        number = float(cast(int | float, value))
    except OverflowError:
        raise ValueError("evaluation metrics MUST be finite nonnegative numbers") from None
    if not math.isfinite(number) or number < 0:
        raise ValueError("evaluation metrics MUST be finite nonnegative numbers")
    return number if number else 0.0


def _array(value: object) -> object:
    """Only materialized arrays enter a bounded contract; do not consume iterators."""
    if type(value) not in (list, tuple):
        raise ValueError("evaluation collections MUST be arrays")
    if len(cast(list[object] | tuple[object, ...], value)) > MAX_OBSERVATIONS:
        raise ValueError("evaluation collection exceeds its hard item bound")
    return value


def _revision(value: str) -> str:
    if len(value) not in (40, 64) or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("source revision MUST be an exact lowercase 40 or 64 character commit")
    return value


def _false(value: object) -> Literal[False]:
    if value is not False:
        raise ValueError("evaluation cannot assert authority or production qualification")
    return False


MetricNumber = Annotated[float, BeforeValidator(_number), Field(ge=0, le=10**15)]
NoAuthority = Annotated[Literal[False], BeforeValidator(_false)]
EvaluationRevision = Annotated[CommitRevision, Field(strict=True), AfterValidator(_revision)]
EvidenceIds = Annotated[tuple[EvaluationId, ...], BeforeValidator(_array), Field(max_length=64)]


class _EvaluationContract(KnowledgeContract):
    """Reuse closed frozen knowledge records, revalidating nested model instances too."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)


class CloudKnowledgeEvaluationError(ValueError):
    """Invalid evaluation input, without question text or filesystem details."""


class CloudKnowledgeEvaluationCase(_EvaluationContract):
    """One localized instance; EN/KO siblings share one semantic case and gold labels.

    Gold labels are supplied assertions, not independently verified semantic truth.
    A single case needs one evidence ID, a dependency needs two to eight, and a
    negative has none. Both members of a pair must carry identical gold sets.
    """

    case_id: EvaluationId
    language: Language
    question: Annotated[StrictStr, Field(min_length=1, max_length=4096, repr=False)]
    split: CaseSplit
    kind: CaseKind
    required_evidence_ids: EvidenceIds
    forbidden_evidence_ids: EvidenceIds

    @field_validator("question")
    @classmethod
    def bounded_question(cls, value: str) -> str:
        """Retain readable NFC UTF-8 while bounding both characters and encoded bytes."""
        if (
            not value.strip()
            or unicodedata.normalize("NFC", value) != value
            or len(value.encode("utf-8")) > 8192
        ):
            raise ValueError("questions MUST be nonblank NFC UTF-8 within 8192 bytes")
        return value

    @field_validator("required_evidence_ids", "forbidden_evidence_ids")
    @classmethod
    def unique_gold_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Gold sets have no ranking; canonicalize order without dropping duplicates."""
        if len(value) != len(set(value)):
            raise ValueError("gold evidence IDs MUST be unique")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def consistent_gold(self) -> Self:
        """Reject contradictory labels and gold evidence that cannot fit the rank-eight gate."""
        if set(self.required_evidence_ids) & set(self.forbidden_evidence_ids):
            raise ValueError("required and forbidden evidence MUST be disjoint")
        minimum = {"single": 1, "dependency": 2, "negative": 0}[self.kind]
        maximum = {"single": 1, "dependency": TOP_K, "negative": 0}[self.kind]
        if not minimum <= len(self.required_evidence_ids) <= maximum:
            raise ValueError("case kind MUST have a representable required evidence set at eight")
        return self


class CloudKnowledgeQuestionSet(_EvaluationContract):
    """A bounded paired set, with exact duplicate and declared split-leakage rejection.

    Normalized same-language question reuse cannot inflate the case denominator.
    This does not prove that differently worded cases are semantically independent.
    """

    schema_version: Literal["fdai.cloud-knowledge-questions.v1"] = (
        "fdai.cloud-knowledge-questions.v1"
    )
    cases: Annotated[
        tuple[CloudKnowledgeEvaluationCase, ...],
        BeforeValidator(_array),
        Field(min_length=2, max_length=MAX_OBSERVATIONS, repr=False),
    ]

    @field_validator("cases")
    @classmethod
    def ordered_cases(
        cls, value: tuple[CloudKnowledgeEvaluationCase, ...]
    ) -> tuple[CloudKnowledgeEvaluationCase, ...]:
        """Canonicalize instance order without changing either question or evidence ranking."""
        return tuple(sorted(value, key=lambda case: (case.case_id, case.language)))

    @model_validator(mode="after")
    def paired_cases(self) -> Self:
        """Require one unambiguous pair per semantic identity with the same frozen labels."""
        pairs: dict[str, list[CloudKnowledgeEvaluationCase]] = {}
        identities: set[tuple[str, str]] = set()
        questions: set[tuple[str, str]] = set()
        for case in self.cases:
            identity = (case.case_id, case.language)
            question = (case.language, " ".join(case.question.split()).casefold())
            if identity in identities or question in questions:
                raise ValueError("case/language IDs and same-language questions MUST be unique")
            identities.add(identity)
            questions.add(question)
            pairs.setdefault(case.case_id, []).append(case)
        for siblings in pairs.values():
            if len(siblings) != 2 or {case.language for case in siblings} != set(LANGUAGES):
                raise ValueError("every semantic case MUST have exactly one EN and one KO instance")
            first, second = siblings
            if (
                first.split != second.split
                or first.kind != second.kind
                or first.required_evidence_ids != second.required_evidence_ids
                or first.forbidden_evidence_ids != second.forbidden_evidence_ids
            ):
                raise ValueError("paired cases MUST share split, kind, and exact gold evidence")
        return self

    @property
    def digest(self) -> str:
        """Bind normalized gold records in case/language order, independent of input ordering."""
        return content_digest(canonical_bytes(self))


class CloudKnowledgeEvaluationPlan(_EvaluationContract):
    """Frozen evaluation inputs; declared venue is descriptive, never authorization.

    The question digest is recomputed. Corpus, recipe, and source-revision identities
    are only declarations because the evaluator never reads those external objects.
    """

    schema_version: Literal["fdai.cloud-knowledge-evaluation-plan.v1"] = (
        "fdai.cloud-knowledge-evaluation-plan.v1"
    )
    corpus_digest: EvaluationDigest
    question_set_digest: EvaluationDigest
    recipe_digest: EvaluationDigest
    source_revision: EvaluationRevision
    evidence_venue: EvidenceVenue
    question_set: CloudKnowledgeQuestionSet

    @model_validator(mode="after")
    def question_binding(self) -> Self:
        """Reject a digest claiming a different question set, without authenticating gold."""
        if self.question_set_digest != self.question_set.digest:
            raise ValueError("evaluation plan MUST bind the exact question-set digest")
        return self

    @property
    def digest(self) -> str:
        """Bind all plan declarations; recomputing this digest authenticates none of them."""
        return content_digest(canonical_bytes(self))


class CloudKnowledgeEvaluationObservation(_EvaluationContract):
    """Unverified counts for one exact plan/case/language, including failed outcomes.

    Critical claims are a subset of material claims, themselves a subset of all
    claims. ``cited_claim_count`` counts covered claims, not repeated references;
    ``citation_count`` counts claim-to-evidence citation occurrences. Neither is
    proof of citation correctness or of independent human review.
    """

    plan_digest: EvaluationDigest
    case_id: EvaluationId
    language: Language
    returned_evidence_ids: EvidenceIds
    outcome: Literal["answer", "hold", "clarify", "deny"]
    claim_count: ClaimCount
    cited_claim_count: ClaimCount
    material_claim_count: ClaimCount
    supported_material_claim_count: ClaimCount
    critical_claim_count: ClaimCount
    supported_critical_claim_count: ClaimCount
    citation_count: Annotated[StrictInt, Field(ge=0, le=100_000)]
    latency_ms: Annotated[MetricNumber, Field(le=10**9)]
    cost_usd: Annotated[MetricNumber, Field(le=10**6)]
    unapproved_effect: StrictBool

    @model_validator(mode="after")
    def consistent_counts(self) -> Self:
        """Keep support and citation assertions within their declared claim populations."""
        if len(self.returned_evidence_ids) != len(set(self.returned_evidence_ids)):
            raise ValueError("returned evidence IDs MUST be unique without changing rank")
        if not 0 <= self.critical_claim_count <= self.material_claim_count <= self.claim_count:
            raise ValueError("critical and material claim counts MUST be nested subsets")
        if (
            self.supported_critical_claim_count > self.critical_claim_count
            or self.supported_material_claim_count > self.material_claim_count
            or self.supported_critical_claim_count > self.supported_material_claim_count
            or self.critical_claim_count - self.supported_critical_claim_count
            > self.material_claim_count - self.supported_material_claim_count
        ):
            raise ValueError("supported and unsupported claim counts MUST be consistent subsets")
        if (
            self.cited_claim_count > self.claim_count
            or self.citation_count < self.cited_claim_count
            or (self.cited_claim_count == 0 and self.citation_count != 0)
        ):
            raise ValueError("citation occurrences MUST cover the declared distinct cited claims")
        if (
            self.cited_claim_count or self.supported_material_claim_count
        ) and not self.returned_evidence_ids:
            raise ValueError("claimed support and citations MUST reference returned evidence")
        return self


class CloudKnowledgeEvaluationBatch(_EvaluationContract):
    """One bounded observation set; missing instances remain reportable, never a pass.

    Duplicate, unplanned, or differently bound observations are invalid. Missing
    cases are retained as a counted hold/no-evidence result, not silently excluded.
    Observation records cannot relabel their split or supply a denominator.
    """

    schema_version: Literal["fdai.cloud-knowledge-evaluation.v1"] = (
        "fdai.cloud-knowledge-evaluation.v1"
    )
    plan: CloudKnowledgeEvaluationPlan
    observations: Annotated[
        tuple[CloudKnowledgeEvaluationObservation, ...],
        BeforeValidator(_array),
        Field(max_length=MAX_OBSERVATIONS),
    ]

    @field_validator("observations")
    @classmethod
    def ordered_observations(
        cls, value: tuple[CloudKnowledgeEvaluationObservation, ...]
    ) -> tuple[CloudKnowledgeEvaluationObservation, ...]:
        """Record order is immaterial; ranked evidence order inside each record is preserved."""
        return tuple(sorted(value, key=lambda item: (item.case_id, item.language)))

    @model_validator(mode="after")
    def exact_observation_identity(self) -> Self:
        """Exclude replays, substitutions, and unplanned instances before any metric is reduced."""
        expected = {(case.case_id, case.language) for case in self.plan.question_set.cases}
        seen: set[tuple[str, str]] = set()
        digest = self.plan.digest
        for observation in self.observations:
            key = (observation.case_id, observation.language)
            if key in seen or key not in expected:
                raise ValueError(
                    "observations MUST be a unique subset of the exact case/language set"
                )
            if observation.plan_digest != digest:
                raise ValueError("every observation MUST bind the exact evaluation plan")
            seen.add(key)
        return self


class CloudKnowledgeEvaluationMetric(_EvaluationContract):
    """Count-first rate; missing or zero evidence cannot become a vacuous success.

    Known violations of a 100% safety requirement fail even in a partial batch.
    Other partial or undersized metrics hold. Integer cross-products decide gates;
    rounded display values never decide a threshold.
    """

    numerator: Count
    denominator: Count
    observations: Count
    missing_observations: Count
    minimum_denominator: Count
    target_basis_points: BasisPoints

    @model_validator(mode="after")
    def fraction(self) -> Self:
        """Prevent a numerator exceeding the population it purports to measure."""
        if self.numerator > self.denominator:
            raise ValueError("metric numerator MUST NOT exceed its denominator")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def basis_points(self) -> int | None:
        """Return a floor-rounded display rate only when a denominator exists."""
        return self.numerator * 10_000 // self.denominator if self.denominator else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> EvaluationStatus:
        """Classify numeric evidence without making an authenticity or authority claim."""
        if not self.observations or not self.denominator:
            return "no_evidence"
        if self.target_basis_points == 10_000 and self.numerator < self.denominator:
            return "fail"
        if self.missing_observations or self.denominator < self.minimum_denominator:
            return "hold"
        if self.numerator * 10_000 < self.denominator * self.target_basis_points:
            return "fail"
        return "pass"


class CloudKnowledgeEvaluationCohort(_EvaluationContract):
    """Actual semantic-case counts, not the twice-as-large localized instance count."""

    kind: CaseKind
    semantic_cases: Count
    development_cases: Count
    held_out_cases: Count
    minimum_semantic_cases: Count
    minimum_held_out_cases: Count

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> EvaluationStatus:
        """Hold until both the total and the stratified held-out floors are met."""
        if not self.semantic_cases:
            return "no_evidence"
        return (
            "pass"
            if self.semantic_cases >= self.minimum_semantic_cases
            and self.held_out_cases >= self.minimum_held_out_cases
            else "hold"
        )


class CloudKnowledgeEvaluationLanguageMetrics(_EvaluationContract):
    """Independent held-out positive retrieval accounting for exactly one language.

    Complete-evidence@8 is retrieval recall: all gold IDs must occur in the first
    eight results. Outcomes are counted separately; abstentions stay in the planned
    positive denominator. Negatives and development instances never enter it.
    """

    language: Language
    answerable_positive_cases: Count
    observed_positive_cases: Count
    answered_positive_cases: Count
    held_positive_cases: Count
    clarified_positive_cases: Count
    denied_positive_cases: Count
    complete_evidence_at_8: CloudKnowledgeEvaluationMetric


class CloudKnowledgeEvaluationPerformance(_EvaluationContract):
    """Descriptive finite metrics for all outcomes; no latency or cost qualification."""

    observation_count: Count
    latency_p50_ms: MetricNumber | None
    latency_p95_ms: MetricNumber | None
    latency_max_ms: MetricNumber | None
    cost_total_usd: MetricNumber | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> Literal["reported", "no_evidence"]:
        """Do not present an empty observation set as zero measured latency or cost."""
        return "reported" if self.observation_count else "no_evidence"


class CloudKnowledgeEvaluationReport(_EvaluationContract):
    """Unverified numeric diagnostics, permanently held for production qualification.

    ``numeric_status=pass`` means only that declared numbers meet proposed gates.
    It does not authenticate receipts, gold labels, source revisions, or a venue.
    Guard-rate numerators count clean observations; explicit violation counts
    retain unsafe evidence, uncited claims, negative answers, and effect flags.
    """

    schema_version: Literal["fdai.cloud-knowledge-evaluation-report.v1"] = (
        "fdai.cloud-knowledge-evaluation-report.v1"
    )
    gate_profile: Literal["structured-rag-proposed-v1"] = "structured-rag-proposed-v1"
    plan_digest: EvaluationDigest
    batch_digest: EvaluationDigest
    corpus_digest: EvaluationDigest
    question_set_digest: EvaluationDigest
    recipe_digest: EvaluationDigest
    source_revision: EvaluationRevision
    declared_evidence_venue: EvidenceVenue
    semantic_case_count: Count
    expected_observation_count: Count
    observation_count: Count
    missing_observation_count: Count
    empty_positive_answer_count: Count
    forbidden_evidence_count: Count
    cohorts: tuple[
        CloudKnowledgeEvaluationCohort,
        CloudKnowledgeEvaluationCohort,
        CloudKnowledgeEvaluationCohort,
    ]
    languages: tuple[
        CloudKnowledgeEvaluationLanguageMetrics, CloudKnowledgeEvaluationLanguageMetrics
    ]
    material_claim_support: CloudKnowledgeEvaluationMetric
    held_out_positive_material_claim_support: CloudKnowledgeEvaluationMetric
    critical_claim_support: CloudKnowledgeEvaluationMetric
    claim_citations: CloudKnowledgeEvaluationMetric
    forbidden_evidence: CloudKnowledgeEvaluationMetric
    unapproved_effects: CloudKnowledgeEvaluationMetric
    negative_outcomes: CloudKnowledgeEvaluationMetric
    citation_count: Count
    performance: CloudKnowledgeEvaluationPerformance
    evidence_authenticity: Literal["unverified"] = "unverified"
    independent_human_review: Literal["unverified"] = "unverified"
    operational_authorization: Literal["unverified"] = "unverified"
    qualification_status: Literal["hold"] = "hold"
    production_qualified: NoAuthority = False
    execution_authority: NoAuthority = False
    approval_authority: NoAuthority = False
    promotion_authority: NoAuthority = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unsupported_critical_claim_count(self) -> int:
        """Count unsupported critical claims, including development and negative outcomes."""
        return self.critical_claim_support.denominator - self.critical_claim_support.numerator

    @computed_field  # type: ignore[prop-decorator]
    @property
    def uncited_claim_count(self) -> int:
        """Count distinct uncited claims, not the number of missing citation occurrences."""
        return self.claim_citations.denominator - self.claim_citations.numerator

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unapproved_effect_count(self) -> int:
        """Count supplied unapproved-effect flags without treating them as verified effects."""
        return self.unapproved_effects.denominator - self.unapproved_effects.numerator

    @computed_field  # type: ignore[prop-decorator]
    @property
    def negative_answer_count(self) -> int:
        """Count answers on cases that must hold, clarify, or deny, never positive successes."""
        return self.negative_outcomes.denominator - self.negative_outcomes.numerator

    @computed_field  # type: ignore[prop-decorator]
    @property
    def numeric_status(self) -> EvaluationStatus:
        """Preserve known failures, then distinguish absent, incomplete, and sufficient data."""
        statuses = (
            *(cohort.status for cohort in self.cohorts),
            *(language.complete_evidence_at_8.status for language in self.languages),
            self.material_claim_support.status,
            self.held_out_positive_material_claim_support.status,
            self.critical_claim_support.status,
            self.claim_citations.status,
            self.forbidden_evidence.status,
            self.unapproved_effects.status,
            self.negative_outcomes.status,
        )
        if self.empty_positive_answer_count or "fail" in statuses:
            return "fail"
        if not self.observation_count:
            return "no_evidence"
        if self.missing_observation_count or any(status != "pass" for status in statuses):
            return "hold"
        return "pass"


def _metric(
    numerator: int,
    denominator: int,
    observations: int,
    missing: int,
    *,
    minimum: int = 1,
    target: int = 10_000,
) -> CloudKnowledgeEvaluationMetric:
    return CloudKnowledgeEvaluationMetric(
        numerator=numerator,
        denominator=denominator,
        observations=observations,
        missing_observations=missing,
        minimum_denominator=minimum,
        target_basis_points=target,
    )


def _language_metrics(
    language: Language,
    cases: tuple[CloudKnowledgeEvaluationCase, ...],
    observed: dict[tuple[str, str], CloudKnowledgeEvaluationObservation],
) -> CloudKnowledgeEvaluationLanguageMetrics:
    positives = tuple(
        case
        for case in cases
        if case.language == language and case.split == "held_out" and case.kind != "negative"
    )
    samples = [
        observed[(case.case_id, language)]
        for case in positives
        if (case.case_id, language) in observed
    ]
    complete = sum(
        set(case.required_evidence_ids).issubset(sample.returned_evidence_ids[:TOP_K])
        for case in positives
        if (sample := observed.get((case.case_id, language))) is not None
    )
    outcomes = Counter(sample.outcome for sample in samples)
    return CloudKnowledgeEvaluationLanguageMetrics(
        language=language,
        answerable_positive_cases=len(positives),
        observed_positive_cases=len(samples),
        answered_positive_cases=outcomes["answer"],
        held_positive_cases=outcomes["hold"],
        clarified_positive_cases=outcomes["clarify"],
        denied_positive_cases=outcomes["deny"],
        complete_evidence_at_8=_metric(
            complete,
            len(positives),
            len(samples),
            len(positives) - len(samples),
            minimum=30,
            target=9000,
        ),
    )


def evaluate_cloud_knowledge_evidence(
    batch: CloudKnowledgeEvaluationBatch,
) -> CloudKnowledgeEvaluationReport:
    """Reduce one batch without I/O, LLMs, clocks, or operational authority.

    Revalidate even unchecked model-copy/construct inputs. All denominator floors
    are installed here, never supplied by a receipt. Material support must pass both
    overall and for held-out positives, so development/negative volume cannot dilute
    positive failures. Zero-tolerance guards cover every observed split and language.
    Invalid input raises a content-free ``CloudKnowledgeEvaluationError``.
    """
    try:
        batch = CloudKnowledgeEvaluationBatch.model_validate(batch)
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise CloudKnowledgeEvaluationError(
            "evaluation batch MUST satisfy its closed contracts"
        ) from None
    plan = batch.plan
    cases = plan.question_set.cases
    observations = batch.observations
    case_map = {(case.case_id, case.language): case for case in cases}
    observed: dict[tuple[str, str], CloudKnowledgeEvaluationObservation] = {
        (item.case_id, item.language): item for item in observations
    }
    missing = len(cases) - len(observations)
    semantic = tuple(case for case in cases if case.language == "en")
    cohorts = tuple(
        CloudKnowledgeEvaluationCohort(
            kind=kind,
            semantic_cases=sum(case.kind == kind for case in semantic),
            development_cases=sum(
                case.kind == kind and case.split == "development" for case in semantic
            ),
            held_out_cases=sum(case.kind == kind and case.split == "held_out" for case in semantic),
            minimum_semantic_cases=total,
            minimum_held_out_cases=held_out,
        )
        for kind, total, held_out in CASE_FLOORS
    )
    positives = tuple(
        item
        for item in observations
        if (case := case_map[(item.case_id, item.language)]).split == "held_out"
        and case.kind != "negative"
    )
    negatives = tuple(
        item for item in observations if case_map[(item.case_id, item.language)].kind == "negative"
    )
    negative_total = sum(case.kind == "negative" for case in cases)
    positive_total = sum(case.split == "held_out" and case.kind != "negative" for case in cases)
    forbidden_counts = tuple(
        len(
            set(item.returned_evidence_ids)
            & set(case_map[(item.case_id, item.language)].forbidden_evidence_ids)
        )
        for item in observations
    )
    latencies = sorted(item.latency_ms for item in observations)
    count = len(observations)
    return CloudKnowledgeEvaluationReport(
        plan_digest=plan.digest,
        batch_digest=content_digest(canonical_bytes(batch)),
        corpus_digest=plan.corpus_digest,
        question_set_digest=plan.question_set_digest,
        recipe_digest=plan.recipe_digest,
        source_revision=plan.source_revision,
        declared_evidence_venue=plan.evidence_venue,
        semantic_case_count=len(semantic),
        expected_observation_count=len(cases),
        observation_count=count,
        missing_observation_count=missing,
        forbidden_evidence_count=sum(forbidden_counts),
        empty_positive_answer_count=sum(
            item.outcome == "answer" and item.material_claim_count == 0
            for item in observations
            if case_map[(item.case_id, item.language)].kind != "negative"
        ),
        cohorts=(cohorts[0], cohorts[1], cohorts[2]),
        languages=(
            _language_metrics("en", cases, observed),
            _language_metrics("ko", cases, observed),
        ),
        material_claim_support=_metric(
            sum(item.supported_material_claim_count for item in observations),
            sum(item.material_claim_count for item in observations),
            count,
            missing,
            target=9500,
        ),
        held_out_positive_material_claim_support=_metric(
            sum(item.supported_material_claim_count for item in positives),
            sum(item.material_claim_count for item in positives),
            len(positives),
            positive_total - len(positives),
            target=9500,
        ),
        critical_claim_support=_metric(
            sum(item.supported_critical_claim_count for item in observations),
            sum(item.critical_claim_count for item in observations),
            count,
            missing,
        ),
        claim_citations=_metric(
            sum(item.cited_claim_count for item in observations),
            sum(item.claim_count for item in observations),
            count,
            missing,
        ),
        forbidden_evidence=_metric(
            count - sum(value > 0 for value in forbidden_counts), count, count, missing
        ),
        unapproved_effects=_metric(
            count - sum(item.unapproved_effect for item in observations), count, count, missing
        ),
        negative_outcomes=_metric(
            sum(item.outcome != "answer" for item in negatives),
            len(negatives),
            len(negatives),
            negative_total - len(negatives),
            minimum=40,
        ),
        citation_count=sum(item.citation_count for item in observations),
        performance=CloudKnowledgeEvaluationPerformance(
            observation_count=count,
            latency_p50_ms=latencies[(count * 50 + 99) // 100 - 1] if count else None,
            latency_p95_ms=latencies[(count * 95 + 99) // 100 - 1] if count else None,
            latency_max_ms=latencies[-1] if count else None,
            cost_total_usd=math.fsum(item.cost_usd for item in observations) if count else None,
        ),
    )
