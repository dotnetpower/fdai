from __future__ import annotations

from pathlib import Path

import pytest

from fdai_deployment_cli import source_application_inputs as inputs


def _snapshot(root: Path) -> Path:
    tree = root / "source-snapshot/tree"
    (tree / "infra/runtimes/aks/cluster").mkdir(parents=True)
    (tree / "infra/main.tf").write_text("# root\n")
    (tree / "infra/runtimes/aks/cluster/main.tf").write_text("# cluster\n")
    return tree


def test_terraform_writes_go_to_a_private_copy_not_the_snapshot(tmp_path: Path) -> None:
    tree = _snapshot(tmp_path)
    work = tmp_path / "application"
    work.mkdir(mode=0o700)

    copy = inputs.source_tree_copy(tree, work)
    (copy / "infra/backend.tf").write_text("generated\n")

    assert (copy / "infra/runtimes/aks/cluster/main.tf").read_text() == "# cluster\n"
    assert not (tree / "infra/backend.tf").exists()
    assert copy.stat().st_mode & 0o777 == 0o700
    assert inputs.source_tree_copy(tree, work) == copy
    assert (copy / "infra/backend.tf").exists()


def test_a_retained_source_context_is_rebound_out_of_the_snapshot(tmp_path: Path) -> None:
    tree = _snapshot(tmp_path)
    work = tmp_path / "application"
    work.mkdir(mode=0o700)
    snapshot_infra = tree / "infra"
    context: dict[str, object] = {
        "artifact_source": "operator-selected-source",
        "source_snapshot": str(tree.parent),
        "infra": str(snapshot_infra),
        "runtime_infra": str(snapshot_infra / "runtimes/aks/cluster"),
        "terraform_data": str(work / "terraform-data"),
    }

    assert inputs.rebind_source_tree(context, work) is True
    assert context["infra"] == str(work / "source-tree/infra")
    assert context["runtime_infra"] == str(work / "source-tree/infra/runtimes/aks/cluster")
    assert context["terraform_data"] == str(work / "terraform-data")
    assert inputs.rebind_source_tree(context, work) is False


def test_kit_contexts_are_never_rebound(tmp_path: Path) -> None:
    context: dict[str, object] = {"artifact_source": "signed-kit", "infra": "/kit/infra"}
    assert inputs.rebind_source_tree(context, tmp_path) is False
    assert context["infra"] == "/kit/infra"


def test_a_rerun_rebuilds_the_source_console_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fdai_deployment_cli import console_artifact

    def build(*, source_root: Path, revision: str, output_dir: Path, timeout_seconds: int):
        if output_dir.exists():
            raise ValueError("Console artifact output MUST be a new absolute directory")
        output_dir.mkdir()
        (output_dir / "console.tar.gz").write_bytes(revision.encode())
        return {"artifact_directory": str(output_dir), "archive_sha256": "a" * 64}

    monkeypatch.setattr(console_artifact, "build_console_update_artifact", build)
    for _attempt in range(2):
        archive, digest = inputs.build_source_console(
            source_root=tmp_path, source_commit="c" * 40, prepared_root=tmp_path, timeout_seconds=60
        )
    assert archive == tmp_path / "source-console-artifact/console.tar.gz"
    assert digest == "a" * 64
