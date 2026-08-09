from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

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


def test_unrouted_change_needs_no_doc_churn() -> None:
    module = _load_module()

    failures = module.missing_doc_updates({"tests/unit/test_example.py"}, _manifest())

    assert failures == []


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
