"""Materialize only pinned Git files for connected builds and private-host transfer."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.source_input import SourceDeploymentInput, _git, _read_tracked

_MANIFEST = "source-input.json"


def materialize_source(source: SourceDeploymentInput, destination: Path) -> str:
    """Create a fresh private execution copy, excluding every ignored or untracked input.

    Return the manifest digest for independent retention. Failure preserves the partial
    destination for inspection; it never repairs, reuses or deletes prior deployment state.
    """
    source.reverify()
    destination.mkdir(mode=0o700)
    tree = destination / "tree"
    tree.mkdir(mode=0o700)
    records: list[dict[str, str]] = []
    for entry in _git(source.root, "ls-tree", "-rz", "--full-tree", source.commit).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, _blob = metadata.decode("ascii").split()
        relative = raw_path.decode("utf-8")
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ValueError("source snapshot contains an unsupported input")
        content = _read_tracked(source.root, relative, mode=mode)
        output = tree / relative
        for parent in reversed(output.parents):
            if parent == tree or not parent.is_relative_to(tree):
                continue
            parent.mkdir(mode=0o700, exist_ok=True)
        if mode == "120000":
            output.symlink_to(os.fsdecode(content))
        else:
            write_private_bytes(output, content)
            if mode == "100755":
                output.chmod(0o700)
        records.append(
            {"path": relative, "mode": mode, "sha256": hashlib.sha256(content).hexdigest()}
        )
    source.reverify()
    if canonical_digest({"files": records}) != source.content_digest:
        raise ValueError("source snapshot differs from the selected input")
    manifest = {
        "schema_version": "fdai.source-snapshot.v1",
        "source": source.to_mapping(),
        "files": records,
    }
    digest = canonical_digest(manifest)
    write_private_bytes(destination / _MANIFEST, canonical_bytes(manifest))
    verify_source_snapshot(destination, expected_digest=digest)
    return digest


def verify_source_snapshot(directory: Path, *, expected_digest: str) -> dict[str, Any]:
    """Recheck an execution snapshot against an independently retained manifest digest."""
    raw = read_private_bytes(directory / _MANIFEST, max_bytes=16 * 1024 * 1024)
    manifest = load_json_object(raw, label="source snapshot", max_bytes=16 * 1024 * 1024)
    if canonical_digest(manifest) != expected_digest or raw != canonical_bytes(manifest):
        raise ValueError("source snapshot manifest differs from the retained digest")
    if (
        set(manifest) != {"schema_version", "source", "files"}
        or manifest["schema_version"] != "fdai.source-snapshot.v1"
    ):
        raise ValueError("source snapshot schema is invalid")
    source = manifest["source"]
    records = manifest["files"]
    if (
        not isinstance(source, dict)
        or source.get("provenance") != "operator-selected-source"
        or source.get("release_signature_verified") is not False
    ):
        raise ValueError("source snapshot cannot claim release trust")
    if not isinstance(records, list) or len(records) != source.get("file_count"):
        raise ValueError("source snapshot inventory is invalid")
    if canonical_digest({"files": records}) != source.get("content_digest"):
        raise ValueError("source snapshot content binding is invalid")
    tree = directory / "tree"
    if tree.is_symlink() or not tree.is_dir():
        raise ValueError("source snapshot root is invalid")
    paths = set()
    for record in records:
        relative, mode = record["path"], record["mode"]
        if relative in paths:
            raise ValueError("source snapshot repeats a file")
        paths.add(relative)
        content = _read_tracked(tree, relative, mode=mode)
        if hashlib.sha256(content).hexdigest() != record["sha256"]:
            raise ValueError("source snapshot content changed")
        if mode == "120000":
            target = (tree / relative).resolve(strict=True)
            if not target.is_relative_to(tree.resolve()) or target.relative_to(
                tree
            ).as_posix() not in {item["path"] for item in records}:
                raise ValueError("source snapshot link leaves the tracked file set")
    actual = set()
    for root, directories, files in os.walk(tree, followlinks=False):
        for name in directories:
            if (Path(root) / name).is_symlink():
                raise ValueError("source snapshot cannot contain linked directories")
        for name in files:
            path = Path(root) / name
            if not stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink():
                raise ValueError("source snapshot contains a special file")
            actual.add(path.relative_to(tree).as_posix())
    if actual != paths:
        raise ValueError("source snapshot file set changed")
    return source
