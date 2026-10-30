"""Exact opt-in CI pool routing; no deployment or activation authority."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

CI = ".github/workflows/ci.yml"
CONTAINER = ".github/workflows/container-supply-chain.yml"
VALIDATION_WORKFLOWS = (CI, CONTAINER)
LEGACY_RUNNERS = {
    "python-tests-ssd": ["self-hosted", "Linux", "X64", "fdai-ci", "fdai-ci-ssd"],
    "python-tests-elastic": ["self-hosted", "Linux", "X64", "fdai-ci", "fdai-ci-aca"],
}
CONTAINER_VALIDATION_ROLES = {
    "ci-admission": "control",
    "select-images": "control",
    "pr-build-scan": "docker",
    "required": "control",
}
CONTAINER_ROLES = {**CONTAINER_VALIDATION_ROLES, "build-scan-attest": "docker"}


def runner_expression(
    labels: list[str], fallback: list[str] | None = None, *, pr_only: bool = False
) -> str:
    """Keep disabled/unset routing exact, with a separate native PR approval gate."""
    condition = "vars.FDAI_CI_POOLS_ENABLED == 'true'"
    if pr_only:
        condition += " && github.event_name == 'pull_request'"
    selected = json.dumps(labels, separators=(",", ":"))
    old = json.dumps(fallback or ["ubuntu-24.04"], separators=(",", ":"))
    return "${{ " + condition + " && fromJSON('" + selected + "') || fromJSON('" + old + "') }}"


def approved_container_runner(job_name: str, runner: Any) -> bool:
    """Allow exact isolated validation routes, never publication authority or arbitrary labels."""
    pool = CONTAINER_VALIDATION_ROLES.get(job_name)
    if pool is None:
        return False
    labels = ["self-hosted", "Linux", "X64", f"fdai-ci-{pool}"]
    return isinstance(runner, str) and runner == runner_expression(labels)


def job_routes(policy: dict[str, Any], workflow: str) -> dict[str, str]:
    if workflow == CI:
        return dict(policy["jobs"])
    if workflow == CONTAINER:
        return dict(policy["workflow_jobs"][CONTAINER])
    raise ValueError("workflow is outside CI validation routing")


def routing_errors(policy: dict[str, Any], documents: dict[str, Any]) -> list[str]:
    """Account for CI image publication without treating CI admission as publication authority."""
    errors: list[str] = []
    if set(documents) != set(VALIDATION_WORKFLOWS):
        return ["complete CI validation workflow inventory required"]
    if policy.get("mode") != "plan":
        errors.append("routing policy cannot activate workers")
    if policy.get("workflow_jobs", {}).get(CONTAINER) != CONTAINER_ROLES:
        errors.append("container CI job inventory differs from approved roles")
    for path in VALIDATION_WORKFLOWS:
        jobs = documents[path]["jobs"]
        routes = job_routes(policy, path)
        if set(jobs) != set(routes):
            errors.append(f"{path}: complete job routing inventory required")
            continue
        for name, pool in routes.items():
            job = jobs[name]
            expected = runner_expression(
                policy["pools"][pool]["labels"],
                LEGACY_RUNNERS.get(name) if path == CI else None,
            )
            if job.get("runs-on") != expected:
                errors.append(f"{path}:{name}: incorrect opt-in {pool} route")
            publisher = path == CONTAINER and name == "build-scan-attest"
            if name != "ci-admission" and not publisher:
                needs = job.get("needs", [])
                if isinstance(needs, str):
                    needs = [needs]
                if "ci-admission" not in needs:
                    errors.append(f"{path}:{name}: direct source admission dependency required")
            docker = bool(job.get("services")) or any(
                str(step.get("uses", "")).startswith("docker/") for step in job.get("steps", [])
            )
            if docker and (pool != "docker" or not policy["pools"][pool]["docker"]):
                errors.append(f"{path}:{name}: Docker VM pool required")
    regression = documents[CI]["jobs"]
    for name in ("python-tests", "python-tests-ssd"):
        if "vars.FDAI_CI_POOLS_ENABLED != 'true'" not in str(regression[name].get("if")):
            errors.append(f"{name}: legacy suite must be disabled by the full pool flag")
    if regression["python-tests-elastic"]["strategy"]["matrix"]["shard"] != list(range(1, 9)):
        errors.append("elastic regression must retain all eight shards")
    return errors


def main() -> int:
    policy = json.loads(Path("config/ci-runner-pools.json").read_text())
    documents = {path: yaml.safe_load(Path(path).read_text()) for path in VALIDATION_WORKFLOWS}
    errors = routing_errors(policy, documents)
    for error in errors:
        print(error)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
