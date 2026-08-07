from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "services" / "Dockerfile"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "container-supply-chain.yml"
PYTHON_DIGEST = "9d7f287598e1a5a978c015ee176d8216435aaf335ed69ac3c38dd1bbb10e8d64"

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
    assert "rule-catalog/" in operator and "policies/" in operator and "config/" in operator
    assert "resolved-models.json" in core and "resolved-models.json" in operator
    for stage in (ingestion_api, worker):
        assert "config/" in stage
        assert "rule-catalog/" not in stage
        assert "policies/" not in stage
        assert "resolved-models.json" not in stage
        assert "opa-builder" not in stage
    for asset in ("config/", "rule-catalog/", "policies/", "resolved-models.json", "opa-builder"):
        assert asset not in executor


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
    assert "subject-digest: ${{ steps.push.outputs.digest }}" in text
    assert text.count("uses: actions/attest@v4.2.0") == 2
