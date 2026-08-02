from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/automation/configure-vscode-profile.py"
    spec = importlib.util.spec_from_file_location("configure_vscode_profile", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_profile_artifacts_are_consistent() -> None:
    module = _load_module()

    extension_count, setting_count = module.validate_artifacts()

    assert extension_count == 18
    assert setting_count == 6


def test_profile_extensions_reject_export_metadata() -> None:
    module = _load_module()
    profile = {
        "extensions": json.dumps(
            [
                {
                    "identifier": {"id": "example.extension", "uuid": "local-only"},
                    "version": "1.0.0",
                }
            ]
        )
    }

    with pytest.raises(module.ProfileContractError, match="only identifier"):
        module._profile_extensions(profile)


def test_machine_settings_reject_terraform_ls_reserved_ignore_names() -> None:
    module = _load_module()

    with pytest.raises(module.ProfileContractError, match="reserved ignore directory"):
        module._validate_machine_settings(
            {"terraform.languageServer.indexing.ignoreDirectoryNames": [".terraform"]}
        )


def test_apply_machine_settings_preserves_existing_values_and_is_idempotent(
    tmp_path: Path,
) -> None:
    module = _load_module()
    template = tmp_path / "template.json"
    destination = tmp_path / "Machine" / "settings.json"
    template.write_text(json.dumps({"terraform.ignore": ["node_modules"]}), encoding="utf-8")
    destination.parent.mkdir()
    destination.write_text(json.dumps({"chat.enabled": True}), encoding="utf-8")

    assert module.apply_machine_settings(destination, template) is True
    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "chat.enabled": True,
        "terraform.ignore": ["node_modules"],
    }
    assert module.apply_machine_settings(destination, template) is False
    assert module.machine_settings_match(destination, template) is True


def test_apply_machine_settings_fails_closed_on_jsonc(tmp_path: Path) -> None:
    module = _load_module()
    template = tmp_path / "template.json"
    destination = tmp_path / "settings.json"
    template.write_text(json.dumps({"terraform.ignore": []}), encoding="utf-8")
    original = '{\n  // keep this comment\n  "chat.enabled": true\n}\n'
    destination.write_text(original, encoding="utf-8")

    with pytest.raises(module.ProfileContractError, match="cannot read JSON"):
        module.apply_machine_settings(destination, template)

    assert destination.read_text(encoding="utf-8") == original
