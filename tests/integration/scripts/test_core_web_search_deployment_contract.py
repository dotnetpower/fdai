"""Independent Core deployment contract for controlled public-web execution."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[3]
_SERVICE_SCRIPTS = _ROOT / "scripts" / "deployment" / "service"
_CORE_MODULE = (
    _ROOT
    / "infra"
    / "services"
    / "core-control-plane"
    / "modules"
    / "core-control-plane"
    / "main.tf"
).read_text(encoding="utf-8")


def _service_contract() -> ModuleType:
    path = _SERVICE_SCRIPTS / "service_contract.py"
    spec = importlib.util.spec_from_file_location("core_web_service_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_core_deployment_binds_attested_models_and_web_search_egress() -> None:
    contract = _service_contract().resolve_service("core-control-plane", "dev")
    expected = {
        "LLM_MODE",
        "LLM_RESOLVED_MODELS_PATH",
        "FDAI_LLM_ENDPOINT",
        "FDAI_WEB_SEARCH_ENABLED",
        "FDAI_WEB_SEARCH_ALLOWED_DOMAINS",
        "FDAI_WEB_SEARCH_MAX_RESULTS",
        "FDAI_WEB_SEARCH_TIMEOUT_SECONDS",
    }

    assert expected <= set(contract.required_environment)
    for name in expected:
        assert f'{{ name = "{name}"' in _CORE_MODULE
    assert 'value = "/app/resolved-models.json"' in _CORE_MODULE
    assert 'value = join(",", var.llm.web_search_allowed_domains)' in _CORE_MODULE
