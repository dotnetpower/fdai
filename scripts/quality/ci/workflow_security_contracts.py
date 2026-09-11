"""Validate semantic privilege and protected-source workflow contracts."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

PRIVILEGED_COMMAND_RE = re.compile(
    r"\b(?:terraform\s+(?:apply|destroy)|git\s+push|docker\s+push|"
    r"gh\s+(?:release|issue)\s+(?:create|delete|edit|upload|close|reopen)|"
    r"az\s+\S+\s+(?:create|delete|deploy|import|restart|set|start|stop|update))\b"
)


def is_privileged_workflow(content: str) -> bool:
    """Return whether parsed workflow behavior can use a privileged boundary."""
    try:
        document: Any = yaml.safe_load(content)
    except yaml.YAMLError:
        return True

    def is_privileged(node: Any) -> bool:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "permissions":
                    if permissions_are_privileged(value):
                        return True
                elif key == "runs-on":
                    if runner_is_privileged(value):
                        return True
                elif (
                    key == "run"
                    and isinstance(value, str)
                    and PRIVILEGED_COMMAND_RE.search(value) is not None
                ):
                    return True
                if is_privileged(value):
                    return True
        elif isinstance(node, list):
            return any(is_privileged(value) for value in node)
        return False

    return is_privileged(document)


def is_event_scoped_issue_mutation(
    document: Any,
    *,
    approved_github_script_ref: str,
) -> bool:
    """Recognize the sole issues-only workflow exemption."""
    if not isinstance(document, dict):
        return False
    triggers = document.get("on", document.get(True))
    if not isinstance(triggers, dict) or set(triggers) != {"issues"}:
        return False
    if document.get("permissions") != {"contents": "read", "issues": "write"}:
        return False
    jobs = document.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return False
    required_conditions = (
        "github.event_name == 'issues'",
        "github.event.issue.pull_request == null",
        "github.actor != 'github-actions[bot]'",
    )
    for job in jobs.values():
        if not isinstance(job, dict) or "permissions" in job:
            return False
        condition = job.get("if")
        if not isinstance(condition, str) or not all(
            required in condition for required in required_conditions
        ):
            return False
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            return False
        for step in steps:
            if not isinstance(step, dict) or set(step) & {"run", "shell"}:
                return False
            if step.get("uses") != approved_github_script_ref:
                return False
    return True


def workflow_triggers(document: Any) -> dict[str, Any]:
    """Return the parsed trigger mapping, including PyYAML's legacy boolean key."""
    if not isinstance(document, dict):
        return {}
    triggers = document.get("on", document.get(True))
    return triggers if isinstance(triggers, dict) else {}


def dispatch_guard_errors(document: Any, relative: str) -> list[str]:
    """Validate exact-revision inputs and protected-main root jobs."""
    triggers = workflow_triggers(document)
    dispatch_triggers = {"workflow_dispatch", "workflow_call"} & set(triggers)
    if not dispatch_triggers:
        return []
    errors: list[str] = []
    for trigger in sorted(dispatch_triggers):
        config = triggers[trigger]
        inputs = config.get("inputs") if isinstance(config, dict) else None
        if not isinstance(inputs, dict) or "commit_sha" not in inputs:
            errors.append(f"{relative} {trigger} must declare an exact commit_sha input")
    jobs = document.get("jobs") if isinstance(document, dict) else None
    if not isinstance(jobs, dict):
        return [*errors, f"{relative} dispatch workflow must declare jobs"]
    for job_name, job in jobs.items():
        if not isinstance(job, dict) or "needs" in job:
            continue
        condition = job.get("if")
        if not isinstance(condition, str) or "github.ref == 'refs/heads/main'" not in condition:
            errors.append(
                f"{relative} root job {job_name} must restrict dispatch to protected main"
            )
    return errors


def permissions_are_privileged(permissions: Any) -> bool:
    """Return whether a permissions mapping can write repository state."""
    return permissions == "write-all" or (
        isinstance(permissions, dict)
        and any(permission == "write" for permission in permissions.values())
    )


def runner_is_privileged(runner: Any) -> bool:
    """Treat self-hosted and unresolved expression runners as privileged."""
    runners = runner if isinstance(runner, list) else [runner]
    return any(
        value == "self-hosted" or (isinstance(value, str) and "${{" in value) for value in runners
    )


def job_is_privileged(job: Any, default_permissions: Any) -> bool:
    """Return whether one job needs an executable provenance chain."""
    if not isinstance(job, dict):
        return False
    permissions = job.get("permissions", default_permissions)
    if permissions_are_privileged(permissions) or runner_is_privileged(job.get("runs-on")):
        return True
    steps = job.get("steps")
    return isinstance(steps, list) and any(
        isinstance(step, dict)
        and isinstance(step.get("run"), str)
        and PRIVILEGED_COMMAND_RE.search(step["run"]) is not None
        for step in steps
    )


def job_needs(job: Any) -> set[str]:
    """Normalize one job's direct dependency ids."""
    if not isinstance(job, dict):
        return set()
    needs = job.get("needs", [])
    if isinstance(needs, str):
        return {needs}
    return (
        {value for value in needs if isinstance(value, str)} if isinstance(needs, list) else set()
    )


