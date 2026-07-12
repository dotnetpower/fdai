"""Typed configuration models.

Mirrors ``src/fdai/shared/config/schema.json``. The JSON Schema is the
source of truth for validation at the config-load boundary; these pydantic
models are the typed programmatic view used inside the process.

Design rules (see ``coding-conventions.instructions.md``):

- Frozen, ``extra='forbid'`` - no runtime mutation, no drift from schema.
- Fields default only where the schema does; a required field with no default
  MUST make ``AppConfig.model_validate`` fail-closed.
- No secret material lives here - only *references* (``keyvault_url`` etc.
  land in a later phase). Secrets are read through the ``SecretProvider``
  seam, never through :class:`AppConfig`.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from fdai.shared.contracts.models import Mode, SemVer

# Keep the module import surface minimal - ``Mode`` (autonomy mode) is reused
# so an ``autonomy_mode_default`` sits in the same vocabulary as
# ``Event.mode`` / ``Action.mode`` and cannot drift out of sync.


class _ConfigBase(BaseModel):
    """Shared config-model settings."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class AzureConfig(_ConfigBase):
    tenant_id: UUID
    subscription_id: UUID
    resource_group: Annotated[str, Field(min_length=1, max_length=90)] = "rg-fdai"
    region: Annotated[str, Field(min_length=2, max_length=32)]


class KafkaSecurityProtocol(_ConfigBase):
    pass  # placeholder; kept explicit for future non-str security config


class KafkaConfig(_ConfigBase):
    bootstrap_servers: Annotated[str, Field(min_length=1)]
    security_protocol: str = "SASL_SSL"
    sasl_mechanism: str = "OAUTHBEARER"
    topic_events: Annotated[str, Field(min_length=1)]
    topic_dlq_suffix: Annotated[str, Field(pattern=r"^\.[a-z][a-z0-9._-]{1,63}$")] = ".dlq"


class PostgresConfig(_ConfigBase):
    host: Annotated[str, Field(min_length=1)]
    database: Annotated[str, Field(min_length=1)]


class RuleCatalogConfig(_ConfigBase):
    ref: Annotated[str, Field(min_length=1)] = "main"


class RuntimeEnv:  # noqa: D401 - tiny wrapper so pydantic keeps a real enum
    """Container for the runtime env values so users import a single symbol."""

    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"

    ALL = ("dev", "staging", "prod")


class RuntimeConfig(_ConfigBase):
    env: Annotated[str, Field(pattern=r"^(dev|staging|prod)$")]
    autonomy_mode_default: Mode = Mode.SHADOW


class LlmMode:
    """Container for llm.mode values so callers import a single symbol."""

    LOCAL_FAKE = "local-fake"
    AZURE = "azure"

    ALL = ("local-fake", "azure")


_DEFAULT_LLM_CAPABILITIES: tuple[str, ...] = (
    "t1.embedding",
    "t1.judge",
    "t2.reasoner.primary",
    "t2.reasoner.secondary",
)


class LlmConfig(_ConfigBase):
    """LLM binding mode + optional resolved-models pointer.

    Governs which composition-root bindings are used (deterministic fake vs
    Azure adapter). See docs/roadmap/deployment/dev-and-deploy-parity.md § Parity
    Contract. ``mode='azure'`` MUST supply ``resolved_models_path``; the
    validator refuses partial config so the process never starts in a
    half-bound state.
    """

    mode: Annotated[str, Field(pattern=r"^(local-fake|azure)$")] = LlmMode.LOCAL_FAKE
    resolved_models_path: Annotated[str, Field(min_length=1)] | None = None
    capabilities: tuple[str, ...] = _DEFAULT_LLM_CAPABILITIES
    t2_primary_latency_routing: bool = True
    """Latency routing of the T2 primary proposer among its same-publisher
    candidate pool (invariant-safe). Enforced on by default; takes effect
    only when ``resolved-models.json`` carries >= 2
    ``reasoner_primary_candidates`` (which the resolver emits with
    ``--emit-primary-pool``). A fork sets this ``false`` to pin the single
    most-preferred primary. See
    docs/roadmap/architecture/llm-strategy.md § T2 Primary Latency Pool."""

    def model_post_init(self, __context: object) -> None:
        if self.mode == LlmMode.AZURE and not self.resolved_models_path:
            raise ValueError(
                "llm.mode='azure' requires llm.resolved_models_path - cannot "
                "load Azure adapters without the resolver output"
            )
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("llm.capabilities MUST NOT contain duplicates")
        for cap in self.capabilities:
            if not cap or "." not in cap:
                raise ValueError(
                    f"llm.capabilities entry {cap!r} MUST match "
                    "'<tier>.<name>' (e.g. 't1.embedding')"
                )


class AppConfig(_ConfigBase):
    """Root configuration object handed to :class:`Container`.

    Instances are frozen; a caller that needs to alter one MUST build a new
    :class:`AppConfig` via :meth:`pydantic.BaseModel.model_copy` with
    ``update=...``, so the change is explicit and reviewable.
    """

    schema_version: SemVer
    azure: AzureConfig
    kafka: KafkaConfig
    postgres: PostgresConfig
    rule_catalog: RuleCatalogConfig = Field(default_factory=RuleCatalogConfig)
    runtime: RuntimeConfig
    llm: LlmConfig = Field(default_factory=LlmConfig)


__all__ = [
    "AppConfig",
    "AzureConfig",
    "KafkaConfig",
    "LlmConfig",
    "LlmMode",
    "PostgresConfig",
    "RuleCatalogConfig",
    "RuntimeConfig",
    "RuntimeEnv",
]
