from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).parents[3]
_SCRIPT = _REPO_ROOT / "scripts/deployment/azure/build_design_mocks_artifact.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_design_mocks_artifact", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_artifact_contains_only_browser_assets_and_hosting_contract(tmp_path: Path) -> None:
    module = _load_script()
    output = tmp_path / "artifact"

    copied = module.build_artifact(_REPO_ROOT, output)

    relative_files = {path.relative_to(output).as_posix() for path in copied}
    assert "index.html" in relative_files
    assert "mocks/ui/dashboard.html" in relative_files
    assert "mocks/ui-cells/data/discovery-stream.jsonl" in relative_files
    assert "console/public/agent-icons/pantheon.svg" in relative_files
    assert "staticwebapp.config.json" in relative_files
    assert "403.html" in relative_files
    assert not any(path.endswith((".md", ".py", ".pyc")) for path in relative_files)

    config = json.loads((output / "staticwebapp.config.json").read_text())
    routes = config["routes"]
    protected_route = next(route for route in routes if route["route"] == "/*")
    assert protected_route["allowedRoles"] == ["reviewer"]
    access_denied_index = next(
        index for index, route in enumerate(routes) if route["route"] == "/403.html"
    )
    protected_index = routes.index(protected_route)
    assert routes[access_denied_index]["allowedRoles"] == ["anonymous"]
    assert access_denied_index < protected_index


def test_artifact_builder_refuses_to_replace_existing_output(tmp_path: Path) -> None:
    module = _load_script()
    output = tmp_path / "artifact"
    output.mkdir()

    with pytest.raises(FileExistsError, match="output already exists"):
        module.build_artifact(_REPO_ROOT, output)
