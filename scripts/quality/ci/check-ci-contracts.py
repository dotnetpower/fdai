#!/usr/bin/env python3
"""Validate clean-checkout inputs shared by local verification and CI."""

from __future__ import annotations

import ast
import json
import re
import shlex
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REQUIRED_TRACKED_PATHS = (
    "scripts/lib/framework-surface.txt",
    "console/package-lock.json",
    "cli/package-lock.json",
)
SHARED_RUNNERS = (
    "scripts/quality/ci/run-python-tests.sh",
    "scripts/quality/ci/run-operator-surfaces.sh",
)
RUNNER_ENTRY_POINTS = (
    ".github/workflows/ci.yml",
    "Makefile",
    "scripts/verify.sh",
)
APPROVED_ACTIONS = {
    "Azure/functions-action": ("bc63708cc6539760eea18d8a7de4ce8ef5fdf593", "v1.5.6"),
    "actions/attest": ("f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6", "v4.2.0"),
    "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
    "actions/configure-pages": ("45bfe0192ca1faeb007ade9deae92b16b8254a0d", "v6.0.0"),
    "actions/deploy-pages": ("cd2ce8fcbc39b97be8ca5fce6e763baed58fa128", "v5.0.0"),
    "actions/download-artifact": ("3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c", "v8.0.1"),
    "actions/github-script": ("d746ffe35508b1917358783b479e04febd2b8f71", "v9.0.0"),
    "actions/setup-node": ("820762786026740c76f36085b0efc47a31fe5020", "v7.0.0"),
    "actions/setup-python": ("5fda3b95a4ea91299a34e894583c3862153e4b97", "v7.0.0"),
    "actions/upload-artifact": ("043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", "v7.0.1"),
    "actions/upload-pages-artifact": ("fc324d3547104276b827a68afc52ff2a11cc49c9", "v5.0.0"),
    "astral-sh/setup-uv": ("11f9893b081a58869d3b5fccaea48c9e9e46f990", "v8.3.2"),
    "docker/build-push-action": ("53b7df96c91f9c12dcc8a07bcb9ccacbed38856a", "v7.3.0"),
    "docker/login-action": ("abd2ef45e78c5afb21d64d4ca52ee8550d9572c7", "v4.5.1"),
    "docker/setup-buildx-action": ("bb05f3f5519dd87d3ba754cc423b652a5edd6d2c", "v4.2.0"),
    "gitleaks/gitleaks-action": ("e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e", "v3.0.0"),
    "hashicorp/setup-terraform": ("dfe3c3f87815947d99a8997f908cb6525fc44e9e", "v4.0.1"),
    "pypa/gh-action-pip-audit": ("1220774d901786e6f652ae159f7b6bc8fea6d266", "v1.1.0"),
    "pypa/gh-action-pypi-publish": ("2834a314042ef964da07689278dd1e9d773e8afd", "v1.14.1"),
}
ACTION_REF_RE = re.compile(
    r"uses:\s*(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)"
    r"@(?P<ref>[^\s#]+)"
    r"(?:\s*#\s*(?P<comment>[^\r\n]+))?"
)
IMMUTABLE_ACTION_REF_RE = re.compile(r"[0-9a-f]{40}")
WRITE_PERMISSION_RE = re.compile(r"(?m)^\s+[a-z-]+:\s*write\s*(?:#.*)?$")
WRITE_ALL_PERMISSION_RE = re.compile(r"(?m)^\s*permissions:\s*write-all\s*(?:#.*)?$")
INLINE_WRITE_PERMISSION_RE = re.compile(r"permissions:\s*\{[^}\n]*:\s*write(?:\s*[,}])")
PRIVILEGED_COMMAND_RE = re.compile(
    r"\b(?:terraform\s+(?:apply|destroy)|git\s+push|docker\s+push|"
    r"gh\s+(?:release|issue)\s+(?:create|delete|edit|upload|close|reopen)|"
    r"az\s+\S+\s+(?:create|delete|deploy|import|restart|set|start|stop|update))\b"
)
PROTECTED_WORKFLOW_GUARD = "Verify protected workflow source"
UV_SETUP_BLOCK_RE = re.compile(r"(?ms)^\s+- name: Set up uv \(Python 3\.13\).*?(?=^\s+- name:|\Z)")
BASE_IMAGE_REGISTRY_ARG = "BASE_IMAGE_REGISTRY"
BASE_IMAGE_PREFIX = "${" + BASE_IMAGE_REGISTRY_ARG + "}/"


