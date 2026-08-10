#!/usr/bin/env python3
"""Bind tracked remote-service evidence to GitHub run and artifact records."""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from scripts.deployment.service.deployment_inputs import verify_unchanged
from scripts.quality.architecture.remote_service_evidence import SERVICE_IDS

REPOSITORY = "dotnetpower/fdai"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EVIDENCE = REPO_ROOT / "config" / "independent-service-remote-evidence.json"


class GitHubEvidenceError(ValueError):
    """Report a mismatch between tracked evidence and GitHub records."""


class GitHubClient(Protocol):
    """Read the bounded GitHub records needed by remote proof verification."""

    def json(self, path: str) -> Any: ...

    def bytes(self, url: str) -> bytes: ...


class ApiClient:
    """Read GitHub API records with one repository-scoped Actions token."""

    def __init__(self, token: str) -> None:
        if not token:
            raise GitHubEvidenceError("GitHub token is required")
        self._token = token

    def _request(self, url: str) -> urllib.request.Request:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "api.github.com":
            raise GitHubEvidenceError("GitHub API URL is outside the allowed origin")
        return urllib.request.Request(  # noqa: S310 - URL origin is constrained above.
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def json(self, path: str) -> Any:
        url = path if path.startswith("https://") else f"https://api.github.com/{path}"
        with urllib.request.urlopen(  # noqa: S310 - URL origin is constrained above.
            self._request(url), timeout=30
        ) as response:
            return json.load(response)

    def bytes(self, url: str) -> bytes:
        with urllib.request.urlopen(  # noqa: S310 - URL origin is constrained above.
            self._request(url), timeout=60
        ) as response:
            return bytes(response.read())


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GitHubEvidenceError(f"{label} must be an object")
    return value


def _archive_json(payload: bytes, basename: str) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        matches = [name for name in archive.namelist() if Path(name).name == basename]
        if len(matches) != 1:
            raise GitHubEvidenceError(f"artifact must contain one {basename}")
        return _object(json.loads(archive.read(matches[0])), basename)


def _run_record(client: GitHubClient, run: Mapping[str, Any], label: str) -> dict[str, Any]:
    run_id = run.get("workflow_run_id")
    value = _object(
        client.json(f"repos/{REPOSITORY}/actions/runs/{run_id}"),
        f"{label} GitHub run",
    )
    expected = {
        "id": run_id,
        "run_attempt": run.get("workflow_run_attempt"),
        "head_sha": run.get("workflow_head_sha"),
        "conclusion": "success",
        "run_started_at": run.get("started_at"),
        "updated_at": run.get("completed_at"),
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            raise GitHubEvidenceError(f"{label} GitHub {key} binding is invalid")
    return value


def _supply_chain_record(client: GitHubClient, release: Mapping[str, Any], label: str) -> None:
    run_id = release.get("supply_chain_run_id")
    value = _object(
        client.json(f"repos/{REPOSITORY}/actions/runs/{run_id}"),
        f"{label} GitHub run",
    )
    expected = {
        "id": run_id,
        "run_attempt": release.get("supply_chain_run_attempt"),
        "head_sha": release.get("workflow_head_sha"),
        "conclusion": "success",
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            raise GitHubEvidenceError(f"{label} GitHub {key} binding is invalid")


def _adoption_run_record(
    client: GitHubClient,
    run: Mapping[str, Any],
    service_id: str,
    *,
    step_name: str,
    step_conclusion_key: str,
    label: str,
) -> None:
    run_id = run.get("workflow_run_id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
        raise GitHubEvidenceError(f"{service_id} adoption GitHub run id is invalid")
    value = _object(
        client.json(f"repos/{REPOSITORY}/actions/runs/{run_id}"),
        f"{service_id} adoption GitHub run",
    )
    expected = {
        "id": run_id,
        "run_attempt": run.get("workflow_run_attempt"),
        "head_sha": run.get("workflow_head_sha"),
        "conclusion": run.get("conclusion"),
        "event": "workflow_dispatch",
        "head_branch": "main",
        "path": ".github/workflows/service-deploy.yml",
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            raise GitHubEvidenceError(f"{service_id} adoption GitHub {key} binding is invalid")
    _require_run_steps(
        client,
        run_id,
        {step_name: run.get(step_conclusion_key)},
        label=f"{service_id} adoption {label}",
    )


def _require_run_steps(
    client: GitHubClient,
    run_id: int,
    expected_steps: Mapping[str, object],
    *,
    label: str,
) -> None:
    jobs = _object(
        client.json(f"repos/{REPOSITORY}/actions/runs/{run_id}/jobs?per_page=100"),
        f"{label} GitHub jobs",
    ).get("jobs")
    if not isinstance(jobs, list):
        raise GitHubEvidenceError(f"{label} GitHub jobs are invalid")
    steps = [step for job in jobs if isinstance(job, dict) for step in job.get("steps", [])]
    for name, conclusion in expected_steps.items():
        matches = [step for step in steps if isinstance(step, dict) and step.get("name") == name]
        if len(matches) != 1 or matches[0].get("conclusion") != conclusion:
            raise GitHubEvidenceError(f"{label} GitHub step binding is invalid")


def _verify_adoptions(
    client: GitHubClient,
    evidence: Mapping[str, Any],
) -> None:
    adoptions = evidence.get("adoptions")
    if not isinstance(adoptions, list):
        raise GitHubEvidenceError("remote adoptions must be an array")
    for service_id, raw in zip(SERVICE_IDS, adoptions, strict=True):
        adoption = _object(raw, f"{service_id} adoption")
        completion = _object(adoption.get("completion"), f"{service_id} adoption completion")
        artifact_record = _object(adoption.get("artifact"), f"{service_id} adoption artifact")
        _adoption_run_record(
            client,
            completion,
            service_id,
            step_name="Apply service-owned database migrations",
            step_conclusion_key="migration_step_conclusion",
            label="completion",
        )
        _adoption_run_record(
            client,
            artifact_record,
            service_id,
            step_name="Upload service migration adoption evidence",
            step_conclusion_key="artifact_step_conclusion",
            label="artifact",
        )
        run_id = int(artifact_record["workflow_run_id"])
        attempt = int(artifact_record["workflow_run_attempt"])
        artifacts = _artifact_map(client, run_id)
        name = f"service-migration-adoption-{service_id}-dev-{run_id}-{attempt}"
        adoption_record = _artifact(
            client,
            artifacts,
            name=name,
            digest=artifact_record["artifact_sha256"],
            basename="service-migration-adoption.json",
        )
        expected_adoption = {
            "service_id": service_id,
            "observed_legacy_head": artifact_record["observed_legacy_head"],
            "observed_legacy_revision_count": artifact_record["observed_legacy_revision_count"],
            "observed_schema_fingerprint": artifact_record["observed_schema_fingerprint"],
            "schema_reference": "service-migration-schema.json",
            "verified_at": artifact_record["verified_at"],
            "rollback_reference": artifact_record["rollback_reference"],
        }
        if adoption_record != expected_adoption:
            raise GitHubEvidenceError(f"{service_id} adoption record binding is invalid")
        schema = _artifact(
            client,
            artifacts,
            name=name,
            digest=artifact_record["artifact_sha256"],
            basename="service-migration-schema.json",
        )
        if set(schema) != {
            "service_id",
            "schema_version",
            "observed_schema_fingerprint",
            "owned_tables",
            "verified_at",
        }:
            raise GitHubEvidenceError(f"{service_id} adoption schema fields are invalid")
        owned_tables = schema.get("owned_tables")
        if (
            schema.get("service_id") != service_id
            or schema.get("schema_version") != artifact_record["schema_version"]
            or schema.get("observed_schema_fingerprint")
            != artifact_record["observed_schema_fingerprint"]
            or schema.get("verified_at") != artifact_record["verified_at"]
            or not isinstance(owned_tables, list)
            or len(owned_tables) != artifact_record["owned_table_count"]
            or not all(isinstance(table, str) and table for table in owned_tables)
            or len(set(owned_tables)) != len(owned_tables)
        ):
            raise GitHubEvidenceError(f"{service_id} adoption schema binding is invalid")


def _artifact_map(client: GitHubClient, run_id: int) -> dict[str, dict[str, Any]]:
    response = _object(
        client.json(f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100"),
        "GitHub artifacts response",
    )
    raw = response.get("artifacts")
    if not isinstance(raw, list):
        raise GitHubEvidenceError("GitHub artifacts must be an array")
    artifacts: dict[str, dict[str, Any]] = {}
    for item in raw:
        artifact = _object(item, "GitHub artifact")
        name = artifact.get("name")
        if not isinstance(name, str) or name in artifacts:
            raise GitHubEvidenceError("GitHub artifact names must be unique strings")
        artifacts[name] = artifact
    return artifacts


def _artifact(
    client: GitHubClient,
    artifacts: Mapping[str, dict[str, Any]],
    *,
    name: str,
    digest: object,
    basename: str,
) -> dict[str, Any]:
    artifact = artifacts.get(name)
    if artifact is None or artifact.get("expired") is not False:
        raise GitHubEvidenceError(f"required GitHub artifact is unavailable: {name}")
    if artifact.get("digest") != digest:
        raise GitHubEvidenceError(f"GitHub artifact digest is invalid: {name}")
    url = artifact.get("archive_download_url")
    if not isinstance(url, str):
        raise GitHubEvidenceError(f"GitHub artifact download URL is invalid: {name}")
    return _archive_json(client.bytes(url), basename)


def _verify_peer_receipt(
    receipt: Mapping[str, Any],
    *,
    service_id: str,
    stage: Mapping[str, Any],
    run: Mapping[str, Any],
    mode: str,
    plan_run: Mapping[str, Any],
) -> None:
    image_digest = stage["image_digest"]
    expected = {
        "status": "verified",
        "mode": mode,
        "service": service_id,
        "commit_sha": stage["source_revision"],
        "workflow_run_id": str(run["workflow_run_id"]),
        "workflow_run_attempt": str(run["workflow_run_attempt"]),
        "plan_run_id": str(plan_run["workflow_run_id"]),
        "plan_run_attempt": str(plan_run["workflow_run_attempt"]),
        "plan_digest": str(plan_run["plan_digest"]).removeprefix("sha256:"),
        "context_digest": str(plan_run["context_digest"]).removeprefix("sha256:"),
        "peer_count": 4,
    }
    for key, wanted in expected.items():
        if receipt.get(key) != wanted:
            raise GitHubEvidenceError(
                f"{service_id} {stage['name']} {mode} peer receipt {key} is invalid"
            )
    image_ref = receipt.get("image_ref")
    if not isinstance(image_ref, str) or not image_ref.endswith(f"@{image_digest}"):
        raise GitHubEvidenceError(
            f"{service_id} {stage['name']} {mode} peer receipt image is invalid"
        )


def _verify_stage(
    client: GitHubClient,
    *,
    service_id: str,
    stage: Mapping[str, Any],
) -> None:
    plan = _object(stage.get("plan"), f"{service_id} plan")
    apply = _object(stage.get("apply"), f"{service_id} apply")
    _run_record(client, plan, f"{service_id} {stage['name']} plan")
    plan_id = int(plan["workflow_run_id"])
    plan_attempt = int(plan["workflow_run_attempt"])
    plan_artifacts = _artifact_map(client, plan_id)
    plan_name = f"service-plan-{service_id}-dev-{plan_id}-{plan_attempt}"
    metadata = _artifact(
        client,
        plan_artifacts,
        name=plan_name,
        digest=plan["metadata_artifact_sha256"],
        basename="service-plan-metadata.json",
    )
    expected_metadata = {
        "service": service_id,
        "commit_sha": stage["source_revision"],
        "image_digest": stage["image_digest"],
        "controls_commit_sha": plan["controls_commit_sha"],
        "workflow_run_id": str(plan_id),
        "workflow_run_attempt": str(plan_attempt),
        "deployment_mode": plan["deployment_mode"],
        "plan_digest": str(plan["plan_digest"]).removeprefix("sha256:"),
        "context_digest": str(plan["context_digest"]).removeprefix("sha256:"),
        "status": "ready",
    }
    for key, wanted in expected_metadata.items():
        if metadata.get(key) != wanted:
            raise GitHubEvidenceError(
                f"{service_id} {stage['name']} plan metadata {key} is invalid"
            )
    plan_peer_name = f"service-peer-isolation-{service_id}-dev-{plan_id}-{plan_attempt}"
    plan_receipt = _artifact(
        client,
        plan_artifacts,
        name=plan_peer_name,
        digest=plan["peer_receipt_artifact_sha256"],
        basename="service-peer-isolation-receipt.json",
    )
    _verify_peer_receipt(
        plan_receipt,
        service_id=service_id,
        stage=stage,
        run=plan,
        mode="plan",
        plan_run=plan,
    )
    _run_record(client, apply, f"{service_id} {stage['name']} apply")
    apply_id = int(apply["workflow_run_id"])
    apply_attempt = int(apply["workflow_run_attempt"])
    apply_artifacts = _artifact_map(client, apply_id)
    apply_peer_name = f"service-peer-isolation-{service_id}-dev-{apply_id}-{apply_attempt}"
    apply_receipt = _artifact(
        client,
        apply_artifacts,
        name=apply_peer_name,
        digest=apply["peer_receipt_artifact_sha256"],
        basename="service-peer-isolation-receipt.json",
    )
    _verify_peer_receipt(
        apply_receipt,
        service_id=service_id,
        stage=stage,
        run=apply,
        mode="apply",
        plan_run=plan,
    )
    _require_run_steps(
        client,
        apply_id,
        {
            "Verify immutable service image attestation": "success",
            "Apply service-owned database migrations": "success",
            "Verify post-apply service health": "success",
            "Verify peer isolation and seal receipt": "success",
            "Seal live service observations": "success",
            "Upload live service observations": "success",
        },
        label=f"{service_id} {stage['name']} apply",
    )
    live_name = f"service-live-observations-{service_id}-dev-{apply_id}-{apply_attempt}"
    live_record = _artifact(
        client,
        apply_artifacts,
        name=live_name,
        digest=apply["live_observation_artifact_sha256"],
        basename="service-live-observations.json",
    )
    expected_live_record = {
        "schema_version": "1.0.0",
        "service_id": service_id,
        "workflow_run_id": apply_id,
        "workflow_run_attempt": apply_attempt,
        "commit_sha": stage["source_revision"],
        "image_digest": stage["image_digest"],
        "plan_digest": plan["plan_digest"],
        "context_digest": plan["context_digest"],
        "observations": apply["observations"],
    }
    if live_record != expected_live_record:
        raise GitHubEvidenceError(
            f"{service_id} {stage['name']} live observation binding is invalid"
        )


def validate_github_evidence(
    evidence: dict[str, Any],
    client: GitHubClient,
    *,
    controls_equivalent: Callable[[str, str], None],
) -> None:
    """Verify every claimed remote run and artifact against GitHub records."""
    controls = str(evidence["controls_commit_sha"])
    checked_heads: set[str] = set()
    for release_name in ("n", "n_minus_one"):
        release = _object(evidence.get(release_name), f"{release_name} release")
        _supply_chain_record(client, release, f"{release_name} supply chain")
    _verify_adoptions(client, evidence)
    services = evidence.get("services")
    if not isinstance(services, list):
        raise GitHubEvidenceError("remote evidence services must be an array")
    for service in services:
        service_record = _object(service, "remote evidence service")
        service_id = str(service_record["id"])
        if service_id not in SERVICE_IDS:
            raise GitHubEvidenceError("remote evidence service id is invalid")
        stages = service_record.get("stages")
        if not isinstance(stages, list):
            raise GitHubEvidenceError(f"{service_id} stages must be an array")
        for stage in stages:
            stage_record = _object(stage, f"{service_id} stage")
            for mode in ("plan", "apply"):
                run = _object(stage_record[mode], f"{service_id} {mode}")
                head = str(run["workflow_head_sha"])
                if head not in checked_heads:
                    controls_equivalent(head, controls)
                    checked_heads.add(head)
            _verify_stage(client, service_id=service_id, stage=stage_record)


def _verify_image_attestations(evidence: Mapping[str, Any]) -> None:
    for release_name in ("n", "n_minus_one"):
        release = _object(evidence.get(release_name), f"{release_name} release")
        source = str(release["source_revision"])
        images = _object(release.get("images"), f"{release_name} images")
        for service_id, value in images.items():
            image = _object(value, f"{service_id} image")
            digest = str(image["digest"])
            image_name = IMAGE_NAMES[service_id]
            reference = f"oci://ghcr.io/dotnetpower/fdai/{image_name}@{digest}"
            for kind in image["attestations"]:
                predicate = {
                    "provenance": "https://slsa.dev/provenance/v1",
                    "sbom": "https://spdx.dev/Document/v2.3",
                    "resolved-models": (
                        "https://github.com/dotnetpower/fdai/attestations/resolved-models/v1"
                    ),
                }[kind]
                subprocess.run(
                    [
                        "gh",
                        "attestation",
                        "verify",
                        reference,
                        "--repo",
                        REPOSITORY,
                        "--source-digest",
                        source,
                        "--predicate-type",
                        predicate,
                        "--signer-workflow",
                        f"{REPOSITORY}/.github/workflows/container-supply-chain.yml",
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )


IMAGE_NAMES = {
    "core-control-plane": "fdai-core-control-plane",
    "operator-service": "fdai-operator-service",
    "document-ingestion-api": "fdai-document-ingestion-api",
    "document-processing-worker": "fdai-document-processing-worker",
    "isolated-executor": "fdai-isolated-executor",
}


def main() -> int:
    """Verify tracked remote evidence against GitHub and image attestations."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--repository-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--skip-image-attestations", action="store_true")
    args = parser.parse_args()
    try:
        evidence = _object(json.loads(args.evidence.read_text(encoding="utf-8")), "evidence")
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
        validate_github_evidence(
            evidence,
            ApiClient(token),
            controls_equivalent=lambda before, after: verify_unchanged(
                args.repository_root, before, after
            ),
        )
        if not args.skip_image_attestations:
            _verify_image_attestations(evidence)
    except (OSError, KeyError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"verify-remote-github-evidence: ERROR: {exc}")
        return 1
    print("verify-remote-github-evidence: OK (runs=32 artifacts=45 images=10)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
