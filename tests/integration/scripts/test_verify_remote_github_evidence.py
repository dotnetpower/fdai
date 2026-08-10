from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

import pytest
from scripts.quality.architecture.verify_remote_github_evidence import (
    GitHubEvidenceError,
    _adoption_run_record,
    _artifact,
    _ArtifactRedirectHandler,
    _run_record,
    _verify_adoption_controls,
    _verify_stage,
    _verify_transition_control_equivalence,
)

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = (_ROOT / ".github/workflows/remote-evidence-attest.yml").read_text(encoding="utf-8")


class _Client:
    def __init__(self, records: dict[str, Any], archives: dict[str, bytes] | None = None) -> None:
        self.records = records
        self.archives = archives or {}

    def json(self, path: str) -> Any:
        return self.records[path]

    def bytes(self, url: str) -> bytes:
        return self.archives[url]


def _run() -> dict[str, Any]:
    return {
        "workflow_run_id": 123,
        "workflow_run_attempt": 2,
        "workflow_head_sha": "a" * 40,
        "started_at": "2026-08-10T00:00:00Z",
        "completed_at": "2026-08-10T00:01:00Z",
    }


def _archive(name: str, value: object) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, json.dumps(value))
    return output.getvalue()


def test_run_record_binds_exact_github_metadata() -> None:
    client = _Client(
        {
            "repos/dotnetpower/fdai/actions/runs/123": {
                "id": 123,
                "run_attempt": 2,
                "head_sha": "a" * 40,
                "conclusion": "success",
                "run_started_at": "2026-08-10T00:00:00Z",
                "updated_at": "2026-08-10T00:01:00Z",
            }
        }
    )

    _run_record(client, _run(), "test run")


def test_run_record_rejects_invented_conclusion() -> None:
    client = _Client(
        {
            "repos/dotnetpower/fdai/actions/runs/123": {
                "id": 123,
                "run_attempt": 2,
                "head_sha": "a" * 40,
                "conclusion": "failure",
                "run_started_at": "2026-08-10T00:00:00Z",
                "updated_at": "2026-08-10T00:01:00Z",
            }
        }
    )

    with pytest.raises(GitHubEvidenceError, match="conclusion binding is invalid"):
        _run_record(client, _run(), "test run")


def test_adoption_run_allows_later_failure_only_after_successful_adoption_steps() -> None:
    adoption_run = {
        "workflow_run_id": 123,
        "workflow_run_attempt": 2,
        "workflow_head_sha": "a" * 40,
        "conclusion": "failure",
        "migration_step_conclusion": "success",
    }
    records = {
        "repos/dotnetpower/fdai/actions/runs/123": {
            "id": 123,
            "run_attempt": 2,
            "head_sha": "a" * 40,
            "conclusion": "failure",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "path": ".github/workflows/service-deploy.yml",
        },
        "repos/dotnetpower/fdai/actions/runs/123/jobs?per_page=100": {
            "jobs": [
                {
                    "steps": [
                        {
                            "name": "Apply service-owned database migrations",
                            "conclusion": "success",
                        },
                        {
                            "name": "Upload service migration adoption evidence",
                            "conclusion": "success",
                        },
                    ]
                }
            ]
        },
    }

    _adoption_run_record(
        _Client(records),
        adoption_run,
        "isolated-executor",
        step_name="Apply service-owned database migrations",
        step_conclusion_key="migration_step_conclusion",
        label="completion",
    )

    records["repos/dotnetpower/fdai/actions/runs/123/jobs?per_page=100"]["jobs"][0]["steps"][0][
        "conclusion"
    ] = "failure"
    with pytest.raises(GitHubEvidenceError, match="step binding is invalid"):
        _adoption_run_record(
            _Client(records),
            adoption_run,
            "isolated-executor",
            step_name="Apply service-owned database migrations",
            step_conclusion_key="migration_step_conclusion",
            label="completion",
        )


def test_split_adoption_revisions_must_ancestry_bind_to_aggregate_controls() -> None:
    checked: list[tuple[str, str]] = []

    _verify_adoption_controls(
        {"workflow_head_sha": "a" * 40},
        {"workflow_head_sha": "b" * 40, "controls_commit_sha": "c" * 40},
        controls="d" * 40,
        controls_ancestor=lambda before, after: checked.append((before, after)),
    )

    assert checked == [
        ("a" * 40, "d" * 40),
        ("b" * 40, "d" * 40),
        ("c" * 40, "d" * 40),
    ]


