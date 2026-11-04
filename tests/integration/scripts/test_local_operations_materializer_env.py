"""The Operator-only alert principal map never reaches the Core runtime environment."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_PATH = _ROOT / "scripts/deployment/local/local_operations_materializer.py"
_KEY = "FDAI_ALERT_NOISE_PRINCIPAL_SCOPES_JSON"


def _module():
    sys.path[:0] = [
        str(_ROOT / "services/core-control-plane/src"),
        str(_ROOT / "packages/service-contracts/src"),
    ]
    spec = importlib.util.spec_from_file_location("local_operations_materializer_env", _PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_principal_map_is_set_for_operator_and_removed_from_core(tmp_path: Path) -> None:
    module = _module()
    runtime, operator = tmp_path / "runtime.env", tmp_path / "operator.env"
    runtime.write_text(f"KEEP=1\n{_KEY}='{{}}'\n", encoding="utf-8")
    operator.write_text("KEEP=2\n", encoding="utf-8")

    module._update_env_file_alert_scopes(runtime, None)
    module._update_env_file_alert_scopes(operator, '{"p":["scope"]}')

    assert runtime.read_text(encoding="utf-8") == "KEEP=1\n"
    assert operator.read_text(encoding="utf-8").splitlines() == [
        "KEEP=2",
        f'{_KEY}=\'{{"p":["scope"]}}\'',
    ]


def test_missing_env_file_is_left_missing(tmp_path: Path) -> None:
    module = _module()

    module._update_env_file_alert_scopes(tmp_path / "absent.env", None)

    assert not (tmp_path / "absent.env").exists()
