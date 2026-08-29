"""Architecture-review readiness contract validation."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest
import yaml

_REPO_ROOT = Path(__file__).parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "governance" / "check-arb-readiness.py"
_MANIFEST = _REPO_ROOT / "config" / "architecture-review.yaml"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_check_arb_readiness", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MOD = _load_script()


def _manifest() -> dict[str, object]:
    raw = yaml.safe_load(_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def test_upstream_manifest_is_structurally_valid() -> None:
    _MOD.validate_contract(_manifest(), _REPO_ROOT, require_production_ready=False)


def test_production_mode_rejects_open_blockers() -> None:
    with pytest.raises(ValueError, match="unresolved critical/high blockers"):
        _MOD.validate_contract(_manifest(), _REPO_ROOT, require_production_ready=True)


def test_duplicate_artifact_id_is_rejected() -> None:
    raw = copy.deepcopy(_manifest())
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    artifacts = review["artifacts"]
    assert isinstance(artifacts, list)
    artifacts.append(copy.deepcopy(artifacts[0]))

    with pytest.raises(ValueError, match="duplicate artifact id"):
        _MOD.validate_contract(raw, _REPO_ROOT, require_production_ready=False)


def test_missing_evidence_path_is_rejected() -> None:
    raw = copy.deepcopy(_manifest())
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    artifacts = review["artifacts"]
    assert isinstance(artifacts, list)
    artifact = artifacts[0]
    assert isinstance(artifact, dict)
    artifact["evidence"] = ["docs/does-not-exist.md"]

    with pytest.raises(ValueError, match="references missing evidence"):
        _MOD.validate_contract(raw, _REPO_ROOT, require_production_ready=False)


def test_complete_production_bindings_pass_strict_mode() -> None:
    raw = copy.deepcopy(_manifest())
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    review["design_review_status"] = "approved"
    review["production_approval_status"] = "ready"
    artifacts = review["artifacts"]
    assert isinstance(artifacts, list)
    for artifact in artifacts:
        assert isinstance(artifact, dict)
        artifact["status"] = "ready"
    blockers = review["blockers"]
    assert isinstance(blockers, list)
    for blocker in blockers:
        assert isinstance(blocker, dict)
        blocker["status"] = "resolved"
    gate = review["production_gate"]
    assert isinstance(gate, dict)
    required_owners = gate["required_owner_slots"]
    required_evidence = gate["required_evidence"]
    assert isinstance(required_owners, list)
    assert isinstance(required_evidence, list)
    gate["owner_bindings"] = {
        slot: {"subject": f"group:{slot}", "escalation": "platform-maintainers"}
        for slot in required_owners
    }
    bodies = {str(item): f'{{"item":"{item}"}}'.encode() for item in required_evidence}
    gate["evidence_bindings"] = {
        str(item): {
            "uri": f"evidence://{item}",
            "sha256": hashlib.sha256(bodies[str(item)]).hexdigest(),
            "scope_ref": "scope:example-production",
            "revision": "revision:example-1",
            "approved_by": "group:architecture-reviewers",
            "approved_at": "2026-08-28T00:00:00Z",
            "expires_at": "2099-07-13T00:00:00Z",
            "freshness_seconds": 604800,
        }
        for item in required_evidence
    }
    attestations = {
        item: _MOD.ProductionEvidenceAttestation(
            uri=f"evidence://{item}",
            body=body,
            scope_ref="scope:example-production",
            revision="revision:example-1",
            observed_at=datetime(2026, 8, 28, tzinfo=UTC),
            authorized_approvers=("group:architecture-reviewers",),
            authentication_ref=f"auth:{item}",
            synthetic=False,
        )
        for item, body in bodies.items()
    }

    _MOD.validate_contract(
        raw,
        _REPO_ROOT,
        require_production_ready=True,
        evaluated_at=datetime(2026, 8, 29, tzinfo=UTC),
        evidence_attestations=attestations,
    )


def test_expired_production_evidence_is_rejected() -> None:
    raw = copy.deepcopy(_manifest())
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    gate = review["production_gate"]
    assert isinstance(gate, dict)
    gate["evidence_bindings"] = {
        "production-terraform-plan": {
            "uri": "evidence://production-terraform-plan",
            "sha256": "a" * 64,
            "scope_ref": "scope:example-production",
            "revision": "revision:example-1",
            "approved_by": "group:architecture-reviewers",
            "approved_at": "2026-07-01T00:00:00Z",
            "expires_at": "2026-07-15T00:00:00Z",
            "freshness_seconds": 604800,
        }
    }

    with pytest.raises(ValueError, match="expired production evidence"):
        _MOD.validate_contract(
            raw,
            _REPO_ROOT,
            require_production_ready=True,
            evaluated_at=datetime(2026, 7, 29, tzinfo=UTC),
        )


def test_cli_production_mode_cannot_certify_metadata_without_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw = copy.deepcopy(_manifest())
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    review["design_review_status"] = "approved"
    review["production_approval_status"] = "ready"
    for artifact in review["artifacts"]:
        assert isinstance(artifact, dict)
        artifact["status"] = "ready"
    for blocker in review["blockers"]:
        assert isinstance(blocker, dict)
        blocker["status"] = "resolved"
    gate = review["production_gate"]
    assert isinstance(gate, dict)
    required_owners = gate["required_owner_slots"]
    required_evidence = gate["required_evidence"]
    assert isinstance(required_owners, list)
    assert isinstance(required_evidence, list)
    gate["owner_bindings"] = {
        slot: {"subject": f"group:{slot}", "escalation": "platform-maintainers"}
        for slot in required_owners
    }
    gate["evidence_bindings"] = {
        item: {
            "uri": f"evidence://{item}",
            "sha256": hashlib.sha256(str(item).encode()).hexdigest(),
            "scope_ref": "scope:example-production",
            "revision": "revision:example-1",
            "approved_by": "group:architecture-reviewers",
            "approved_at": "2026-08-28T00:00:00Z",
            "expires_at": "2099-07-13T00:00:00Z",
            "freshness_seconds": 604800,
        }
        for item in required_evidence
    }
    manifest = tmp_path / "architecture-review.yaml"
    manifest.write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["check-arb-readiness.py", "--file", str(manifest), "--require-production-ready"],
    )

    assert _MOD.main() == 1
    assert "unattested production evidence" in capsys.readouterr().out
