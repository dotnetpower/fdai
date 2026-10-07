"""#1949: the Hub starts and computes Plans with no Azure credential or SDK client."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from types import ModuleType

import pytest
from starlette.testclient import TestClient

from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.domain import Installation, Issued, Planner
from fdai_lifecycle_hub.store import HubStore

_AZURE_PACKAGES = frozenset({"azure", "msal"})
_CREDENTIAL_PREFIXES = ("AZURE_", "ARM_", "MSI_", "IDENTITY_")


class _DenyAzureImports(MetaPathFinder):
    def find_spec(
        self, fullname: str, path: Sequence[str] | None, target: ModuleType | None = None
    ) -> ModuleSpec | None:
        if fullname.partition(".")[0] in _AZURE_PACKAGES:
            raise ImportError(f"the Hub must not import {fullname}")
        return None


def test_hub_modules_import_no_azure_package() -> None:
    script = (
        "import sys\n"
        "import fdai_lifecycle_hub.api, fdai_lifecycle_hub.cli\n"
        "loaded = sorted(m for m in sys.modules if m.partition('.')[0] in {'azure', 'msal'})\n"
        "assert not loaded, loaded\n"
    )
    subprocess.run(  # noqa: S603 - fixed interpreter and inline script
        [sys.executable, "-c", script],
        check=True,
        env={"PYTHONPATH": os.pathsep.join(sys.path)},
    )


def test_hub_serves_a_plan_without_credentials_or_azure_sdk(
    store: HubStore,
    installation: Installation,
    planner: Planner,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in [n for n in os.environ if n.startswith(_CREDENTIAL_PREFIXES)]:
        monkeypatch.delenv(name)
    for module in [m for m in sys.modules if m.partition(".")[0] in _AZURE_PACKAGES]:
        monkeypatch.delitem(sys.modules, module)
    monkeypatch.setattr(sys, "meta_path", [_DenyAzureImports(), *sys.meta_path])

    store.register(installation, now=now)
    outcome = store.recompute(installation.installation_id, planner, now=now)
    response = TestClient(create_app(store, clock=lambda: now)).get(
        "/v1/installations/installation-alpha/plan"
    )

    assert isinstance(outcome, Issued)
    assert response.status_code == 200