def test_artifact_binds_api_digest_and_downloaded_content() -> None:
    payload = _archive("nested/service-plan-metadata.json", {"status": "ready"})
    client = _Client({}, {"https://api.github.test/archive": payload})
    artifacts = {
        "service-plan": {
            "digest": "sha256:" + "b" * 64,
            "expired": False,
            "archive_download_url": "https://api.github.test/archive",
        }
    }

    value = _artifact(
        client,
        artifacts,
        name="service-plan",
        digest="sha256:" + "b" * 64,
        basename="service-plan-metadata.json",
    )

    assert value == {"status": "ready"}


def test_artifact_rejects_self_asserted_digest() -> None:
    client = _Client({}, {})
    artifacts = {
        "service-plan": {
            "digest": "sha256:" + "b" * 64,
            "expired": False,
            "archive_download_url": "https://api.github.test/archive",
        }
    }

    with pytest.raises(GitHubEvidenceError, match="artifact digest is invalid"):
        _artifact(
            client,
            artifacts,
            name="service-plan",
            digest="sha256:" + "c" * 64,
            basename="service-plan-metadata.json",
        )


def test_artifact_redirect_removes_api_authorization() -> None:
    request = _ArtifactRedirectHandler().redirect_request(
        urllib_request.Request(
            "https://api.github.com/repos/dotnetpower/fdai/actions/artifacts/1/zip",
            headers={"Authorization": "Bearer secret"},
        ),
        None,
        302,
        "Found",
        {},
        "https://productionresultssa10.blob.core.windows.net/actions-results/archive.zip?sig=x",
    )

    assert request.get_header("Authorization") is None
    assert request.get_header("Accept") == "application/octet-stream"


def test_artifact_redirect_rejects_untrusted_origin() -> None:
    with pytest.raises(GitHubEvidenceError, match="outside the allowed origin"):
        _ArtifactRedirectHandler().redirect_request(
            urllib_request.Request("https://api.github.com/artifact"),
            None,
            302,
            "Found",
            {},
            "https://example.com/archive.zip",
        )


def test_stage_rejects_apply_controls_not_bound_to_plan() -> None:
    stage = {
        "name": "rollback",
        "plan": {"controls_commit_sha": "a" * 40},
        "apply": {"controls_commit_sha": "b" * 40},
    }

    with pytest.raises(GitHubEvidenceError, match="apply controls are not bound"):
        _verify_stage(_Client({}), service_id="operator-service", stage=stage)


def test_transition_controls_check_each_unique_revision_once() -> None:
    checked: list[tuple[str, str]] = []
    services = [
        {
            "id": "operator-service",
            "stages": [
                {
                    "plan": {
                        "workflow_head_sha": "b" * 40,
                        "controls_commit_sha": "c" * 40,
                    },
                    "apply": {
                        "workflow_head_sha": "d" * 40,
                        "controls_commit_sha": "c" * 40,
                    },
                },
                {
                    "plan": {
                        "workflow_head_sha": "e" * 40,
                        "controls_commit_sha": "f" * 40,
                    },
                    "apply": {
                        "workflow_head_sha": "e" * 40,
                        "controls_commit_sha": "f" * 40,
                    },
                },
            ],
        }
    ]

    _verify_transition_control_equivalence(
        services,
        controls="a" * 40,
        controls_equivalent=lambda before, after: checked.append((before, after)),
    )

    assert checked == [
        ("b" * 40, "a" * 40),
        ("c" * 40, "a" * 40),
        ("d" * 40, "a" * 40),
        ("e" * 40, "a" * 40),
        ("f" * 40, "a" * 40),
    ]


def test_remote_evidence_workflow_is_read_only_and_pinned() -> None:
    assert "actions: read" in _WORKFLOW
    assert "contents: read" in _WORKFLOW
    assert "attestations: write" in _WORKFLOW
    assert "id-token: write" in _WORKFLOW
    assert "packages: read" in _WORKFLOW
    assert "PYTHONPATH: ${{ github.workspace }}" in _WORKFLOW
    assert "diff --brief" in _WORKFLOW
    assert "diff --quiet" not in _WORKFLOW
    assert "verify_remote_github_evidence.py" in _WORKFLOW
    assert "check-remote-service-evidence.py" in _WORKFLOW
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in _WORKFLOW
    assert "actions/attest@f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6" in _WORKFLOW
    assert "docker/login-action@abd2ef45e78c5afb21d64d4ca52ee8550d9572c7" in _WORKFLOW
