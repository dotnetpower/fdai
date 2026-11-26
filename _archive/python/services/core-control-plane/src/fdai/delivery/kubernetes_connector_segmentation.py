"""Shadow-only segmentation registration, policy-engine gate, and independent probe evaluation."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, Self

from fdai_service_contracts.cluster_connector import (
    ConnectorContract,
    Digest,
    Namespace,
    connector_time,
)
from fdai_service_contracts.compatibility import canonical_digest
from pydantic import Field, field_validator, model_validator

from fdai.delivery.kubernetes_connector_executor_installation import (
    ExecutorInstallationInput as ExecutorInstallationInput,
)
from fdai.delivery.kubernetes_connector_executor_installation import (
    build_management_egress_rules,
)
from fdai.delivery.kubernetes_connector_executor_installation import (
    render_executor_installation as render_executor_installation,
)
from fdai.delivery.kubernetes_connector_executor_installation import (
    validate_executor_material as validate_executor_material,
)
from fdai.delivery.kubernetes_connector_executor_installation import (
    verify_executor_documents as verify_executor_documents,
)
from fdai.delivery.kubernetes_connector_installation import GatewayPeer, KubernetesName, LabelText
from fdai.delivery.kubernetes_connector_policy import PodPolicyEndpoint, assess_policy_flow
from fdai.shared.providers.state_store import StateStore

SEGMENTATION_PREFIX = "kubernetes-connector:segmentation-shadow:v1:"
SEGMENTATION_ACTION_TYPE = "remediate.kubernetes-network-policy"
PolicyEngine = Literal["cilium", "calico", "azure"]
_SUPPORTED_POLICY_ENGINES: frozenset[str] = frozenset({"cilium", "calico", "azure"})


class SegmentationRegistrationError(ValueError):
    """Reject segmentation state that could be mistaken for an executable capability."""


class PolicyEngineCapabilityFact(ConnectorContract):
    """Target-bound fact proving whether the cluster enforces Kubernetes NetworkPolicy."""

    target_ref: Annotated[
        str, Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    ]
    state: Literal["allowed", "denied", "unknown"]
    policy_engine: PolicyEngine | None = None
    reason: str
    evidence_digest: Digest
    observed_at: datetime
    expires_at: datetime

    @field_validator("observed_at", "expires_at", mode="before")
    @classmethod
    def _clock(cls, value: object) -> datetime:
        return connector_time(value)

    @model_validator(mode="after")
    def _window(self) -> Self:
        if not timedelta(0) < self.expires_at - self.observed_at <= timedelta(hours=1):
            raise ValueError("policy engine capability evidence must expire within one hour")
        if (self.state == "allowed") != (self.policy_engine is not None):
            raise ValueError("allowed policy engine fact requires a supported policy_engine")
        return self


def inspect_aks_policy_engine(
    *,
    target_ref: str,
    cluster: Mapping[str, object],
    observed_at: datetime,
    expires_at: datetime | None = None,
) -> PolicyEngineCapabilityFact:
    """Evaluate ARM networkProfile to reject Azure CNI clusters that lack a policy engine."""
    observed = connector_time(observed_at)
    expires = connector_time(expires_at or (observed + timedelta(minutes=5)))
    properties = cluster.get("properties") if isinstance(cluster, Mapping) else None
    network = properties.get("networkProfile") if isinstance(properties, Mapping) else None
    if not isinstance(network, Mapping):
        evidence: dict[str, object] = {"reason": "network_profile_unreadable"}
        return PolicyEngineCapabilityFact(
            target_ref=target_ref,
            state="unknown",
            policy_engine=None,
            reason="network_profile_unreadable",
            evidence_digest=canonical_digest({"target_ref": target_ref, "evidence": evidence}),
            observed_at=observed,
            expires_at=expires,
        )
    plugin = str(network.get("networkPlugin") or "").strip().casefold()
    policy = str(network.get("networkPolicy") or "").strip().casefold()
    dataplane = str(network.get("networkDataplane") or "").strip().casefold()
    evidence = {
        "network_plugin": plugin,
        "network_policy": policy,
        "network_dataplane": dataplane,
    }
    digest = canonical_digest({"target_ref": target_ref, "evidence": evidence})
    if plugin == "none":
        return PolicyEngineCapabilityFact(
            target_ref=target_ref,
            state="denied",
            policy_engine=None,
            reason="network_plugin_disabled",
            evidence_digest=digest,
            observed_at=observed,
            expires_at=expires,
        )
    resolved = policy or ("cilium" if dataplane == "cilium" else "")
    if not resolved or resolved == "none":
        return PolicyEngineCapabilityFact(
            target_ref=target_ref,
            state="denied",
            policy_engine=None,
            reason="policy_engine_missing",
            evidence_digest=digest,
            observed_at=observed,
            expires_at=expires,
        )
    if resolved not in _SUPPORTED_POLICY_ENGINES:
        return PolicyEngineCapabilityFact(
            target_ref=target_ref,
            state="unknown",
            policy_engine=None,
            reason="unsupported_policy_engine",
            evidence_digest=digest,
            observed_at=observed,
            expires_at=expires,
        )
    return PolicyEngineCapabilityFact(
        target_ref=target_ref,
        state="allowed",
        policy_engine=resolved,  # type: ignore[arg-type]
        reason="policy_engine_enabled",
        evidence_digest=digest,
        observed_at=observed,
        expires_at=expires,
    )


class ManagementDependencyAllowlist(ConnectorContract):
    """Explicit observer and executor dependencies (DNS, Kubernetes API, and mTLS gateway)."""

    gateway_port: Annotated[int, Field(strict=True, ge=1, le=65535)]
    api_port: Annotated[int, Field(strict=True, ge=1, le=65535)]
    gateway_cidrs: Annotated[tuple[str, ...], Field(max_length=8)] = ()
    gateway_peer: GatewayPeer | None = None
    api_cidrs: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]
    dns_cidrs: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def _gateway(self) -> Self:
        if not self.gateway_cidrs and self.gateway_peer is None:
            raise ValueError("management allowlist requires gateway CIDRs or an in-cluster peer")
        return self

    @field_validator("gateway_cidrs", "api_cidrs", "dns_cidrs")
    @classmethod
    def _networks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        result = []
        for value in values:
            network = ipaddress.ip_network(value, strict=True)
            if (
                network.prefixlen < (24 if network.version == 4 else 64)
                or network.is_multicast
                or network.is_loopback
                or network.is_unspecified
            ):
                raise ValueError("management dependency networks must be bounded unicast CIDRs")
            result.append(str(network))
        if len(set(result)) != len(result):
            raise ValueError("management dependency networks must be unique")
        return tuple(sorted(result))

    def egress_rules(self) -> list[dict[str, Any]]:
        return build_management_egress_rules(
            gateway_cidrs=self.gateway_cidrs,
            gateway_peer=self.gateway_peer,
            gateway_port=self.gateway_port,
            api_cidrs=self.api_cidrs,
            api_port=self.api_port,
            dns_cidrs=self.dns_cidrs,
        )

    @property
    def dependency_digests(self) -> tuple[str, ...]:
        rules = self.egress_rules()
        named = (("mtls_gateway", rules[0]), ("kubernetes_api", rules[1]), ("dns", rules[2]))
        return tuple(
            sorted(canonical_digest({"dependency": name, "rule": rule}) for name, rule in named)
        )


def render_segmentation_network_policy(
    *,
    namespace: KubernetesName,
    name: KubernetesName,
    pod_selector_labels: Mapping[str, str],
    allowlist: ManagementDependencyAllowlist,
    ingress_rules: tuple[Mapping[str, object], ...] = (),
    workload_egress_rules: tuple[Mapping[str, object], ...] = (),
    owner_ref: str = "fdai-segmentation",
) -> dict[str, Any]:
    """Render a namespace-scoped NetworkPolicy that always preserves observer dependencies."""
    if namespace == "default" or namespace.startswith("kube-") or namespace == "fdai-runtime":
        raise SegmentationRegistrationError(
            "segmentation NetworkPolicy requires a dedicated non-system target namespace"
        )
    egress = [*allowlist.egress_rules(), *(dict(rule) for rule in workload_egress_rules)]
    document: dict[str, Any] = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "fdai-segmentation",
                "app.kubernetes.io/instance": name,
            },
            "annotations": {
                "fdai.dev/policy-owner": owner_ref,
                "fdai.dev/execution-authority": "false",
                "fdai.dev/mode": "shadow",
            },
        },
        "spec": {
            "podSelector": {"matchLabels": dict(sorted(pod_selector_labels.items()))},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [dict(rule) for rule in ingress_rules],
            "egress": egress,
        },
    }
    verify_management_dependencies_allowed(document, allowlist)
    return document


def verify_management_dependencies_allowed(
    policy: Mapping[str, object], allowlist: ManagementDependencyAllowlist
) -> None:
    """Reject a segmentation policy that omits DNS, API, or gateway egress rules."""
    spec = policy.get("spec") if isinstance(policy, Mapping) else None
    types = spec.get("policyTypes", []) if isinstance(spec, Mapping) else []
    if not isinstance(spec, Mapping) or "Egress" not in types:
        return
    egress = spec.get("egress")
    if not isinstance(egress, list):
        raise SegmentationRegistrationError("segmentation policy egress must be a list")
    required = allowlist.egress_rules()
    if any(rule not in egress for rule in required):
        raise SegmentationRegistrationError(
            "segmentation policy omits required DNS, Kubernetes API, or gateway egress rules"
        )


class SegmentationRollbackPlan(ConnectorContract):
    """Deterministic rollback contract bound to ShadowSegmentationRegistration.recovery_digest."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    action_type: Literal["remediate.kubernetes-network-policy"] = (
        "remediate.kubernetes-network-policy"
    )
    target_ref: Annotated[
        str, Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    ]
    namespace: Namespace
    policy_name: KubernetesName
    operation: Literal["delete_created_policy", "restore_prior_policy"]
    proposed_policy_digest: Digest
    prior_policy_digest: Digest | None = None
    prior_policy: dict[str, Any] | None = None
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        restoring = self.operation == "restore_prior_policy"
        if restoring != (self.prior_policy is not None) or restoring != (
            self.prior_policy_digest is not None
        ):
            raise ValueError("restore_prior_policy requires prior_policy and prior_policy_digest")
        if (
            self.prior_policy is not None
            and canonical_digest(self.prior_policy) != self.prior_policy_digest
        ):
            raise ValueError("prior_policy_digest does not match prior_policy")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