def _service_dockerfiles() -> tuple[Path, ...]:
    return tuple(sorted(REPO_ROOT.glob("services/*/docker/Dockerfile")))


def _tracked_paths() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return {path for path in result.stdout.decode().split("\0") if path}


def _docker_copy_sources() -> tuple[str, ...]:
    sources: list[str] = []
    for dockerfile in _service_dockerfiles():
        logical_line = ""
        for raw_line in dockerfile.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            logical_line = f"{logical_line} {stripped}".strip()
            if logical_line.endswith("\\"):
                logical_line = logical_line[:-1].rstrip()
                continue
            parts = shlex.split(logical_line)
            logical_line = ""
            if (
                not parts
                or parts[0].upper() != "COPY"
                or any(part.startswith("--from=") for part in parts[1:])
            ):
                continue
            operands = [part for part in parts[1:] if not part.startswith("--")]
            sources.extend(operands[:-1])
    return tuple(sources)


def _dockerignore_pattern_matches(pattern: str, path: str) -> bool:
    normalized_pattern = pattern.lstrip("/").rstrip("/")
    normalized_path = path.lstrip("/").rstrip("/")
    if not normalized_pattern:
        return False
    if pattern.endswith("/"):
        return fnmatchcase(normalized_path, normalized_pattern) or fnmatchcase(
            normalized_path, f"{normalized_pattern}/**"
        )
    if "/" not in normalized_pattern:
        return any(fnmatchcase(part, normalized_pattern) for part in normalized_path.split("/"))
    return fnmatchcase(normalized_path, normalized_pattern)


def _docker_path_is_ignored(path: str, rules: tuple[str, ...]) -> bool:
    ignored = False
    for rule in rules:
        exception = rule.startswith("!")
        pattern = rule[1:] if exception else rule
        if _dockerignore_pattern_matches(pattern, path):
            ignored = not exception
    return ignored


