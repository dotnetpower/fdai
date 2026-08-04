"""Deterministic roadmap document, route, and evidence inventory."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import subprocess
from pathlib import Path


def _git(*arguments: str, cwd: Path) -> str:
    return subprocess.check_output(["git", *arguments], cwd=cwd, text=True).strip()


def file_blob(repo_root: Path, relative: str) -> str:
    path = repo_root / relative
    if not path.is_file():
        return "missing"
    return _git("hash-object", relative, cwd=repo_root)


def evidence_digest(repo_root: Path, evidence_paths: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(set(evidence_paths)):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_blob(repo_root, relative).encode("ascii"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def canonical_documents(repo_root: Path) -> list[str]:
    output = _git("ls-files", "docs/roadmap/*.md", "docs/roadmap/**/*.md", cwd=repo_root)
    return sorted({path for path in output.splitlines() if not path.endswith("-ko.md")})


def route_evidence(repo_root: Path, document: str) -> tuple[list[str], list[str]]:
    route_path = repo_root / "scripts/lib/design-routes.json"
    payload = json.loads(route_path.read_text(encoding="utf-8"))
    route_ids: list[str] = []
    validation_commands: list[str] = []
    for route in payload.get("routes", []):
        direct = document in route.get("must_read", []) or document in route.get("docs_update", [])
        matched = any(
            pattern == "**" or fnmatch.fnmatchcase(document, pattern)
            for pattern in route.get("paths", [])
        )
        if not direct and not matched:
            continue
        route_ids.append(str(route["id"]))
        if route.get("id") != "baseline":
            validation_commands.extend(str(command) for command in route.get("validate", []))
    return sorted(set(route_ids)), list(dict.fromkeys(validation_commands))


def route_digest(route_ids: list[str], commands: list[str]) -> str:
    encoded = json.dumps(
        {"route_ids": route_ids, "validation_commands": commands},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
