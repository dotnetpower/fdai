from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from scripts.deployment.service.select_changed_images import (
    IMAGE_TARGETS,
    matrix_json,
    select_image_targets,
    select_requested_images,
)


def _services(paths: list[str]) -> list[str]:
    return [target.service for target in select_image_targets(paths)]


def _targets(paths: list[str]) -> list[str]:
    return [target.target for target in select_image_targets(paths)]


def test_service_source_change_selects_only_its_owned_image() -> None:
    assert _services(["services/operator-service/src/fdai_operator_service/main.py"]) == [
        "operator-service"
    ]


def test_shared_inputs_and_service_metadata_select_all_images() -> None:
    expected = [target.service for target in IMAGE_TARGETS]

    assert _services(["packages/service-contracts/src/contracts.py"]) == expected
    assert _services(["services/operator-service/pyproject.toml"]) == expected
    assert _services(["uv.lock"]) == expected


def test_runtime_assets_select_only_their_consumers() -> None:
    assert _targets(["policies/risk.rego"]) == [
        "core-control-plane",
        "cost-governance",
    ]
    assert _targets(["config/agent-stewardship.yaml"]) == [
        "core-control-plane",
        "cost-governance",
        "document-ingestion-api",
    ]
    assert _targets(["packages/github-app-auth/src/fdai_github_app_auth/provider.py"]) == [
        "core-control-plane",
        "cost-governance",
        "document-ingestion-api",
    ]


def test_cost_governance_sources_select_the_distribution_profile_only() -> None:
    assert _targets(["extensions/cost-governance/src/fdai_cost_governance/__init__.py"]) == [
        "cost-governance"
    ]
    assert _targets(["extensions/cost-governance/docker/Dockerfile"]) == ["cost-governance"]
    assert _targets(["extensions/cost-governance/pyproject.toml"]) == [
        target.target for target in IMAGE_TARGETS
    ]


def test_unknown_service_path_fails_closed_to_all_images() -> None:
    assert _services(["services/new-service/source.py"]) == [
        target.service for target in IMAGE_TARGETS
    ]


def test_unrelated_paths_do_not_select_images() -> None:
    assert select_image_targets(["docs/user-guide/get-started.md"]) == ()


def test_pr_trigger_excludes_known_runtime_source_but_keeps_build_assets() -> None:
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/container-supply-chain.yml").read_text())
    paths = workflow[True]["pull_request"]["paths"]
    assert "README.md" not in paths
    assert select_image_targets(["README.md"], packaging_only=True) == ()
    for service in {target.service for target in IMAGE_TARGETS}:
        assert f"!services/{service}/src/**/*.py" in paths
        assert f"!services/{service}/src/**/*.pyi" in paths
        assert f"!services/{service}/tests/**" in paths
        assert f"!services/{service}/docs/**" in paths
        assert select_image_targets([f"services/{service}/docker/Dockerfile"], packaging_only=True)
    assert "services/**" in paths
    assert paths.index("services/core-control-plane/tests/scenarios/**") > paths.index(
        "!services/core-control-plane/tests/**"
    )
    assert not any(path.startswith("!services/*/") for path in paths)


def test_matrix_json_contains_complete_target_records() -> None:
    payload = json.loads(matrix_json(select_image_targets(["services/isolated-executor/main.py"])))

    assert payload == {
        "include": [
            {
                "target": "isolated-executor",
                "service": "isolated-executor",
                "dockerfile": "services/isolated-executor/docker/Dockerfile",
                "image": "fdai-isolated-executor",
            }
        ]
    }


