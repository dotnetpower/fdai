from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "scripts/deployment/release/issue-license.py"
SPEC = importlib.util.spec_from_file_location("issue_license", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
write_private_text = MODULE._write_private_text


def test_license_output_is_created_private(tmp_path: Path) -> None:
    output = tmp_path / "license.token"

    write_private_text(output, "token\n")

    assert output.read_text(encoding="ascii") == "token\n"
    assert output.stat().st_mode & 0o777 == 0o600


def test_license_output_never_replaces_existing_file(tmp_path: Path) -> None:
    output = tmp_path / "license.token"
    output.write_text("existing\n", encoding="ascii")
    output.chmod(0o644)

    with pytest.raises(FileExistsError):
        write_private_text(output, "token\n")

    assert output.read_text(encoding="ascii") == "existing\n"
    assert output.stat().st_mode & 0o777 == 0o644
