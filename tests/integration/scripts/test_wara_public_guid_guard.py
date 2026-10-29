"""Public recommendation references cannot turn the GUID guard into a path exclusion."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GUARD = ROOT / "scripts/quality/repository/check-guids.sh"
CATALOG = "rule-catalog/collected/wara-aprl/azure-wara.json"


@pytest.fixture
def repository(tmp_path):
    git = shutil.which("git")
    assert git is not None, "Git is required for the repository guard regression"
    subprocess.run(  # noqa: S603 - fixed Git command and pytest-owned temporary path
        [git, "init", "--quiet", str(tmp_path)],
        check=True,
    )
    target = tmp_path / CATALOG
    target.parent.mkdir(parents=True)
    target.write_bytes((ROOT / CATALOG).read_bytes())
    catalog = json.loads(target.read_text())
    public_id = catalog["areas"][0]["controls"][0]["id"]
    return tmp_path, public_id


def _check(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    bash = shutil.which("bash")
    assert bash is not None, "Bash is required for the repository guard regression"
    return subprocess.run(  # noqa: S603 - fixed local guard and test-controlled relative paths
        [bash, str(GUARD), path],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "path",
    [
        "rule-catalog/guidance/azure-wara/authoring-manifest.json",
        "rule-catalog/guidance/azure-wara/coverage.json",
        "packages/service-contracts/src/fdai_service_contracts/data/wara-guidance-00.json",
        "scripts/catalog/wara_guidance_pilots.py",
        "packages/service-contracts/tests/test_wara_guidance_corpus.py",
        "console/src/routes/wara-guidance.fixture.ts",
    ],
)
def test_only_pinned_public_ids_are_admitted_on_guidance_surfaces(repository, path) -> None:
    root, public_id = repository
    result = _check(root, path, public_id)
    assert result.returncode == 0, result.stderr


def test_known_public_guid_is_not_globally_allowlisted(repository) -> None:
    root, public_id = repository
    result = _check(root, "examples/customer.json", public_id)
    assert result.returncode == 1


def test_unknown_guid_remains_blocked_inside_generated_public_data(repository) -> None:
    root, public_id = repository
    unknown = "-".join(("12345678", "1234", "1234", "1234", "123456789abc"))
    result = _check(
        root,
        "packages/service-contracts/src/fdai_service_contracts/data/wara-guidance-00.json",
        public_id + "\n" + unknown,
    )
    assert result.returncode == 1
    assert unknown in result.stderr


def test_source_catalog_tampering_cannot_register_a_customer_guid(repository) -> None:
    root, public_id = repository
    target = root / CATALOG
    target.write_bytes(target.read_bytes() + b" ")
    result = _check(root, "rule-catalog/guidance/azure-wara/coverage.json", public_id)
    assert result.returncode == 1
    assert "source pin is invalid" in result.stderr


def test_neighboring_files_do_not_inherit_public_reference_permission(repository) -> None:
    root, public_id = repository
    result = _check(
        root, "packages/service-contracts/src/fdai_service_contracts/data/customer.json", public_id
    )
    assert result.returncode == 1
