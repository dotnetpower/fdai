"""The workstation coordinator removes only its own per-run kit execution copies."""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai_deployment_cli import cli
from fdai_deployment_cli.deployment_kit_cache import execution_bundle_destination
from fdai_deployment_cli.execution_copies import execution_copy_scope, new_execution_copy


def test_scope_removes_the_copies_created_inside_it(tmp_path: Path) -> None:
    with execution_copy_scope():
        source = new_execution_copy(tmp_path, "offline-source-")
        (source / "kit").mkdir()
        (source / "kit" / "payload").write_bytes(b"verified copy")
        bundle = new_execution_copy(tmp_path, "bundle-recheck-")
    assert not source.exists()
    assert not bundle.exists()


def test_scope_removes_copies_when_the_run_fails(tmp_path: Path) -> None:
    created: list[Path] = []
    with pytest.raises(ValueError, match="synthetic"), execution_copy_scope():
        created.append(new_execution_copy(tmp_path, "bundle-recheck-"))
        raise ValueError("synthetic failure")
    assert not created[0].exists()


def test_copies_outside_a_scope_are_kept_for_later_host_steps(tmp_path: Path) -> None:
    copy = new_execution_copy(tmp_path, "bundle-recheck-")
    with execution_copy_scope():
        pass
    assert copy.is_dir()


def test_retained_originals_are_never_execution_copies(tmp_path: Path) -> None:
    original = tmp_path / "bundle"
    with execution_copy_scope():
        assert execution_bundle_destination(tmp_path) == original
        original.mkdir()
        recheck = execution_bundle_destination(tmp_path)
        assert recheck.parent.name.startswith("bundle-recheck-")
    assert original.is_dir()
    assert not recheck.parent.exists()


def test_unknown_copy_prefix_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="prefix"):
        new_execution_copy(tmp_path, "run-")


@pytest.mark.parametrize("ready", [True, False])
def test_provision_removes_its_execution_copies_after_success_or_failure(
    ready: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[Path] = []

    def deploy(**_kwargs: object) -> dict[str, object]:
        created.append(new_execution_copy(tmp_path, "offline-source-"))
        if not ready:
            raise ValueError("synthetic deployment failure")
        return {"deployment_ready": True}

    monkeypatch.setattr(cli, "deploy_azure_foundation", deploy)
    result = cli.main(["provision", "azure", "--online", "--output", "json"])
    assert result == (0 if ready else 3)
    assert created and not created[0].exists()
