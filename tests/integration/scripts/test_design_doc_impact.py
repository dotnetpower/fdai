from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/architecture/check-design-doc-impact.py"
    spec = importlib.util.spec_from_file_location("check_design_doc_impact", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest() -> dict[str, object]:
    return {
        "routes": [
            {
                "id": "local",
                "paths": ["services/core-control-plane/src/fdai/delivery/operator_api/dev/**"],
                "docs_update": ["docs/parity.md", "docs/rbac.md"],
            }
        ]
    }


def test_behavior_change_requires_route_owned_doc() -> None:
    module = _load_module()

    failures = module.missing_doc_updates(
        {"services/core-control-plane/src/fdai/delivery/operator_api/dev/factory.py"}, _manifest()
    )

    assert failures == [
        (
            "local",
            ("services/core-control-plane/src/fdai/delivery/operator_api/dev/factory.py",),
            ("docs/parity.md", "docs/rbac.md"),
        )
    ]


def test_final_operator_path_requires_logical_route_doc() -> None:
    module = _load_module()

    failures = module.missing_doc_updates(
        {"services/operator-service/src/fdai_operator_service/dev/factory.py"},
        _manifest(),
    )

    assert failures == [
        (
            "local",
            ("services/operator-service/src/fdai_operator_service/dev/factory.py",),
            ("docs/parity.md", "docs/rbac.md"),
        )
    ]


def test_one_owning_doc_satisfies_route() -> None:
    module = _load_module()

    failures = module.missing_doc_updates(
        {
            "services/core-control-plane/src/fdai/delivery/operator_api/dev/factory.py",
            "docs/parity.md",
        },
        _manifest(),
    )

    assert failures == []


def test_shared_semantic_coverage_accepts_ontology_owner_doc() -> None:
    module = _load_module()
    manifest = json.loads(
        (REPO_ROOT / "scripts/lib/design-routes.json").read_text(encoding="utf-8")
    )

    failures = module.missing_doc_updates(
        {
            "eval/golden-dataset/semantic-intent-coverage.json",
            "docs/roadmap/interfaces/continuous-question-space.md",
        },
        manifest,
    )

    assert failures == []


def test_explicit_overlapping_route_doc_satisfies_only_owned_paths() -> None:
    module = _load_module()
    manifest = {
        "routes": [
            {
                "id": "broad",
                "paths": ["services/**"],
                "docs_update": ["docs/broad.md"],
                "docs_update_routes": ["narrow"],
            },
            {
                "id": "narrow",
                "paths": ["services/attachments/**"],
                "docs_update": ["docs/attachments.md"],
            },
        ]
    }

    assert (
        module.missing_doc_updates(
            {"services/attachments/intake.py", "docs/attachments.md"},
            manifest,
        )
        == []
    )
    assert module.missing_doc_updates(
        {"services/cost/runtime.py", "docs/attachments.md"},
        manifest,
    ) == [("broad", ("services/cost/runtime.py",), ("docs/broad.md",))]


def test_overlapping_route_doc_does_not_hide_mixed_unowned_paths() -> None:
    module = _load_module()
    manifest = {
        "routes": [
            {
                "id": "broad",
                "paths": ["services/**"],
                "docs_update": ["docs/broad.md"],
                "docs_update_routes": ["narrow"],
            },
            {
                "id": "narrow",
                "paths": ["services/attachments/**"],
                "docs_update": ["docs/attachments.md"],
            },
        ]
    }

    failures = module.missing_doc_updates(
        {
            "services/attachments/intake.py",
            "services/cost/runtime.py",
            "docs/attachments.md",
        },
        manifest,
    )

    assert failures == [("broad", ("services/cost/runtime.py",), ("docs/broad.md",))]


def test_localized_owning_doc_satisfies_route() -> None:
    module = _load_module()
    manifest = {
        "routes": [
            {
                "id": "localized",
                "paths": ["docs/**"],
                "docs_update": ["docs/parity.md"],
            }
        ]
    }

    failures = module.missing_doc_updates({"docs/parity-ko.md"}, manifest)

    assert failures == []


def test_unrouted_change_needs_no_doc_churn() -> None:
    module = _load_module()

    failures = module.missing_doc_updates({"tests/unit/test_example.py"}, _manifest())

    assert failures == []


def test_generated_question_bank_outputs_need_no_duplicate_design_update() -> None:
    module = _load_module()
    manifest = {
        "routes": [
            {
                "id": "questions",
                "paths": ["eval/golden-dataset/question-bank/**"],
                "docs_update": ["docs/questions.md"],
            }
        ]
    }

    failures = module.missing_doc_updates(
        {
            "eval/golden-dataset/question-bank/question-bank.json",
            "eval/golden-dataset/question-bank/review-catalog.md",
        },
        manifest,
    )

    assert failures == []


def test_generated_system_knowledge_catalog_needs_no_duplicate_design_update() -> None:
    module = _load_module()
    manifest = {
        "routes": [
            {
                "id": "system-knowledge",
                "paths": [
                    "services/system-knowledge-service/src/"
                    "fdai_system_knowledge_service/data/catalog.json"
                ],
                "docs_update": ["docs/system-knowledge.md"],
            }
        ]
    }

    failures = module.missing_doc_updates(
        {"services/system-knowledge-service/src/fdai_system_knowledge_service/data/catalog.json"},
        manifest,
    )

    assert failures == []


def test_question_bank_source_change_still_requires_design_update() -> None:
    module = _load_module()
    manifest = {
        "routes": [
            {
                "id": "questions",
                "paths": ["eval/golden-dataset/question-bank/**"],
                "docs_update": ["docs/questions.md"],
            }
        ]
    }

    failures = module.missing_doc_updates(
        {"eval/golden-dataset/question-bank/question-bank.source.yaml"},
        manifest,
    )

    assert failures == [
        (
            "questions",
            ("eval/golden-dataset/question-bank/question-bank.source.yaml",),
            ("docs/questions.md",),
        )
    ]


def test_cached_change_scope_reads_only_staged_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    calls: list[list[str]] = []

    def record_call(arguments: list[str]) -> set[str]:
        calls.append(arguments)
        return {"staged.py"}

    monkeypatch.setattr(module, "_git_paths", record_call)

    assert module.changed_paths(cached=True) == {"staged.py"}
    assert calls == [["--cached", "HEAD"]]


def test_version_only_package_metadata_needs_no_design_doc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    before = {
        "name": "fdai-console",
        "version": "0.1.231",
        "packages": {"": {"name": "fdai-console", "version": "0.1.231"}},
    }
    after = {
        "name": "fdai-console",
        "version": "0.1.232",
        "packages": {"": {"name": "fdai-console", "version": "0.1.232"}},
    }
    monkeypatch.setattr(
        module,
        "_git_json",
        lambda revision, _path: before if revision == "base" else after,
    )

    assert module.is_version_only_package_metadata("console/package-lock.json", "base..head")


def test_package_dependency_change_still_requires_design_doc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    before = {"name": "fdai-console", "version": "0.1.231", "dependencies": {"a": "1"}}
    after = {"name": "fdai-console", "version": "0.1.232", "dependencies": {"a": "2"}}
    monkeypatch.setattr(
        module,
        "_git_json",
        lambda revision, _path: before if revision == "base" else after,
    )

    assert not module.is_version_only_package_metadata("console/package.json", "base..head")


def _service_suite_manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "coverage": {"test_patterns": ["services/*/tests/**/*.py"]},
        "services": [
            {
                "id": "operator-service",
                "source_roots": ["services/operator-service"],
                "test_groups": {
                    "unit": [],
                    "contract": [
                        "services/operator-service/tests/test_operator_workflow_family.py"
                    ],
                    "integration": [],
                    "smoke": [],
                },
            }
        ],
    }


