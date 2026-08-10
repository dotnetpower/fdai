from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from scripts.quality.architecture.verify_remote_github_evidence import (
    GitHubEvidenceError,
    _adoption_run_record,
    _artifact,
    _run_record,
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
    adoption = {
        "workflow_run_id": 123,
        "workflow_run_attempt": 2,
        "workflow_head_sha": "a" * 40,
        "conclusion": "failure",
        "migration_step_conclusion": "success",
        "artifact_step_conclusion": "success",
    }
    records = {
        "repos/dotnetpower/fdai/actions/runs/123": {
            "id": 123,
            "run_attempt": 2,
            "head_sha": "a" * 40,
            "conclusion": "failure",
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

    _adoption_run_record(_Client(records), adoption, "isolated-executor")

    records["repos/dotnetpower/fdai/actions/runs/123/jobs?per_page=100"]["jobs"][0]["steps"][0][
        "conclusion"
    ] = "failure"
    with pytest.raises(GitHubEvidenceError, match="step binding is invalid"):
        _adoption_run_record(_Client(records), adoption, "isolated-executor")


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


def test_remote_evidence_workflow_is_read_only_and_pinned() -> None:
    assert "actions: read" in _WORKFLOW
    assert "contents: read" in _WORKFLOW
    assert "attestations: write" in _WORKFLOW
    assert "id-token: write" in _WORKFLOW
    assert "packages: read" in _WORKFLOW
    assert "verify_remote_github_evidence.py" in _WORKFLOW
    assert "check-remote-service-evidence.py" in _WORKFLOW
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in _WORKFLOW
    assert "actions/attest@f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6" in _WORKFLOW
    assert "docker/login-action@abd2ef45e78c5afb21d64d4ca52ee8550d9572c7" in _WORKFLOW
