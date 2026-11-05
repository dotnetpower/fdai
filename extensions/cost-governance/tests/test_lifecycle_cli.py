from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fdai.shared.providers.cost_governance_lifecycle import (
    CostEvidenceKind,
    CostLifecycleOperation,
    CostLifecycleOutcome,
    CostLifecycleReceipt,
    CostRevisionPin,
)

import fdai_cost_governance.lifecycle_cli as lifecycle_cli
from fdai_cost_governance.lifecycle_cli import (
    _canonical_digest,
    _json_object,
    _parser,
    _psycopg_dsn,
    _register_release,
    _release_identity,
    _required_digest,
    _required_path,
    _required_revision,
    _required_text,
    _run,
    _runtime_config_digest,
    _set_enabled,
    main,
)


def _wheel(
    tmp_path: Path,
    *,
    tamper_resource: bool = False,
    resource_path: str = "semantic-profile.json",
) -> Path:
    profile_body = {
        "ontology_release_digest": f"sha256:{'a' * 64}",
        "package_id": "cost-governance",
        "schema_version": "1.0.0",
    }
    profile = {
        **profile_body,
        "canonical_sha256": _canonical_digest(profile_body),
    }
    profile_bytes = json.dumps(profile, sort_keys=True).encode()
    manifest = {
        "assets": [
            {
                "id": "semantic-profile:cost-governance",
                "kind": "semantic_profile",
                "path": resource_path,
                "references": [],
                "sha256": hashlib.sha256(profile_bytes).hexdigest(),
            }
        ],
        "candidate_state": "inert",
        "package_id": "cost-governance",
        "package_version": "0.1.1",
        "schema_version": "1.0.0",
    }
    wheel = tmp_path / "fdai_cost_governance-0.1.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "fdai_cost_governance-0.1.1.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: fdai-cost-governance\nVersion: 0.1.1\n",
        )
        archive.writestr(
            "fdai_cost_governance/resources/manifest.json",
            json.dumps(manifest),
        )
        archive.writestr(
            str(Path("fdai_cost_governance/resources") / resource_path),
            b"tampered" if tamper_resource else profile_bytes,
        )
    return wheel


def test_release_identity_is_derived_from_verified_wheel_bytes(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)

    identity = _release_identity(wheel)

    assert identity.package_version == "0.1.1"
    assert identity.wheel_digest == f"sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}"
    assert identity.semantic_profile_digest.startswith("sha256:")
    assert identity.ontology_release_digest == f"sha256:{'a' * 64}"


def test_release_identity_rejects_tampered_wheel_resource(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="resource digest mismatch"):
        _release_identity(_wheel(tmp_path, tamper_resource=True))


def test_release_identity_rejects_resource_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="member path escapes"):
        _release_identity(_wheel(tmp_path, resource_path="../semantic-profile.json"))


def test_runtime_config_digest_rejects_duplicate_keys(tmp_path: Path) -> None:
    config = tmp_path / "runtime-config.json"
    config.write_text('{"enabled":true,"enabled":false}', encoding="utf-8")

    with pytest.raises(ValueError, match="repeats key"):
        _runtime_config_digest(config)


