from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "services" / "Dockerfile"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "container-supply-chain.yml"
PYTHON_DIGEST = "9d7f287598e1a5a978c015ee176d8216435aaf335ed69ac3c38dd1bbb10e8d64"
ACTION_PINS = {
    "actions/checkout": "11bd71901bbe5b1630ceea73d27597364c9af683",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
    "actions/attest": "f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6",
    "docker/setup-buildx-action": "bb05f3f5519dd87d3ba754cc423b652a5edd6d2c",
    "docker/build-push-action": "53b7df96c91f9c12dcc8a07bcb9ccacbed38856a",
    "docker/login-action": "abd2ef45e78c5afb21d64d4ca52ee8550d9572c7",
}
TRIVY_ARCHIVE_SHA256 = "bbb64b9695866ce4a7a8f5c9592002c5961cab378577fa3f8a040df362b9b2ea"
IMAGE_AFFECTING_PATHS = {
    ".dockerignore",
    ".trivyignore.yaml",
    ".github/workflows/container-supply-chain.yml",
    "LICENSE",
    "README.md",
    "alembic.ini",
    "alembic/**",
    "benchmarks/cybergym/pyproject.toml",
    "benchmarks/sregym/pyproject.toml",
    "config/**",
    "docs/internals/sregym-absorption-ledger.json",
    "evaluation-sdk/**",
    "extensions/code-assurance/pyproject.toml",
    "policies/**",
    "pyproject.toml",
    "rule-catalog/**",
    "service-contracts/**",
    "services/**",
    "src/**",
    "tests/scenarios/**",
    "uv.lock",
}

SERVICES = {
    "core-control-plane": (
        "fdai-core-control-plane",
        "fdai-core-control-plane",
        "fdai-core-control-plane",
    ),
    "operator-service": (
        "fdai-operator-service",
        "fdai-operator-service",
        "fdai-operator-service",
    ),
    "document-ingestion-api": (
        "fdai-document-ingestion-api",
        "fdai-document-ingestion-api",
        "fdai-document-ingestion-api",
    ),
    "document-processing-worker": (
        "fdai-document-processing-worker",
        "fdai-document-processing-worker",
        "fdai-document-processing-worker",
    ),
    "isolated-executor": (
        "fdai-isolated-executor-service",
        "fdai-isolated-executor-service",
        "fdai-isolated-executor",
    ),
}


def _stage(text: str, name: str) -> str:
    match = re.search(
        rf"^FROM [^\n]+ AS {re.escape(name)}\n(?P<body>.*?)(?=^FROM |\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing Docker stage {name}"
    return match.group("body")


def test_service_targets_install_owned_wheels_and_entrypoints() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    final_targets = set(
        re.findall(r"^FROM runtime-base AS ([a-z0-9-]+)$", dockerfile, re.MULTILINE)
    )
    assert final_targets == set(SERVICES)
    assert dockerfile.count(f"library/python@sha256:{PYTHON_DIGEST}") == 2

    for target, (distribution, entrypoint, _) in SERVICES.items():
        builder = _stage(dockerfile, f"{target}-builder")
        runtime = _stage(dockerfile, target)
        wheel_name = distribution.replace("-", "_")
        assert f"uv build --wheel --package {distribution}" in builder
        assert f"uv sync --frozen --package {distribution} --no-dev --no-editable" in builder
        assert f"/wheels/{wheel_name}-*.whl" in builder
        assert f"COPY --from={target}-builder" in runtime
        assert "USER 65532" in runtime
        assert f'ENTRYPOINT ["{entrypoint}"]' in runtime


def test_runtime_assets_follow_service_ownership() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    core = _stage(dockerfile, "core-control-plane")
    operator = _stage(dockerfile, "operator-service")
    ingestion_api = _stage(dockerfile, "document-ingestion-api")
    worker = _stage(dockerfile, "document-processing-worker")
    executor = _stage(dockerfile, "isolated-executor")

    assert "COPY --from=opa-builder /go/bin/opa" in core
    assert "rule-catalog/" in core and "policies/" in core and "config/" in core
    assert "resolved-models.json" in core
    for asset in ("config/", "rule-catalog/", "policies/", "resolved-models.json"):
        assert asset not in operator
    assert "config/agent-stewardship.yaml /app/config/agent-stewardship.yaml" in ingestion_api
    assert "COPY --chown=65532:65532 config/ /app/config/" not in ingestion_api
    for stage in (ingestion_api, worker):
        assert "rule-catalog/" not in stage
        assert "policies/" not in stage
        assert "resolved-models.json" not in stage
        assert "opa-builder" not in stage
    assert "config/" not in worker
    for asset in ("config/", "rule-catalog/", "policies/", "resolved-models.json", "opa-builder"):
        assert asset not in executor


def test_service_images_use_tracked_fail_closed_model_manifest() -> None:
    manifest_path = REPO_ROOT / "services" / "assets" / "resolved-models.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest == {
        "capabilities": [],
        "mixed_model_mode": "hil-only",
        "schema_version": "1.0.0",
    }
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert dockerfile.count("services/assets/resolved-models.json") == 1


