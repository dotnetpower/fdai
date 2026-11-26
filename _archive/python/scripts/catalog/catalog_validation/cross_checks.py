"""Source-manifest and local upstream snapshot cross-checks."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .common import (
    CATALOG_ROOT,
    REPO_ROOT,
    SOURCES_DIR,
    Runner,
    StepResult,
    load_yaml,
    run_subprocess,
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ZERO_SHA = "0" * 40


def step_source_manifests(runner: Runner) -> StepResult:
    if not SOURCES_DIR.is_dir():
        return StepResult(
            name="source_manifests",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="sources/ not present",
        )
    findings: list[str] = []
    checked = 0
    for manifest in sorted(SOURCES_DIR.glob("*/manifest.yaml")):
        data = load_yaml(manifest)
        relative_path = manifest.relative_to(REPO_ROOT)
        if not isinstance(data, dict):
            findings.append(f"{relative_path}: malformed manifest")
            continue
        revision = ((data.get("fetch") or {}).get("revision")) or data.get("revision")
        if revision is None:
            checked += 1
            continue
        source_id = str(data.get("id") or manifest.parent.name)
        collected_here = CATALOG_ROOT / "collected" / source_id
        has_imports = collected_here.is_dir() and any(collected_here.rglob("*.yaml"))
        revision_text = str(revision)
        if revision_text == _ZERO_SHA:
            if has_imports:
                findings.append(
                    f"{relative_path}: revision is the all-zero placeholder but"
                    f" collected/{source_id}/ has imported rules"
                )
        elif not _SHA_RE.fullmatch(revision_text):
            findings.append(
                f"{relative_path}: revision {revision_text!r} is not a 40-hex commit SHA"
            )
        checked += 1
    return StepResult(
        name="source_manifests",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={"checked": checked},
    )


def _pinned_clone(
    name: str,
    clone: Path,
    manifest: Path,
    missing_reason: str,
) -> StepResult | None:
    if not clone.is_dir() or not manifest.is_file():
        return StepResult(
            name=name,
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason=missing_reason,
        )
    data = load_yaml(manifest)
    pinned = (
        ((data.get("fetch") or {}).get("revision")) or data.get("revision")
        if isinstance(data, dict)
        else None
    )
    if pinned is None and name == "cross_check_azure":
        return StepResult(
            name=name,
            ok=False,
            duration_s=0.0,
            findings=["azure manifest has no revision"],
        )
    return_code, output = run_subprocess(["git", "-C", str(clone), "rev-parse", "HEAD"])
    if pinned is None or return_code != 0 or output.strip() != str(pinned):
        return StepResult(
            name=name,
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason=f"clone HEAD {output.strip()!r} != manifest {pinned!r}",
        )
    return None


def step_cross_check_azure(runner: Runner) -> StepResult:
    clone = Path("/tmp/azure-policy-clone/azure-policy")  # noqa: S108
    early = _pinned_clone(
        "cross_check_azure",
        clone,
        SOURCES_DIR / "azure-policy-builtin" / "manifest.yaml",
        "azure-policy clone or manifest not present",
    )
    if early is not None:
        return early
    upstream: set[str] = set()
    definitions = clone / "built-in-policies" / "policyDefinitions"
    for path in definitions.rglob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(document, dict) and isinstance(document.get("name"), str):
            upstream.add(document["name"].lower())
    root = CATALOG_ROOT / "collected" / "azure-builtin"
    if not root.is_dir():
        return StepResult(
            name="cross_check_azure",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="no imported azure-builtin rules on disk",
        )
    findings: list[str] = []
    checked = 0
    orphans = 0
    for path in root.rglob("*.yaml"):
        data = load_yaml(path)
        if not isinstance(data, dict):
            continue
        provenance = data.get("provenance") or {}
        origin = str(
            (provenance.get("source") or {}).get("id") or provenance.get("upstream_id") or ""
        )
        match = re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            origin.lower(),
        )
        if match and match.group(0) not in upstream:
            orphans += 1
            if len(findings) < 20:
                findings.append(
                    f"{path.relative_to(REPO_ROOT)}: upstream GUID {match.group(0)} not found"
                )
        checked += 1
    if orphans:
        findings.append(f"total orphan azure rules: {orphans}")
    return StepResult(
        name="cross_check_azure",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={"checked": checked, "upstream_guids": len(upstream), "orphans": orphans},
    )


def step_cross_check_kube(runner: Runner) -> StepResult:
    clone = Path("/tmp/kube-bench-clone/kube-bench")  # noqa: S108
    early = _pinned_clone(
        "cross_check_kube",
        clone,
        SOURCES_DIR / "kube-bench" / "manifest.yaml",
        "kube-bench clone or manifest not present",
    )
    if early is not None:
        return early
    upstream: set[str] = set()
    for path in (clone / "cfg").rglob("*.yaml"):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(document, dict):
            continue
        for group in document.get("groups") or []:
            if not isinstance(group, dict):
                continue
            for check in group.get("checks") or []:
                if isinstance(check, dict) and isinstance(check.get("id"), (str, int)):
                    upstream.add(str(check["id"]))
    root = CATALOG_ROOT / "collected" / "kube-bench"
    if not root.is_dir():
        return StepResult(
            name="cross_check_kube",
            ok=True,
            duration_s=0.0,
            skipped=True,
            skipped_reason="no imported kube-bench rules on disk",
        )
    findings: list[str] = []
    checked = 0
    orphans = 0
    for path in root.rglob("*.yaml"):
        data = load_yaml(path)
        if not isinstance(data, dict):
            continue
        provenance = data.get("provenance") or {}
        check_id = str(
            (provenance.get("source") or {}).get("id") or provenance.get("upstream_id") or ""
        )
        if check_id and check_id not in upstream:
            orphans += 1
            if len(findings) < 20:
                findings.append(
                    f"{path.relative_to(REPO_ROOT)}: upstream id {check_id!r} not found"
                )
        checked += 1
    if orphans:
        findings.append(f"total orphan kube-bench rules: {orphans}")
    return StepResult(
        name="cross_check_kube",
        ok=not findings,
        duration_s=0.0,
        findings=findings,
        stats={"checked": checked, "upstream_ids": len(upstream), "orphans": orphans},
    )
