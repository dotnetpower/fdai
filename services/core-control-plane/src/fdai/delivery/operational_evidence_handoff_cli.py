"""Executable connected-environment handoff for independent operational evidence.

The handoff runs only after separate explicit authorization, on a selected non-production target,
from the same source revision. It executes the automatable stages - identity separation, pinned
registries, proof-store writer readback, and verifier readiness - stops at the first failed stage,
and lists the positive-issuance and negative-drill observations still owed. It never mutates a
resource, never retries, and never claims independent operational qualification (#1026).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fdai_service_contracts.operational_evidence import (
    OPERATIONAL_EVIDENCE_PURPOSES,
    OperationalEvidenceRejectionClass,
)

from fdai.core.operational_evidence.registry_json import RegistryUnavailableError
from fdai.core.operational_evidence.separation import (
    ProofStoreGrantReadback,
    VerifierSeparationError,
    assert_verifier_separation,
)
from fdai.delivery.operational_evidence_configuration import (
    VERIFIER_ID,
    OperationalEvidenceSettings,
    load_anchors,
    load_registry_history,
    string_list,
)
from fdai.delivery.persistence.postgres_operational_evidence import (
    VERIFIER_ROLE,
    PostgresOperationalEvidenceConfig,
)
from fdai.delivery.persistence.postgres_operational_evidence_grants import (
    read_proof_store_grants,
)

AUTHORIZATION_ENV = "FDAI_OPERATIONAL_EVIDENCE_HANDOFF_AUTHORIZED"
SOURCE_SHA_ENV = "FDAI_SOURCE_SHA"
STAGES = ("identity", "registry", "writer_readback", "verifier_readiness")
_READINESS_PATH = "/v1/operational-evidence/readiness"


@dataclass(slots=True)
class HandoffReceipt:
    """Content-free record of one handoff run; it grants no authority."""

    venue: str
    source_sha: str | None
    started_at: str
    stages: list[dict[str, object]] = field(default_factory=list)
    registry_pins: dict[str, str] = field(default_factory=dict)
    owed_observations: list[dict[str, str]] = field(default_factory=list)
    operational_qualification: str = "retained separately under #1026"
    execution_authority: bool = False

    def as_mapping(self) -> dict[str, object]:
        return {
            "venue": self.venue,
            "source_sha": self.source_sha,
            "started_at": self.started_at,
            "stages": self.stages,
            "registry_pins": self.registry_pins,
            "owed_observations": self.owed_observations,
            "operational_qualification": self.operational_qualification,
            "execution_authority": self.execution_authority,
        }

    @property
    def passed(self) -> bool:
        return all(stage["status"] == "passed" for stage in self.stages)


GrantReader = Callable[[PostgresOperationalEvidenceConfig], Awaitable[ProofStoreGrantReadback]]
ReadinessReader = Callable[[str], Awaitable[Mapping[str, object]]]


def owed_observations() -> list[dict[str, str]]:
    """Return the positive and negative observations a connected run must still record."""

    owed = [
        {"stage": "positive_issuance", "purpose": purpose, "expect": "admission consumed by owner"}
        for purpose in OPERATIONAL_EVIDENCE_PURPOSES
    ]
    owed.extend(
        {"stage": "negative_drill", "class": item.value, "expect": "matching owner reason"}
        for item in OperationalEvidenceRejectionClass
    )
    owed.append({"stage": "negative_drill", "class": "self_verified", "expect": "capability state"})
    owed.append({"stage": "negative_drill", "class": "unavailable", "expect": "stopped verifier"})
    return owed


async def run_handoff(
    env: Mapping[str, str],
    *,
    venue: str,
    root: Path,
    grants_reader: GrantReader = read_proof_store_grants,
    readiness_reader: ReadinessReader | None = None,
    now: datetime | None = None,
) -> HandoffReceipt:
    """Run the automatable stages in order and stop at the first failure."""

    receipt = HandoffReceipt(
        venue=venue,
        source_sha=env.get(SOURCE_SHA_ENV, "").strip() or None,
        started_at=(now or datetime.now(UTC)).isoformat(),
    )
    if venue == "connected" and env.get(AUTHORIZATION_ENV, "").strip() != "1":
        receipt.stages.append(
            {
                "stage": "authorization",
                "status": "failed",
                "reason": "explicit_authorization_absent",
            }
        )
        return receipt
    settings = OperationalEvidenceSettings.from_environment(env)
    try:
        history = load_registry_history(settings, root=root)
        anchors = load_anchors(settings)
        trust = history.current.trust
        verifier_anchor = {
            item.trust_anchor_id
            for entry in trust.purposes.values()
            for item in entry.verifiers
            if item.verifier_id == VERIFIER_ID
        }
        principals = {anchors.principal(anchor) for anchor in verifier_anchor}
        if len(principals) != 1 or None in principals:
            raise VerifierSeparationError("verifier principal is unbound")
        assert_verifier_separation(
            trust,
            anchors,
            verifier_principal=str(next(iter(principals))),
            executor_class_principals=string_list(
                settings.executor_principals_json, label="executor principals"
            ),
        )
    except (RegistryUnavailableError, VerifierSeparationError, ValueError) as exc:
        receipt.stages.append(
            {"stage": "identity", "status": "failed", "reason": type(exc).__name__}
        )
        return _stopped(receipt, after="identity")
    receipt.stages.append({"stage": "identity", "status": "passed"})
    receipt.registry_pins = {
        "trust_registry_pin": history.current.pins.trust_pin,
        "grant_registry_pin": history.current.pins.grant_pin,
    }
    receipt.stages.append(
        {"stage": "registry", "status": "passed", "revisions": len(history.step_classes()) + 1}
    )
    try:
        readback = await grants_reader(
            PostgresOperationalEvidenceConfig(
                dsn=settings.verifier_dsn, expected_role=VERIFIER_ROLE
            )
        )
    except (OSError, PermissionError, RuntimeError, ValueError) as exc:
        receipt.stages.append(
            {"stage": "writer_readback", "status": "failed", "reason": type(exc).__name__}
        )
        return _stopped(receipt, after="writer_readback")
    reasons = readback.self_verified_reasons()
    receipt.stages.append(
        {
            "stage": "writer_readback",
            "status": "failed" if reasons else "passed",
            "self_verified_reasons": list(reasons),
        }
    )
    if reasons:
        return _stopped(receipt, after="writer_readback")
    reader = readiness_reader or _readiness
    try:
        readiness = await reader(settings.verifier_url)
    except (OSError, httpx.HTTPError, ValueError) as exc:
        receipt.stages.append(
            {"stage": "verifier_readiness", "status": "failed", "reason": type(exc).__name__}
        )
        return _stopped(receipt, after="verifier_readiness")
    state = str(readiness.get("state"))
    raw_bound = readiness.get("bound_purposes")
    receipt.stages.append(
        {
            "stage": "verifier_readiness",
            "status": "passed" if state == "ready" else "failed",
            "state": state,
            "bound_purposes": sorted(
                str(item) for item in (raw_bound if isinstance(raw_bound, list) else [])
            ),
        }
    )
    receipt.owed_observations = owed_observations()
    return receipt


def _stopped(receipt: HandoffReceipt, *, after: str) -> HandoffReceipt:
    started = False
    for stage in STAGES:
        if started:
            receipt.stages.append(
                {"stage": stage, "status": "not_run", "reason": f"stopped_after:{after}"}
            )
        started = started or stage == after
    return receipt


async def _readiness(base_url: str) -> Mapping[str, object]:
    async with httpx.AsyncClient(timeout=2.0) as client:
        response = await client.get(base_url.rstrip("/") + _READINESS_PATH)
    if response.status_code != 200:
        raise ValueError("verifier readiness is unavailable")
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("verifier readiness is malformed")
    return body


def main(argv: list[str] | None = None) -> int:
    """Print one handoff receipt as JSON; exit non-zero unless every automatable stage passed."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "run"))
    parser.add_argument("--venue", choices=("local", "connected"), default="local")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    arguments = parser.parse_args(argv)
    if arguments.command == "plan":
        print(
            json.dumps({"stages": list(STAGES), "owed_observations": owed_observations()}, indent=2)
        )
        return 0
    receipt = asyncio.run(run_handoff(os.environ, venue=arguments.venue, root=arguments.root))
    print(json.dumps(receipt.as_mapping(), indent=2, sort_keys=True))
    return 0 if receipt.passed else 1


__all__ = [
    "AUTHORIZATION_ENV",
    "STAGES",
    "HandoffReceipt",
    "main",
    "owed_observations",
    "run_handoff",
]


if __name__ == "__main__":  # pragma: no cover - manual handoff entry point
    sys.exit(main())
