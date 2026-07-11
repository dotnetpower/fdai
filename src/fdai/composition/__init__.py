"""Composition root - the ONE place that instantiates concrete implementations.

``core/`` modules never construct adapters; they receive :class:`Container`
instances (or the individual seam Protocols) via arguments. Only entry points
(``__main__``, CLIs, tests) call :func:`default_container` /
:func:`default_container_from_env`. A per-customer fork registers its own
bindings by exposing its own container factory in its composition root -
it MUST NOT edit ``core/`` or patch upstream defaults.

Fail-fast contract
------------------
:func:`default_container` **requires an explicit** :class:`AppConfig`. There
is no implicit env-var read in the primary factory. That way, unit tests
build a config in code (no environment surprises), and only the operator's
entry point calls :func:`default_container_from_env`, which does read the
process environment.

LLM bindings
------------

The container carries an :class:`LlmBindings` that resolves the T1 embedding
model and the T2 cross-check models. In ``llm.mode == 'local-fake'`` (the
default in dev), the composition root binds the deterministic in-memory
fakes from ``core/tiers/t1_lightweight/testing.py`` and
``core/quality_gate/testing.py`` - the pipeline works end-to-end with zero
Azure credentials. In ``llm.mode == 'azure'``, ``Container.llm_bindings``
starts as ``None``; the entry point MUST call :func:`bind_azure_llm_bindings`
with a live :class:`httpx.AsyncClient` and a :class:`WorkloadIdentity` to
attach the real adapters. Attempting to use ``Container.llm_bindings``
before that hand-off raises :class:`LlmBindingsUnavailableError`, so the
process cannot silently degrade to fakes in production.

Design references
-----------------
- ``docs/roadmap/architecture/project-structure.md § Customization via Dependency Injection``
- ``docs/roadmap/deployment/dev-and-deploy-parity.md § Parity Contract``
- ``docs/roadmap/deployment/deploy-and-onboard.md § Runtime Configuration Matrix``
- ``.github/instructions/generic-scope.instructions.md``
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from ..core.metering.pricing import PricingTable
from ..core.quality_gate.testing import MatchTypeCrossCheckModel
from ..core.tiers.t1_lightweight.testing import DeterministicEmbeddingModel
from ..shared.config.loader import load_config_from_env
from ..shared.config.models import AppConfig, LlmMode
from ..shared.contracts.registry import (
    PackageResourceSchemaRegistry,
    SchemaRegistry,
)
from ..shared.contracts.validation import (
    ContractValidator,
    EventValidator,
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from ..shared.providers.change_feed import EmptyChangeFeed  # noqa: F401 - public re-export
from ..shared.providers.exemption import (
    empty_exemption_registry,
)
from ..shared.providers.inventory import EmptyInventory  # noqa: F401 - public re-export
from ..shared.providers.knowledge import (
    EmbeddingKnowledgeSource,
    EmptyKnowledgeSource,  # noqa: F401 - public re-export
    KnowledgeSource,  # noqa: F401 - public re-export
)
from ..shared.providers.metric import NoopMetricProvider  # noqa: F401 - public re-export
from ..shared.providers.workload_identity import WorkloadIdentity

if TYPE_CHECKING:
    from ..delivery.azure.activity_log import AzureActivityLogFactoryConfig
    from ..delivery.azure.arg_query import AzureArgQueryFactoryConfig
    from ..delivery.azure.inventory import AzureInventoryConfig
    from ..delivery.azure.metric_logs import AzureMonitorLogsConfig
    from ..delivery.azure_devops.change_feed import AzureDevOpsChangeFeedConfig
    from ..delivery.github.change_feed import GitHubChangeFeedConfig, TokenProvider
    from ..rule_catalog.schema.resource_type import ResourceTypeRegistry

_LOGGER = logging.getLogger(__name__)


from ._helpers import (  # noqa: E402 - after TYPE_CHECKING block
    Container,
    LlmBindings,
    LlmBindingsUnavailableError,
)


def _local_fake_llm_bindings() -> LlmBindings:
    """Build deterministic fakes for `llm.mode='local-fake'`."""
    return LlmBindings(
        embedding_model=DeterministicEmbeddingModel(),
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="fake-primary"),
            MatchTypeCrossCheckModel(model_id="fake-secondary"),
        ),
    )


def default_container(config: AppConfig) -> Container:
    """Return the upstream default binding of every seam.

    The caller MUST hand in an already-validated :class:`AppConfig`. Building
    one from the process environment is the entry point's job - see
    :func:`default_container_from_env`.

    A fork MAY:

    - construct a :class:`Container` with a different :class:`SchemaRegistry`
      (e.g. a remote registry adapter),
    - or wrap :func:`default_container` and override individual fields via
      :func:`dataclasses.replace`.

    This function MUST NOT be called from within ``core/``.
    """
    registry: SchemaRegistry = PackageResourceSchemaRegistry()
    contract_v: ContractValidator = JsonSchemaContractValidator(registry)
    event_v: EventValidator = JsonSchemaEventValidator(contract_v)
    llm = _local_fake_llm_bindings() if config.llm.mode == LlmMode.LOCAL_FAKE else None
    return Container(
        config=config,
        schema_registry=registry,
        contract_validator=contract_v,
        event_validator=event_v,
        exemption_registry=empty_exemption_registry(),
        feasibility_probes=(),
        llm_bindings=llm,
    )


def bind_azure_monitor_logs(
    container: Container,
    *,
    config: AzureMonitorLogsConfig,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
) -> Container:
    """Return a new :class:`Container` with the live Azure Monitor Logs
    metric adapter bound in place of the default :class:`NoopMetricProvider`.

    Kept symmetric to :func:`bind_azure_llm_bindings`: an entry point that
    runs against real Azure telemetry constructs the adapter and swaps it
    in via :func:`dataclasses.replace`. Dev / local-fake runs never call
    this, so ``container.metric_provider`` stays the no-op default and the
    dev-to-deploy parity contract holds. ``core/`` never imports the
    concrete adapter - only this composition-root helper does.
    """
    from ..delivery.azure.metric_logs import AzureMonitorLogsMetricProvider

    provider = AzureMonitorLogsMetricProvider(
        config=config,
        identity=identity,
        http_client=http_client,
    )
    return replace(container, metric_provider=provider)


def bind_azure_inventory(
    container: Container,
    *,
    arg_config: AzureArgQueryFactoryConfig,
    inventory_config: AzureInventoryConfig,
    resource_types: ResourceTypeRegistry,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    activity_log_config: "AzureActivityLogFactoryConfig | None" = None,
) -> Container:
    """Return a new :class:`Container` with the live Azure Resource Graph
    inventory bound in place of the default :class:`EmptyInventory`.

    Wires the real Kusto-over-ARG :class:`AzureArgQueryFactory` (from
    ``delivery/azure/arg_query.py``) into the
    :class:`AzureResourceGraphInventory` shard runner - the pairing that
    was documented but never assembled. Kept symmetric to
    :func:`bind_azure_monitor_logs` and :func:`bind_azure_llm_bindings`:
    dev / local-fake runs never call this, so ``container.inventory``
    stays the empty default and the parity contract holds. ``core/``
    never imports the concrete adapter.

    The ``full_snapshot`` path is live once bound. When
    ``activity_log_config`` is supplied, the ``delta`` path is also live:
    an :class:`AzureActivityLogFactory` builds the forwarded-Activity-Log
    fetch function so :meth:`AzureResourceGraphInventory.delta` streams
    real change batches. When it is ``None``, ``delta`` stays the
    empty-fence stub (see ``docs/roadmap/architecture/csp-neutrality.md § 5``).
    """
    from ..delivery.azure.arg_query import AzureArgQueryFactory
    from ..delivery.azure.inventory import AzureResourceGraphInventory

    query_fn = AzureArgQueryFactory(
        identity=identity,
        resource_types=resource_types,
        http_client=http_client,
        config=arg_config,
    ).build_query_fn()

    delta_fetch = None
    if activity_log_config is not None:
        from ..delivery.azure.activity_log import AzureActivityLogFactory

        delta_fetch = AzureActivityLogFactory(
            identity=identity,
            resource_types=resource_types,
            http_client=http_client,
            config=activity_log_config,
        ).build_fetch_fn()

    inventory = AzureResourceGraphInventory(
        config=inventory_config,
        query=query_fn,
        delta_fetch=delta_fetch,
    )
    return replace(container, inventory=inventory)


def bind_embedding_knowledge_source(
    container: Container,
    *,
    max_chars: int = 1_200,
    overlap: int = 150,
) -> Container:
    """Return a new :class:`Container` with an embedding-backed
    :class:`KnowledgeSource` in place of the default
    :class:`EmptyKnowledgeSource`.

    Reuses the already-bound embedding model from ``llm_bindings`` (Azure
    OpenAI in deploy mode, the deterministic fake in local-fake), so the
    free-form grounding leg works in both parity modes. The returned
    source starts empty; the entry point ingests documents at startup via
    ``await container.knowledge_source.ingest(...)`` (ingest is async and
    therefore not done inside this sync helper).
    """
    bindings = container.require_llm_bindings()
    source = EmbeddingKnowledgeSource(
        embedder=bindings.embedding_model,
        max_chars=max_chars,
        overlap=overlap,
    )
    return replace(container, knowledge_source=source)


def bind_github_change_feed(
    container: Container,
    *,
    config: GitHubChangeFeedConfig,
    http_client: httpx.AsyncClient,
    token_provider: TokenProvider,
) -> Container:
    """Return a new :class:`Container` with a live GitHub change feed in
    place of the default :class:`EmptyChangeFeed`.

    Supplies the read-side deploy/commit signal RCA correlates against an
    incident (``correlate_changes``). Dev / local-fake runs keep the empty
    default so no GitHub call is made and the parity contract holds.
    """
    from ..delivery.github.change_feed import GitHubChangeFeed

    feed = GitHubChangeFeed(
        config=config,
        http_client=http_client,
        token_provider=token_provider,
    )
    return replace(container, change_feed=feed)


def bind_azure_devops_change_feed(
    container: Container,
    *,
    config: "AzureDevOpsChangeFeedConfig",
    http_client: httpx.AsyncClient,
    token_provider: "TokenProvider",
) -> Container:
    """Return a new :class:`Container` with a live Azure DevOps change feed
    in place of the default :class:`EmptyChangeFeed`.

    The Azure DevOps counterpart to :func:`bind_github_change_feed`: both
    satisfy the same :class:`~fdai.shared.providers.change_feed.ChangeFeed`
    Protocol, so RCA's ``correlate_changes`` grounding works identically
    whichever VCS a fork runs. Dev / local-fake runs keep the empty default
    so no Azure DevOps call is made and the parity contract holds.
    """
    from ..delivery.azure_devops.change_feed import AzureDevOpsChangeFeed

    feed = AzureDevOpsChangeFeed(
        config=config,
        http_client=http_client,
        token_provider=token_provider,
    )
    return replace(container, change_feed=feed)


def load_pricing_table(path: Path) -> PricingTable:
    """Load an LLM :class:`PricingTable` from a ``llm-pricing.yaml`` file.

    The file's top-level ``models`` mapping is passed to
    :meth:`PricingTable.from_mapping`; ``schema_version`` and any other
    top-level keys are ignored. Raises :class:`ValueError` on a malformed
    file so a bad price table is caught at composition time, not at bill
    time. A fork calls this to build the table it injects via
    :attr:`AzureWireOverrides.pricing`.
    """
    import yaml  # local import: only the composition root reads config files

    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, Mapping):
        raise ValueError(f"pricing file {path} MUST contain a mapping")
    models = raw.get("models")
    if not isinstance(models, Mapping):
        raise ValueError(f"pricing file {path} MUST declare a 'models' mapping")
    return PricingTable.from_mapping(models)


def default_container_from_env() -> Container:
    """Entry-point convenience: load config from env, then bind every seam.

    A missing / invalid env raises :class:`fdai.shared.config.ConfigError`
    with every problem listed. Never returns a partially-built container.

    Side-effect: configures process-wide telemetry (JSON logging + OTel
    tracer/meter providers) before returning. Idempotent.

    ``FDAI_LOG_LEVEL`` (default ``INFO``) picks the root logger level so
    a fork can dial verbosity without editing code. Unrecognized values
    fall back to ``INFO`` rather than failing startup - telemetry is a
    diagnostic, not a control-loop dependency.
    """
    config = load_config_from_env()
    # Wire telemetry once, before any provider emits log or span.
    import logging
    import os

    from ..shared.telemetry.setup import configure_telemetry

    level_name = os.environ.get("FDAI_LOG_LEVEL", "INFO").upper().strip()
    level = getattr(logging, level_name, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO
    configure_telemetry(config, level=level)
    return default_container(config)


# G-3 extractions - keep public API by re-exporting from wire files.
# noqa E402 justified: wire_azure imports back from this package so the
# re-export MUST land after every public symbol is defined; moving it to
# the top of the file creates a circular import.
from .wire_azure import AzureWireOverrides, wire_azure_container  # noqa: E402
from .wire_llm import bind_azure_llm_bindings  # noqa: E402

__all__ = [
    "AzureWireOverrides",
    "Container",
    "LlmBindings",
    "LlmBindingsUnavailableError",
    "bind_azure_llm_bindings",
    "default_container",
    "default_container_from_env",
    "load_pricing_table",
    "wire_azure_container",
]
