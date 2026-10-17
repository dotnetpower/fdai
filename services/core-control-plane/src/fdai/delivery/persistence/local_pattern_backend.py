"""Reusable, closed-owner LOCAL T1 validation composition; never a runtime bootstrap."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from fdai.core.case_history import CaseHistoryMaterializer
from fdai.core.ontology_platform.pattern_queries import OperatingPatternQuery
from fdai.core.tiers.t1_lightweight.retained_patterns import (
    ActionResolver,
    RequestSource,
    RetainedPatternSource,
)
from fdai.core.tiers.t1_lightweight.tier import (
    EmbeddingModel,
    PatternLibrary,
    T1Config,
    T1Tier,
)
from fdai.shared.contracts.models import OntologyActionType

from .local_pattern_owner import LocalPatternArtifactStore, LocalPatternOwner, local_dsn
from .local_pattern_qualification import LocalPostgresPatternQualifier
from .postgres import PostgresStateStore, PostgresStateStoreConfig
from .state_store_case_history import StateStoreCaseHistoryMetadataStore
from .state_store_decision_evidence import StateStoreDecisionEvidenceAdmissionProvider


class LocalPostgresPatternBackend:
    """Keep every qualified source and all writer interactions in one owning database.

    Source facts and independent gate/recorder admissions must be populated explicitly.
    Missing facts/admissions HOLD. This factory creates no proof, principal permission,
    successful measurement, ActionType, or enabled comparison default.
    """

    def __init__(
        self,
        *,
        dsn: str,
        venue: str,
        read_source_revision: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        pinned = local_dsn(dsn, venue=venue)
        if not read_source_revision.strip():
            raise ValueError("local Pattern backend requires its read source revision")
        self._clock = clock or (lambda: datetime.now(UTC))
        self.store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=pinned))
        self.admission = StateStoreDecisionEvidenceAdmissionProvider(
            store=self.store, clock=self._clock
        )
        self.owner = LocalPatternOwner(store=self.store, admission=self.admission, venue=venue)
        self.metadata = StateStoreCaseHistoryMetadataStore(store=self.store)
        self.artifacts = LocalPatternArtifactStore(store=self.store, venue=venue)
        self.materializer = CaseHistoryMaterializer(
            metadata=self.metadata, artifacts=self.artifacts
        )
        self.qualifier = LocalPostgresPatternQualifier(dsn=pinned, venue=venue, clock=self._clock)
        self.query = OperatingPatternQuery(
            store=self.store,
            materializer=lambda: self.materializer,
            admission=self.admission,
            source_revision=read_source_revision,
            clock=self._clock,
        )

    def tier(
        self,
        *,
        embedding_model: EmbeddingModel,
        baseline_library: PatternLibrary,
        request_source: RequestSource,
        action_resolver: ActionResolver,
        action_types: Callable[[], Mapping[str, OntologyActionType]],
        config: T1Config | None = None,
    ) -> T1Tier:
        source = RetainedPatternSource(
            query=self.query,
            request_source=request_source,
            action_resolver=action_resolver,
            action_types=action_types,
            store=self.store,
            materializer=lambda: self.materializer,
            statistics_source=self.owner.statistics,
            leased_qualifier=self.qualifier,
            clock=self._clock,
        )
        return T1Tier(
            embedding_model=embedding_model,
            pattern_library=baseline_library,
            current_reuse_verifier=self.owner,
            case_history=self.materializer,
            retained_pattern_source=source,
            clock=self._clock,
            config=config,
        )

    async def aclose(self) -> None:
        await self.store.aclose()
