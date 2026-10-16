from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fdai.runtime.bootstrap_loki_scenarios import build_loki_scenario_bindings

_ACTION = "tool.run-chaos-experiment"
_REVISION = "a" * 40


def _schedule(schedule_id: str, target: str) -> dict[str, object]:
    return {
        "schedule_id": schedule_id,
        "cadence_seconds": 3600,
        "targets": [target],
        "action_type": _ACTION,
        "start_at": "2026-10-01T00:00:00+00:00",
        "causal_hypothesis_ref": f"hypothesis:{schedule_id}",
        "refutation_query_ref": f"query:{schedule_id}",
        "impact_envelope_id": f"impact:{schedule_id}",
        "recovery_plan_id": f"recovery:{schedule_id}",
        "dry_run_receipt": f"dry-run:{schedule_id}",
    }


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "source_revision": _REVISION,
        "review_ref": "review:loki:42",
        "design_ref": "design:loki:42",
        "frozen_corpus": [_schedule("baseline", "resource-a")],
        "candidates": [
            {
                "scenario_id": "candidate-b",
                "schedule": _schedule("candidate", "resource-b"),
                "evidence_refs": ["evidence:loki:42"],
            }
        ],
    }


def _environment(path: Path, payload: dict[str, object]) -> dict[str, str]:
    content = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    path.write_bytes(content)
    return {
        "FDAI_LOKI_SCENARIO_EVIDENCE_PATH": str(path),
        "FDAI_LOKI_SCENARIO_EVIDENCE_SHA256": hashlib.sha256(content).hexdigest(),
        "FDAI_SOURCE_REVISION": _REVISION,
    }


async def test_reviewed_loki_source_binds_generator_and_frozen_corpus(tmp_path: Path) -> None:
    bindings = build_loki_scenario_bindings(
        environment=_environment(tmp_path / "loki.json", _manifest()),
        action_type_names=frozenset({_ACTION}),
    )
    assert bindings is not None
    assert [item.schedule_id for item in bindings.corpus] == ["baseline"]
    candidates = await bindings.generator.generate_scenarios("design:loki:42")
    assert [item.scenario_id for item in candidates] == ["candidate-b"]
    with pytest.raises(ValueError, match="design reference differs"):
        await bindings.generator.generate_scenarios("design:other")


@pytest.mark.parametrize("mutation", ["digest", "revision", "unknown_field", "duplicate_coverage"])
def test_reviewed_loki_source_rejects_changed_evidence(tmp_path: Path, mutation: str) -> None:
    payload = _manifest()
    environment = _environment(tmp_path / "loki.json", payload)
    if mutation == "digest":
        environment["FDAI_LOKI_SCENARIO_EVIDENCE_SHA256"] = "f" * 64
    elif mutation == "revision":
        environment["FDAI_SOURCE_REVISION"] = "b" * 40
    elif mutation == "duplicate_coverage":
        duplicate_schedule = _schedule("candidate", "resource-b")
        duplicate_schedule["schedule_id"] = "candidate-two"
        payload["candidates"] = [
            *payload["candidates"],  # type: ignore[misc]
            {
                "scenario_id": "candidate-c",
                "schedule": duplicate_schedule,
                "evidence_refs": ["evidence:loki:43"],
            },
        ]
        environment = _environment(tmp_path / "loki.json", payload)
    else:
        payload["execution_authority"] = True
        environment = _environment(tmp_path / "loki.json", payload)
    with pytest.raises(RuntimeError, match="evidence is invalid"):
        build_loki_scenario_bindings(
            environment=environment,
            action_type_names=frozenset({_ACTION}),
        )


def test_absent_loki_source_stays_unbound() -> None:
    assert build_loki_scenario_bindings(environment={}, action_type_names=frozenset()) is None
