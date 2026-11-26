"""Normal fallback routes and an independently authorized, pre-cutover canary path."""

from __future__ import annotations

import ast
import copy
import itertools
import json
import os
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from scripts.quality.ci import ci_pool_routes as routes
from scripts.quality.ci import workflow_security_contracts as security

ROOT = Path(__file__).resolve().parents[3]
POLICY = json.loads((ROOT / "config/ci-runner-pools.json").read_text())
DOCUMENTS = {
    path: yaml.safe_load((ROOT / path).read_text()) for path in routes.VALIDATION_WORKFLOWS
}
PRODUCTION = "./.fdai-protected-workflow-verifier/.github/actions/verify-protected-workflow-source"
PIN = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"


def condition_value(condition: str, values: dict[str, Any]) -> bool:
    for key in sorted(values, key=len, reverse=True):
        condition = condition.replace(key, repr(values[key]))
    condition = " ".join(condition.split()).replace("&&", " and ").replace("||", " or ")
    condition = re.sub(r"!(?!=)", " not ", condition).replace("== true", "== True")

    def evaluate(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BoolOp):
            operands = [bool(evaluate(value)) for value in node.values]
            return all(operands) if isinstance(node.op, ast.And) else any(operands)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not evaluate(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id == "always" and not node.args
            return True
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = evaluate(node.left), evaluate(node.comparators[0])
            if isinstance(node.ops[0], ast.Eq):
                return left == right
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
        raise AssertionError("unexpected CI routing condition syntax")

    return bool(evaluate(ast.parse(condition.strip(), mode="eval").body))


def selected_runner(expression: Any, flag: str) -> list[str]:
    if isinstance(expression, list):
        return list(expression)
    match = re.fullmatch(
        r"\$\{\{ vars.FDAI_CI_POOLS_ENABLED == 'true' && fromJSON\('(.*?)'\) "
        r"\|\| fromJSON\('(.*?)'\) \}\}",
        expression,
    )
    assert match is not None
    return list(json.loads(match.group(1 if flag == "true" else 2)))


@pytest.mark.parametrize("flag", ["", "false", "true"])
def test_full_flag_routes_all_eligible_ci_without_hosted_and_preserves_old_fallback(
    flag: str,
) -> None:
    assert routes.routing_errors(POLICY, DOCUMENTS) == []
    for path, document in DOCUMENTS.items():
        for name, pool in routes.job_routes(POLICY, path).items():
            selected = selected_runner(document["jobs"][name]["runs-on"], flag)
            if path == routes.CONTAINER and name in routes.CANARY_ROLES:
                assert selected == POLICY["pools"][pool]["labels"]
            else:
                fallback = routes.LEGACY_RUNNERS.get(name, ["ubuntu-24.04"])
                assert selected == (POLICY["pools"][pool]["labels"] if flag == "true" else fallback)


def test_regression_truth_table_never_duplicates_or_drops_a_suite() -> None:
    jobs = DOCUMENTS[routes.CI]["jobs"]
    names = ("python-tests", "python-tests-ssd", "python-tests-elastic")
    for full, elastic, ssd, event, changed in itertools.product(
        ("", "false", "true"),
        ("false", "true"),
        ("false", "true"),
        ("pull_request", "push", "workflow_dispatch"),
        (False, True),
    ):
        values = {
            "vars.FDAI_CI_POOLS_ENABLED": full,
            "vars.FDAI_CI_ELASTIC_RUNNER_ENABLED": elastic,
            "vars.FDAI_CI_SSD_RUNNER_ENABLED": ssd,
            "github.event_name": event,
            "github.ref": "refs/pull/42/merge" if event == "pull_request" else "refs/heads/main",
            "needs.changes.outputs.python": "true" if changed else "false",
        }
        selected = [name for name in names if condition_value(jobs[name]["if"], values)]
        if not changed:
            assert selected == []
            continue
        expected = "python-tests"
        if full == "true" or (event != "pull_request" and elastic == "true"):
            expected = "python-tests-elastic"
        elif event != "pull_request" and ssd == "true":
            expected = "python-tests-ssd"
        assert selected == [expected], values
        assert len(jobs[expected]["strategy"]["matrix"]["shard"]) == (
            8 if expected == "python-tests-elastic" else 4
        )


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch"])
@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/heads/other"])
def test_canary_is_manual_main_only_and_never_runs_normal_jobs(
    mode: bool, event: str, ref: str
) -> None:
    jobs = DOCUMENTS[routes.CONTAINER]["jobs"]
    values = {
        "inputs.canary": mode,
        "github.event_name": event,
        "github.ref": ref,
        "needs.canary-plan.outputs.pool": "general",
        "needs.select-images.outputs.has_images": "true",
    }
    active = mode and event == "workflow_dispatch" and ref == "refs/heads/main"
    assert condition_value(jobs["canary-plan"]["if"], values) is active
    assert condition_value(jobs["canary-results"]["if"], values) is active
    if active:
        for name in routes.CONTAINER_VALIDATION_ROLES:
            assert condition_value(jobs[name]["if"], values) is False
        assert condition_value(jobs["build-scan-attest"]["if"], values) is False
        assert condition_value(jobs["canary-general"]["if"], values) is True
        assert condition_value(jobs["canary-docker"]["if"], values) is False
    assert DOCUMENTS[routes.CI]["jobs"]["required"]["if"] == "always()"


def test_canary_fixed_pool_and_production_prefix_do_not_need_the_global_flag() -> None:
    document = DOCUMENTS[routes.CONTAINER]
    for name, pool in routes.CANARY_ROLES.items():
        job = document["jobs"][name]
        assert job["runs-on"] == POLICY["pools"][pool]["labels"]
        assert job["steps"][1]["uses"] == PRODUCTION
        assert not any(
            step.get("uses") == security.CI_CANDIDATE_ACTION_REF for step in job["steps"]
        )
    assert document["concurrency"] == {
        "group": "ci-container-candidates-${{ github.run_id }}",
        "cancel-in-progress": False,
    }
    assert DOCUMENTS[routes.CI]["jobs"]["db-integration"]["services"]
    assert POLICY["jobs"]["db-integration"] == "docker"


def test_source_error_and_main_publisher_failure_are_not_skip_neutral() -> None:
    for path, document in DOCUMENTS.items():
        assert (
            security.protected_guard_prefix_errors(
                document,
                path,
                approved_checkout_ref=PIN,
                protected_action_ref=PRODUCTION,
                guard_name="Verify protected workflow source",
            )
            == []
        )
        required = document["jobs"]["required"]
        assert required["steps"][1]["name"] == "Verify CI candidate source"
        command = required["steps"][-1]["run"]
        body = command.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        for conclusion in ("failure", "cancelled", "skipped", "unknown"):
            values = {name: {"result": "success"} for name in required["needs"]}
            values["ci-admission"]["result"] = conclusion
            with patch.dict(os.environ, {"NEEDS_JSON": json.dumps(values)}):
                with pytest.raises(SystemExit):
                    exec(compile(body, "<required-ci-check>", "exec"), {})  # noqa: S102
        if path == routes.CONTAINER:
            values = {name: {"result": "success"} for name in required["needs"]}
            values["build-scan-attest"]["result"] = "failure"
            with patch.dict(os.environ, {"NEEDS_JSON": json.dumps(values)}):
                with pytest.raises(SystemExit):
                    exec(compile(body, "<required-publication-check>", "exec"), {})  # noqa: S102


def test_publisher_retains_main_only_production_authority_and_permissions() -> None:
    publisher = DOCUMENTS[routes.CONTAINER]["jobs"]["build-scan-attest"]
    assert publisher["needs"] == "select-images"
    assert publisher.get("environment") is None
    assert publisher["steps"][1]["uses"] == PRODUCTION
    assert publisher["permissions"] == {
        "contents": "read",
        "packages": "write",
        "attestations": "write",
        "id-token": "write",
    }
    assert "github.event_name == 'workflow_dispatch'" in publisher["if"]
    assert "github.ref == 'refs/heads/main'" in publisher["if"]


@pytest.mark.parametrize(
    "violation",
    [
        "publisher-ci-guard",
        "canary-ci-guard",
        "canary-hosted",
        "canary-pr",
        "canary-fast-fail",
        "canary-dynamic-pool",
        "canary-write-token",
        "cancel-busy",
        "fake-required-green",
        "publisher-on-canary",
        "canary-publish",
        "unclassified-job",
    ],
)
def test_routing_and_authority_boundaries_reject_bypasses(violation: str) -> None:
    documents = copy.deepcopy(DOCUMENTS)
    jobs = documents[routes.CONTAINER]["jobs"]
    if violation == "publisher-ci-guard":
        jobs["build-scan-attest"]["steps"][:2] = copy.deepcopy(jobs["ci-admission"]["steps"][:2])
    elif violation == "canary-ci-guard":
        jobs["canary-general"]["steps"][:2] = copy.deepcopy(jobs["ci-admission"]["steps"][:2])
    elif violation == "canary-hosted":
        jobs["canary-general"]["runs-on"] = "ubuntu-24.04"
    elif violation == "canary-pr":
        jobs["canary-plan"]["if"] = "github.event_name == 'pull_request'"
    elif violation == "canary-fast-fail":
        jobs["canary-general"]["strategy"]["fail-fast"] = True
    elif violation == "canary-dynamic-pool":
        jobs["canary-general"]["runs-on"] = "${{ inputs.canary_pool }}"
    elif violation == "canary-write-token":
        jobs["canary-results"]["permissions"]["id-token"] = "write"
    elif violation == "cancel-busy":
        documents[routes.CONTAINER]["concurrency"]["cancel-in-progress"] = True
    elif violation == "fake-required-green":
        jobs["required"]["if"] = "always()"
    elif violation == "publisher-on-canary":
        jobs["build-scan-attest"]["if"] = jobs["build-scan-attest"]["if"].replace(
            " && !inputs.canary", ""
        )
    elif violation == "canary-publish":
        jobs["canary-results"]["steps"].append(
            {
                "name": "publish",
                "uses": "actions/attest@untrusted",
            }
        )
    else:
        jobs["unclassified"] = {"runs-on": "ubuntu-24.04"}
    errors = routes.routing_errors(POLICY, documents)
    errors += security.protected_guard_prefix_errors(
        documents[routes.CONTAINER],
        routes.CONTAINER,
        approved_checkout_ref=PIN,
        protected_action_ref=PRODUCTION,
        guard_name="Verify protected workflow source",
    )
    assert errors
