"""Connected-handoff mechanics: authorization gate, ordered stages, and stop conditions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.core.operational_evidence.separation import ProofStoreGrantReadback
from fdai.delivery.operational_evidence_handoff_cli import (
    AUTHORIZATION_ENV,
    main,
    run_handoff,
)
from fdai.delivery.persistence.postgres_operational_evidence import (
    EXPECTED_GUARDS,
    PostgresOperationalEvidenceConfig,
)

from tests.core.operational_evidence.support import NOW
from tests.delivery.test_operational_evidence_readiness import _environment


def _grants(*, foreign: bool = False) -> object:
    async def read(_config: PostgresOperationalEvidenceConfig) -> ProofStoreGrantReadback:
        return ProofStoreGrantReadback(
            writer_role="fdai_operational_evidence_verifier",
            reader_roles=("fdai_core",),
            insert_holders=(
                ("fdai_core", "fdai_operational_evidence_verifier")
                if foreign
                else ("fdai_operational_evidence_verifier",)
            ),
            mutation_holders=(),
            writer_role_members=(),
            immutability_guards=EXPECTED_GUARDS,
            expected_guards=EXPECTED_GUARDS,
        )

    return read


async def _ready(_url: str) -> dict[str, object]:
    return {"state": "ready", "bound_purposes": ["operator-test-context-command"]}


def _env(tmp_path: Path, **principals: str) -> dict[str, str]:
    env = _environment(tmp_path, **principals)
    env["FDAI_OPERATIONAL_EVIDENCE_VERIFIER_DSN"] = "postgresql://placeholder@127.0.0.1:5433/x"
    return env


async def test_connected_venue_requires_separate_explicit_authorization(tmp_path: Path) -> None:
    receipt = await run_handoff(_env(tmp_path), venue="connected", root=tmp_path, now=NOW)
    assert [stage["stage"] for stage in receipt.stages] == ["authorization"]
    assert not receipt.passed and receipt.owed_observations == []


async def test_all_automatable_stages_pass_and_list_owed_drills(tmp_path: Path) -> None:
    env = {**_env(tmp_path), AUTHORIZATION_ENV: "1", "FDAI_SOURCE_SHA": "0" * 40}
    receipt = await run_handoff(
        env,
        venue="connected",
        root=tmp_path,
        grants_reader=_grants(),  # type: ignore[arg-type]
        readiness_reader=_ready,
        now=NOW,
    )
    assert receipt.passed
    assert [stage["stage"] for stage in receipt.stages] == [
        "identity",
        "registry",
        "writer_readback",
        "verifier_readiness",
    ]
    owed = receipt.owed_observations
    assert len([item for item in owed if item["stage"] == "positive_issuance"]) == 11
    drills = {item["class"] for item in owed if item["stage"] == "negative_drill"}
    assert {"stale", "revoked", "self_verified", "unavailable"} <= drills
    assert "#1026" in receipt.operational_qualification
    serialized = json.dumps(receipt.as_mapping())
    assert (
        "postgresql://" not in serialized and receipt.as_mapping()["execution_authority"] is False
    )


@pytest.mark.parametrize(
    ("principals", "foreign", "failed", "not_run"),
    [
        ({"anchor:operational-evidence-verifier": "fdai_core"}, False, "identity", 3),
        ({}, True, "writer_readback", 1),
    ],
)
async def test_first_failed_stage_stops_the_run(
    tmp_path: Path, principals: dict[str, str], foreign: bool, failed: str, not_run: int
) -> None:
    receipt = await run_handoff(
        _env(tmp_path, **principals),
        venue="local",
        root=tmp_path,
        grants_reader=_grants(foreign=foreign),  # type: ignore[arg-type]
        readiness_reader=_ready,
        now=NOW,
    )
    statuses = {str(stage["stage"]): stage["status"] for stage in receipt.stages}
    assert statuses[failed] == "failed"
    assert sum(1 for value in statuses.values() if value == "not_run") == not_run
    assert not receipt.passed


def test_plan_prints_the_stage_contract(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["plan"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["stages"] == ["identity", "registry", "writer_readback", "verifier_readiness"]
