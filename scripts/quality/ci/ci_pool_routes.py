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
CANARY_ROLES = {
    "canary-plan": "control",
    "canary-control": "control",
    "canary-general": "general",
    "canary-docker": "docker",
    "canary-results": "control",
}
CONTAINER_ROLES = {**CONTAINER_VALIDATION_ROLES, "build-scan-attest": "docker", **CANARY_ROLES}
CANARY_IF = (
    "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' "
    "&& inputs.canary == true"
)
NORMAL_ENTRY_IF = (
    "github.event_name == 'pull_request' || (github.event_name == 'workflow_dispatch' "
    "&& github.ref == 'refs/heads/main' && !inputs.canary)"
)
NORMAL_REQUIRED_IF = "always() && !(github.event_name == 'workflow_dispatch' && inputs.canary)"


def canary_errors(policy: dict[str, Any], document: dict[Any, Any]) -> list[str]:
    """Keep the pre-activation path fixed-pool, production-guarded and publication-free."""
    errors: list[str] = []
    jobs = document["jobs"]
    if document.get("concurrency") != {
        "group": "ci-container-candidates-${{ github.run_id }}",
        "cancel-in-progress": False,
    }:
        errors.append("container canary must never cancel an earlier run")
    triggers: Any = document.get("on", document.get(True, {}))
    inputs = triggers.get("workflow_dispatch", {}).get("inputs", {})
    if (
        inputs.get("canary", {}).get("type") != "boolean"
        or inputs.get("canary", {}).get("default") is not False
    ):
        errors.append("canary must default to disabled")
    expected_conditions = {
        "ci-admission": NORMAL_ENTRY_IF,
        "select-images": NORMAL_ENTRY_IF,
        "required": NORMAL_REQUIRED_IF,
        "pr-build-scan": (
            "github.event_name == 'pull_request' && "
            "needs.select-images.outputs.has_images == 'true'"
        ),
        "build-scan-attest": (
            "needs.select-images.outputs.has_images == 'true' && "
            "github.event_name == 'workflow_dispatch' && "
            "github.ref == 'refs/heads/main' && !inputs.canary"
        ),
    }
    expected_conditions.update({name: CANARY_IF for name in CANARY_ROLES})
    expected_conditions["canary-results"] = "always() && " + CANARY_IF
    for pool in ("control", "general", "docker"):
        expected_conditions[f"canary-{pool}"] += f" && needs.canary-plan.outputs.pool == '{pool}'"
    for name, condition in expected_conditions.items():
        if " ".join(str(jobs[name].get("if", "")).split()) != condition:
            errors.append(f"{name}: invalid canary/normal event boundary")
    for name, pool in CANARY_ROLES.items():
        job = jobs[name]
        expected_steps = ["Checkout protected canary tools"]
        if name == "canary-plan":
            expected_steps += ["Validate explicit canary inputs"]
        elif name == "canary-results":
            expected_steps += [
                "Download this attempt's observations",
                "Collect independently verified canary receipt",
                "Upload redacted canary receipt",
            ]
        else:
            expected_steps += [
                "Verify canary isolation and Docker runtime",
                "Hold pool canary capacity",
                "Upload canary observation",
            ]
        steps = job.get("steps", [])
        if [step.get("name") for step in steps[2:]] != expected_steps:
            errors.append(f"{name}: unexpected canary work or publication")
        if any(
            str(step.get("uses", "")).startswith(("actions/attest", "docker/", "azure/"))
            for step in steps
        ):
            errors.append(f"{name}: canary cannot publish or deploy")
        permissions = {"contents": "read"}
        if name == "canary-results":
            permissions["actions"] = "read"
        if job.get("permissions") != permissions:
            errors.append(f"{name}: canary must remain read-only")
        if name in {"canary-plan", "canary-results"}:
            continue
        strategy = job.get("strategy", {})
        if (
            strategy.get("fail-fast") is not False
            or strategy.get("max-parallel") != policy["pools"][pool]["maximum"]
            or strategy.get("matrix")
            != f"${{{{ fromJSON(needs.canary-plan.outputs.matrix_{pool}) }}}}"
            or job.get("needs") != "canary-plan"
        ):
            errors.append(f"{name}: invalid fixed-pool canary matrix")
    collector_needs = jobs["canary-results"].get("needs", [])
    if set(collector_needs) != set(CANARY_ROLES) - {"canary-results"}:
        errors.append("canary results must follow every canary job")
    return errors


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
            canary = path == CONTAINER and name in CANARY_ROLES
            expected = (
                policy["pools"][pool]["labels"]
                if canary
                else runner_expression(
                    policy["pools"][pool]["labels"],
                    LEGACY_RUNNERS.get(name) if path == CI else None,
                )
            )
            if job.get("runs-on") != expected:
                errors.append(f"{path}:{name}: incorrect opt-in {pool} route")
            publisher = path == CONTAINER and name == "build-scan-attest"
            if name != "ci-admission" and not publisher and not canary:
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
    if set(documents[CONTAINER]["jobs"]) == set(CONTAINER_ROLES):
        errors.extend(canary_errors(policy, documents[CONTAINER]))
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
