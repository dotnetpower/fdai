"""Verify local artifact pruning preserves audit evidence and active generations."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts/deployment/local/prune-local-artifacts.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prune_local_artifacts", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_readonly_snapshot(snapshots_dir: Path, digest: str, mtime: float) -> Path:
    snap = snapshots_dir / digest
    cache = snap / "cache"
    cache.mkdir(parents=True)
    db_file = cache / "trivy.db"
    db_file.write_bytes(b"x" * 1024)
    db_file.chmod(0o400)
    cache.chmod(0o500)
    snap.chmod(0o500)
    os.utime(snap, (mtime, mtime))
    return snap


def test_security_cache_keeps_active_pointer_and_rollback_generation(tmp_path: Path) -> None:
    module = _load_module()
    cache_root = tmp_path / "code-security-cache"
    snapshots_dir = cache_root / "snapshots"
    d1 = "1" * 64
    d2 = "2" * 64
    d3 = "3" * 64
    s1 = _write_readonly_snapshot(snapshots_dir, d1, 1000.0)
    s2 = _write_readonly_snapshot(snapshots_dir, d2, 2000.0)
    s3 = _write_readonly_snapshot(snapshots_dir, d3, 3000.0)
    (cache_root / "current.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cache_digest": d1,
                "cache_subpath": f"snapshots/{d1}/cache",
                "prepared_at": "2026-10-24T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    staging = cache_root / "staging"
    old_stage = staging / "cache-old"
    fresh_stage = staging / "cache-fresh"
    old_stage.mkdir(parents=True)
    fresh_stage.mkdir(parents=True)
    os.utime(old_stage, (100.0, 100.0))
    os.utime(fresh_stage, (99_500.0, 99_500.0))

    preview = module.PruneSummary(apply=False)
    module.prune_security_cache_snapshots(
        cache_root,
        preview,
        keep_generations=2,
        staging_max_age_hours=1.0,
        now=100_000.0,
    )
    assert s2.exists()
    assert str(s2) in preview.removed_paths
    assert str(old_stage) in preview.removed_paths

    applied = module.PruneSummary(apply=True)
    module.prune_security_cache_snapshots(
        cache_root,
        applied,
        keep_generations=2,
        staging_max_age_hours=1.0,
        now=100_000.0,
    )
    assert s1.exists()
    assert s3.exists()
    assert not s2.exists()
    assert not old_stage.exists()
    assert fresh_stage.exists()


def test_standalone_kits_prune_intermediate_trees_and_old_kits(tmp_path: Path) -> None:
    module = _load_module()
    kits_root = tmp_path / "kits"
    for index, sha in enumerate(("aaaa1111", "bbbb2222", "cccc3333")):
        kit_dir = kits_root / sha
        (kit_dir / "stage").mkdir(parents=True)
        (kit_dir / "stage/payload.bin").write_bytes(b"s" * 512)
        (kit_dir / "release-input").mkdir(parents=True)
        (kit_dir / "release-input/service.oci.tar").write_bytes(b"r" * 256)
        (kit_dir / "source").mkdir(parents=True)
        (kit_dir / "source/README.md").write_text("checkout", encoding="utf-8")
        (kit_dir / ".fdai-standalone-release").write_text(
            "fdai-standalone-release-v1\n",
            encoding="utf-8",
        )
        (kit_dir / "fdai-deployment-kit-0.1.1-linux-x86_64.tar.gz").write_bytes(b"k" * 1024)
        mtime = 10_000.0 + index * 1000.0
        os.utime(kit_dir, (mtime, mtime))

    in_progress = kits_root / "dddd4444"
    (in_progress / "stage").mkdir(parents=True)
    os.utime(in_progress, (99_900.0, 99_900.0))

    preview = module.PruneSummary(apply=False)
    module.prune_standalone_kits(kits_root, preview, keep_kits=2, now=100_000.0)
    applied = module.PruneSummary(apply=True)
    module.prune_standalone_kits(kits_root, applied, keep_kits=2, now=100_000.0)

    assert preview.reclaimed_bytes == applied.reclaimed_bytes
    assert not (kits_root / "aaaa1111").exists()
    for kept in ("bbbb2222", "cccc3333"):
        assert (kits_root / kept / "fdai-deployment-kit-0.1.1-linux-x86_64.tar.gz").is_file()
        assert (kits_root / kept / ".fdai-standalone-release").is_file()
        assert not (kits_root / kept / "stage").exists()
        assert not (kits_root / kept / "release-input").exists()
        assert not (kits_root / kept / "source").exists()
    assert (in_progress / "stage").is_dir()


def test_local_state_preserves_audit_evidence_and_prunes_disposable_binaries(
    tmp_path: Path,
) -> None:
    module = _load_module()
    state_root = tmp_path / "state"
    newest_run = state_root / "azure/run-newest"
    older_run = state_root / "azure/run-older"
    legacy_run = state_root / "azure-westus3-old"
    updates_root = state_root / "source-service-updates"

    for index, run_dir in enumerate((older_run, legacy_run, newest_run)):
        providers = (
            run_dir
            / "foundation/foundation-plan-attempt-1/terraform-data/providers/registry.terraform.io"
        )
        providers.mkdir(parents=True)
        (providers / "terraform-provider-azapi_v2.12.0").write_bytes(b"p" * 2048)
        (run_dir / "kit-work/verified").mkdir(parents=True)
        (run_dir / "kit-work/verified/blob.bin").write_bytes(b"v" * 1024)
        (run_dir / "source-snapshot").mkdir(parents=True)
        (run_dir / "source-snapshot/tree.tar").write_bytes(b"t" * 512)
        (run_dir / "run").mkdir(parents=True)
        (run_dir / "run/standalone-kit.tar.gz").write_bytes(b"a" * 1024)
        (run_dir / "foundation/source-transfer.tar").write_bytes(b"x" * 512)
        (run_dir / "foundation/foundation-apply-claim.json").write_text("{}", encoding="utf-8")
        (run_dir / "foundation/foundation-apply-receipt.json").write_text("{}", encoding="utf-8")
        (run_dir / "foundation/plan.tfplan").write_bytes(b"plan")
        (run_dir / "foundation/apply.log").write_text("log", encoding="utf-8")
        mtime = 10_000.0 + index * 1000.0
        os.utime(run_dir, (mtime, mtime))

    old_update = updates_root / ("a" * 40) / "core-control-plane"
    new_update = updates_root / ("b" * 40) / "core-control-plane"
    for index, update_dir in enumerate((old_update, new_update)):
        update_dir.mkdir(parents=True)
        (update_dir / "core-control-plane.oci.tar").write_bytes(b"o" * 1024)
        (update_dir / "core-control-plane.claim.json").write_text("{}", encoding="utf-8")
        (update_dir / "core-control-plane.receipt.json").write_text("{}", encoding="utf-8")
        os.utime(update_dir.parent, (10_000.0 + index * 1000.0, 10_000.0 + index * 1000.0))

    summary = module.PruneSummary(apply=True)
    module.prune_local_state(
        state_root,
        summary,
        keep_kits=2,
        active_min_age_hours=2.0,
        now=100_000.0,
    )

    assert (newest_run / "run/standalone-kit.tar.gz").is_file()
    assert (newest_run / "kit-work/verified/blob.bin").is_file()
    for pruned_run in (older_run, legacy_run):
        assert not (pruned_run / "kit-work").exists()
        assert not (pruned_run / "source-snapshot").exists()
        assert not (pruned_run / "run/standalone-kit.tar.gz").exists()
        assert not (pruned_run / "foundation/source-transfer.tar").exists()
        assert not (
            pruned_run / "foundation/foundation-plan-attempt-1/terraform-data/providers"
        ).exists()
        assert (pruned_run / "foundation/foundation-apply-claim.json").is_file()
        assert (pruned_run / "foundation/foundation-apply-receipt.json").is_file()
        assert (pruned_run / "foundation/plan.tfplan").is_file()
        assert (pruned_run / "foundation/apply.log").is_file()

    assert not (old_update / "core-control-plane.oci.tar").exists()
    assert (old_update / "core-control-plane.claim.json").is_file()
    assert (old_update / "core-control-plane.receipt.json").is_file()
    assert (new_update / "core-control-plane.oci.tar").is_file()

    second = module.PruneSummary(apply=False)
    module.prune_local_state(
        state_root,
        second,
        keep_kits=2,
        active_min_age_hours=2.0,
        now=100_000.0,
    )
    assert second.removed_paths == []
    assert str(newest_run) in second.preserved_paths


def test_cli_reports_json_and_rejects_invalid_arguments(tmp_path: Path) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed local repository script under test.
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--repo-root",
            str(tmp_path),
            "--state-root",
            str(tmp_path / "state"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == "fdai.local-artifact-prune.v1"
    assert payload["apply"] is False

    invalid = subprocess.run(  # noqa: S603 - fixed local repository script under test.
        [sys.executable, str(SCRIPT_PATH), "--keep-kits", "0"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert invalid.returncode == 2