def _validate_build_context() -> list[str]:
    errors: list[str] = []
    tracked = _tracked_paths()
    container_workflow = REPO_ROOT / ".github" / "workflows" / "container-supply-chain.yml"
    workflow_text = container_workflow.read_text(encoding="utf-8")
    materialized_sources = {
        "resolved-models.json": (
            "Materialize resolved model manifest",
            'Path("resolved-models.json").write_text(',
        )
    }
    for path in REQUIRED_TRACKED_PATHS:
        if path not in tracked:
            errors.append(f"required clean-checkout input is not tracked: {path}")

    dockerignore_rules = tuple(
        line.strip()
        for line in (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    docker_sources = _docker_copy_sources()
    for source in docker_sources:
        if any(character in source for character in "*?["):
            continue
        materialization_contract = materialized_sources.get(source.rstrip("/"))
        if materialization_contract is not None:
            for fragment in materialization_contract:
                if fragment not in workflow_text:
                    errors.append(
                        f"container-supply-chain.yml does not materialize Docker source "
                        f"{source}: missing {fragment}"
                    )
        elif not (REPO_ROOT / source.rstrip("/")).exists():
            errors.append(f"Dockerfile COPY source is missing: {source}")
        if _docker_path_is_ignored(source, dockerignore_rules):
            errors.append(f"Dockerfile COPY source is excluded by .dockerignore: {source}")

    dockerignore = set(dockerignore_rules)
    if "tests/" in dockerignore:
        errors.append(".dockerignore must not exclude tests/ before its scenarios exception")
    for rule in (
        "tests/*",
        "services/*/tests/*",
        "!services/core-control-plane/tests/scenarios/",
    ):
        if rule not in dockerignore:
            errors.append(f".dockerignore is missing required rule: {rule}")

    manifest_path = REPO_ROOT / "resolved-models.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"resolved-models.json is not valid JSON: {exc}")
        else:
            if not isinstance(manifest, dict) or not isinstance(manifest.get("capabilities"), list):
                errors.append("resolved-models.json must be an object with a capabilities array")
    return errors


def _validate_base_images() -> list[str]:
    """Keep every external base image mirror-overridable and digest-pinned.

    A disconnected tenant builds from an internal registry mirror, so the
    registry host MUST be a build argument. The digest MUST stay in the file so
    the override can redirect where bytes come from but never which bytes are
    accepted.
    """
    errors: list[str] = []
    dockerfiles = _service_dockerfiles()
    if not dockerfiles:
        return ["service-owned Dockerfiles are missing"]
    for dockerfile in dockerfiles:
        lines = dockerfile.read_text(encoding="utf-8").splitlines()
        if not any(line.strip().startswith(f"ARG {BASE_IMAGE_REGISTRY_ARG}=") for line in lines):
            errors.append(f"Dockerfile must declare ARG {BASE_IMAGE_REGISTRY_ARG} with a default")
        stages: set[str] = set()
        for line in lines:
            parts = line.strip().split()
            if len(parts) < 2 or parts[0].upper() != "FROM":
                continue
            reference = parts[1]
            if len(parts) >= 4 and parts[2].upper() == "AS":
                stages.add(parts[3])
            if reference in stages:
                continue
            if not reference.startswith(BASE_IMAGE_PREFIX):
                errors.append(
                    f"Dockerfile base image {reference} must be prefixed with {BASE_IMAGE_PREFIX}"
                )
            if "@sha256:" not in reference:
                errors.append(f"Dockerfile base image {reference} must be digest-pinned")
    return errors


def _validate_shared_runners() -> list[str]:
    errors: list[str] = []
    for entry_point in RUNNER_ENTRY_POINTS:
        content = (REPO_ROOT / entry_point).read_text(encoding="utf-8")
        for runner in SHARED_RUNNERS:
            if runner not in content:
                errors.append(f"{entry_point} does not delegate to {runner}")
        if "--cov=services/core-control-plane/src/fdai/core" in content:
            errors.append(f"{entry_point} duplicates the safety-core coverage target list")
    return errors


def _validate_python_test_partitioning() -> list[str]:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    runner = (REPO_ROOT / "scripts" / "quality" / "ci" / "run-python-tests.sh").read_text(
        encoding="utf-8"
    )
    required_workflow_fragments = (
        "pytest regression shard ${{ matrix.shard }}/3",
        "FDAI_PYTEST_MODE: coverage",
        "FDAI_PYTEST_MODE: integration",
        "behavior source citation precision",
    )
    errors = [
        f"ci.yml is missing partition contract: {fragment}"
        for fragment in required_workflow_fragments
        if fragment not in workflow
    ]
    for mode in ("all)", "full)", "coverage)", "integration)"):
        if mode not in runner:
            errors.append(f"run-python-tests.sh is missing mode branch: {mode}")
    return errors


def _validate_action_runtime_versions() -> list[str]:
    errors: list[str] = []
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        content = path.read_text(encoding="utf-8")
        relative = path.relative_to(REPO_ROOT)
        for match in ACTION_REF_RE.finditer(content):
            action = match.group("action")
            actual_ref = match.group("ref")
            approved = APPROVED_ACTIONS.get(action)
            if approved is None:
                errors.append(f"{relative} uses unapproved remote action {action}@{actual_ref}")
                continue
            expected_ref, expected_version = approved
            if IMMUTABLE_ACTION_REF_RE.fullmatch(actual_ref) is None:
                errors.append(
                    f"{relative} must pin {action} to an immutable 40-character SHA; "
                    f"found {actual_ref}"
                )
            elif actual_ref != expected_ref:
                errors.append(f"{relative} uses {action}@{actual_ref}; expected {expected_ref}")
            else:
                comment = (match.group("comment") or "").split(",", maxsplit=1)[0].strip()
                if comment != expected_version:
                    errors.append(
                        f"{relative} must document {action}@{actual_ref} with trusted "
                        f"version comment # {expected_version}"
                    )
    return errors


def _is_privileged_workflow(content: str) -> bool:
    """Detect workflows that can mutate durable state or use a privileged identity."""
    return any(
        (
            WRITE_PERMISSION_RE.search(content),
            WRITE_ALL_PERMISSION_RE.search(content),
            INLINE_WRITE_PERMISSION_RE.search(content),
            re.search(r"runs-on:\s*(?:\[[^\]]*\bself-hosted\b|self-hosted\b)", content),
            PRIVILEGED_COMMAND_RE.search(content),
        )
    )


def _validate_privileged_workflow_guards() -> list[str]:
    """Require protected source provenance before privileged repository code executes."""
    errors: list[str] = []
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        content = path.read_text(encoding="utf-8")
        if not _is_privileged_workflow(content):
            continue
        relative = path.relative_to(REPO_ROOT).as_posix()
        event_scoped_issue_mutation = (
            re.search(r"(?m)^\s+issues:\s*$", content) is not None
            and "github.event_name == 'issues'" in content
            and "github.event.issue.pull_request == null" in content
            and "actions/checkout@" not in content
            and "\n        run:" not in content
        )
        if event_scoped_issue_mutation:
            continue
        common_fragments = (
            PROTECTED_WORKFLOW_GUARD,
            "refs/heads/main:refs/remotes/origin/main",
            'merge-base --is-ancestor "$TARGET_COMMIT_SHA"',
        )
        for fragment in common_fragments:
            if fragment not in content:
                errors.append(
                    f"{relative} is privileged and lacks protected-source guard: {fragment}"
                )
        exact_source_fragments = (
            f"PROTECTED_WORKFLOW_PATH: {relative}",
            '"$TARGET_COMMIT_SHA:$PROTECTED_WORKFLOW_PATH"',
            '"refs/remotes/origin/main:$PROTECTED_WORKFLOW_PATH"',
        )
        has_exact_source_guard = all(
            fragment in content for fragment in exact_source_fragments
        ) and any(flag in content for flag in ("diff --brief", "diff -q", "diff --quiet"))
        protected_controls_fragments = (
            "path: trusted-controls",
            "ref: main",
            f'expected_workflow_ref="$GITHUB_REPOSITORY/{relative}@refs/heads/main"',
            '[[ "$GITHUB_WORKFLOW_REF" == "$expected_workflow_ref" ]]',
            'controls_commit_sha="$(git -C "$TRUSTED_CONTROLS" rev-parse HEAD)"',
            "deployment controls do not match protected origin/main.",
        )
        if not has_exact_source_guard and not all(
            fragment in content for fragment in protected_controls_fragments
        ):
            errors.append(
                f"{relative} is privileged and lacks a complete exact-source or "
                "protected-controls guard"
            )
        guard_index = content.find(PROTECTED_WORKFLOW_GUARD)
        action_index = content.find("uses:")
        if guard_index >= 0 and action_index >= 0 and guard_index > action_index:
            errors.append(f"{relative} executes a remote action before its protected-source guard")
        if "workflow_dispatch:" in content or "workflow_call:" in content:
            if "commit_sha:" not in content:
                errors.append(f"{relative} must accept an exact commit_sha for privileged dispatch")
            if "github.ref == 'refs/heads/main'" not in content:
                errors.append(f"{relative} must restrict privileged dispatch to protected main")
    return errors


def _validate_uv_cache_writers() -> list[str]:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    blocks = UV_SETUP_BLOCK_RE.findall(workflow)
    if not blocks:
        return ["ci.yml has no setup-uv cache blocks"]
    errors = [
        "every ci.yml setup-uv block must restore the shared cache"
        for block in blocks
        if "enable-cache: true" not in block
    ]
    errors.extend(
        "every ci.yml Python 3.13 setup-uv block must pin python-version: 3.13"
        for block in blocks
        if 'python-version: "3.13"' not in block
    )
    writer_count = sum("save-cache: false" not in block for block in blocks)
    if writer_count != 1:
        errors.append(f"ci.yml must have exactly one setup-uv cache writer; found {writer_count}")
    return errors


def _contains_guard_call(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == "_requires_live_db"
        for child in ast.walk(node)
    )


def _validate_live_db_guards() -> list[str]:
    errors: list[str] = []
    for path in sorted((REPO_ROOT / "tests/persistence").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_requires_live_db"
            for node in tree.body
        ):
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_") or not _contains_guard_call(node):
                continue
            executable_body = node.body
            if (
                executable_body
                and isinstance(executable_body[0], ast.Expr)
                and isinstance(executable_body[0].value, ast.Constant)
                and isinstance(executable_body[0].value.value, str)
            ):
                executable_body = executable_body[1:]
            if not executable_body or not _contains_guard_call(executable_body[0]):
                relative = path.relative_to(REPO_ROOT)
                errors.append(f"{relative}:{node.lineno} must call _requires_live_db() first")
    return errors


def main() -> int:
    errors = [
        *_validate_build_context(),
        *_validate_base_images(),
        *_validate_shared_runners(),
        *_validate_python_test_partitioning(),
        *_validate_action_runtime_versions(),
        *_validate_privileged_workflow_guards(),
        *_validate_uv_cache_writers(),
        *_validate_live_db_guards(),
    ]
    if errors:
        for error in errors:
            print(f"ci-contracts: ERROR: {error}")
        return 1
    print("ci-contracts: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