def test_release_identity_and_validator_edge_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="bounded regular file"):
        _release_identity(tmp_path / "missing.whl")
    with pytest.raises(ValueError, match="bounded regular file"):
        _runtime_config_digest(tmp_path / "missing.json")
    with pytest.raises(ValueError, match="exceeds the byte limit"):
        _json_object(b"x" * (1024 * 1024 + 1), label="blob")
    with pytest.raises(ValueError, match="MUST contain a JSON object"):
        _json_object(b"[1, 2]", label="array")
    with pytest.raises(ValueError, match="is invalid"):
        _json_object(b"{bad", label="malformed")
    with pytest.raises(ValueError, match="is required"):
        _required_path(None, "--wheel")
    with pytest.raises(ValueError, match="sha256:<digest>"):
        _required_digest("bad", "--image-digest")
    with pytest.raises(ValueError, match="40-character revision"):
        _required_revision("short")
    with pytest.raises(ValueError, match="bounded non-empty ASCII"):
        _required_text("", "--ontology-release-id")
    assert _psycopg_dsn("postgresql+psycopg://localhost/db") == "postgresql://localhost/db"

    dup_wheel = tmp_path / "dup.whl"
    with zipfile.ZipFile(dup_wheel, "w") as zf:
        zf.writestr("a.txt", "1")
        zf.writestr("a.txt", "2")
    with pytest.raises(ValueError, match="duplicate member names"):
        _release_identity(dup_wheel)

    no_meta = tmp_path / "nometa.whl"
    with zipfile.ZipFile(no_meta, "w") as zf:
        zf.writestr("other.txt", "1")
    with pytest.raises(ValueError, match="one Cost Governance METADATA"):
        _release_identity(no_meta)

    def _custom_wheel(
        name: str,
        *,
        pkg_name: str = "fdai-cost-governance",
        version: str = "0.1.1",
        manifest_override: dict[str, object] | None = None,
        profile_override: dict[str, object] | None = None,
    ) -> Path:
        p_body = {
            "ontology_release_digest": f"sha256:{'a' * 64}",
            "package_id": "cost-governance",
            "schema_version": "1.0.0",
        }
        prof = profile_override or {**p_body, "canonical_sha256": _canonical_digest(p_body)}
        p_bytes = json.dumps(prof, sort_keys=True).encode()
        man = manifest_override or {
            "assets": [
                {
                    "id": "semantic-profile:cost-governance",
                    "kind": "semantic_profile",
                    "path": "semantic-profile.json",
                    "references": [],
                    "sha256": hashlib.sha256(p_bytes).hexdigest(),
                }
            ],
            "candidate_state": "inert",
            "package_id": "cost-governance",
            "package_version": version,
            "schema_version": "1.0.0",
        }
        w_path = tmp_path / name
        with zipfile.ZipFile(w_path, "w") as zf:
            zf.writestr(
                "fdai_cost_governance-0.1.1.dist-info/METADATA",
                f"Metadata-Version: 2.4\nName: {pkg_name}\nVersion: {version}\n",
            )
            zf.writestr("fdai_cost_governance/resources/manifest.json", json.dumps(man))
            zf.writestr("fdai_cost_governance/resources/semantic-profile.json", p_bytes)
        return w_path

    with pytest.raises(ValueError, match="not fdai-cost-governance"):
        _release_identity(_custom_wheel("badname.whl", pkg_name="other"))
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        _release_identity(_custom_wheel("badver.whl", version="0.1"))
    with pytest.raises(ValueError, match="manifest identity is inconsistent"):
        _release_identity(
            _custom_wheel(
                "badman.whl",
                manifest_override={"package_id": "other", "package_version": "0.1.1"},
            )
        )
    with pytest.raises(ValueError, match="assets MUST be non-empty"):
        _release_identity(
            _custom_wheel(
                "emptyassets.whl",
                manifest_override={
                    "package_id": "cost-governance",
                    "package_version": "0.1.1",
                    "candidate_state": "inert",
                    "assets": [],
                },
            )
        )
    with pytest.raises(ValueError, match="asset is invalid"):
        _release_identity(
            _custom_wheel(
                "nondictasset.whl",
                manifest_override={
                    "package_id": "cost-governance",
                    "package_version": "0.1.1",
                    "candidate_state": "inert",
                    "assets": ["bad"],
                },
            )
        )
    with pytest.raises(ValueError, match="asset identity is invalid"):
        _release_identity(
            _custom_wheel(
                "badassetid.whl",
                manifest_override={
                    "package_id": "cost-governance",
                    "package_version": "0.1.1",
                    "candidate_state": "inert",
                    "assets": [{"id": "a", "path": 1, "sha256": 2}],
                },
            )
        )
    with pytest.raises(ValueError, match="unique and bounded"):
        _release_identity(
            _custom_wheel(
                "unboundasset.whl",
                manifest_override={
                    "package_id": "cost-governance",
                    "package_version": "0.1.1",
                    "candidate_state": "inert",
                    "assets": [{"id": "", "path": "semantic-profile.json", "sha256": "abc"}],
                },
            )
        )
    with pytest.raises(ValueError, match="semantic profile digest mismatch"):
        _release_identity(
            _custom_wheel(
                "badprof.whl",
                profile_override={
                    "ontology_release_digest": f"sha256:{'a' * 64}",
                    "canonical_sha256": f"sha256:{'0' * 64}",
                },
            )
        )

    valid_wheel = _wheel(tmp_path)
    monkeypatch.setattr(lifecycle_cli, "_MAX_WHEEL_CONTENT_BYTES", 5)
    with pytest.raises(ValueError, match="uncompressed content exceeds"):
        _release_identity(valid_wheel)


