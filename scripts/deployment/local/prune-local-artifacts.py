#!/usr/bin/env python3
"""Prune disposable local build, kit, cache, and Docker artifacts while keeping audit evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = "fdai.local-artifact-prune.v1"
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_KIT_ARCHIVE_GLOB = "fdai-deployment-kit-*.tar.gz"
_DISPOSABLE_RUN_DIRS = frozenset({"kit-work", "source-snapshot", "source-tools"})
_DISPOSABLE_RUN_FILES = frozenset(
    {
        "standalone-kit.tar.gz",
        "source-transfer.tar",
        "source-runtime-support.tar",
    }
)
_PROTECTED_EVIDENCE_SUFFIXES = (
    ".json",
    ".log",
    ".err",
    ".tfplan",
    ".tfstate",
    ".tfstate.backup",
    ".hcl",
    ".pub",
    ".pyz",
    ".lock",
)


@dataclass
class PruneSummary:
    """Accumulate removed paths and reclaimed byte counts across retention rules."""

    apply: bool
    reclaimed_bytes: int = 0
    removed_paths: list[str] = field(default_factory=list)
    preserved_paths: list[str] = field(default_factory=list)
    docker_actions: list[str] = field(default_factory=list)

    def record_removal(self, path: Path, size_bytes: int) -> None:
        self.reclaimed_bytes += max(0, size_bytes)
        self.removed_paths.append(str(path))

    def record_preserved(self, path: Path) -> None:
        self.preserved_paths.append(str(path))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "apply": self.apply,
            "reclaimed_bytes": self.reclaimed_bytes,
            "reclaimed_gb": round(self.reclaimed_bytes / (1024**3), 2),
            "removed_count": len(self.removed_paths),
            "preserved_count": len(self.preserved_paths),
            "removed_paths": self.removed_paths,
            "preserved_paths": self.preserved_paths,
            "docker_actions": self.docker_actions,
        }


def _path_size(path: Path) -> int:
    """Calculate total bytes on disk for a file or directory without following symlinks."""
    if path.is_symlink():
        return 0
    try:
        if not path.is_dir():
            return path.stat().st_size
    except OSError:
        return 0
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        for name in files:
            candidate = root_path / name
            if candidate.is_symlink():
                continue
            try:
                total += candidate.stat().st_size
            except OSError:
                continue
    return total


def _make_writable_and_remove(path: Path) -> None:
    """Restore owner write bits on read-only cache trees before removing them."""
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
        return
    for item in path.rglob("*"):
        if item.is_symlink():
            continue
        try:
            mode = stat.S_IMODE(item.stat().st_mode)
            item.chmod(mode | (0o700 if item.is_dir() else 0o600))
        except OSError:
            continue
    try:
        path.chmod(0o700)
    except OSError:
        pass
    shutil.rmtree(path)


def _is_protected_evidence_file(path: Path) -> bool:
    name = path.name
    return name.endswith(_PROTECTED_EVIDENCE_SUFFIXES)


def prune_security_cache_snapshots(
    cache_root: Path,
    summary: PruneSummary,
    *,
    keep_generations: int = 2,
    staging_max_age_hours: float = 24.0,
    now: float | None = None,
) -> None:
    """Keep the active current.json snapshot plus N-1 newest rollback snapshots."""
    if keep_generations < 1:
        raise ValueError("keep_generations must be at least 1")
    if not cache_root.is_dir() or cache_root.is_symlink():
        return
    current_time = time.time() if now is None else now
    pointer_path = cache_root / "current.json"
    active_digest: str | None = None
    if pointer_path.is_file() and not pointer_path.is_symlink():
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        digest = pointer.get("cache_digest") if isinstance(pointer, dict) else None
        if isinstance(digest, str) and _DIGEST_PATTERN.fullmatch(digest):
            active_digest = digest
        else:
            return
    snapshots_dir = cache_root / "snapshots"
    if snapshots_dir.is_dir() and not snapshots_dir.is_symlink():
        candidates = sorted(
            (
                entry
                for entry in snapshots_dir.iterdir()
                if entry.is_dir()
                and not entry.is_symlink()
                and _DIGEST_PATTERN.fullmatch(entry.name) is not None
            ),
            key=lambda entry: entry.stat().st_mtime,
            reverse=True,
        )
        keep: set[str] = {active_digest} if active_digest is not None else set()
        for entry in candidates:
            if len(keep) >= keep_generations:
                break
            keep.add(entry.name)
        for entry in candidates:
            if entry.name in keep:
                summary.record_preserved(entry)
                continue
            size = _path_size(entry)
            if summary.apply:
                _make_writable_and_remove(entry)
            summary.record_removal(entry, size)

    staging_dir = cache_root / "staging"
    if staging_dir.is_dir() and not staging_dir.is_symlink():
        cutoff = current_time - staging_max_age_hours * 3600
        for entry in sorted(staging_dir.iterdir(), key=lambda item: item.name):
            if entry.is_symlink():
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            if mtime > cutoff:
                summary.record_preserved(entry)
                continue
            size = _path_size(entry)
            if summary.apply:
                _make_writable_and_remove(entry)
            summary.record_removal(entry, size)


def _remove_registered_worktree(repo_root: Path | None, worktree_path: Path) -> None:
    if repo_root is not None and (repo_root / ".git").exists():
        subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(worktree_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    if worktree_path.exists() or worktree_path.is_symlink():
        _make_writable_and_remove(worktree_path)


def prune_standalone_kits(
    kits_root: Path,
    summary: PruneSummary,
    *,
    keep_kits: int = 2,
    active_min_age_hours: float = 6.0,
    repo_root: Path | None = None,
    now: float | None = None,
) -> None:
    """Remove intermediate kit build trees and retain only the newest N completed kits."""
    if keep_kits < 1:
        raise ValueError("keep_kits must be at least 1")
    if not kits_root.is_dir() or kits_root.is_symlink():
        return
    current_time = time.time() if now is None else now
    cutoff = current_time - active_min_age_hours * 3600
    kit_dirs = sorted(
        (entry for entry in kits_root.iterdir() if entry.is_dir() and not entry.is_symlink()),
        key=lambda entry: entry.stat().st_mtime,
        reverse=True,
    )
    completed_kits: list[Path] = []
    for kit_dir in kit_dirs:
        archives = [
            item
            for item in kit_dir.glob(_KIT_ARCHIVE_GLOB)
            if item.is_file() and not item.is_symlink() and item.stat().st_size > 0
        ]
        if not archives and kit_dir.stat().st_mtime > cutoff:
            summary.record_preserved(kit_dir)
            continue
        completed_kits.append(kit_dir)

    for index, kit_dir in enumerate(completed_kits):
        if index < keep_kits:
            try:
                kit_stat = kit_dir.stat()
            except OSError:
                kit_stat = None
            for child_name in ("stage", "release-input", "source"):
                child = kit_dir / child_name
                if not child.exists() and not child.is_symlink():
                    continue
                size = _path_size(child)
                if summary.apply:
                    if child_name == "source":
                        _remove_registered_worktree(repo_root, child)
                    else:
                        _make_writable_and_remove(child)
                summary.record_removal(child, size)
            if summary.apply and kit_stat is not None:
                try:
                    os.utime(kit_dir, (kit_stat.st_atime, kit_stat.st_mtime))
                except OSError:
                    pass
            summary.record_preserved(kit_dir)
            continue
        source_child = kit_dir / "source"
        size = _path_size(kit_dir)
        if summary.apply:
            if source_child.exists() or source_child.is_symlink():
                _remove_registered_worktree(repo_root, source_child)
            _make_writable_and_remove(kit_dir)
        summary.record_removal(kit_dir, size)


def _prune_disposable_in_run_tree(run_dir: Path, summary: PruneSummary) -> None:
    """Remove re-derivable binary caches inside an inactive run directory while keeping evidence."""
    try:
        run_stat = run_dir.stat()
    except OSError:
        run_stat = None
    for root, dirs, files in os.walk(run_dir, followlinks=False):
        root_path = Path(root)
        for dname in list(dirs):
            candidate = root_path / dname
            if candidate.is_symlink():
                dirs.remove(dname)
                continue
            is_provider_dir = dname == "providers" and root_path.name == "terraform-data"
            if is_provider_dir or dname in _DISPOSABLE_RUN_DIRS:
                size = _path_size(candidate)
                if summary.apply:
                    _make_writable_and_remove(candidate)
                summary.record_removal(candidate, size)
                dirs.remove(dname)
        for fname in files:
            candidate = root_path / fname
            if candidate.is_symlink() or _is_protected_evidence_file(candidate):
                continue
            if fname in _DISPOSABLE_RUN_FILES or fname.endswith(".oci.tar"):
                try:
                    size = candidate.stat().st_size
                except OSError:
                    continue
                if summary.apply:
                    candidate.unlink(missing_ok=True)
                summary.record_removal(candidate, size)
    if summary.apply and run_stat is not None:
        try:
            os.utime(run_dir, (run_stat.st_atime, run_stat.st_mtime))
        except OSError:
            pass


def prune_local_state(
    state_root: Path,
    summary: PruneSummary,
    *,
    keep_kits: int = 2,
    active_min_age_hours: float = 2.0,
    repo_root: Path | None = None,
    now: float | None = None,
) -> None:
    """Prune disposable binaries under ~/.local/state/fdai while keeping all JSON/log evidence."""
    if not state_root.is_dir() or state_root.is_symlink():
        return
    current_time = time.time() if now is None else now
    cutoff = current_time - active_min_age_hours * 3600

    prune_standalone_kits(
        state_root / "kits",
        summary,
        keep_kits=keep_kits,
        active_min_age_hours=max(active_min_age_hours, 6.0),
        repo_root=repo_root,
        now=current_time,
    )

    azure_root = state_root / "azure"
    if azure_root.is_dir() and not azure_root.is_symlink():
        azure_runs = sorted(
            (entry for entry in azure_root.iterdir() if entry.is_dir() and not entry.is_symlink()),
            key=lambda entry: entry.stat().st_mtime,
            reverse=True,
        )
        for index, run_dir in enumerate(azure_runs):
            if index == 0 or run_dir.stat().st_mtime > cutoff:
                summary.record_preserved(run_dir)
                continue
            _prune_disposable_in_run_tree(run_dir, summary)

    for entry in sorted(state_root.iterdir(), key=lambda item: item.name):
        if entry.is_symlink() or not entry.is_dir():
            continue
        if entry.name in {"kits", "azure"}:
            continue
        if entry.name.startswith(("azure-", "deploy-", "console-update-")):
            if entry.stat().st_mtime > cutoff:
                summary.record_preserved(entry)
                continue
            _prune_disposable_in_run_tree(entry, summary)
        elif entry.name in {"source-service-updates", "source-image-stage"}:
            commits = sorted(
                (sub for sub in entry.iterdir() if sub.is_dir() and not sub.is_symlink()),
                key=lambda sub: sub.stat().st_mtime,
                reverse=True,
            )
            for index, commit_dir in enumerate(commits):
                if index == 0 or commit_dir.stat().st_mtime > cutoff:
                    summary.record_preserved(commit_dir)
                    continue
                _prune_disposable_in_run_tree(commit_dir, summary)


def prune_docker_resources(
    summary: PruneSummary,
    *,
    buildx_keep_gb: int = 25,
) -> None:
    """Prune exited native-* containers, dangling images, and excess Buildx cache."""
    if buildx_keep_gb < 1:
        raise ValueError("buildx_keep_gb must be at least 1")
    if shutil.which("docker") is None:
        return
    containers = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "name=^native-",
            "--filter",
            "status=exited",
            "--filter",
            "status=created",
            "-q",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    container_ids = [line.strip() for line in containers.stdout.splitlines() if line.strip()]
    if container_ids:
        summary.docker_actions.append(f"remove_native_containers={len(container_ids)}")
        if summary.apply:
            subprocess.run(
                ["docker", "rm", *container_ids],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
    summary.docker_actions.append("docker_image_prune_dangling")
    if summary.apply:
        subprocess.run(
            ["docker", "image", "prune", "-f"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    summary.docker_actions.append(f"docker_buildx_prune_keep_{buildx_keep_gb}gb")
    if summary.apply:
        subprocess.run(
            ["docker", "buildx", "prune", "--keep-storage", f"{buildx_keep_gb}GB", "-f"],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Remove eligible disposable artifacts")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="Repository root containing .fdai/code-security-cache",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=Path.home() / ".local/state/fdai",
        help="Local FDAI state directory (default: ~/.local/state/fdai)",
    )
    parser.add_argument(
        "--keep-cache-generations",
        type=int,
        default=2,
        help="Number of vulnerability cache generations to keep (default: 2)",
    )
    parser.add_argument(
        "--keep-kits",
        type=int,
        default=2,
        help="Number of completed standalone deployment kit archives to keep (default: 2)",
    )
    parser.add_argument(
        "--active-min-age-hours",
        type=float,
        default=2.0,
        help="Minimum age in hours before inactive run directories are pruned (default: 2.0)",
    )
    parser.add_argument(
        "--include-docker",
        action="store_true",
        help="Also prune stopped native-* containers, dangling images, and Buildx cache",
    )
    parser.add_argument(
        "--buildx-keep-gb",
        type=int,
        default=25,
        help="Buildx cache storage cap in GB when --include-docker is set (default: 25)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if (
        args.keep_cache_generations < 1
        or args.keep_kits < 1
        or args.active_min_age_hours < 0
        or args.buildx_keep_gb < 1
    ):
        print("prune-local-artifacts: retention arguments are out of range", file=sys.stderr)
        return 2
    summary = PruneSummary(apply=args.apply)
    repo_root = args.repo_root.resolve()
    prune_security_cache_snapshots(
        repo_root / ".fdai/code-security-cache",
        summary,
        keep_generations=args.keep_cache_generations,
    )
    user_cache_root = (
        Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        / "fdai-code-security"
        / "cache"
    )
    prune_security_cache_snapshots(
        user_cache_root,
        summary,
        keep_generations=args.keep_cache_generations,
    )
    prune_local_state(
        args.state_root.resolve(),
        summary,
        keep_kits=args.keep_kits,
        active_min_age_hours=args.active_min_age_hours,
        repo_root=repo_root,
    )
    if args.include_docker:
        prune_docker_resources(summary, buildx_keep_gb=args.buildx_keep_gb)
    print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
