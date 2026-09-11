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
    r"az(?:\s+\S+){1,3}\s+(?:create|delete|deploy|import|restart|set|start|stop|update))\b"
)
SECRET_REF_RE = re.compile(r"\$\{\{\s*secrets(?:\.|\[['\"])([A-Za-z_][A-Za-z0-9_]*)(?:['\"]\])?")
BUILTIN_CONTEXT_NAMES = frozenset(("GITHUB_TOKEN",))
GITHUB_HOSTED_RUNNER_RE = re.compile(
    r"(?:ubuntu-(?:latest|\d{2}\.\d{2})(?:-arm)?"
    r"|windows-(?:latest|\d{4})"
    r"|macos-(?:latest|\d+(?:-large)?(?:-arm64)?))"
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
        elif isinstance(node, str):
            if "secrets[" in node:
                return True
            return any(
                secret_name not in BUILTIN_CONTEXT_NAMES
                for secret_name in SECRET_REF_RE.findall(node)
            )
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


def strip_outer_parentheses(expression: str) -> str:
    """Remove balanced parentheses that wrap an entire expression."""
    stripped = expression.strip()
    while stripped.startswith("(") and stripped.endswith(")"):
        depth = 0
        closes_at_end = False
        for index, character in enumerate(stripped):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    closes_at_end = index == len(stripped) - 1
                    break
        if not closes_at_end:
            break
        stripped = stripped[1:-1].strip()
    return stripped


def split_top_level_operator(expression: str, operator: str) -> list[str]:
    """Split an Actions condition on one operator outside parentheses."""
    clauses: list[str] = []
    start = 0
    depth = 0
    index = 0
    while index < len(expression) - 1:
        character = expression[index]
        if character == "(":
            depth += 1
        elif character == ")":
            depth = max(0, depth - 1)
        elif expression[index : index + 2] == operator and depth == 0:
            clauses.append(expression[start:index].strip())
            start = index + 2
            index += 1
        index += 1
    clauses.append(expression[start:].strip())
    return clauses


def dispatch_condition_is_protected(
    condition: Any,
    dispatch_triggers: set[str],
) -> bool:
    """Prove every top-level dispatch-capable clause requires protected main."""
    if not isinstance(condition, str):
        return False
    protected_main = "github.ref == 'refs/heads/main'"
    for raw_clause in split_top_level_operator(" ".join(condition.split()), "||"):
        clause = strip_outer_parentheses(raw_clause)
        event_matches = set(re.findall(r"github\.event_name\s*==\s*'([A-Za-z_]+)'", clause))
        if event_matches and not (event_matches & dispatch_triggers):
            continue
        conjuncts = {
            strip_outer_parentheses(value) for value in split_top_level_operator(clause, "&&")
        }
        if protected_main not in conjuncts:
            return False
        for trigger in event_matches & dispatch_triggers:
            if f"github.event_name == '{trigger}'" not in conjuncts:
                return False
    return True


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
        if not dispatch_condition_is_protected(condition, dispatch_triggers):
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
    if runner is None:
        return False
    if isinstance(runner, dict):
        return True
    if isinstance(runner, list):
        return len(runner) != 1 or runner_is_privileged(runner[0])
    return not isinstance(runner, str) or (
        "${{" in runner or GITHUB_HOSTED_RUNNER_RE.fullmatch(runner) is None
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


def condition_overrides_guard_failure(condition: Any) -> bool:
    """Return whether a condition may run after a failed dependency or step."""
    if not isinstance(condition, str):
        return False
    return any(
        token in condition
        for token in (
            "always()",
            "failure()",
            "cancelled()",
            "!cancelled()",
            "! success()",
            "!success()",
            "success() == false",
        )
    )


def condition_requires_prior_step(
    condition: Any,
    eligible_step_ids: set[str],
) -> bool:
    """Return whether a status override is fail-closed on a later step result."""
    if not isinstance(condition, str):
        return False
    referenced = set(
        re.findall(
            r"steps\.([A-Za-z0-9_-]+)\.(?:outcome|conclusion)\s*==\s*'success'",
            condition,
        )
    )
    referenced.update(
        re.findall(
            r"steps\.([A-Za-z0-9_-]+)\.outputs\.[A-Za-z0-9_-]+\s*==\s*'true'",
            condition,
        )
    )
    return bool(referenced & eligible_step_ids)


def condition_requires_guard_success(condition: Any, guard_id: Any) -> bool:
    """Return whether an override explicitly requires verifier success."""
    return (
        isinstance(condition, str)
        and isinstance(guard_id, str)
        and f"steps.{guard_id}.outcome == 'success'" in condition
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
        if job.get("container") is not None or job.get("services") is not None:
            errors.append(
                f"{relative} job {job_name} cannot run its verifier in a job container "
                "or with service containers"
            )
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
        guard_id = guard.get("id") if isinstance(guard, dict) else None
        allowed_targets = {
            "${{ github.sha }}",
            "${{ inputs.commit_sha }}",
            "${{ env.TARGET_COMMIT_SHA }}",
            "${{ inputs.commit_sha != '' && inputs.commit_sha || github.sha }}",
            "${{ github.event_name == 'workflow_dispatch' && inputs.commit_sha || github.sha }}",
        }
        if not isinstance(guard, dict) or (
            guard.get("name") != guard_name
            or guard.get("uses") != protected_action_ref
            or not isinstance(guard_with, dict)
            or guard_with.get("target-commit-sha") not in allowed_targets
            or guard_with.get("workflow-path") != relative
            or guard_with.get("origin-url")
            != "${{ github.server_url }}/${{ github.repository }}.git"
            or guard_with.get("github-token") != "${{ github.token }}"
            or guard.get("continue-on-error") not in {None, False}
            or guard.get("if") != allowed_condition
        ):
            errors.append(f"{relative} job {job_name} has an invalid protected-source verifier")
        post_verifier_ids: set[str] = set()
        for step in steps[2:]:
            condition = step.get("if") if isinstance(step, dict) else None
            if (
                isinstance(step, dict)
                and condition_overrides_guard_failure(condition)
                and isinstance(step.get("run"), str)
                and PRIVILEGED_COMMAND_RE.search(step["run"]) is not None
                and not condition_requires_prior_step(condition, post_verifier_ids)
            ):
                errors.append(
                    f"{relative} job {job_name} can execute a privileged step after "
                    "verifier failure"
                )
            if (
                isinstance(step, dict)
                and condition_overrides_guard_failure(condition)
                and "uses" in step
                and not condition_requires_guard_success(condition, guard_id)
            ):
                errors.append(
                    f"{relative} job {job_name} can execute an action after verifier failure"
                )
            if isinstance(step, dict) and isinstance(step.get("id"), str):
                post_verifier_ids.add(step["id"])
    if not guarded_jobs:
        errors.append(f"{relative} is privileged and has no executable protected-source guard")
        return errors
    jobs = document["jobs"]
    default_permissions = document.get("permissions")
    for job_name, job in jobs.items():
        if not job_is_privileged(job, default_permissions) or job_name in guarded_jobs:
            continue
        if condition_overrides_guard_failure(job.get("if")):
            errors.append(
                f"{relative} privileged job {job_name} can override guarded dependency failure"
            )
            continue
        if not (job_needs(job) & guarded_jobs):
            errors.append(
                f"{relative} privileged job {job_name} has no direct guarded needs dependency"
            )
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
        "workflow source ref must resolve to protected main or an immutable release tag",
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