def test_supply_chain_matrix_builds_and_attests_all_service_targets() -> None:
    workflow = cast(dict[str, Any], yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
    job = workflow["jobs"]["build-scan-attest"]
    matrix = job["strategy"]["matrix"]["include"]
    assert matrix == [
        {"service": service, "target": service, "image": image}
        for service, (_, _, image) in SERVICES.items()
    ]

    text = WORKFLOW.read_text(encoding="utf-8")
    assert "file: ./services/Dockerfile" in text
    assert "target: ${{ matrix.target }}" in text
    assert "${{ env.IMAGE_NAME }}/${{ matrix.image }}" in text
    assert "sbom-${{ matrix.service }}.cdx.json" in text
    assert '--format spdx-json --output "sbom-${{ matrix.service }}.spdx.json"' in text
    assert "subject-digest: ${{ steps.push.outputs.digest }}" in text
    assert "sbom-path: sbom-${{ matrix.service }}.spdx.json" in text
    assert text.count(f"uses: actions/attest@{ACTION_PINS['actions/attest']}") == 3


def test_supply_chain_uses_docker_push_digest_as_exact_evidence_subject() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "docker buildx imagetools inspect" not in text
    assert 'docker push "$image" 2>&1 | tee "$push_receipt"' in text
    assert "docker push must return exactly one immutable image digest" in text
    assert 'echo "reference=$repository@$digest" >> "$GITHUB_OUTPUT"' in text
    assert text.count('"${{ steps.subject.outputs.reference }}"') == 3


def test_core_provenance_contains_only_canonical_resolved_models_digest() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "id: models" in text
    assert 'canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()' in text
    assert '"resolved_models": {"canonical_json_sha256": digest}' in text
    assert "matrix.service == 'core-control-plane'" in text
    assert "predicate-path: resolved-models.provenance.json" in text
    assert "predicate: ${{ vars.RESOLVED_MODELS_JSON }}" not in text


def test_supply_chain_pins_node_compatible_actions_to_full_shas() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    uses = re.findall(r"^\s*uses:\s+([^\s#]+)", text, re.MULTILINE)

    assert uses
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", value) for value in uses)
    for action, sha in ACTION_PINS.items():
        assert f"{action}@{sha}" in uses


def test_supply_chain_verifies_pinned_trivy_archive_checksum() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert f'TRIVY_ARCHIVE_SHA256: "{TRIVY_ARCHIVE_SHA256}"' in text
    assert 'echo "${TRIVY_ARCHIVE_SHA256}  ${archive}" | sha256sum --check --strict' in text
    assert 'tar -xzf "${archive}" -C /usr/local/bin trivy' in text
    assert "--severity HIGH,CRITICAL" in text
    assert "--ignore-unfixed" not in text


def test_supply_chain_triggers_for_every_image_and_scan_input() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    for path in IMAGE_AFFECTING_PATHS:
        assert text.count(f'- "{path}"') == 2, path
