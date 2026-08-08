from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

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
                "paths": ["src/fdai/delivery/operator_api/dev/**"],
                "docs_update": ["docs/parity.md", "docs/rbac.md"],
            }
        ]
    }


def test_behavior_change_requires_route_owned_doc() -> None:
    module = _load_module()

    failures = module.missing_doc_updates(
        {"src/fdai/delivery/operator_api/dev/factory.py"}, _manifest()
    )

    assert failures == [
        (
            "local",
            ("src/fdai/delivery/operator_api/dev/factory.py",),
            ("docs/parity.md", "docs/rbac.md"),
        )
    ]


def test_one_owning_doc_satisfies_route() -> None:
    module = _load_module()

    failures = module.missing_doc_updates(
        {
            "src/fdai/delivery/operator_api/dev/factory.py",
            "docs/parity.md",
        },
        _manifest(),
    )

    assert failures == []


def test_unrouted_change_needs_no_doc_churn() -> None:
    module = _load_module()

    failures = module.missing_doc_updates({"tests/unit/test_example.py"}, _manifest())

    assert failures == []