def protected_guard_prefix_errors(
    document: Any,
    relative: str,
    *,
    approved_checkout_ref: str,
    protected_action_ref: str,
    guard_name: str,
) -> list[str]:
    """Require each privileged job to own or depend on an exact verifier prefix."""
    if not isinstance(document, dict) or not isinstance(document.get("jobs"), dict):
        return [f"{relative} is privileged and has no executable protected-source guard"]
    errors: list[str] = []
    guarded_jobs: set[str] = set()
    expected_checkout_with = {
        "ref": "main",
        "fetch-depth": 1,
        "sparse-checkout": ".github/actions/verify-protected-workflow-source",
        "path": ".fdai-protected-workflow-verifier",
    }
    for job_name, job in document["jobs"].items():
        if not isinstance(job, dict) or not isinstance(job.get("steps"), list):
            continue
        steps = job["steps"]
        guard_indexes = [
            index
            for index, step in enumerate(steps)
            if isinstance(step, dict) and step.get("uses") == protected_action_ref
        ]
        if not guard_indexes:
            continue
        guarded_jobs.add(job_name)
        if len(guard_indexes) != 1 or guard_indexes[0] != 1 or len(steps) < 2:
            errors.append(
                f"{relative} job {job_name} must start with the exact protected-source "
                "checkout and verifier steps"
            )
            continue
        checkout, guard = steps[:2]
        allowed_condition = (
            "github.event_name != 'pull_request'"
            if relative == ".github/workflows/container-supply-chain.yml"
            and job_name == "select-images"
            else None
        )
        if not isinstance(checkout, dict) or (
            checkout.get("name") != "Checkout protected workflow verifier"
            or checkout.get("uses") != approved_checkout_ref
            or checkout.get("with") != expected_checkout_with
            or checkout.get("continue-on-error") not in {None, False}
            or checkout.get("if") != allowed_condition
        ):
            errors.append(f"{relative} job {job_name} has an invalid protected verifier checkout")
        guard_with = guard.get("with") if isinstance(guard, dict) else None
        if not isinstance(guard, dict) or (
            guard.get("name") != guard_name
            or guard.get("uses") != protected_action_ref
            or not isinstance(guard_with, dict)
            or not isinstance(guard_with.get("target-commit-sha"), str)
            or guard_with.get("workflow-path") != relative
            or guard_with.get("origin-url")
            != "${{ github.server_url }}/${{ github.repository }}.git"
            or guard_with.get("github-token") != "${{ github.token }}"
            or guard.get("continue-on-error") not in {None, False}
            or guard.get("if") != allowed_condition
        ):
            errors.append(f"{relative} job {job_name} has an invalid protected-source verifier")
    if not guarded_jobs:
        errors.append(f"{relative} is privileged and has no executable protected-source guard")
        return errors
    jobs = document["jobs"]
    default_permissions = document.get("permissions")
    for job_name, job in jobs.items():
        if not job_is_privileged(job, default_permissions) or job_name in guarded_jobs:
            continue
        pending = list(job_needs(job))
        visited: set[str] = set()
        protected_by_dependency = False
        while pending:
            dependency = pending.pop()
            if dependency in visited:
                continue
            visited.add(dependency)
            if dependency in guarded_jobs:
                protected_by_dependency = True
                break
            pending.extend(job_needs(jobs.get(dependency)))
        if not protected_by_dependency:
            errors.append(f"{relative} privileged job {job_name} has no guarded needs dependency")
    return errors


def protected_action_source_errors(content: str, expected_digest: str) -> list[str]:
    """Validate the exact reviewed verifier source and its critical commands."""
    actual_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    errors = []
    if actual_digest != expected_digest:
        errors.append(
            "verify-protected-workflow-source/action.yml digest differs from the reviewed source"
        )
    required_fragments = (
        "+refs/heads/main:refs/remotes/origin/main",
        'merge-base --is-ancestor "$TARGET_COMMIT_SHA"',
        '"$TARGET_COMMIT_SHA:$PROTECTED_WORKFLOW_PATH"',
        '"refs/remotes/origin/main:$PROTECTED_WORKFLOW_PATH"',
        "diff --quiet",
    )
    errors.extend(
        f"verify-protected-workflow-source/action.yml lacks protected-source guard: {fragment}"
        for fragment in required_fragments
        if fragment not in content
    )
    return errors


def validate_privileged_workflow_guards(
    root: Path,
    workflow_paths: tuple[Path, ...],
    *,
    approved_actions: dict[str, tuple[str, str]],
    protected_action_ref: str,
    guard_name: str,
    expected_verifier_digest: str,
) -> list[str]:
    """Validate protected-source admission for every privileged workflow."""
    errors: list[str] = []
    action_path = root / ".github" / "actions" / "verify-protected-workflow-source" / "action.yml"
    action = action_path.read_text(encoding="utf-8") if action_path.is_file() else ""
    action_checked = False
    approved_github_script_ref = (
        f"actions/github-script@{approved_actions['actions/github-script'][0]}"
    )
    approved_checkout_ref = f"actions/checkout@{approved_actions['actions/checkout'][0]}"
    for path in workflow_paths:
        content = path.read_text(encoding="utf-8")
        if not is_privileged_workflow(content):
            continue
        relative = path.relative_to(root).as_posix()
        document = yaml.safe_load(content)
        if is_event_scoped_issue_mutation(
            document,
            approved_github_script_ref=approved_github_script_ref,
        ):
            continue
        errors.extend(dispatch_guard_errors(document, relative))
        guard_errors = protected_guard_prefix_errors(
            document,
            relative,
            approved_checkout_ref=approved_checkout_ref,
            protected_action_ref=protected_action_ref,
            guard_name=guard_name,
        )
        errors.extend(guard_errors)
        if not guard_errors and not action_checked:
            errors.extend(protected_action_source_errors(action, expected_verifier_digest))
            action_checked = True
    return errors