def build_segmentation_rollback_plan(
    *,
    target_ref: str,
    namespace: str,
    policy_name: str,
    proposed_policy: Mapping[str, object],
    prior_policy: Mapping[str, object] | None = None,
    expected_owner_ref: str = "fdai-segmentation",
) -> SegmentationRollbackPlan:
    """Build the tested rollback contract before registering shadow segmentation."""
    proposed_digest = canonical_digest(dict(proposed_policy))
    if prior_policy is None:
        return SegmentationRollbackPlan(
            target_ref=target_ref,
            namespace=namespace,
            policy_name=policy_name,
            operation="delete_created_policy",
            proposed_policy_digest=proposed_digest,
        )
    metadata = prior_policy.get("metadata") if isinstance(prior_policy, Mapping) else None
    annotations = metadata.get("annotations") if isinstance(metadata, Mapping) else None
    owner = annotations.get("fdai.dev/policy-owner") if isinstance(annotations, Mapping) else None
    if owner != expected_owner_ref:
        raise SegmentationRegistrationError(
            "cannot build a segmentation rollback plan over a foreign-owned NetworkPolicy"
        )
    normalized = json.loads(json.dumps(dict(prior_policy), sort_keys=True))
    return SegmentationRollbackPlan(
        target_ref=target_ref,
        namespace=namespace,
        policy_name=policy_name,
        operation="restore_prior_policy",
        proposed_policy_digest=proposed_digest,
        prior_policy_digest=canonical_digest(normalized),
        prior_policy=normalized,
    )


