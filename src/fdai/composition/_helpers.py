"""Shared composition types (extracted from composition/__init__.py, G-3).

Contains :class:`Container`, :class:`LlmBindings`, and
:class:`LlmBindingsUnavailableError` - the three types every wire file
needs to import without going through the package facade. Keeping them
in a private submodule prevents circular imports between
``__init__.py`` and the ``wire_*.py`` extractors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..core.browser_evidence.service import BrowserEvidenceCaptureService
from ..core.browser_evidence.surfaces import (
    BrowserEvidenceConsoleTool,
    BrowserEvidenceWorkflowStepDispatcher,
)
from ..core.capability_catalog import CapabilityRuntime
from ..core.execution_backend import ExecutionBackendCoordinator
from ..core.mscp_profile import ExpectedEffectProvider, IndependentEffectObserver
from ..core.quality_gate.critic import CriticModel
from ..core.quality_gate.debate import DebateOrchestrator
from ..core.quality_gate.gate import CrossCheckModel
from ..core.quality_gate.judge import JudgeModel
from ..core.quality_gate.rubric import RubricEvaluator
from ..core.rca import RcaReasoner
from ..core.readiness import StartupProbeResult, StartupProbeSpec
from ..core.tiers.t1_lightweight.tier import EmbeddingModel
from ..core.tiers.t2_reasoning import T2Proposer
from ..core.trajectory import TrajectoryJoinService
from ..core.working_context import ContextSelectionPolicyAuthority
from ..shared.config.models import AppConfig
from ..shared.contracts.models import OntologyLinkType, OntologyObjectType, Workflow
from ..shared.contracts.registry import SchemaRegistry
from ..shared.contracts.validation import ContractValidator, EventValidator
from ..shared.providers.change_feed import ChangeFeed, EmptyChangeFeed
from ..shared.providers.distiller import AbstainingDistiller, Distiller
from ..shared.providers.exemption import ExemptionRegistry
from ..shared.providers.feasibility_probe import FeasibilityProbe
from ..shared.providers.inventory import EmptyInventory, Inventory
from ..shared.providers.knowledge import EmptyKnowledgeSource, KnowledgeSource
from ..shared.providers.log_query import LogQueryProvider, NoopLogQueryProvider
from ..shared.providers.manual_classifier import (
    AbstainingManualClassifier,
    ManualClassifier,
)
from ..shared.providers.manual_source import EmptyManualSource, ManualSource
from ..shared.providers.metric import MetricProvider, NoopMetricProvider
from ..shared.providers.startup_probe import StartupProbe
from ..shared.providers.trace_query import NoopTraceQueryProvider, TraceQueryProvider
from ..shared.providers.trajectory import TrajectoryDatasetStore


class LlmBindingsUnavailableError(RuntimeError):
    """Raised when core code touches LLM bindings that were never attached.

    Fail-close guard: azure-mode containers start with ``llm_bindings=None``
    and MUST be finalized via :func:`bind_azure_llm_bindings`. A caller that
    reaches this exception is running in production without having wired
    the Azure adapters - the process refuses to proceed.
    """


@dataclass(frozen=True, slots=True)
class LlmBindings:
    """Runtime-bound LLM seams handed to core code.

    ``cross_check_models`` MUST contain the number of models the quality
    gate expects to reach quorum (default 2 - see
    :class:`~fdai.core.quality_gate.gate.QualityGateConfig`).

    ``critic_model`` (Wave 4 beta-2) is OPTIONAL. When the
    ``t2.critic`` capability resolves in ``resolved-models.json`` the
    composition root binds a real :class:`CriticModel` here so the
    Wave 4.5 debate orchestrator can consume it; otherwise the
    field stays ``None`` and the flow keeps its pre-Wave-4 shape.

    ``judge_model`` (Wave 4.5 delta-1) is OPTIONAL. Analogous to
    ``critic_model`` but backed by the ``t1.judge`` capability. Kept
    as an independent binding (not derived from ``critic_model``) so
    a fork can bind the Judge without the Critic (e.g. for a
    single-role review pass) or vice versa.

    ``debate_orchestrator`` (Wave 4.5 delta-1) is OPTIONAL and is
    auto-constructed by the composition root **only when both
    ``critic_model`` AND ``judge_model`` are bound**. A fork that
    supplies its own orchestrator implementation (custom max_rounds,
    different transcript store) can pass one in via
    :func:`dataclasses.replace`.

    ``rubric_evaluator`` (hallucination-rubric-gate) is OPTIONAL. When a
    fork resolves the ``t2.rubric.judge`` capability it binds a real
    :class:`RubricEvaluator` here; the composition root then hands it to
    the :class:`~fdai.core.quality_gate.gate.QualityGate` it assembles.
    ``None`` (the upstream default) means the rubric leg is absent - the
    gate behaves exactly as it did before the rubric was added. NOTE:
    upstream does not yet assemble a live ``QualityGate`` into the
    control loop (T2 wiring is shadow-only backlog - see
    ``docs/roadmap/decisioning/hallucination-rubric-gate.md § Integration status``),
    so this seam is provided for symmetry with ``critic_model`` /
    ``judge_model`` and is consumed by a fork's gate assembly.
    """

    embedding_model: EmbeddingModel
    cross_check_models: tuple[CrossCheckModel, ...]
    critic_model: CriticModel | None = None
    judge_model: JudgeModel | None = None
    debate_orchestrator: DebateOrchestrator | None = None
    rca_reasoner: RcaReasoner | None = None
    rubric_evaluator: RubricEvaluator | None = None
    t2_proposer: T2Proposer | None = None

    def __post_init__(self) -> None:
        if not self.cross_check_models:
            raise ValueError("LlmBindings.cross_check_models MUST have at least one entry")
        # Cross-consistency: the orchestrator needs both role models.
        # A caller that manually built LlmBindings without both roles
        # but with an orchestrator has a wiring bug that will surface
        # as a runtime failure inside the orchestrator; catch it here.
        if self.debate_orchestrator is not None and (
            self.critic_model is None or self.judge_model is None
        ):
            raise ValueError(
                "LlmBindings.debate_orchestrator requires both critic_model "
                "and judge_model to be bound"
            )

    def require_t2_proposer(self) -> T2Proposer:
        if self.t2_proposer is None:
            raise LlmBindingsUnavailableError(
                "LlmBindings.t2_proposer is None; T2 reasoning cannot start"
            )
        return self.t2_proposer


@dataclass(frozen=True, slots=True)
class Container:
    """Bag of already-bound seams handed to the rest of the app.

    Immutable so a caller cannot silently rewire a seam mid-flight. A
    fork MAY produce a new :class:`Container` via
    :func:`dataclasses.replace` to substitute individual seams without
    editing ``core/``.
    """

    config: AppConfig
    schema_registry: SchemaRegistry
    contract_validator: ContractValidator
    event_validator: EventValidator
    exemption_registry: ExemptionRegistry
    feasibility_probes: tuple[FeasibilityProbe, ...] = ()
    startup_probe_specs: tuple[StartupProbeSpec, ...] = ()
    startup_probes: tuple[StartupProbe[StartupProbeResult], ...] = ()
    ontology_object_types: tuple[OntologyObjectType, ...] = ()
    ontology_link_types: tuple[OntologyLinkType, ...] = ()
    workflows: tuple[Workflow, ...] = ()
    llm_bindings: LlmBindings | None = field(default=None)
    metric_provider: MetricProvider = field(default_factory=NoopMetricProvider)
    log_query_provider: LogQueryProvider = field(default_factory=NoopLogQueryProvider)
    trace_query_provider: TraceQueryProvider = field(default_factory=NoopTraceQueryProvider)
    inventory: Inventory = field(default_factory=EmptyInventory)
    knowledge_source: KnowledgeSource = field(default_factory=EmptyKnowledgeSource)
    change_feed: ChangeFeed = field(default_factory=EmptyChangeFeed)
    distiller: Distiller = field(default_factory=AbstainingDistiller)
    manual_source: ManualSource = field(default_factory=EmptyManualSource)
    manual_classifier: ManualClassifier = field(default_factory=AbstainingManualClassifier)
    capability_runtime: CapabilityRuntime = field(default_factory=CapabilityRuntime)
    context_selection_policy_authority: ContextSelectionPolicyAuthority | None = None
    trajectory_dataset_store: TrajectoryDatasetStore | None = None
    trajectory_join_service: TrajectoryJoinService | None = None
    mscp_expected_effect_provider: ExpectedEffectProvider | None = None
    mscp_effect_observer: IndependentEffectObserver | None = None
    execution_backend_coordinator: ExecutionBackendCoordinator | None = None
    browser_evidence_capture_service: BrowserEvidenceCaptureService | None = None
    browser_evidence_console_tool: BrowserEvidenceConsoleTool | None = None
    browser_evidence_workflow_dispatcher: BrowserEvidenceWorkflowStepDispatcher | None = None

    def __post_init__(self) -> None:
        if (self.mscp_expected_effect_provider is None) != (self.mscp_effect_observer is None):
            raise ValueError(
                "Container MSCP expected-effect provider and observer MUST be bound together"
            )
        if self.context_selection_policy_authority is None:
            object.__setattr__(
                self,
                "context_selection_policy_authority",
                ContextSelectionPolicyAuthority(capability_runtime=self.capability_runtime),
            )

    def require_llm_bindings(self) -> LlmBindings:
        """Return :attr:`llm_bindings` or raise :class:`LlmBindingsUnavailableError`."""
        if self.llm_bindings is None:
            raise LlmBindingsUnavailableError(
                "Container.llm_bindings is None. In llm.mode='azure' the "
                "entry point MUST call bind_azure_llm_bindings() before "
                "core code invokes the T1/T2 tiers."
            )
        return self.llm_bindings


from ..rule_catalog.schema.llm_resolver import (  # noqa: E402 - appended for helper functions extracted from composition.py
    CapabilityStatus,
    ResolvedCapability,
    ResolvedModels,
)


def _load_resolved_models(path_or_ref: str) -> ResolvedModels:
    """Load ``resolved-models.json``.

    Two shapes are accepted:

    - a filesystem path - used when Container Apps mounts the KV secret
      as a file under ``/mnt/secrets/`` (or when a dev laptop writes the
      resolver output next to the checkout);
    - an inline JSON document - used when the Container App reads the
      secret through a ``secretRef`` env var (no volume-mount extension
      required). Detected by a leading ``{`` after stripping whitespace.

    A future Key-Vault-backed loader lands with the reconciler; for now
    the filesystem / env-var pair covers the day-zero deployment.
    """
    stripped = path_or_ref.strip()
    if stripped.startswith("{"):
        return ResolvedModels.from_json(stripped)
    path = Path(path_or_ref)
    if not path.exists():
        raise LlmBindingsUnavailableError(
            f"resolved-models.json not found at {path_or_ref!r}. "
            "Run the bootstrap resolver first (llm_resolver_cli)."
        )
    return ResolvedModels.from_json(path.read_text(encoding="utf-8"))


def _capability(resolved: ResolvedModels, name: str) -> ResolvedCapability | None:
    """Return the resolved capability iff it is bindable (not hil-only)."""
    for cap in resolved.capabilities:
        if cap.name != name:
            continue
        if cap.status is CapabilityStatus.HIL_ONLY:
            return None
        return cap
    return None


def _default_dim_for_family(family: str) -> int:
    """Return the fixed pgvector dimension for supported embedding families.

    A future resolver revision MAY carry the vector dim on
    ``ResolvedCapability`` directly; today we keep the mapping small.
    """
    if family not in {"text-embedding-3-small", "text-embedding-3-large"}:
        raise LlmBindingsUnavailableError(
            f"embedding family {family!r} does not support the FDAI 384-dimension contract"
        )
    return 384
