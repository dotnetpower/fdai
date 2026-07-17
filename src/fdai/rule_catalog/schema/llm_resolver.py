"""Bootstrap resolver - deployer-scoped LLM capability resolution.

Pure-function core; SDK bindings sit at the edges. Given a
:class:`~fdai.rule_catalog.schema.llm_registry.LlmRegistry` and three
:class:`Protocol`-shaped query surfaces (catalog / permission / quota),
:func:`resolve` picks one deployment per capability, enforces the five
deployer-permission gates from
[dev-and-deploy-parity.md § Deployer-Scoped LLM Provisioning](
../../../../docs/roadmap/deployment/dev-and-deploy-parity.md#deployer-scoped-llm-provisioning),
and returns a deterministic :class:`ResolvedModels` record ready for
serialization to ``resolved-models.json``.

Rules the resolver enforces (MUST):

- **Missing deployer principal or missing `Cognitive Services Contributor`
  role** on the target subscription: every capability degrades to
  ``hil-only``; the resolver DOES NOT raise (fork can grant the role
  later and re-run). No LLM deployment is proposed.
- **Region missing every preferred family** for a capability: that
  capability degrades to ``hil-only``; others keep going.
- **Insufficient quota**: reduce to the largest available capacity that
  is at least 20% of the requested ``capacity_tpm``; below that floor,
  refuse and mark ``hil-only``.
- **Mixed-model invariant** (`t2.reasoner.primary.publisher !=
  t2.reasoner.secondary.publisher`) after resolution: raise
  :class:`ResolverError` - do NOT partially deploy a T2 tier that would
  fail the quality gate.

The output is deterministic: same registry + region + subscription +
catalog snapshot → identical :class:`ResolvedModels`. That is what makes
the CI idempotency gate meaningful.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from fdai.rule_catalog.schema.llm_endpoint_projection import (
    _capability_to_dict,
    _narrator_from_dict,
    _narrator_to_dict,
)
from fdai.rule_catalog.schema.llm_endpoint_selection import (
    collect_narrator,
    collect_narrator_deployments,
    collect_primary_candidates,
    collect_primary_deployments,
    narrator_deployment_name,
    reasoner_primary_deployment_name,
)
from fdai.rule_catalog.schema.llm_registry import (
    LlmRegistry,
    MixedModelMode,
)
from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle, ModelEndpointBinding

_MIN_QUOTA_RATIO = 0.2
"""Floor: challenger capacity must be at least this share of requested."""


class ResolverError(RuntimeError):
    """Raised when a hard invariant fails (e.g. mixed-model publishers)."""


class CapabilityStatus(StrEnum):
    RESOLVED = "resolved"
    """A deployment is provisioned for this capability."""

    HIL_ONLY = "hil-only"
    """No deployment; the tier's traffic MUST route to HIL."""

    CAPACITY_REDUCED = "capacity-reduced"
    """A deployment is provisioned with reduced capacity_tpm."""


# ---------------------------------------------------------------------------
# DI seams - three tiny Protocols so tests never need Azure SDKs.
# ---------------------------------------------------------------------------


@runtime_checkable
class CatalogQuery(Protocol):
    """Which model families are available in the target region."""

    def families_in_region(self, region: str) -> set[str]: ...


@runtime_checkable
class PermissionQuery(Protocol):
    """Whether the deployer holds provisioning permission on the subscription."""

    def principal_has_cognitive_services_contributor(
        self, *, subscription_id: str, principal_object_id: str
    ) -> bool: ...


@runtime_checkable
class QuotaQuery(Protocol):
    """Available capacity_tpm for (region, publisher, family) - 0 = none."""

    def available_capacity_tpm(self, *, region: str, publisher: str, family: str) -> int: ...


@runtime_checkable
class ProvisionedCapacityQuery(Protocol):
    """Available deployable PTUs after both quota and service capacity checks."""

    def available_capacity_ptu(
        self,
        *,
        region: str,
        publisher: str,
        family: str,
        sku: str,
    ) -> int: ...


