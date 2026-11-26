from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.no_cover

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = REPO_ROOT / "scripts/quality/architecture/check-contract-pins.sh"


def test_gate_script_is_valid_bash_and_runs_both_contract_suites() -> None:
    body = GATE.read_text(encoding="utf-8")
    bash = shutil.which("bash")
    assert bash is not None
    checked = subprocess.run(  # noqa: S603 - resolved interpreter and repository path
        [bash, "-n", str(GATE)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert checked.returncode == 0, checked.stderr
    assert "tests/integration/test_composition_package_split.py" in body
    assert "tests/integration/services/test_service_migration_inventory.py" in body


def test_gate_is_wired_into_pre_commit_for_every_drifting_path() -> None:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hook = next(
        hook
        for repo in config["repos"]
        for hook in repo["hooks"]
        if hook["id"] == "check-contract-pins"
    )

    assert hook["entry"] == "bash scripts/quality/architecture/check-contract-pins.sh"
    assert hook["pass_filenames"] is False
    for path in (
        "alembic/versions/",
        "service-migrations/",
        "services/core-control-plane/src/fdai/composition/",
    ):
        assert path in hook["files"]