async def test_lifecycle_cli_db_and_main_flows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    pin = CostRevisionPin(
        package_id="cost-governance",
        package_version="0.1.1",
        source_revision="a" * 40,
        wheel_digest=f"sha256:{'b' * 64}",
        image_digest=f"sha256:{'c' * 64}",
        asset_manifest_digest=f"sha256:{'d' * 64}",
        semantic_profile_digest=f"sha256:{'e' * 64}",
        ontology_release_digest=f"sha256:{'f' * 64}",
        runtime_config_digest=f"sha256:{'0' * 64}",
        activation_revision=1,
    )
    state_box: dict[str, Any] = {
        "replay_row": None,
        "result_row": {"revision": 1, "enabled": True},
        "receipt_op": CostLifecycleOperation.ENABLE,
        "receipt_key": "req-1",
    }

    class _FakeCursor:
        def __init__(self, row: Any) -> None:
            self._row = row

        async def fetchone(self) -> Any:
            return self._row

    class _FakeConn:
        async def __aenter__(self) -> _FakeConn:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def execute(self, sql: str, params: Any = None) -> _FakeCursor:
            if "FROM cost_governance_lifecycle_receipt" in sql:
                return _FakeCursor(state_box["replay_row"])
            return _FakeCursor(state_box["result_row"])

    async def _fake_connect(*args: Any, **kwargs: Any) -> _FakeConn:
        return _FakeConn()

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _fake_connect)

    class _FakeValStore:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

        async def read_cost_lifecycle_receipts(
            self, package_id: str, limit: int
        ) -> tuple[Any, ...]:
            return (
                CostLifecycleReceipt(
                    schema_version="1.0.0",
                    receipt_id="rec-1",
                    idempotency_key=state_box["receipt_key"],
                    operation=state_box["receipt_op"],
                    outcome=CostLifecycleOutcome.SUCCEEDED,
                    revision_pin=pin,
                    available=True,
                    enabled=state_box["receipt_op"]
                    not in {CostLifecycleOperation.INSTALL, CostLifecycleOperation.DISABLE},
                    occurred_at=now,
                    evidence_kind=CostEvidenceKind.LIVE_AUTHORITATIVE,
                    evidence_refs=("ev:1",),
                    retention_until=now + timedelta(days=400),
                ),
            )

    monkeypatch.setattr(lifecycle_cli, "PostgresCostGovernanceValidationStore", _FakeValStore)

    parser = _parser()
    with pytest.raises(ValueError, match="FDAI_STATE_STORE_DSN MUST be configured"):
        await _run(
            parser.parse_args(["enable", "--expected-revision", "0", "--request-id", "r"]),
            {},
        )
    with pytest.raises(ValueError, match="nonnegative"):
        await _run(
            parser.parse_args(["enable", "--expected-revision", "-1", "--request-id", "r"]),
            {"FDAI_STATE_STORE_DSN": "postgresql://localhost/db"},
        )
    with pytest.raises(ValueError, match="require --actor-id"):
        await _run(
            parser.parse_args(["enable", "--expected-revision", "0", "--request-id", "r"]),
            {"FDAI_STATE_STORE_DSN": "postgresql://localhost/db"},
        )

    out_enable = await _run(
        parser.parse_args(
            ["enable", "--expected-revision", "0", "--request-id", "req-1", "--actor-id", "op-1"]
        ),
        {"FDAI_STATE_STORE_DSN": "postgresql://localhost/db"},
    )
    assert out_enable["operation"] == "enable"

    wheel = _wheel(tmp_path)
    rt_cfg = tmp_path / "rt.json"
    rt_cfg.write_text('{"mode":"shadow"}', encoding="utf-8")

    with pytest.raises(ValueError, match="requires --evidence-ref"):
        await _run(
            parser.parse_args(
                [
                    "install",
                    "--expected-revision",
                    "0",
                    "--request-id",
                    "req-1",
                    "--wheel",
                    str(wheel),
                    "--image-digest",
                    f"sha256:{'c' * 64}",
                    "--source-revision",
                    "a" * 40,
                    "--runtime-config",
                    str(rt_cfg),
                    "--ontology-release-id",
                    "rel-1",
                ]
            ),
            {"FDAI_STATE_STORE_DSN": "postgresql://localhost/db"},
        )

    state_box["receipt_op"] = CostLifecycleOperation.INSTALL
    out_install = await _run(
        parser.parse_args(
            [
                "install",
                "--expected-revision",
                "0",
                "--request-id",
                "req-1",
                "--wheel",
                str(wheel),
                "--image-digest",
                f"sha256:{'c' * 64}",
                "--source-revision",
                "a" * 40,
                "--runtime-config",
                str(rt_cfg),
                "--ontology-release-id",
                "rel-1",
                "--evidence-ref",
                "ev:1",
            ]
        ),
        {"FDAI_STATE_STORE_DSN": "postgresql://localhost/db"},
    )
    assert out_install["operation"] == "install"

    state_box["receipt_key"] = "other-key"
    with pytest.raises(RuntimeError, match="receipt verification failed"):
        await _run(
            parser.parse_args(
                ["enable", "--expected-revision", "0", "--request-id", "req-1", "--actor-id", "op"]
            ),
            {"FDAI_STATE_STORE_DSN": "postgresql://localhost/db"},
        )

    state_box["result_row"] = None
    with pytest.raises(RuntimeError, match="returned no state"):
        await _set_enabled(
            dsn="postgresql://localhost/db",
            enabled=True,
            expected_revision=0,
            request_id="req-1",
            actor_id="op",
        )
    with pytest.raises(RuntimeError, match="returned no state"):
        await _register_release(
            dsn="postgresql://localhost/db",
            operation="install",
            expected_revision=0,
            request_id="req-1",
            evidence_refs=("ev:1",),
            identity=_release_identity(wheel),
            image_digest=f"sha256:{'c' * 64}",
            source_revision="a" * 40,
            runtime_config_digest=_runtime_config_digest(rt_cfg),
            ontology_release_id="rel-1",
        )


def test_lifecycle_cli_main_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_run(args: Any, env: Any) -> dict[str, object]:
        if not env.get("FDAI_STATE_STORE_DSN"):
            raise ValueError("missing dsn")
        return {"ok": True}

    monkeypatch.setattr(lifecycle_cli, "_run", _fake_run)
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://localhost/db")
    assert (
        main(["enable", "--expected-revision", "0", "--request-id", "req-1", "--actor-id", "op"])
        == 0
    )
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    assert (
        main(["enable", "--expected-revision", "0", "--request-id", "req-1", "--actor-id", "op"])
        == 2
    )
