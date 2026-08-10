#!/usr/bin/env python3
"""Validate final independent-service ownership and package boundaries."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import subprocess
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "config" / "independent-services.json"
LOCAL_TRANSITION_EVIDENCE_PATH = (
    REPO_ROOT / "config" / "independent-service-local-transition-evidence.json"
)
COMPATIBILITY_MANIFEST_PATH = (
    REPO_ROOT
    / "packages"
    / "service-contracts"
    / "src"
    / "fdai_service_contracts"
    / "compatibility-manifest.json"
)
UPGRADE_RECEIPTS_PATH = (
    REPO_ROOT
    / "packages"
    / "service-contracts"
    / "tests"
    / "fixtures"
    / "services"
    / "upgrade-receipts.json"
)
REMOTE_EVIDENCE_PATH = REPO_ROOT / "config" / "independent-service-remote-evidence.json"
REMOTE_EVIDENCE_BUNDLE_PATH = (
    REPO_ROOT / "config" / "independent-service-remote-evidence.attestation.jsonl"
)
LIVE_RECEIPTS_PATH = REPO_ROOT / "config" / "independent-service-live-receipts.json"
LIVE_EVIDENCE_MANIFEST_PATH = (
    REPO_ROOT / "config" / "independent-service-live-evidence-manifest.json"
)
COMPATIBILITY_CHECKER_PATH = (
    REPO_ROOT / "scripts" / "quality" / "architecture" / "check-service-compatibility.py"
)
REMOTE_EVIDENCE_VALIDATOR_PATH = (
    REPO_ROOT / "scripts" / "quality" / "architecture" / "remote_service_evidence.py"
)
LIVE_REMOTE_EVIDENCE_PATH = (
    REPO_ROOT / "scripts" / "quality" / "architecture" / "live_remote_evidence.py"
)
SERVICE_IDS = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)


def _load_manifest() -> dict[str, Any]:
    value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("independent-services manifest must be an object")
    return value


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        try:
            display_path = path.relative_to(REPO_ROOT)
        except ValueError:
            display_path = path
        raise ValueError(f"cannot load {label}: {display_path}") from exc


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _imports_prefix(path: Path, prefix: str) -> bool:
    def matches(module: str) -> bool:
        return module == prefix.removesuffix(".") or module.startswith(prefix)

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and matches(node.module or ""):
            return True
        if isinstance(node, ast.Import) and any(matches(alias.name) for alias in node.names):
            return True
    return False


def _count_files_importing(root: Path, prefix: str, pattern: str = "*.py") -> int:
    return sum(1 for path in root.rglob(pattern) if _imports_prefix(path, prefix))


def _count_service_forbidden_imports() -> int:
    forbidden_by_service = {
        "core-control-plane": (
            "fdai.delivery.operator_api",
            "fdai.delivery.ingestion_gateway",
            "fdai_executor_service",
            "fdai_operator_service",
            "fdai_ingestion_api_service",
            "fdai_document_worker_service",
        ),
        "operator-service": ("fdai.",),
        "document-ingestion-api": ("fdai.", "fdai_document_worker_service"),
        "document-processing-worker": ("fdai.", "fdai_ingestion_api_service"),
        "isolated-executor": ("fdai.",),
    }
    count = 0
    for service_id, prefixes in forbidden_by_service.items():
        source = REPO_ROOT / "services" / service_id / "src"
        count += sum(
            1
            for path in set(source.rglob("*.py"))
            if any(_imports_prefix(path, prefix) for prefix in prefixes)
        )
    return count


def _require_directory(path: Path, description: str) -> None:
    if not path.is_dir():
        raise ValueError(f"missing {description}: {path.relative_to(REPO_ROOT)}")


def _require_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise ValueError(f"missing {description}: {path.relative_to(REPO_ROOT)}")


def _validate_final_layout() -> None:
    for legacy_path in (
        REPO_ROOT / "Dockerfile",
        REPO_ROOT / "src" / "fdai",
        REPO_ROOT / "service-contracts",
        REPO_ROOT / "services" / "Dockerfile",
    ):
        if legacy_path.exists():
            raise ValueError(
                f"retired compatibility path must not exist: {legacy_path.relative_to(REPO_ROOT)}"
            )

    for service_id in SERVICE_IDS:
        service_root = REPO_ROOT / "services" / service_id
        _require_directory(service_root / "src", "service-owned source directory")
        _require_directory(service_root / "tests", "service-owned test directory")
        _require_file(service_root / "docker" / "Dockerfile", "service-owned Dockerfile")
        _require_file(service_root / "pyproject.toml", "service-owned distribution")

    contract_root = REPO_ROOT / "packages" / "service-contracts"
    _require_directory(contract_root / "src", "contract source directory")
    _require_directory(contract_root / "tests", "contract test directory")
    _require_file(contract_root / "pyproject.toml", "contract distribution")

    root_tests = REPO_ROOT / "tests"
    _require_directory(root_tests / "integration", "root integration test directory")
    unexpected = sorted(
        path.name
        for path in root_tests.iterdir()
        if path.name not in {"integration", "__pycache__", ".pytest_cache"}
    )
    if unexpected:
        raise ValueError(
            "root tests must contain integration tests only; unexpected entries: "
            + ", ".join(unexpected)
        )


def _distribution_scripts(target_package: Path) -> dict[str, str]:
    try:
        pyproject = tomllib.loads((target_package / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot load service distribution: {target_package}") from exc
    project = pyproject.get("project")
    scripts = project.get("scripts") if isinstance(project, dict) else None
    if not isinstance(scripts, dict) or not scripts:
        raise ValueError(f"service distribution has no project scripts: {target_package}")
    if not all(
        isinstance(name, str) and isinstance(target, str) for name, target in scripts.items()
    ):
        raise ValueError(f"service distribution scripts are malformed: {target_package}")
    return scripts


def _validate_graph(work_packages: list[dict[str, Any]]) -> None:
    by_id = {str(item["id"]): item for item in work_packages}
    if len(by_id) != len(work_packages):
        raise ValueError("work-package ids must be unique")
    remaining = set(by_id)
    resolved: set[str] = set()
    while remaining:
        ready = {
            item_id for item_id in remaining if set(by_id[item_id]["dependencies"]) <= resolved
        }
        if not ready:
            raise ValueError(f"cyclic or unknown work-package dependencies: {sorted(remaining)}")
        resolved.update(ready)
        remaining.difference_update(ready)


def _load_python_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load program-final validator: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_compatibility_checker() -> ModuleType:
    return _load_python_module(
        COMPATIBILITY_CHECKER_PATH,
        "check_service_compatibility_for_program_final",
    )


def _validate_remote_service_evidence(manifest: dict[str, Any], evidence: dict[str, Any]) -> Any:
    validator = _load_python_module(
        REMOTE_EVIDENCE_VALIDATOR_PATH,
        "remote_service_evidence_for_program_final",
    )
    return validator.validate_remote_service_evidence(manifest, evidence)


def _build_live_remote_evidence(
    compatibility: dict[str, Any], remote: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    builder = _load_python_module(
        LIVE_REMOTE_EVIDENCE_PATH,
        "live_remote_evidence_for_program_final",
    )
    return builder.build_live_remote_evidence(compatibility, remote)


def _validate_completed_remote_evidence(
    manifest: dict[str, Any],
    targets: dict[str, int],
) -> None:
    remote = _load_json(REMOTE_EVIDENCE_PATH, "remote service evidence")
    if not isinstance(remote, dict):
        raise ValueError("remote service evidence must be an object")
    summary = _validate_remote_service_evidence(manifest, remote)
    if (
        summary.service_plan_apply_receipts != targets["service_plan_apply_receipts"]
        or summary.service_upgrade_and_rollback_proofs
        != targets["service_upgrade_and_rollback_proofs"]
        or summary.protected_plan_runs != 15
        or summary.protected_apply_runs != 15
        or summary.peer_isolation_receipts != 30
    ):
        raise ValueError("remote service evidence does not satisfy program-final targets")
    live_receipts = _load_json(LIVE_RECEIPTS_PATH, "live service receipts")
    live_manifest = _load_json(LIVE_EVIDENCE_MANIFEST_PATH, "live service evidence manifest")
    compatibility = _load_json(COMPATIBILITY_MANIFEST_PATH, "compatibility manifest")
    if not isinstance(compatibility, dict):
        raise ValueError("compatibility manifest must be an object")
    expected_receipts, expected_manifest = _build_live_remote_evidence(compatibility, remote)
    if live_receipts != expected_receipts or live_manifest != expected_manifest:
        raise ValueError("live service evidence is not bound to remote transitions")
    _load_compatibility_checker().validate(
        mode="live",
        receipts_path=LIVE_RECEIPTS_PATH,
        evidence_manifest_path=LIVE_EVIDENCE_MANIFEST_PATH,
    )


def _validate_remote_attestation(policy: dict[str, Any]) -> None:
    attestation = policy.get("remote_attestation")
    if not isinstance(attestation, dict) or set(attestation) != {
        "state",
        "evidence_source_revision",
        "bundle_path",
        "signer_workflow",
    }:
        raise ValueError("program-final remote attestation fields are invalid")
    expected_bundle = REMOTE_EVIDENCE_BUNDLE_PATH.relative_to(REPO_ROOT).as_posix()
    if attestation.get("bundle_path") != expected_bundle:
        raise ValueError("program-final remote attestation bundle path is invalid")
    if (
        attestation.get("signer_workflow")
        != "dotnetpower/fdai/.github/workflows/remote-evidence-attest.yml"
    ):
        raise ValueError("program-final remote attestation signer is invalid")
    if policy["status"] != "completed":
        if attestation.get("state") != "pending" or attestation.get(
            "evidence_source_revision"
        ) not in {"", None}:
            raise ValueError("deferred program-final attestation must remain pending")
        return
    source_revision = attestation.get("evidence_source_revision")
    if (
        attestation.get("state") != "verified"
        or not isinstance(source_revision, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_revision) is None
    ):
        raise ValueError("completed program-final attestation is invalid")
    try:
        subprocess.run(
            [
                "gh",
                "attestation",
                "verify",
                str(REMOTE_EVIDENCE_PATH),
                "--bundle",
                str(REMOTE_EVIDENCE_BUNDLE_PATH),
                "--repo",
                "dotnetpower/fdai",
                "--signer-workflow",
                str(attestation["signer_workflow"]),
                "--source-digest",
                source_revision,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("program-final remote attestation verification failed") from exc


def _validate_program_final_verification(manifest: dict[str, Any]) -> None:
    policy = manifest["program_final_verification"]
    if policy["completion_basis"] != "local-executable-evidence":
        raise ValueError("independent-service completion must use local executable evidence")
    if policy["required_before_work_package"] != "IS-09":
        raise ValueError("remote verification must remain an IS-09 completion gate")
    if policy["status"] not in {"deferred", "completed"}:
        raise ValueError("program-final verification status is invalid")
    targets = policy["remote_targets"]
    accepted = policy["accepted_remote_evidence"]
    expected_keys = {
        "service_plan_apply_receipts",
        "service_upgrade_and_rollback_proofs",
    }
    if set(targets) != expected_keys or set(accepted) != expected_keys:
        raise ValueError("program-final verification evidence keys are invalid")
    if any(targets[key] != 5 for key in expected_keys):
        raise ValueError("program-final remote verification targets must cover five services")
    if any(not 0 <= accepted[key] <= targets[key] for key in expected_keys):
        raise ValueError("accepted remote verification evidence count is invalid")
    if policy["status"] == "completed":
        if accepted != targets:
            raise ValueError("completed program-final verification requires all remote evidence")
    _validate_remote_attestation(policy)
    if policy["status"] == "completed":
        _validate_completed_remote_evidence(manifest, targets)
    statuses = {item["id"]: item["status"] for item in manifest["work_packages"]}
    if statuses["IS-06"] != "completed":
        raise ValueError("IS-06 local deployment evidence must release IS-07")
    if statuses["IS-09"] == "completed" and (
        statuses["IS-07"] != "completed" or statuses["IS-08"] != "completed"
    ):
        raise ValueError("IS-09 cannot complete before IS-07 and IS-08")
    if statuses["IS-09"] == "completed" and policy["status"] != "completed":
        raise ValueError("IS-09 cannot complete before program-final remote verification")


def _validate_release_transition(manifest: dict[str, Any]) -> None:
    transition = manifest["release_transition"]
    if transition != {
        "n_distribution_version": "0.1.3",
        "n_source_revision": transition.get("n_source_revision"),
        "n_minus_one_distribution_version": "0.1.2",
        "n_minus_one_source_revision": transition.get("n_minus_one_source_revision"),
        "n_contract_set_version": "1.1.0",
        "n_minus_one_contract_set_version": "1.0.0",
    }:
        raise ValueError("independent-service release transition contract is invalid")
    for release in ("n", "n_minus_one"):
        revision = transition[f"{release}_source_revision"]
        if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            raise ValueError(
                f"{release.replace('_', '-').upper()} source revision must be a lowercase "
                "40-character git SHA"
            )
    for service in manifest["services"]:
        if service["distribution_version"] != transition["n_distribution_version"]:
            raise ValueError(f"{service['id']} N distribution version is inconsistent")
        if (
            service["previous_distribution_version"]
            != transition["n_minus_one_distribution_version"]
        ):
            raise ValueError(f"{service['id']} N-1 distribution version is inconsistent")
        if service["contract_set_version"] != transition["n_contract_set_version"]:
            raise ValueError(f"{service['id']} contract set version is inconsistent")


def _validate_local_transition_evidence(manifest: dict[str, Any]) -> None:
    evidence = _load_json(LOCAL_TRANSITION_EVIDENCE_PATH, "local transition evidence")
    if not isinstance(evidence, dict) or evidence.get("schema_version") != "1.0.0":
        raise ValueError("local transition evidence schema version is invalid")
    if set(evidence) != {
        "schema_version",
        "proof_kind",
        "matrix_digest",
        "n",
        "n_minus_one",
        "services",
        "summary",
    }:
        raise ValueError("local transition evidence fields are invalid")
    if evidence.get("proof_kind") != "local":
        raise ValueError("local transition evidence proof kind is invalid")
    transition = manifest["release_transition"]
    if evidence.get("n") != {
        "distribution_version": transition["n_distribution_version"],
        "source_revision": "f983b1117af2b10dfb7fcae914ce5222a12e6723",
    }:
        raise ValueError("local N artifact source is invalid")
    if evidence.get("n_minus_one") != {
        "distribution_version": transition["n_minus_one_distribution_version"],
        "source_revision": transition["n_minus_one_source_revision"],
    }:
        raise ValueError("local N-1 artifact source is invalid")
    compatibility = _load_json(COMPATIBILITY_MANIFEST_PATH, "compatibility manifest")
    if evidence.get("matrix_digest") != _canonical_digest(
        compatibility["producer_consumer_matrix"]
    ):
        raise ValueError("local transition matrix digest is invalid")
    raw_receipts = _load_json(UPGRADE_RECEIPTS_PATH, "focused upgrade receipts")
    if not isinstance(raw_receipts, list):
        raise ValueError("focused upgrade receipts must be an array")
    receipts = {
        (receipt.get("service_id"), receipt.get("direction")): receipt
        for receipt in raw_receipts
        if isinstance(receipt, dict)
    }
    service_map = {service["id"]: service for service in manifest["services"]}
    raw_services = evidence.get("services")
    if not isinstance(raw_services, list) or len(raw_services) != 5:
        raise ValueError("local transition evidence must contain five services")
    digest_pattern = re.compile(r"sha256:[0-9a-f]{64}")
    seen: set[str] = set()
    for item in raw_services:
        if not isinstance(item, dict) or item.get("id") not in service_map:
            raise ValueError("local transition evidence service identity is invalid")
        if set(item) != {
            "id",
            "distribution",
            "entrypoint",
            "n",
            "n_minus_one",
            "transition_sequence",
            "migration_receipt_id",
            "rollback_receipt_id",
            "peer_stable",
        }:
            raise ValueError("local transition evidence service fields are invalid")
        service_id = str(item["id"])
        if service_id in seen:
            raise ValueError("local transition evidence service ids must be unique")
        seen.add(service_id)
        service = service_map[service_id]
        if item.get("distribution") != service["distribution"]:
            raise ValueError(f"{service_id} evidence distribution is invalid")
        if item.get("entrypoint") != service["entrypoint"]:
            raise ValueError(f"{service_id} evidence entrypoint is invalid")
        for release in ("n", "n_minus_one"):
            artifact = item.get(release)
            if not isinstance(artifact, dict):
                raise ValueError(f"{service_id} {release} artifact is missing")
            if set(artifact) != {
                "wheel_sha256",
                "image_sha256",
                "nonroot_user",
                "healthcheck",
            }:
                raise ValueError(f"{service_id} {release} artifact fields are invalid")
            if any(
                not isinstance(artifact.get(key), str)
                or digest_pattern.fullmatch(str(artifact[key])) is None
                for key in ("wheel_sha256", "image_sha256")
            ):
                raise ValueError(f"{service_id} {release} artifact digest is invalid")
            if artifact.get("nonroot_user") != 65532 or artifact.get("healthcheck") is not True:
                raise ValueError(f"{service_id} {release} runtime contract is invalid")
        if item.get("transition_sequence") != ["0.1.3", "0.1.2", "0.1.3"]:
            raise ValueError(f"{service_id} transition sequence is invalid")
        if item.get("peer_stable") is not True:
            raise ValueError(f"{service_id} local transition is not peer stable")
        for direction in ("migration", "rollback"):
            receipt = receipts.get((service_id, direction))
            if receipt is None or item.get(f"{direction}_receipt_id") != receipt.get("receipt_id"):
                raise ValueError(f"{service_id} {direction} receipt binding is invalid")
            if (
                receipt.get("proof_kind") != "focused"
                or receipt.get("outcome") != "stable"
                or receipt.get("peer_versions_before") != receipt.get("peer_versions_after")
                or receipt.get("peer_restart_count") != 0
                or receipt.get("duplicate_terminal_effects") != 0
                or receipt.get("offsets_preserved") is not True
            ):
                raise ValueError(f"{service_id} {direction} receipt is not stable")
    if seen != set(SERVICE_IDS):
        raise ValueError("local transition evidence must cover the canonical five services")
    expected_summary = {
        "service_artifact_pairs": 5,
        "focused_transition_receipts": 10,
        "independent_upgrade_and_rollback_proofs": 5,
        "peer_restart_count": 0,
        "duplicate_terminal_effects": 0,
        "offsets_preserved": True,
        "outcome": "stable",
    }
    if evidence.get("summary") != expected_summary:
        raise ValueError("local transition evidence summary is invalid")
    if manifest["current_baseline"]["independent_upgrade_and_rollback_proofs"] != 5:
        raise ValueError("local transition proof baseline must be five")
    statuses = {item["id"]: item["status"] for item in manifest["work_packages"]}
    if statuses["IS-07"] != "completed":
        raise ValueError("IS-07 local transition evidence must release IS-09")


def validate() -> None:
    manifest = _load_manifest()
    services = manifest["services"]
    if manifest["target_service_count"] != 5 or len(services) != 5:
        raise ValueError("independent-services target must contain exactly five services")
    service_ids = [str(item["id"]) for item in services]
    if tuple(service_ids) != SERVICE_IDS:
        raise ValueError("independent-services manifest must name the canonical five services")
    _validate_final_layout()
    for service in services:
        for key in (
            "source_roots",
            "target_package",
            "entrypoint",
            "target_image",
            "target_terraform_root",
            "target_migration_branch",
        ):
            if not service.get(key):
                raise ValueError(f"{service['id']} is missing {key}")
        for source_root in service["source_roots"]:
            source_path = REPO_ROOT / source_root
            if not source_path.is_dir() or not any(source_path.rglob("*.py")):
                raise ValueError(f"missing service-owned source root: {source_root}")
        target_package = REPO_ROOT / service["target_package"]
        if not (target_package / "pyproject.toml").is_file():
            raise ValueError(f"missing service distribution: {service['target_package']}")
        scripts = _distribution_scripts(target_package)
        if service["entrypoint"] not in scripts:
            raise ValueError(
                f"{service['id']} entrypoint is not a service-owned distribution script"
            )
        terraform_root = REPO_ROOT / service["target_terraform_root"]
        if not (terraform_root / "main.tf").is_file():
            raise ValueError(f"missing service Terraform root: {service['target_terraform_root']}")
        migration_branch = (
            REPO_ROOT / "service-migrations" / "branches" / service["target_migration_branch"]
        )
        if not (migration_branch / "versions").is_dir():
            raise ValueError(
                f"missing service migration branch: {service['target_migration_branch']}"
            )

    _validate_graph(manifest["work_packages"])
    _validate_program_final_verification(manifest)
    _validate_release_transition(manifest)
    _validate_local_transition_evidence(manifest)
    baseline = manifest["current_baseline"]
    top_level_source_roots = int((REPO_ROOT / "src" / "fdai").exists())
    if top_level_source_roots != int(baseline["top_level_production_source_roots"]):
        raise ValueError("top-level production source root must be retired")
    forbidden_imports = _count_service_forbidden_imports()
    if forbidden_imports != 0:
        raise ValueError(
            f"cross-service implementation import count must be zero, got {forbidden_imports}"
        )
    targets = manifest["independence_targets"]
    if targets["cross_service_implementation_imports"] != 0:
        raise ValueError("cross-service implementation import target must be zero")
    for key in (
        "service_python_distributions",
        "service_images",
        "service_terraform_roots",
        "service_migration_branches",
        "independent_upgrade_and_rollback_proofs",
    ):
        if targets[key] != 5:
            raise ValueError(f"{key} target must be five")
    if baseline["service_python_distributions"] != 5:
        raise ValueError("all five service distributions must be present")
    print(
        "check-independent-services: OK "
        f"(services=5 top_level_source={top_level_source_roots} "
        f"service_forbidden={forbidden_imports})"
    )


def main() -> int:
    try:
        validate()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, SyntaxError) as exc:
        print(f"check-independent-services: ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
