from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deployment/service/hydrate_rca_reader_identity.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hydrate_rca_reader_identity", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _payload() -> dict[str, object]:
    return {
        "environments": {
            "dev": {
                "core-control-plane": {"name": "core"},
            }
        }
    }


def test_hydrates_exact_platform_reader_identity() -> None:
    module = _module()
    hydrated = module.hydrate_rca_reader_identity(
        _payload(),
        service="core-control-plane",
        environment="dev",
        identity={
            "resource_id": (
                "/subscriptions/example/resourceGroups/example/providers/"
                "Microsoft.ManagedIdentity/userAssignedIdentities/id-fdai-dev-rca-reader"
            ),
            "client_id": "00000000-0000-0000-0000-000000000001",
            "principal_id": "00000000-0000-0000-0000-000000000002",
        },
    )

    assert hydrated["environments"]["dev"]["core-control-plane"]["rca_reader_identity"] == {
        "resource_id": (
            "/subscriptions/example/resourceGroups/example/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/id-fdai-dev-rca-reader"
        ),
        "client_id": "00000000-0000-0000-0000-000000000001",
    }


def test_rejects_non_dedicated_identity() -> None:
    module = _module()
    with pytest.raises(module.RcaReaderIdentityError, match="dedicated RCA reader"):
        module.hydrate_rca_reader_identity(
            _payload(),
            service="core-control-plane",
            environment="dev",
            identity={
                "resource_id": "identity/inventory",
                "client_id": "client",
                "principal_id": "principal",
            },
        )
