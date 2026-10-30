"""Offline adversarial contracts for the additive, CI-only source admission."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import urllib.error
from dataclasses import replace
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import Mock

import pytest
import yaml
from scripts.quality.ci import workflow_security_contracts as security

ROOT = Path(__file__).resolve().parents[3]
ACTION = ROOT / ".github/actions/verify-ci-runner-source"
WORKFLOW = ".github/workflows/ci.yml"
TARGET, HEAD, BASE, MAIN = (character * 40 for character in "abcd")
CHECKOUT = "actions/checkout@" + "e" * 40
PRODUCTION = "./.fdai-protected-workflow-verifier/.github/actions/verify-protected-workflow-source"


@pytest.fixture(scope="module")
def verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_candidate_verifier", ACTION / "verify.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def evidence(verifier: ModuleType) -> tuple[Any, Any, Any]:
    repository = {"id": 101, "full_name": "example/project", "default_branch": "main"}
    actor = {"id": 202, "login": "contributor"}
    context = verifier.Context(
        repository="example/project",
        repository_id=101,
        run_id=303,
        run_attempt=1,
        event_name="pull_request",
        ref="refs/pull/42/merge",
        sha=TARGET,
        workflow_ref=f"example/project/{WORKFLOW}@refs/pull/42/merge",
        workflow_sha=TARGET,
        actor="contributor",
        actor_id=202,
        triggering_actor="contributor",
        target_sha=TARGET,
        workflow_path=WORKFLOW,
        origin_url="https://github.com/example/project.git",
    )
    run = {
        "id": 303,
        "run_attempt": 1,
        "event": "pull_request",
        "repository": repository.copy(),
        "path": WORKFLOW,
        "workflow_id": 404,
        "head_sha": HEAD,
        "head_branch": "topic",
        "actor": actor.copy(),
        "triggering_actor": actor.copy(),
        "status": "in_progress",
    }
    pr = {
        "number": 42,
        "state": "open",
        "merged": False,
        "merge_commit_sha": TARGET,
        "base": {"sha": BASE, "ref": "main", "repo": repository.copy()},
        "head": {"sha": HEAD, "ref": "topic", "repo": repository.copy()},
    }
    api = verifier.ApiEvidence(
        repository=repository,
        run=run,
        workflow={"id": 404, "path": WORKFLOW, "state": "active"},
        main={"name": "main", "protected": True, "commit": {"sha": MAIN}},
        pull_request=pr,
        permission={"permission": "write", "user": actor.copy()},
    )
    git = verifier.GitEvidence(MAIN, TARGET, True, False, (BASE, HEAD), HEAD, TARGET)
    return context, api, git


def test_pr_merge_sha_is_not_run_head_sha(
    verifier: ModuleType, evidence: tuple[Any, Any, Any]
) -> None:
    context, api, git = evidence
    assert context.sha != api.run["head_sha"]
    verifier.admit(context, replace(api, permission=None), git)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository_id", 999),
        ("repository", "other/project"),
        ("origin_url", "https://example.com/example/project.git"),
        ("origin_url", "https://token@github.com/example/project.git"),
        ("workflow_path", ".github/workflows/deploy.yml"),
        ("workflow_path", "/.github/workflows/ci.yml"),
        ("ref", "refs/pull/42/head"),
        ("ref", "refs/heads/topic"),
        ("ref", "refs/pull/042/merge"),
        ("target_sha", HEAD),
        ("sha", HEAD),
        ("workflow_sha", HEAD),
        ("target_sha", "--upload-pack=bad"),
        ("workflow_ref", f"other/project/{WORKFLOW}@refs/pull/42/merge"),
        ("event_name", "pull_request_target"),
        ("actor", "other"),
        ("actor_id", 999),
        ("triggering_actor", "other"),
        ("run_id", 999),
        ("run_attempt", 2),
    ],
)
def test_wrong_context_denies(
    verifier: ModuleType, evidence: tuple[Any, Any, Any], field: str, value: Any
) -> None:
    context, api, git = evidence
    with pytest.raises(verifier.AdmissionDeniedError):
        verifier.admit(replace(context, **{field: value}), api, git)


@pytest.mark.parametrize(
    ("section", "path", "value"),
    [
        ("repository", ("id",), 999),
        ("repository", ("default_branch",), "topic"),
        ("run", ("id",), 999),
        ("run", ("run_attempt",), 2),
        ("run", ("repository", "id"), 999),
        ("run", ("repository", "full_name"), "other/project"),
        ("run", ("event",), "pull_request_target"),
        ("run", ("status",), "action_required"),
        ("run", ("path",), ".github/workflows/deploy.yml"),
        ("run", ("actor", "id"), 999),
        ("run", ("triggering_actor", "login"), "other"),
        ("run", ("head_sha",), TARGET),
        ("run", ("head_branch",), "wrong"),
        ("workflow", ("id",), 999),
        ("workflow", ("state",), "disabled_manually"),
        ("workflow", ("path",), ".github/workflows/deploy.yml"),
        ("main", ("protected",), False),
        ("main", ("commit", "sha"), BASE),
        ("pull_request", ("number",), 43),
        ("pull_request", ("state",), "closed"),
        ("pull_request", ("merged",), True),
        ("pull_request", ("head", "sha"), MAIN),
        ("pull_request", ("base", "repo", "id"), 999),
        ("pull_request", ("base", "repo", "full_name"), "other/project"),
        ("pull_request", ("base", "ref"), "topic"),
        ("pull_request", ("merge_commit_sha",), HEAD),
        ("pull_request", ("head", "repo", "full_name"), "other/project"),
    ],
)
def test_wrong_api_bindings_and_stale_pr_head_deny(
    verifier: ModuleType,
    evidence: tuple[Any, Any, Any],
    section: str,
    path: tuple[str, ...],
    value: Any,
) -> None:
    context, api, git = evidence
    node = getattr(api, section)
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(verifier.AdmissionDeniedError):
        verifier.admit(context, api, git)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_sha", HEAD),
        ("main_sha", BASE),
        ("head_sha", MAIN),
        ("merge_sha", HEAD),
        ("parents", (HEAD, BASE)),
        ("parents", (BASE, MAIN)),
        ("parents", (BASE, HEAD, MAIN)),
        ("parents", (BASE,)),
    ],
)
def test_wrong_git_objects_deny(
    verifier: ModuleType, evidence: tuple[Any, Any, Any], field: str, value: Any
) -> None:
    context, api, git = evidence
    with pytest.raises(verifier.AdmissionDeniedError):
        verifier.admit(context, api, replace(git, **{field: value}))


@pytest.mark.parametrize("permission", ["write", "maintain", "admin"])
def test_current_writer_can_edit_same_repository_workflow(
    verifier: ModuleType, evidence: tuple[Any, Any, Any], permission: str
) -> None:
    context, api, git = evidence
    api.permission["permission"] = permission
    # Association is deliberately irrelevant, even when it claims ownership.
    api.pull_request["author_association"] = "NONE"
    verifier.admit(context, api, replace(git, workflow_equal=False))


@pytest.mark.parametrize("permission", ["read", "triage", "none", "", None])
def test_association_does_not_authorize_workflow_edit(
    verifier: ModuleType, evidence: tuple[Any, Any, Any], permission: Any
) -> None:
    context, api, git = evidence
    api.permission["permission"] = permission
    api.pull_request["author_association"] = "OWNER"
    with pytest.raises(verifier.AdmissionDeniedError, match="current repository write permission"):
        verifier.admit(context, api, replace(git, workflow_equal=False))


def test_rerunner_permission_cannot_replace_current_effective_actor_permission(
    verifier: ModuleType, evidence: tuple[Any, Any, Any]
) -> None:
    context, api, git = evidence
    api.run["triggering_actor"] = {"id": 909, "login": "maintainer"}
    context = replace(context, triggering_actor="maintainer")
    api.permission["user"] = {"id": 909, "login": "maintainer"}
    with pytest.raises(verifier.AdmissionDeniedError):
        verifier.admit(context, api, replace(git, workflow_equal=False))
    api.permission["user"] = {"id": 202, "login": "contributor"}
    verifier.admit(context, api, replace(git, workflow_equal=False))


@pytest.mark.parametrize("permission", ["read", "write", "maintain", "admin"])
@pytest.mark.parametrize("workflow_equal", [False, True])
def test_external_workflow_equality_cannot_be_overridden_by_actor_permission(
    verifier: ModuleType,
    evidence: tuple[Any, Any, Any],
    permission: str,
    workflow_equal: bool,
) -> None:
    context, api, git = evidence
    api.pull_request["head"]["repo"] = {"id": 505, "full_name": "other/fork"}
    api.permission["permission"] = permission
    if workflow_equal:
        verifier.admit(context, api, git)
    else:
        with pytest.raises(
            verifier.AdmissionDeniedError, match="external PR workflow controls differ"
        ):
            verifier.admit(context, api, replace(git, workflow_equal=False))


@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/tags/v1.2.3"])
@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_main_and_release_keep_ancestry_and_workflow_equality(
    verifier: ModuleType, evidence: tuple[Any, Any, Any], ref: str, event: str
) -> None:
    context, api, git = evidence
    context = replace(
        context, ref=ref, event_name=event, workflow_ref=f"example/project/{WORKFLOW}@{ref}"
    )
    api.run.update(event=event, head_sha=TARGET, head_branch=ref.split("/")[-1])
    git = replace(git, ancestor=True, release_sha=TARGET)
    verifier.admit(context, api, git)
    for bad_git in (
        replace(git, ancestor=False),
        replace(git, workflow_equal=False),
    ):
        with pytest.raises(verifier.AdmissionDeniedError):
            verifier.admit(context, api, bad_git)
    if ref.startswith("refs/tags/"):
        with pytest.raises(verifier.AdmissionDeniedError):
            verifier.admit(context, api, replace(git, release_sha=HEAD))


@pytest.mark.parametrize("section", ["repository", "run", "workflow", "main", "pull_request"])
@pytest.mark.parametrize("malformed", [None, [], "provider-secret", True, {}])
def test_malformed_evidence_fails_closed(
    verifier: ModuleType, evidence: tuple[Any, Any, Any], section: str, malformed: Any
) -> None:
    context, api, git = evidence
    # The API client enforces top-level mappings before the pure helper.
    if not isinstance(malformed, dict):
        with pytest.raises(verifier.AdmissionDeniedError):
            verifier.record(malformed)
    else:
        with pytest.raises(verifier.AdmissionDeniedError):
            verifier.admit(context, replace(api, **{section: malformed}), git)


@pytest.mark.parametrize("status", [403, 404, 429, 503])
def test_provider_errors_are_redacted_without_retry(verifier: ModuleType, status: int) -> None:
    client = verifier.GitHub("example-token")
    client.opener = Mock()
    client.opener.open.side_effect = urllib.error.HTTPError(
        "https://api.github.com",
        status,
        "provider-secret",
        Message(),
        io.BytesIO(b"provider-secret"),
    )
    with pytest.raises(verifier.AdmissionDeniedError, match="^GitHub API request failed$"):
        client.get("/repos/example/project")
    assert client.opener.open.call_count == 1


@pytest.mark.parametrize("body", [b"not-json provider-secret", b"[]", b"null", b"true", b"{}"])
def test_api_output_requires_json_mapping(verifier: ModuleType, body: bytes) -> None:
    client = verifier.GitHub("example-token")
    response = Mock(status=200)
    response.read.return_value = body
    client.opener = Mock()
    client.opener.open.return_value.__enter__ = Mock(return_value=response)
    client.opener.open.return_value.__exit__ = Mock(return_value=False)
    if body == b"{}":
        assert client.get("/repos/example/project") == {}
    else:
        with pytest.raises(verifier.AdmissionDeniedError) as failure:
            client.get("/repos/example/project")
        assert "provider-secret" not in str(failure.value)
    request = client.opener.open.call_args.args[0]
    assert request.full_url == "https://api.github.com/repos/example/project"
    assert request.get_header("Authorization") == "Bearer example-token"


def test_api_redirects_are_denied(verifier: ModuleType) -> None:
    with pytest.raises(verifier.AdmissionDeniedError, match="GitHub API request failed"):
        verifier.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")


def test_client_observes_current_pr_after_fetching_refs(
    verifier: ModuleType, evidence: tuple[Any, Any, Any]
) -> None:
    context, api, git = evidence
    events: list[str] = []
    documents = {
        "/repos/example/project": api.repository,
        "/repos/example/project/actions/runs/303": api.run,
        "/repos/example/project/actions/workflows/404": api.workflow,
        "/repos/example/project/branches/main": api.main,
        "/repos/example/project/pulls/42": api.pull_request,
    }

    def get(path: str) -> Any:
        events.append(path)
        return documents[path]

    def fetch(unused: Any) -> Any:
        events.append("fetch")
        api.pull_request["head"]["sha"] = MAIN
        return git

    with pytest.raises(verifier.AdmissionDeniedError, match="stale PR head"):
        verifier.verify(context, Mock(get=get), Mock(evidence=fetch))
    assert events.index("fetch") < events.index("/repos/example/project/pulls/42")


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize("workflow_equal", [False, True])
def test_client_queries_permission_only_for_same_repository_workflow_changes(
    verifier: ModuleType,
    evidence: tuple[Any, Any, Any],
    external: bool,
    workflow_equal: bool,
) -> None:
    context, api, git = evidence
    if external:
        api.pull_request["head"]["repo"] = {"id": 505, "full_name": "other/fork"}
    documents = {
        "/repos/example/project": api.repository,
        "/repos/example/project/actions/runs/303": api.run,
        "/repos/example/project/actions/workflows/404": api.workflow,
        "/repos/example/project/branches/main": api.main,
        "/repos/example/project/pulls/42": api.pull_request,
        "/repos/example/project/collaborators/contributor/permission": api.permission,
    }
    client = Mock()
    client.get.side_effect = documents.__getitem__
    git_client = Mock(evidence=Mock(return_value=replace(git, workflow_equal=workflow_equal)))
    if external and not workflow_equal:
        with pytest.raises(verifier.AdmissionDeniedError):
            verifier.verify(context, client, git_client)
    else:
        verifier.verify(context, client, git_client)
    permission_calls = [
        call for call in client.get.call_args_list if call.args[0].endswith("/permission")
    ]
    assert len(permission_calls) == (0 if external or workflow_equal else 1)


def test_git_uses_only_fixed_plumbing_and_environment_auth(
    verifier: ModuleType, evidence: tuple[Any, Any, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    context, _, _ = evidence
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((args, kwargs))
        if "rev-parse" in args:
            ref = args[-1]
            sha = MAIN if "/main^" in ref else HEAD if "/head^" in ref else TARGET
            output = sha.encode()
        elif "cat-file" in args:
            output = b"trusted workflow"
        elif "rev-list" in args:
            output = f"{TARGET} {BASE} {HEAD}".encode()
        else:
            output = b""
        return subprocess.CompletedProcess(args, 0, output, b"")

    monkeypatch.setattr(verifier.subprocess, "run", run)
    git = verifier.Git("example-repo", "example-token")
    result = git.evidence(context)
    assert result.parents == (BASE, HEAD)
    assert result.head_sha == HEAD and result.merge_sha == TARGET
    assert result.workflow_equal
    serialized = json.dumps([call[0] for call in calls])
    assert "example-token" not in serialized
    assert not any(command in serialized for command in ["checkout", "config --file", "clone"])
    fetch = next(args for args, _ in calls if "fetch" in args)
    assert "+refs/pull/42/merge:refs/admission/merge" in fetch
    assert "+refs/pull/42/head:refs/admission/head" in fetch
    for _, kwargs in calls:
        assert kwargs["env"]["GIT_CONFIG_GLOBAL"] == verifier.os.devnull
        assert kwargs["env"]["GIT_NO_REPLACE_OBJECTS"] == "1"
        assert "AUTHORIZATION: basic " in kwargs["env"]["GIT_CONFIG_VALUE_0"]
        assert kwargs["timeout"] == 60 and kwargs["check"] is False


def test_git_errors_never_expose_provider_output(
    verifier: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 128, b"", b"provider-secret")),
    )
    with pytest.raises(verifier.AdmissionDeniedError, match="^git evidence unavailable$"):
        verifier.Git("example-repo", "example-token")


def candidate_job() -> dict[str, Any]:
    return {
        "runs-on": "ubuntu-24.04",
        "steps": [
            {
                "name": "Checkout CI source verifier",
                "uses": CHECKOUT,
                "with": {
                    "ref": "main",
                    "fetch-depth": 1,
                    "sparse-checkout": ".github/actions/verify-ci-runner-source",
                    "path": ".fdai-ci-source-verifier",
                    "persist-credentials": False,
                },
            },
            {
                "id": "source",
                "name": "Verify CI candidate source",
                "uses": security.CI_CANDIDATE_ACTION_REF,
                "with": {
                    "target-commit-sha": "${{ github.sha }}",
                    "workflow-path": WORKFLOW,
                    "origin-url": "${{ github.server_url }}/${{ github.repository }}.git",
                    "github-token": "${{ github.token }}",
                },
            },
            {"run": "echo candidate"},
        ],
    }


def candidate_workflow() -> dict[str, Any]:
    required = candidate_job()
    required.update({"if": "always()", "needs": ["guard"]})
    return {
        "on": {"push": {"branches": ["main"]}, "pull_request": None},
        "permissions": {"contents": "read"},
        "jobs": {
            "guard": candidate_job(),
            "privileged": {"runs-on": "self-hosted", "needs": "guard", "steps": [{"run": "true"}]},
            "required": required,
        },
    }


def prefix_errors(document: dict[str, Any], path: str = WORKFLOW) -> list[str]:
    return security.protected_guard_prefix_errors(
        document,
        path,
        approved_checkout_ref=CHECKOUT,
        protected_action_ref=PRODUCTION,
        guard_name="Verify protected workflow source",
    )


def test_additive_ci_prefix_accepts_guarded_privilege_without_exemption() -> None:
    document = candidate_workflow()
    document["jobs"]["privileged"]["permissions"] = {"contents": "write"}
    assert prefix_errors(document) == []


@pytest.mark.parametrize(
    ("step", "key", "value"),
    [
        (0, "uses", "actions/checkout@main"),
        (0, "with.ref", "${{ github.sha }}"),
        (0, "with.fetch-depth", 0),
        (0, "with.sparse-checkout", "."),
        (0, "with.path", "."),
        (0, "with.persist-credentials", True),
        (0, "if", "always()"),
        (0, "continue-on-error", True),
        (0, "run", "echo candidate"),
        (0, "env", {"GIT_CONFIG_COUNT": "2"}),
        (1, "name", "Verify protected workflow source"),
        (1, "with.target-commit-sha", "${{ inputs.commit_sha }}"),
        (1, "with.target-commit-sha", "${{ github.event.pull_request.head.sha }}"),
        (1, "with.workflow-path", ".github/workflows/deploy.yml"),
        (1, "with.origin-url", "https://example.com/project.git"),
        (1, "with.github-token", "${{ secrets.PRIVILEGED_TOKEN }}"),
        (1, "continue-on-error", True),
        (1, "if", "github.event_name != 'pull_request'"),
    ],
)
def test_bad_candidate_prefix_rejected(step: int, key: str, value: Any) -> None:
    document = candidate_workflow()
    node = document["jobs"]["guard"]["steps"][step]
    parts = key.split(".")
    if len(parts) == 2:
        node = node[parts[0]]
    node[parts[-1]] = value
    assert prefix_errors(document)


@pytest.mark.parametrize("position", [0, 1])
def test_candidate_code_cannot_precede_guard(position: int) -> None:
    document = candidate_workflow()
    document["jobs"]["guard"]["steps"].insert(position, {"run": "echo candidate"})
    assert prefix_errors(document)


@pytest.mark.parametrize(
    ("job", "key", "value"),
    [
        ("guard", "container", "example/image"),
        ("guard", "services", {"db": {"image": "postgres"}}),
        ("guard", "continue-on-error", True),
        ("privileged", "needs", []),
        ("privileged", "needs", "required-indirect"),
        ("privileged", "if", "always()"),
        ("privileged", "if", "failure()"),
        ("privileged", "if", "success() || github.event_name == 'pull_request'"),
        ("required", "if", "success()"),
        ("required", "continue-on-error", True),
        ("required", "services", {"db": {"image": "postgres"}}),
    ],
)
def test_job_boundary_rejects_bypasses(job: str, key: str, value: Any) -> None:
    document = candidate_workflow()
    document["jobs"][job][key] = value
    assert prefix_errors(document)


def test_required_cannot_be_skip_neutral_by_only_depending_on_guard() -> None:
    document = candidate_workflow()
    document["jobs"]["required"]["steps"] = [{"run": "true"}]
    assert any("required job must own" in error for error in prefix_errors(document))


@pytest.mark.parametrize(
    "condition", ["always()", "failure()", "cancelled()", "success() || always()"]
)
@pytest.mark.parametrize("kind", ["run", "uses"])
def test_terminal_steps_cannot_override_verifier_failure(condition: str, kind: str) -> None:
    document = candidate_workflow()
    step = {"if": condition, kind: "echo candidate" if kind == "run" else "example/action@v1"}
    document["jobs"]["guard"]["steps"].append(step)
    assert prefix_errors(document)
    step["if"] = f"({condition}) && steps.source.outcome == 'success'"
    assert prefix_errors(document) == []


@pytest.mark.parametrize("path", [".github/workflows/deploy.yml", "/.github/workflows/ci.yml"])
def test_candidate_guard_is_ci_only(path: str) -> None:
    assert prefix_errors(candidate_workflow(), path) == [
        f"{path} cannot use the CI-only candidate verifier"
    ]


def test_existing_validation_hook_recognizes_new_guard_without_wiring_workflow(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / WORKFLOW
    workflow.parent.mkdir(parents=True)
    workflow.write_text(yaml.safe_dump(candidate_workflow()), encoding="utf-8")
    assert (
        security.validate_privileged_workflow_guards(
            tmp_path,
            (workflow,),
            approved_actions={
                "actions/checkout": ("e" * 40, "example"),
                "actions/github-script": ("f" * 40, "example"),
            },
            protected_action_ref=PRODUCTION,
            guard_name="Verify protected workflow source",
            expected_verifier_digest="unused-for-ci-candidate",
        )
        == []
    )


def test_composite_runs_only_its_standalone_trusted_script() -> None:
    action = yaml.safe_load((ACTION / "action.yml").read_text(encoding="utf-8"))
    assert action["name"] == "Verify CI candidate source"
    assert set(action["inputs"]) == {
        "target-commit-sha",
        "workflow-path",
        "origin-url",
        "github-token",
    }
    assert action["runs"]["using"] == "composite"
    (step,) = action["runs"]["steps"]
    assert step["run"] == 'python3 -I "$CI_VERIFIER_PATH/verify.py"'
    assert step["env"]["CI_VERIFIER_PATH"] == "${{ github.action_path }}"
    assert step["env"]["CI_GITHUB_TOKEN"] == "${{ inputs.github-token }}"
    assert "CI_GITHUB_TOKEN" not in step["run"]
    assert "scripts/quality" not in step["run"]