@pytest.mark.parametrize(
    "path",
    (
        "services/operator-service/src/fdai_operator_service/main.py",
        "services/core-control-plane/src/fdai/runtime/bootstrap.py",
        "services/isolated-executor/tests/test_main.py",
        "services/operator-service/docs/README.md",
        "packages/service-contracts/src/contracts.py",
        "packages/github-app-auth/src/auth.py",
        "extensions/cost-governance/src/fdai_cost_governance/__init__.py",
        "evaluation-sdk/src/evaluation/types.pyi",
        "docs/user-guide/get-started.md",
    ),
)
def test_pr_packaging_skips_ordinary_source_tests_and_docs(path: str) -> None:
    assert select_image_targets([path], packaging_only=True) == ()


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        ("services/operator-service/docker/Dockerfile", ["operator-service"]),
        ("services/operator-service/docker/entrypoint.sh", ["operator-service"]),
        (
            "services/operator-service/src/fdai_operator_service/schema.json",
            ["operator-service"],
        ),
        ("extensions/cost-governance/docker/Dockerfile", ["cost-governance"]),
        ("policies/risk.rego", ["core-control-plane", "cost-governance"]),
        (
            "services/core-control-plane/tests/scenarios/scenario.yaml",
            ["core-control-plane", "cost-governance"],
        ),
        (
            "scripts/deployment/local/materialize-authoritative-catalogs.py",
            ["core-control-plane", "cost-governance"],
        ),
    ),
)
def test_pr_packaging_keeps_build_inputs_and_runtime_assets(path: str, expected: list[str]) -> None:
    assert [
        target.target for target in select_image_targets([path], packaging_only=True)
    ] == expected


@pytest.mark.parametrize(
    "path",
    (
        "uv.lock",
        ".dockerignore",
        ".trivyignore.yaml",
        "pyproject.toml",
        "services/operator-service/pyproject.toml",
        "packages/github-app-auth/pyproject.toml",
        "evaluation-sdk/pyproject.toml",
        "config/service-image-build-override.json",
        "scripts/deployment/service/apply_image_build_override.py",
        "scripts/deployment/service/select_changed_images.py",
        ".github/workflows/container-supply-chain.yml",
        "services/new-service/src/new_service/main.py",
    ),
)
def test_pr_packaging_fails_closed_for_shared_or_unknown_build_inputs(path: str) -> None:
    assert select_image_targets([path], packaging_only=True) == IMAGE_TARGETS


def test_pr_packaging_mixed_change_keeps_only_affected_packaging_targets() -> None:
    targets = select_image_targets(
        [
            "services/core-control-plane/src/fdai/runtime/bootstrap.py",
            "./services/operator-service/docker/Dockerfile",
        ],
        packaging_only=True,
    )
    assert [target.target for target in targets] == ["operator-service"]


def test_explicit_candidate_selection_is_ordered_and_does_not_expand_service_profiles() -> None:
    assert [
        target.target
        for target in select_requested_images(" fdai-operator-service , core-control-plane ")
    ] == ["core-control-plane", "operator-service"]
    assert [target.target for target in select_requested_images("cost-governance")] == [
        "cost-governance"
    ]
    assert select_requested_images("all") == IMAGE_TARGETS


@pytest.mark.parametrize(
    "selection",
    (
        "",
        " ",
        ",",
        "all,operator-service",
        "operator-service,",
        "unknown-service",
        "operator-service,operator-service",
        "operator-service,fdai-operator-service",
        "../operator-service",
        "fdai-operator-service:latest",
        "operator-service;echo unsafe",
    ),
)
def test_candidate_selection_rejects_invalid_or_ambiguous_inputs(selection: str) -> None:
    with pytest.raises(ValueError):
        select_requested_images(selection)


def test_selector_cli_rejects_invalid_candidates_without_emitting_a_matrix() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "scripts/deployment/service/select_changed_images.py",
            "--images",
            "unknown-service",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "images must name known targets" in result.stderr


def test_selector_cli_emits_only_explicit_candidate_images() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "scripts/deployment/service/select_changed_images.py",
            "--images",
            "fdai-operator-service,core-control-plane",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    payload = json.loads(lines[0].removeprefix("matrix="))
    assert [item["target"] for item in payload["include"]] == [
        "core-control-plane",
        "operator-service",
    ]
    assert lines[1] == "has_images=true"


def test_selector_cli_accepts_nul_delimited_packaging_paths() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "scripts/deployment/service/select_changed_images.py",
            "--packaging-only",
            "--nul",
        ],
        input=(
            b"services/core-control-plane/src/fdai/runtime/bootstrap.py\0"
            b"services/operator-service/docker/Dockerfile\0"
        ),
        cwd=root,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    lines = result.stdout.decode().splitlines()
    payload = json.loads(lines[0].removeprefix("matrix="))
    assert [item["target"] for item in payload["include"]] == ["operator-service"]
    assert lines[1] == "has_images=true"
