from __future__ import annotations

import json

from scripts.deployment.service.select_changed_images import (
    IMAGE_TARGETS,
    matrix_json,
    select_image_targets,
)


def _services(paths: list[str]) -> list[str]:
    return [target.service for target in select_image_targets(paths)]


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
    assert _services(["policies/risk.rego"]) == ["core-control-plane"]
    assert _services(["config/agent-stewardship.yaml"]) == [
        "core-control-plane",
        "document-ingestion-api",
    ]


def test_unknown_service_path_fails_closed_to_all_images() -> None:
    assert _services(["services/new-service/source.py"]) == [
        target.service for target in IMAGE_TARGETS
    ]


def test_unrelated_paths_do_not_select_images() -> None:
    assert select_image_targets(["docs/user-guide/get-started.md"]) == ()


def test_matrix_json_contains_complete_target_records() -> None:
    payload = json.loads(matrix_json(select_image_targets(["services/isolated-executor/main.py"])))

    assert payload == {
        "include": [
            {
                "service": "isolated-executor",
                "dockerfile": "services/isolated-executor/docker/Dockerfile",
                "image": "fdai-isolated-executor",
            }
        ]
    }
