"""Deployment profiles bind development authority only as an explicit pair."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INFRA_ROOT = ROOT / "infra"


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _has_assignment(source: str, name: str) -> bool:
    return re.search(rf"(?m)^\s*{name}\s*=\s*var[.]{name}\s*$", source) is not None


def test_source_container_apps_binds_profile_and_executor_together() -> None:
    variables = _text("infra/variables.tf")
    root = _text("infra/main.tf")
    module_variables = _text("infra/modules/compute/container-apps/variables.tf")
    module = _text("infra/modules/compute/container-apps/main.tf")

    for source in (variables, module_variables):
        assert 'variable "development_authority_profile_json"' in source
        assert 'variable "development_authority_executor_principal"' in source
        assert "profile and executor must be empty or selected together" in source
    assert _has_assignment(root, "development_authority_profile_json")
    assert _has_assignment(root, "development_authority_executor_principal")
    assert "FDAI_FULL_AUTHORITY_DEVELOPMENT_PROFILE_JSON" in module
    assert "FDAI_FULL_AUTHORITY_DEVELOPMENT_EXECUTOR_PRINCIPAL" in module


def test_protected_core_service_binds_the_same_pair() -> None:
    root = _text("infra/services/core-control-plane/main.tf")
    variables = _text("infra/services/core-control-plane/variables.tf")
    module_variables = _text(
        "infra/services/core-control-plane/modules/core-control-plane/variables.tf"
    )
    module = _text("infra/services/core-control-plane/modules/core-control-plane/main.tf")

    for source in (variables, module_variables):
        assert 'variable "development_authority_profile_json"' in source
        assert 'variable "development_authority_executor_principal"' in source
    assert _has_assignment(root, "development_authority_profile_json")
    assert _has_assignment(root, "development_authority_executor_principal")
    assert "FDAI_FULL_AUTHORITY_DEVELOPMENT_PROFILE_JSON" in module
    assert "FDAI_FULL_AUTHORITY_DEVELOPMENT_EXECUTOR_PRINCIPAL" in module