class ShadowSegmentationRegistration(ConnectorContract):
    """Local registration for analysis-only segmentation readiness evidence."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    target_ref: Annotated[
        str, Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    ]
    namespace: Namespace
    capability_ref: Annotated[
        str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    ]
    mode: Literal["shadow"] = "shadow"
    registered_at: datetime
    expires_at: datetime
    recovery_digest: Digest
    management_dependency_digests: Annotated[tuple[Digest, ...], Field(min_length=1, max_length=8)]
    execution_authority: Literal[False] = False

    @field_validator("registered_at", "expires_at", mode="before")
    @classmethod
    def _clock(cls, value: object) -> datetime:
        return connector_time(value)

    @field_validator("execution_authority", mode="before")
    @classmethod
    def _authority(cls, value: object) -> object:
        if value is not False:
            raise ValueError("shadow segmentation cannot grant execution authority")
        return value

    @model_validator(mode="after")
    def _window(self) -> Self:
        if not timedelta(0) < self.expires_at - self.registered_at <= timedelta(hours=1):
            raise ValueError("shadow segmentation registration must be short lived")
        if (
            tuple(sorted(set(self.management_dependency_digests)))
            != self.management_dependency_digests
        ):
            raise ValueError("management dependency digests must be sorted and unique")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class SegmentationProbe(ConnectorContract):
    """One independent connectivity observation for a proposed policy boundary."""

    target_ref: str
    namespace: Namespace
    probe_ref: str
    observer_ref: str
    kind: Literal["positive", "negative"]
    observed: Literal["connected", "blocked", "unknown"]
    observed_at: datetime
    expires_at: datetime
    evidence_digest: Digest | None = None

    @field_validator("observed_at", "expires_at", mode="before")
    @classmethod
    def _clock(cls, value: object) -> datetime:
        return connector_time(value)

    @model_validator(mode="after")
    def _evidence(self) -> Self:
        if not timedelta(0) < self.expires_at - self.observed_at <= timedelta(minutes=15):
            raise ValueError("segmentation probes must be short lived")
        if self.observed != "unknown" and self.evidence_digest is None:
            raise ValueError("segmentation probe conclusions require evidence")
        return self


@dataclass(frozen=True, slots=True)
class SegmentationProbeAssessment:
    status: Literal["ready_for_review", "needs_evidence", "blocked"]
    reason: str
    registration_digest: str
    execution_authority: Literal[False] = False


async def register_shadow_segmentation(
    store: StateStore,
    registration: ShadowSegmentationRegistration,
    *,
    now: Callable[[], datetime],
    policy_engine_fact: PolicyEngineCapabilityFact | None = None,
) -> bool:
    """Persist a shadow registration and audited recovery dependency, never an action."""
    registration = ShadowSegmentationRegistration.model_validate_json(
        registration.model_dump_json()
    )
    current = connector_time(now())
    if not registration.registered_at <= current < registration.expires_at:
        raise SegmentationRegistrationError("shadow segmentation registration is not current")
    if policy_engine_fact is not None:
        fact = PolicyEngineCapabilityFact.model_validate_json(policy_engine_fact.model_dump_json())
        if (
            fact.target_ref != registration.target_ref
            or not fact.observed_at <= current < fact.expires_at
            or fact.state != "allowed"
        ):
            raise SegmentationRegistrationError(
                f"cluster network policy engine is not eligible: {fact.reason}"
            )
    key = SEGMENTATION_PREFIX + canonical_digest(
        {"target_ref": registration.target_ref, "namespace": registration.namespace}
    )
    value = {
        "revision": 1,
        "registration": registration.model_dump(mode="json"),
        "registration_digest": registration.digest,
    }
    previous = await store.read_state(key)
    if previous is not None:
        old = _decode(previous)
        if old == registration:
            return False
        raise SegmentationRegistrationError("shadow segmentation registration changed")
    return await store.write_state_with_audit_if_absent(
        key,
        value,
        {
            "kind": "kubernetes.segmentation.shadow.registered",
            "correlation_id": registration.digest,
            "target_ref": registration.target_ref,
            "namespace": registration.namespace,
            "mode": "shadow",
            "execution_authority": False,
            "recovery_digest": registration.recovery_digest,
        },
    )


class SegmentationProbeTarget(ConnectorContract):
    """Typed connectivity probe specification; never carries shell text or Secret references."""

    target_ref: Annotated[
        str, Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    ]
    namespace: KubernetesName
    probe_ref: KubernetesName
    observer_ref: Annotated[
        str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    ]
    kind: Literal["positive", "negative"]
    source_labels: Annotated[dict[LabelText, LabelText], Field(min_length=1, max_length=8)]
    destination_host: Annotated[
        str, Field(min_length=1, max_length=253, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
    ]
    port: Annotated[int, Field(strict=True, ge=1, le=65535)]
    protocol: Literal["TCP"] = "TCP"
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=15)] = 3
    image: Annotated[
        str, Field(max_length=512, pattern=r"^[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}$")
    ]

    @field_validator("namespace")
    @classmethod
    def _namespace(cls, value: str) -> str:
        if value == "default" or value.startswith("kube-") or value == "fdai-runtime":
            raise ValueError("segmentation probe requires a dedicated non-system namespace")
        return value


def render_segmentation_probe_job(target: SegmentationProbeTarget) -> dict[str, Any]:
    """Render a restricted, token-less Kubernetes Job that executes one typed TCP probe."""
    target = SegmentationProbeTarget.model_validate_json(target.model_dump_json())
    script = (
        "import hashlib, json, socket, sys\n"
        f"host, port = {target.destination_host!r}, {target.port}\n"
        f"timeout = {target.timeout_seconds}\n"
        "try:\n"
        "    with socket.create_connection((host, port), timeout=timeout):\n"
        "        observed = 'connected'\n"
        "except OSError:\n"
        "    observed = 'blocked'\n"
        "payload = {\n"
        f"    'probe_ref': {target.probe_ref!r},\n"
        f"    'observer_ref': {target.observer_ref!r},\n"
        f"    'kind': {target.kind!r},\n"
        "    'observed': observed,\n"
        "}\n"
        "digest = 'sha256:' + hashlib.sha256(\n"
        "    json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()\n"
        ").hexdigest()\n"
        "print(json.dumps({**payload, 'evidence_digest': digest}, sort_keys=True))\n"
    )
    labels = {
        **dict(sorted(target.source_labels.items())),
        "app.kubernetes.io/managed-by": "fdai-segmentation-probe",
        "fdai.dev/probe-ref": target.probe_ref,
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": f"fdai-probe-{target.probe_ref}"[:63].rstrip("-"),
            "namespace": target.namespace,
            "labels": labels,
            "annotations": {"fdai.dev/execution-authority": "false"},
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 30,
            "ttlSecondsAfterFinished": 60,
            "template": {
                "metadata": {"labels": labels.copy()},
                "spec": {
                    "hostNetwork": False,
                    "hostPID": False,
                    "hostIPC": False,
                    "automountServiceAccountToken": False,
                    "restartPolicy": "Never",
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "runAsGroup": 10001,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "probe",
                            "image": target.image,
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["python", "-c", script],
                            "securityContext": {
                                "privileged": False,
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                                "runAsNonRoot": True,
                                "runAsUser": 10001,
                                "runAsGroup": 10001,
                                "seccompProfile": {"type": "RuntimeDefault"},
                            },
                            "resources": {
                                "requests": {"cpu": "50m", "memory": "64Mi"},
                                "limits": {"cpu": "200m", "memory": "128Mi"},
                            },
                        }
                    ],
                },
            },
        },
    }


@dataclass(frozen=True, slots=True)
class SegmentationScenarioCase:
    """One flow prediction paired with its actual probe observation."""

    source: PodPolicyEndpoint
    destination: PodPolicyEndpoint
    policies: tuple[Mapping[str, object], ...]
    port: int
    protocol: Literal["TCP", "UDP", "SCTP"]
    observed_at: datetime
    probe: SegmentationProbe
    expected_owner_ref: str | None = "fdai-segmentation"


@dataclass(frozen=True, slots=True)
class SegmentationScenarioEvaluation:
    status: Literal["ready_for_review", "needs_evidence", "blocked"]
    reason: str
    registration_digest: str
    total_cases: int
    matched_cases: int
    agreement_rate: float
    policy_escapes: int
    execution_authority: Literal[False] = False


def evaluate_segmentation_scenario(
    registration: ShadowSegmentationRegistration,
    cases: tuple[SegmentationScenarioCase, ...],
    *,
    policy_engine_fact: PolicyEngineCapabilityFact,
    now: datetime,
) -> SegmentationScenarioEvaluation:
    """Compare policy-analyzer predictions with actual probes and gate shadow promotion."""
    registration = ShadowSegmentationRegistration.model_validate_json(
        registration.model_dump_json()
    )
    fact = PolicyEngineCapabilityFact.model_validate_json(policy_engine_fact.model_dump_json())
    current = connector_time(now)
    if (
        fact.target_ref != registration.target_ref
        or not fact.observed_at <= current < fact.expires_at
    ):
        return SegmentationScenarioEvaluation(
            "needs_evidence",
            "policy_engine_evidence_unavailable",
            registration.digest,
            0,
            0,
            0.0,
            0,
        )
    if fact.state == "denied":
        return SegmentationScenarioEvaluation(
            "blocked", fact.reason, registration.digest, 0, 0, 0.0, 0
        )
    if fact.state != "allowed":
        return SegmentationScenarioEvaluation(
            "needs_evidence", fact.reason, registration.digest, 0, 0, 0.0, 0
        )
    if not cases or len(cases) > 16:
        return SegmentationScenarioEvaluation(
            "needs_evidence", "scenario_cases_invalid", registration.digest, len(cases), 0, 0.0, 0
        )
    matched = 0
    escapes = 0
    for case in cases:
        predicted = assess_policy_flow(
            source=case.source,
            destination=case.destination,
            policies=case.policies,
            port=case.port,
            protocol=case.protocol,
            complete=True,
            observed_at=case.observed_at,
            now=current,
            expected_owner_ref=case.expected_owner_ref,
        )
        if predicted.disposition == "unknown" or case.probe.observed == "unknown":
            return SegmentationScenarioEvaluation(
                "needs_evidence",
                "scenario_prediction_or_probe_unknown",
                registration.digest,
                len(cases),
                matched,
                matched / len(cases),
                escapes,
            )
        expected_observed = "connected" if predicted.disposition == "allowed" else "blocked"
        if case.probe.observed == expected_observed:
            matched += 1
        elif predicted.disposition == "blocked" and case.probe.observed == "connected":
            escapes += 1
    rate = matched / len(cases)
    probe_assessment = assess_segmentation_probes(
        registration, tuple(case.probe for case in cases), now=current
    )
    if escapes > 0 or rate < 1.0 or probe_assessment.status == "blocked":
        return SegmentationScenarioEvaluation(
            "blocked",
            "policy_escape_detected" if escapes > 0 else "prediction_probe_mismatch",
            registration.digest,
            len(cases),
            matched,
            rate,
            escapes,
        )
    if probe_assessment.status != "ready_for_review":
        return SegmentationScenarioEvaluation(
            "needs_evidence",
            probe_assessment.reason,
            registration.digest,
            len(cases),
            matched,
            rate,
            escapes,
        )
    return SegmentationScenarioEvaluation(
        "ready_for_review",
        "shadow_scenario_verified",
        registration.digest,
        len(cases),
        matched,
        rate,
        escapes,
    )


def assess_segmentation_probes(
    registration: ShadowSegmentationRegistration,
    probes: tuple[SegmentationProbe, ...],
    *,
    now: datetime,
) -> SegmentationProbeAssessment:
    """Require independent current positive and negative probes before review readiness."""
    registration = ShadowSegmentationRegistration.model_validate_json(
        registration.model_dump_json()
    )
    current = connector_time(now)
    if not registration.registered_at <= current < registration.expires_at:
        return SegmentationProbeAssessment(
            "needs_evidence", "registration_expired", registration.digest
        )
    if len(probes) > 16:
        return SegmentationProbeAssessment(
            "needs_evidence", "probe_bound_exceeded", registration.digest
        )
    outcomes: dict[str, bool] = {}
    observers: set[str] = set()
    for raw_probe in probes:
        try:
            probe = SegmentationProbe.model_validate_json(raw_probe.model_dump_json())
        except ValueError:
            return SegmentationProbeAssessment(
                "needs_evidence", "invalid_probe", registration.digest
            )
        if (
            probe.target_ref != registration.target_ref
            or probe.namespace != registration.namespace
            or not probe.observed_at <= current < probe.expires_at
            or probe.observed == "unknown"
        ):
            return SegmentationProbeAssessment(
                "needs_evidence", "probe_evidence_unavailable", registration.digest
            )
        observers.add(probe.observer_ref)
        expected = "connected" if probe.kind == "positive" else "blocked"
        outcomes[probe.kind] = probe.observed == expected
    if len(observers) < 2:
        return SegmentationProbeAssessment(
            "needs_evidence", "independent_probe_evidence_missing", registration.digest
        )
    if not outcomes.get("positive") or not outcomes.get("negative"):
        return SegmentationProbeAssessment(
            "blocked", "probe_expectation_failed", registration.digest
        )
    return SegmentationProbeAssessment(
        "ready_for_review", "shadow_probes_passed", registration.digest
    )


def _decode(value: Mapping[str, object]) -> ShadowSegmentationRegistration:
    if set(value) != {"revision", "registration", "registration_digest"}:
        raise SegmentationRegistrationError("shadow segmentation checkpoint is invalid")
    registration = ShadowSegmentationRegistration.model_validate(value["registration"])
    if (
        value["revision"] != 1
        or value["registration_digest"] != registration.digest
        or registration.execution_authority is not False
        or registration.mode != "shadow"
    ):
        raise SegmentationRegistrationError("shadow segmentation checkpoint failed integrity")
    return registration