# ---------------------------------------------------------------------------
# Frozen output records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedCapability:
    """One capability's resolution outcome."""

    name: str
    status: CapabilityStatus
    publisher: str | None
    family: str | None
    sku: str | None
    capacity_tpm: int
    invocation: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    """Human-readable breadcrumbs written into the audit entry."""

    capacity_unit: str = "tpm"
    capacity_value: int | None = None

    def __post_init__(self) -> None:
        if self.capacity_unit not in {"tpm", "ptu"}:
            raise ValueError("resolved capability capacity_unit MUST be tpm or ptu")
        if self.capacity_unit == "ptu" and self.capacity_tpm != 0:
            raise ValueError("PTU capability MUST NOT populate capacity_tpm")
        if self.capacity_value is not None and self.capacity_value < 0:
            raise ValueError("resolved capability capacity_value MUST be non-negative")


@dataclass(frozen=True, slots=True)
class NarratorCandidate:
    """One deployable narrator endpoint (matches the console chat backend seam)."""

    endpoint: str
    deployment: str
    api_version: str = "2024-08-01-preview"
    api_style: ModelApiStyle = ModelApiStyle.AZURE_OPENAI
    auth_audience: str = "https://cognitiveservices.azure.com/.default"


@dataclass(frozen=True, slots=True)
class ResolvedModels:
    """Deterministic serializable resolver output."""

    schema_version: str
    region: str
    subscription_id: str
    deployer_object_id: str
    mixed_model_mode: str
    capabilities: tuple[ResolvedCapability, ...]
    narrator: NarratorCandidate | None = None
    """Winning single narrator - what a single-model chat backend uses."""

    narrator_candidates: tuple[NarratorCandidate, ...] = ()
    """All viable narrator deployments - what the latency-routed backend uses.

    Populated by :func:`collect_narrator` when the CLI is given a
    ``--narrator-endpoint``. The list is ordered by the registry's
    preference order (fastest / most-preferred family first). When
    empty, the read-api chat backend falls back to :attr:`narrator`
    (single-narrator path) or a deterministic answerer.
    """

    reasoner_primary_candidates: tuple[NarratorCandidate, ...] = ()
    """Same-publisher latency pool for the T2 primary proposer (opt-in).

    Populated by :func:`collect_primary_candidates`. When present with
    >= 2 entries AND ``llm.t2_primary_latency_routing`` is enabled,
    composition wraps the primary ``CrossCheckModel`` in a
    :class:`LatencyRoutedCrossCheckModel`; otherwise the single primary
    binds unchanged. Every candidate shares one publisher by the
    :func:`collect_primary_candidates` guard, so the mixed-model
    invariant (primary.publisher != secondary.publisher) is preserved -
    see docs/roadmap/architecture/llm-strategy.md § T2 Primary Latency Pool.
    """

    endpoint_bindings: tuple[ModelEndpointBinding, ...] = ()
    """Verified direct or gateway endpoint bindings.

    Optional for schema-v1 compatibility. When absent, existing Azure
    composition continues to use the legacy endpoint plus deployment fields.
    """

    def __post_init__(self) -> None:
        binding_ids = [binding.binding_id for binding in self.endpoint_bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("resolved model endpoint binding ids MUST be unique")
        capabilities = [binding.capability for binding in self.endpoint_bindings]
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("resolved model endpoint capabilities MUST be unique")

    def to_json(self) -> str:
        """JSON with sorted keys - same input yields the same bytes.

        ``narrator`` and ``narrator_candidates`` are only emitted when
        populated so pre-existing golden files stay byte-identical when
        the caller does not opt in to narrator collection.
        """
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "region": self.region,
            "subscription_id": self.subscription_id,
            "deployer_object_id": self.deployer_object_id,
            "mixed_model_mode": self.mixed_model_mode,
            "capabilities": [_capability_to_dict(c) for c in self.capabilities],
        }
        if self.narrator is not None:
            payload["narrator"] = _narrator_to_dict(self.narrator)
        if self.narrator_candidates:
            payload["narrator_candidates"] = [
                _narrator_to_dict(n) for n in self.narrator_candidates
            ]
        if self.reasoner_primary_candidates:
            payload["reasoner_primary_candidates"] = [
                _narrator_to_dict(n) for n in self.reasoner_primary_candidates
            ]
        if self.endpoint_bindings:
            payload["endpoint_bindings"] = [
                binding.to_dict()
                for binding in sorted(self.endpoint_bindings, key=lambda item: item.capability)
            ]
        return json.dumps(payload, sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> ResolvedModels:
        raw = json.loads(text)
        return cls(
            schema_version=str(raw["schema_version"]),
            region=str(raw["region"]),
            subscription_id=str(raw["subscription_id"]),
            deployer_object_id=str(raw["deployer_object_id"]),
            mixed_model_mode=str(raw["mixed_model_mode"]),
            capabilities=tuple(
                ResolvedCapability(
                    name=str(c["name"]),
                    status=CapabilityStatus(c["status"]),
                    publisher=c.get("publisher"),
                    family=c.get("family"),
                    sku=c.get("sku"),
                    capacity_tpm=int(c["capacity_tpm"]),
                    invocation=str(c["invocation"]),
                    reasons=tuple(str(r) for r in c.get("reasons", ())),
                    capacity_unit=str(c.get("capacity", {}).get("unit", "tpm")),
                    capacity_value=(
                        int(c["capacity"]["value"]) if isinstance(c.get("capacity"), dict) else None
                    ),
                )
                for c in raw["capabilities"]
            ),
            narrator=_narrator_from_dict(raw.get("narrator")),
            narrator_candidates=tuple(
                _narrator_from_dict(n)  # type: ignore[misc]
                for n in raw.get("narrator_candidates", ())
                if isinstance(n, dict)
            ),
            reasoner_primary_candidates=tuple(
                _narrator_from_dict(n)  # type: ignore[misc]
                for n in raw.get("reasoner_primary_candidates", ())
                if isinstance(n, dict)
            ),
            endpoint_bindings=tuple(
                ModelEndpointBinding.from_dict(binding)
                for binding in raw.get("endpoint_bindings", ())
                if isinstance(binding, dict)
            ),
        )


# ---------------------------------------------------------------------------
# Core resolver
# ---------------------------------------------------------------------------


def resolve(
    *,
    registry: LlmRegistry,
    region: str,
    subscription_id: str,
    deployer_object_id: str,
    catalog: CatalogQuery,
    permission: PermissionQuery,
    quota: QuotaQuery,
    provisioned_capacity: ProvisionedCapacityQuery | None = None,
    tool_calling_families: frozenset[str] | None = None,
) -> ResolvedModels:
    """Produce a :class:`ResolvedModels` for the target deployment.

    Never raises for "environmental" failures (missing role, missing
    family, low quota) - those degrade the affected capability to
    ``hil-only`` and continue. Raises :class:`ResolverError` only when
    the mixed-model invariant cannot hold at deployment time.

    ``tool_calling_families`` is the optional set of families the target
    region catalog reports as function-calling capable. When supplied, a
    capability with ``tool_calling_required=True`` whose chosen family is
    not in the set degrades to ``hil-only`` (a family that cannot call
    tools would break ``web.search`` at runtime). ``None`` skips the check
    entirely, so existing callers that do not probe tool-calling support
    keep their behavior.
    """
    has_perm = permission.principal_has_cognitive_services_contributor(
        subscription_id=subscription_id,
        principal_object_id=deployer_object_id,
    )
    catalog_families = catalog.families_in_region(region)

    entries: list[ResolvedCapability] = []
    # Sort capabilities by name so the output is deterministic regardless
    # of dict iteration order in the source YAML.
    for name in sorted(registry.models):
        spec = registry.models[name]
        if not has_perm:
            entries.append(
                ResolvedCapability(
                    name=name,
                    status=CapabilityStatus.HIL_ONLY,
                    publisher=None,
                    family=None,
                    sku=None,
                    capacity_tpm=0,
                    invocation=spec.invocation.value,
                    reasons=(
                        f"deployer_lacks_cognitive_services_contributor:sub={subscription_id}",
                    ),
                )
            )
            continue

        chosen_pub: str | None = None
        chosen_family: str | None = None
        for pref in spec.preferences:
            if pref.family in catalog_families:
                chosen_pub = pref.publisher
                chosen_family = pref.family
                break
        if chosen_family is None:
            entries.append(
                ResolvedCapability(
                    name=name,
                    status=CapabilityStatus.HIL_ONLY,
                    publisher=None,
                    family=None,
                    sku=None,
                    capacity_tpm=0,
                    invocation=spec.invocation.value,
                    reasons=(
                        f"no_preferred_family_in_region:region={region}:"
                        f"preferences={[p.family for p in spec.preferences]}",
                    ),
                )
            )
            continue

        if (
            spec.tool_calling_required
            and tool_calling_families is not None
            and chosen_family not in tool_calling_families
        ):
            entries.append(
                ResolvedCapability(
                    name=name,
                    status=CapabilityStatus.HIL_ONLY,
                    publisher=chosen_pub,
                    family=chosen_family,
                    sku=None,
                    capacity_tpm=0,
                    invocation=spec.invocation.value,
                    reasons=(f"family_lacks_tool_calling:family={chosen_family}:region={region}",),
                )
            )
            continue

        requested = spec.requested_capacity
        capacity_unit = spec.capacity_unit
        if capacity_unit == "ptu":
            if provisioned_capacity is None:
                entries.append(
                    ResolvedCapability(
                        name=name,
                        status=CapabilityStatus.HIL_ONLY,
                        publisher=chosen_pub,
                        family=chosen_family,
                        sku=spec.sku.value,
                        capacity_tpm=0,
                        invocation=spec.invocation.value,
                        reasons=("provisioned_capacity_query_unavailable",),
                        capacity_unit="ptu",
                        capacity_value=0,
                    )
                )
                continue
            available = provisioned_capacity.available_capacity_ptu(
                region=region,
                publisher=chosen_pub or "",
                family=chosen_family,
                sku=spec.sku.value,
            )
        else:
            available = quota.available_capacity_tpm(
                region=region, publisher=chosen_pub or "", family=chosen_family
            )
        floor = max(1, int(requested * _MIN_QUOTA_RATIO))
        if available <= 0:
            entries.append(
                ResolvedCapability(
                    name=name,
                    status=CapabilityStatus.HIL_ONLY,
                    publisher=chosen_pub,
                    family=chosen_family,
                    sku=None,
                    capacity_tpm=0,
                    invocation=spec.invocation.value,
                    reasons=(
                        (
                            f"zero_quota:family={chosen_family}:region={region}"
                            if capacity_unit == "tpm"
                            else f"zero_ptu_capacity:family={chosen_family}:region={region}"
                        ),
                    ),
                    capacity_unit=capacity_unit,
                    capacity_value=0 if capacity_unit == "ptu" else None,
                )
            )
            continue

        if available < floor:
            entries.append(
                ResolvedCapability(
                    name=name,
                    status=CapabilityStatus.HIL_ONLY,
                    publisher=chosen_pub,
                    family=chosen_family,
                    sku=None,
                    capacity_tpm=0,
                    invocation=spec.invocation.value,
                    reasons=(
                        f"quota_below_min_ratio:available={available}<"
                        f"floor={floor}:requested={requested}:unit={capacity_unit}",
                    ),
                    capacity_unit=capacity_unit,
                    capacity_value=0 if capacity_unit == "ptu" else None,
                )
            )
            continue

        effective = min(requested, available)
        status = (
            CapabilityStatus.RESOLVED
            if effective == requested
            else CapabilityStatus.CAPACITY_REDUCED
        )
        reasons: tuple[str, ...] = ()
        if status is CapabilityStatus.CAPACITY_REDUCED:
            reasons = (
                f"capacity_reduced:requested={requested}:effective={effective}:"
                f"unit={capacity_unit}",
            )
        entries.append(
            ResolvedCapability(
                name=name,
                status=status,
                publisher=chosen_pub,
                family=chosen_family,
                sku=spec.sku.value,
                capacity_tpm=effective if capacity_unit == "tpm" else 0,
                invocation=spec.invocation.value,
                reasons=reasons,
                capacity_unit=capacity_unit,
                capacity_value=effective if capacity_unit == "ptu" else None,
            )
        )

    # Mixed-model invariant: hard error unless mode is hil-only.
    if registry.mixed_model_mode is not MixedModelMode.HIL_ONLY:
        _enforce_mixed_model_invariant(entries)

    return ResolvedModels(
        schema_version="1.0.0",
        region=region,
        subscription_id=subscription_id,
        deployer_object_id=deployer_object_id,
        mixed_model_mode=registry.mixed_model_mode.value,
        capabilities=tuple(entries),
    )


def _enforce_mixed_model_invariant(entries: list[ResolvedCapability]) -> None:
    """Raise :class:`ResolverError` when a mixed-model pair shares a publisher.

    Two pairs MUST stay cross-publisher so the quality gate's independence
    assumption holds:

    - ``t2.reasoner.primary`` vs ``t2.reasoner.secondary`` (the cross-check
      pair - correlated errors defeat the check);
    - ``t2.rubric.judge`` vs ``t2.reasoner.primary`` (a model must not grade
      its own answer; see docs/roadmap/decisioning/hallucination-rubric-gate.md).

    The rubric judge is intentionally NOT forced distinct from
    ``t2.reasoner.secondary``. The self-grading hazard is specifically the
    judge sharing weights with the PROPOSER (primary). The secondary is a
    cross-check peer playing a different role (structured action agreement,
    not reasoning assessment), so a shared publisher there does not
    reintroduce the self-grading failure - and requiring three distinct
    publishers would make the shipped registry (secondary + judge both
    prefer Anthropic) unresolvable for no safety gain.
    """
    by_name: Mapping[str, ResolvedCapability] = {e.name: e for e in entries}
    primary = by_name.get("t2.reasoner.primary")
    secondary = by_name.get("t2.reasoner.secondary")
    _enforce_distinct_publisher(
        primary,
        secondary,
        pair="t2.reasoner.primary/t2.reasoner.secondary",
    )
    _enforce_distinct_publisher(
        by_name.get("t2.rubric.judge"),
        primary,
        pair="t2.rubric.judge/t2.reasoner.primary",
    )


def _enforce_distinct_publisher(
    left: ResolvedCapability | None,
    right: ResolvedCapability | None,
    *,
    pair: str,
) -> None:
    """Raise when both capabilities resolved to the same publisher."""
    if left is None or right is None:
        return
    # Only the two RESOLVED cases can violate the invariant. If either
    # is hil-only the invariant is not applicable - the affected
    # capability already can't auto-execute.
    if (
        left.status in (CapabilityStatus.RESOLVED, CapabilityStatus.CAPACITY_REDUCED)
        and right.status in (CapabilityStatus.RESOLVED, CapabilityStatus.CAPACITY_REDUCED)
        and left.publisher is not None
        and left.publisher == right.publisher
    ):
        raise ResolverError(
            "mixed_model_invariant_violated_after_resolve: "
            f"{pair} both resolved to publisher={left.publisher!r}. Expand "
            "llm-registry.yaml preferences so a distinct publisher can be "
            "picked in this region, or set mixed_model_mode='hil-only'."
        )


__all__ = [
    "CapabilityStatus",
    "CatalogQuery",
    "NarratorCandidate",
    "PermissionQuery",
    "QuotaQuery",
    "ResolvedCapability",
    "ResolvedModels",
    "ResolverError",
    "collect_narrator",
    "collect_narrator_deployments",
    "collect_primary_candidates",
    "collect_primary_deployments",
    "narrator_deployment_name",
    "reasoner_primary_deployment_name",
    "resolve",
]