def test_additive_service_test_registration_needs_no_unrelated_design_docs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    before = _service_suite_manifest()
    after = deepcopy(before)
    after["services"][0]["test_groups"]["contract"].append(
        "services/operator-service/tests/test_rule_findings_summary_admission.py"
    )
    monkeypatch.setattr(
        module,
        "_git_json",
        lambda revision, _path: before if revision == "HEAD" else after,
    )
    monkeypatch.setattr(
        module,
        "changed_paths",
        lambda diff_range=None, *, cached=False: {"tests/integration/service-suites.json"},
    )

    assert module.is_test_registration_only("tests/integration/service-suites.json", cached=True)
    assert module.is_test_registration_only(
        "tests/integration/service-suites.json", diff_range="HEAD..commit"
    )
    assert module.main(["check-design-doc-impact.py", "--cached"]) == 0


@pytest.mark.parametrize(
    "change",
    ["removed", "moved", "foreign", "duplicate", "coverage", "source-root", "no-addition"],
)
def test_service_suite_design_exemption_refuses_non_additive_changes(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    module = _load_module()
    before = _service_suite_manifest()
    after = deepcopy(before)
    groups = after["services"][0]["test_groups"]
    if change != "no-addition":
        groups["contract"].append(
            "services/operator-service/tests/test_rule_findings_summary_admission.py"
        )
    if change == "removed":
        groups["contract"].clear()
    elif change == "moved":
        groups["unit"] = groups["contract"]
        groups["contract"] = []
    elif change == "foreign":
        groups["contract"].append("services/core-control-plane/tests/test_new.py")
    elif change == "duplicate":
        groups["contract"].append(groups["contract"][-1])
    elif change == "coverage":
        after["coverage"]["test_patterns"].append("tests/**")
    elif change == "source-root":
        after["services"][0]["source_roots"] = ["services/other-service"]
    monkeypatch.setattr(
        module,
        "_git_json",
        lambda revision, _path: before if revision == "base" else after,
    )

    assert not module.is_test_registration_only(
        "tests/integration/service-suites.json", diff_range="base..head"
    )
