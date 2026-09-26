"""Typed runtime-readiness contract for conversation-assurance challenges."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from fdai.core.conversation.semantic_current_evidence import SemanticCurrentEvidenceProbe
from fdai.core.conversation.semantic_manifest import semantic_principal_scope_digest
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform.query_execution import QueryNodeHeldError

CONVERSATION_ASSURANCE_PRINCIPAL_ID = "watchdog-local"
_MANIFEST_FUNCTION = "query.manifest"
_RESOURCE_HEALTH_FUNCTION = "query.resource_health_inventory"
_RESOURCE_STATE_FUNCTION = "query.resource_state_inventory"
_SERVICE_HEALTH_FUNCTION = "query.subscription_service_health"
_CURRENT_EVIDENCE_FUNCTIONS = frozenset(
    {
        _RESOURCE_HEALTH_FUNCTION,
        _RESOURCE_STATE_FUNCTION,
        _SERVICE_HEALTH_FUNCTION,
    }
)
_SCHEMA_EVIDENCE_FUNCTIONS = frozenset(
    {
        _MANIFEST_FUNCTION,
        "query.ontology_declaration",
        "query.ontology_relationships",
    }
)


class ReadinessStage(StrEnum):
    """Highest readiness stage proved by current runtime evidence."""

    UNDECLARED = "undeclared"
    DECLARED = "declared"
    BOUND = "bound"
    REACHABLE = "reachable"
    EVIDENCE_READY = "evidence_ready"


_STAGE_RANK = {
    ReadinessStage.UNDECLARED: 0,
    ReadinessStage.DECLARED: 1,
    ReadinessStage.BOUND: 2,
    ReadinessStage.REACHABLE: 3,
    ReadinessStage.EVIDENCE_READY: 4,
}


@dataclass(frozen=True, slots=True)
class RuntimeCapabilityReadiness:
    """Current proof for one declared function in one runtime instance."""

    function_name: str
    declared: bool
    bound: bool
    reachable: bool
    evidence_ready: bool
    provided_authority: str | None = None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.function_name.strip():
            raise ValueError("runtime capability function_name MUST be non-empty")
        if self.bound and not self.declared:
            raise ValueError("bound runtime capability MUST be declared")
        if self.reachable and not self.bound:
            raise ValueError("reachable runtime capability MUST be bound")
        if self.evidence_ready and not self.reachable:
            raise ValueError("evidence-ready runtime capability MUST be reachable")
        if self.provided_authority is not None and not self.reachable:
            raise ValueError("provided authority requires a reachable runtime capability")
        if self.evidence_ready and self.unavailable_reason is not None:
            raise ValueError("evidence-ready runtime capability MUST NOT be unavailable")
        if not self.evidence_ready and not self.unavailable_reason:
            raise ValueError("unavailable runtime capability requires a reason")

    @property
    def stage(self) -> ReadinessStage:
        if self.evidence_ready:
            return ReadinessStage.EVIDENCE_READY
        if self.reachable:
            return ReadinessStage.REACHABLE
        if self.bound:
            return ReadinessStage.BOUND
        if self.declared:
            return ReadinessStage.DECLARED
        return ReadinessStage.UNDECLARED

    def to_dict(self) -> dict[str, object]:
        return {
            "function_name": self.function_name,
            "declared": self.declared,
            "bound": self.bound,
            "reachable": self.reachable,
            "evidence_ready": self.evidence_ready,
            "provided_authority": self.provided_authority,
            "unavailable_reason": self.unavailable_reason,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RuntimeCapabilityReadiness:
        """Parse one persisted runtime-owned readiness observation."""

        return cls(
            function_name=str(value["function_name"]),
            declared=_required_bool(value, "declared"),
            bound=_required_bool(value, "bound"),
            reachable=_required_bool(value, "reachable"),
            evidence_ready=_required_bool(value, "evidence_ready"),
            provided_authority=(
                str(value["provided_authority"])
                if value.get("provided_authority") is not None
                else None
            ),
            unavailable_reason=(
                str(value["unavailable_reason"])
                if value.get("unavailable_reason") is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class RuntimeReadinessInventory:
    """Immutable readiness evidence for one ephemeral runtime."""

    capabilities: tuple[RuntimeCapabilityReadiness, ...]
    assurance_corpus_digest: str | None = None

    def __post_init__(self) -> None:
        names = tuple(item.function_name for item in self.capabilities)
        if len(names) != len(set(names)):
            raise ValueError("runtime readiness function names MUST be unique")
        if self.assurance_corpus_digest is not None and (
            len(self.assurance_corpus_digest) != 64
            or any(
                character not in "0123456789abcdef" for character in self.assurance_corpus_digest
            )
        ):
            raise ValueError("runtime readiness assurance corpus digest MUST be SHA-256")

    def capability(self, function_name: str) -> RuntimeCapabilityReadiness | None:
        return next(
            (item for item in self.capabilities if item.function_name == function_name),
            None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilities": [item.to_dict() for item in self.capabilities],
            "assurance_corpus_digest": self.assurance_corpus_digest,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RuntimeReadinessInventory:
        """Parse an inventory without inventing absent positive readiness."""

        raw = value.get("capabilities")
        if not isinstance(raw, list):
            raise ValueError("runtime readiness capabilities MUST be a list")
        if any(not isinstance(item, dict) for item in raw):
            raise ValueError("runtime readiness capability MUST be an object")
        corpus_digest = value.get("assurance_corpus_digest")
        if corpus_digest is not None and not isinstance(corpus_digest, str):
            raise ValueError("runtime readiness assurance corpus digest MUST be a string")
        return cls(
            capabilities=tuple(RuntimeCapabilityReadiness.from_dict(item) for item in raw),
            assurance_corpus_digest=corpus_digest,
        )


async def observe_runtime_readiness(
    *,
    declared_function_names: tuple[str, ...],
    function_bindings: Mapping[str, str],
    current_evidence_probe: SemanticCurrentEvidenceProbe | None,
    principal: Principal,
    assurance_corpus_digest: str | None = None,
) -> RuntimeReadinessInventory:
    """Observe bindings and evidence through the providers owned by this runtime."""

    declared = frozenset(declared_function_names)
    unknown_bindings = sorted(set(function_bindings) - declared)
    if unknown_bindings:
        raise ValueError(
            "runtime readiness bindings are absent from the active release: "
            + ", ".join(unknown_bindings)
        )
    capabilities = {
        name: RuntimeCapabilityReadiness(
            function_name=name,
            declared=True,
            bound=name in function_bindings,
            reachable=False,
            evidence_ready=False,
            unavailable_reason=(
                "current_evidence_probe_unavailable"
                if name in function_bindings
                else "runtime_binding_unavailable"
            ),
        )
        for name in declared_function_names
    }
    for function_name in _SCHEMA_EVIDENCE_FUNCTIONS & set(function_bindings):
        capabilities[function_name] = RuntimeCapabilityReadiness(
            function_name=function_name,
            declared=True,
            bound=True,
            reachable=True,
            evidence_ready=True,
            provided_authority=function_bindings[function_name],
        )
    if current_evidence_probe is None:
        return RuntimeReadinessInventory(
            capabilities=tuple(capabilities[name] for name in sorted(capabilities))
        )
    expected_scope_digest = semantic_principal_scope_digest(
        principal=principal,
        purpose="operations-review",
    )
    for function_name in sorted(_CURRENT_EVIDENCE_FUNCTIONS & set(function_bindings)):
        try:
            observation = await current_evidence_probe.observe(
                function_name=function_name,
                principal=principal,
            )
        except QueryNodeHeldError as error:
            capabilities[function_name] = RuntimeCapabilityReadiness(
                function_name=function_name,
                declared=True,
                bound=True,
                reachable=True,
                evidence_ready=False,
                provided_authority=function_bindings[function_name],
                unavailable_reason=error.reason,
            )
            continue
        except (OSError, RuntimeError):
            capabilities[function_name] = RuntimeCapabilityReadiness(
                function_name=function_name,
                declared=True,
                bound=True,
                reachable=False,
                evidence_ready=False,
                unavailable_reason="authority_or_source_unavailable",
            )
            continue
        if observation.function_name != function_name:
            raise ValueError("current-evidence probe returned a different function")
        provided_authority = observation.authority.value
        if observation.principal_scope_digest != expected_scope_digest:
            capabilities[function_name] = RuntimeCapabilityReadiness(
                function_name=function_name,
                declared=True,
                bound=True,
                reachable=True,
                evidence_ready=False,
                provided_authority=provided_authority,
                unavailable_reason="principal_scope_mismatch",
            )
            continue
        if provided_authority != function_bindings[function_name]:
            capabilities[function_name] = RuntimeCapabilityReadiness(
                function_name=function_name,
                declared=True,
                bound=True,
                reachable=True,
                evidence_ready=False,
                provided_authority=provided_authority,
                unavailable_reason="runtime_authority_mismatch",
            )
            continue
        capabilities[function_name] = RuntimeCapabilityReadiness(
            function_name=function_name,
            declared=True,
            bound=True,
            reachable=True,
            evidence_ready=observation.complete,
            provided_authority=provided_authority,
            unavailable_reason=None if observation.complete else "current_evidence_incomplete",
        )
    return RuntimeReadinessInventory(
        capabilities=tuple(capabilities[name] for name in sorted(capabilities)),
        assurance_corpus_digest=assurance_corpus_digest,
    )


def conversation_assurance_probe_principal() -> Principal:
    """Return the fixed local human principal authenticated by the watchdog Operator."""

    return Principal(
        id=CONVERSATION_ASSURANCE_PRINCIPAL_ID,
        role=Role.CONTRIBUTOR,
    )


def write_runtime_readiness_receipt(
    path: Path,
    inventory: RuntimeReadinessInventory,
) -> None:
    """Atomically persist a sanitized private receipt for the local watchdog."""

    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if path.is_symlink():
        raise RuntimeError("runtime readiness receipt path MUST NOT be a symlink")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(inventory.to_dict(), ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class CapabilitySelectionReadiness:
    """Reduced selection decision for one challenge capability."""

    capability_id: str
    stage: ReadinessStage
    selectable: bool
    required_functions: tuple[str, ...]
    expected_authority: str | None
    provided_authority: str | None
    unavailable_reason: str | None
    expected_authorities: tuple[str, ...] = ()
    provided_authorities: tuple[str, ...] = ()


def assess_capability_readiness(
    *,
    capability_id: str,
    enabled: bool,
    required_functions: tuple[str, ...],
    expected_authority: str | None,
    inventory: RuntimeReadinessInventory,
    expected_authorities: tuple[str, ...] = (),
) -> CapabilitySelectionReadiness:
    """Require evidence-ready functions and exact authority before selection."""

    if expected_authorities != tuple(sorted(set(expected_authorities))):
        raise ValueError("expected readiness authorities MUST be unique and ordered")
    if expected_authorities:
        derived_descriptor = (
            expected_authorities[0]
            if len(expected_authorities) == 1
            else "multiple_authoritative_sources"
        )
        if expected_authority != derived_descriptor:
            raise ValueError(
                "expected readiness authority descriptor does not match its authority set"
            )
    if not enabled:
        return _unavailable(
            capability_id,
            required_functions,
            expected_authority,
            ReadinessStage.UNDECLARED,
            "challenge_not_enabled",
            expected_authorities=expected_authorities,
        )
    if not required_functions:
        return _unavailable(
            capability_id,
            required_functions,
            expected_authority,
            ReadinessStage.UNDECLARED,
            "readiness_contract_missing",
            expected_authorities=expected_authorities,
        )
    records = tuple(inventory.capability(name) for name in required_functions)
    missing = tuple(
        name for name, item in zip(required_functions, records, strict=True) if item is None
    )
    if missing:
        return _unavailable(
            capability_id,
            required_functions,
            expected_authority,
            ReadinessStage.UNDECLARED,
            "function_undeclared",
            expected_authorities=expected_authorities,
        )
    resolved = tuple(item for item in records if item is not None)
    stage = min((item.stage for item in resolved), key=_STAGE_RANK.__getitem__)
    first_unavailable = next((item for item in resolved if not item.evidence_ready), None)
    if first_unavailable is not None:
        return _unavailable(
            capability_id,
            required_functions,
            expected_authority,
            stage,
            first_unavailable.unavailable_reason or "evidence_unavailable",
            provided_authority=first_unavailable.provided_authority,
            expected_authorities=expected_authorities,
        )
    authorities = {item.provided_authority for item in resolved}
    provided_authorities = tuple(sorted(item for item in authorities if item is not None))
    provided_authority = (
        next(iter(authorities))
        if len(authorities) == 1
        else "multiple_authoritative_sources"
        if authorities and None not in authorities
        else None
    )
    if expected_authority is None:
        return _unavailable(
            capability_id,
            required_functions,
            expected_authority,
            stage,
            "expected_authority_missing",
            provided_authority=provided_authority,
            expected_authorities=expected_authorities,
            provided_authorities=provided_authorities,
        )
    expected_set = set(expected_authorities) if expected_authorities else {expected_authority}
    if authorities != expected_set:
        return _unavailable(
            capability_id,
            required_functions,
            expected_authority,
            stage,
            "authority_mismatch",
            provided_authority=provided_authority,
            expected_authorities=expected_authorities,
            provided_authorities=provided_authorities,
        )
    return CapabilitySelectionReadiness(
        capability_id=capability_id,
        stage=ReadinessStage.EVIDENCE_READY,
        selectable=True,
        required_functions=required_functions,
        expected_authority=expected_authority,
        provided_authority=provided_authority,
        unavailable_reason=None,
        expected_authorities=expected_authorities,
        provided_authorities=provided_authorities,
    )


def _unavailable(
    capability_id: str,
    required_functions: tuple[str, ...],
    expected_authority: str | None,
    stage: ReadinessStage,
    reason: str,
    *,
    provided_authority: str | None = None,
    expected_authorities: tuple[str, ...] = (),
    provided_authorities: tuple[str, ...] = (),
) -> CapabilitySelectionReadiness:
    return CapabilitySelectionReadiness(
        capability_id=capability_id,
        stage=stage,
        selectable=False,
        required_functions=required_functions,
        expected_authority=expected_authority,
        provided_authority=provided_authority,
        unavailable_reason=reason,
        expected_authorities=expected_authorities,
        provided_authorities=provided_authorities,
    )


def _required_bool(value: dict[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"runtime readiness {key} MUST be boolean")
    return item


__all__ = [
    "CONVERSATION_ASSURANCE_PRINCIPAL_ID",
    "CapabilitySelectionReadiness",
    "ReadinessStage",
    "RuntimeCapabilityReadiness",
    "RuntimeReadinessInventory",
    "assess_capability_readiness",
    "conversation_assurance_probe_principal",
    "observe_runtime_readiness",
    "write_runtime_readiness_receipt",
]
