"""Trusted, standalone CI admission. Never import or execute candidate source."""

from __future__ import annotations

import base64
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WORKFLOWS = frozenset((".github/workflows/ci.yml", ".github/workflows/container-supply-chain.yml"))
SHA = re.compile(r"[0-9a-f]{40}")
LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*(?:\[bot\])?")


class AdmissionDeniedError(Exception):
    """A stable, redacted failure that must fail the guarding job."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AdmissionDeniedError(message)


def record(value: Any) -> dict[str, Any]:
    require(isinstance(value, dict), "invalid GitHub API evidence")
    return dict(value)


def identifier(value: Any) -> int:
    require(type(value) is int and value > 0, "invalid GitHub API evidence")
    return int(value)


def commit(value: Any) -> str:
    require(isinstance(value, str) and SHA.fullmatch(value) is not None, "invalid commit evidence")
    return str(value)


@dataclass(frozen=True)
class Context:
    repository: str
    repository_id: int
    run_id: int
    run_attempt: int
    event_name: str
    ref: str
    sha: str
    workflow_ref: str
    workflow_sha: str
    actor: str
    actor_id: int
    triggering_actor: str
    target_sha: str
    workflow_path: str
    origin_url: str

    def validate(self) -> None:
        require(
            re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository) is not None,
            "invalid repository binding",
        )
        for value in (self.repository_id, self.run_id, self.run_attempt, self.actor_id):
            identifier(value)
        require(
            LOGIN.fullmatch(self.actor) is not None
            and LOGIN.fullmatch(self.triggering_actor) is not None,
            "invalid actor binding",
        )
        require(self.workflow_path in WORKFLOWS, "CI workflow path required")
        require(
            self.origin_url == f"https://github.com/{self.repository}.git",
            "invalid repository origin",
        )
        require(
            commit(self.target_sha) == commit(self.sha) == commit(self.workflow_sha),
            "target must match this run and workflow revision",
        )
        require(
            self.workflow_ref == f"{self.repository}/{self.workflow_path}@{self.ref}",
            "invalid workflow ref binding",
        )
        if self.event_name == "pull_request":
            require(
                re.fullmatch(r"refs/pull/[1-9][0-9]*/merge", self.ref) is not None,
                "PR merge ref required",
            )
        else:
            require(
                self.event_name in {"push", "workflow_dispatch", "release"}
                and (
                    self.ref == "refs/heads/main"
                    or re.fullmatch(r"refs/tags/v[A-Za-z0-9._-]+", self.ref) is not None
                ),
                "protected main or release ref required",
            )

    @classmethod
    def from_env(cls) -> Context:
        values: dict[str, Any] = {}
        for field in cls.__dataclass_fields__:
            name = {"target_sha": "CI_TARGET_SHA"}.get(field, f"CI_{field.upper()}")
            value = os.environ.get(name, "")
            if field in {"repository_id", "run_id", "run_attempt", "actor_id"}:
                require(re.fullmatch(r"[1-9][0-9]*", value) is not None, "invalid run context")
                values[field] = int(value)
            else:
                values[field] = value
        context = cls(**values)
        context.validate()
        return context


@dataclass(frozen=True)
class ApiEvidence:
    repository: dict[str, Any]
    run: dict[str, Any]
    workflow: dict[str, Any]
    main: dict[str, Any]
    pull_request: dict[str, Any] | None = None
    permission: dict[str, Any] | None = None


@dataclass(frozen=True)
class GitEvidence:
    main_sha: str
    target_sha: str
    workflow_equal: bool
    ancestor: bool
    parents: tuple[str, ...] = ()
    head_sha: str | None = None
    merge_sha: str | None = None
    release_sha: str | None = None


def repository_matches(value: Any, context: Context) -> bool:
    repository = record(value)
    return (
        identifier(repository.get("id")) == context.repository_id
        and repository.get("full_name") == context.repository
    )


def actor_matches(value: Any, login: str, actor_id: int | None = None) -> bool:
    actor = record(value)
    observed_id = identifier(actor.get("id"))
    return actor.get("login") == login and (actor_id is None or observed_id == actor_id)


def admit(context: Context, api: ApiEvidence, git: GitEvidence) -> None:
    """Bind API identity and current source objects; permission never authorizes forks."""
    context.validate()
    require(repository_matches(api.repository, context), "repository binding mismatch")
    require(api.repository.get("default_branch") == "main", "protected main required")
    run = api.run
    require(
        identifier(run.get("id")) == context.run_id
        and identifier(run.get("run_attempt")) == context.run_attempt
        and run.get("event") == context.event_name
        and repository_matches(run.get("repository"), context)
        and run.get("path") == context.workflow_path
        and run.get("status") in {"queued", "in_progress"}
        and run.get("conclusion") is None
        and actor_matches(run.get("actor"), context.actor, context.actor_id)
        and actor_matches(run.get("triggering_actor"), context.triggering_actor),
        "workflow run binding mismatch",
    )
    require(
        identifier(api.workflow.get("id")) == identifier(run.get("workflow_id"))
        and api.workflow.get("path") == context.workflow_path
        and api.workflow.get("state") == "active",
        "workflow identity mismatch",
    )
    require(
        api.main.get("name") == "main"
        and api.main.get("protected") is True
        and commit(record(api.main.get("commit")).get("sha")) == commit(git.main_sha),
        "protected main binding mismatch",
    )
    require(commit(git.target_sha) == context.target_sha, "target object mismatch")
    if context.event_name != "pull_request":
        require(
            commit(run.get("head_sha")) == context.target_sha
            and run.get("head_branch")
            == context.ref.removeprefix("refs/heads/").removeprefix("refs/tags/"),
            "protected run revision mismatch",
        )
        require(git.ancestor is True, "target must be an ancestor of protected origin/main")
        require(git.workflow_equal is True, "workflow controls differ from protected origin/main")
        if context.ref.startswith("refs/tags/"):
            require(git.release_sha == context.target_sha, "release tag binding mismatch")
        return

    pr = record(api.pull_request)
    number = int(context.ref.split("/")[2])
    require(
        identifier(pr.get("number")) == number
        and pr.get("state") == "open"
        and pr.get("merged") is False,
        "current open PR required",
    )
    base, head = record(pr.get("base")), record(pr.get("head"))
    head_repo = record(head.get("repo"))
    head_repo_id = identifier(head_repo.get("id"))
    require(
        repository_matches(base.get("repo"), context) and base.get("ref") == "main",
        "PR base repository mismatch",
    )
    head_sha, base_sha = commit(head.get("sha")), commit(base.get("sha"))
    require(
        commit(run.get("head_sha")) == head_sha
        and isinstance(head.get("ref"), str)
        and bool(head["ref"])
        and run.get("head_branch") == head["ref"],
        "stale PR head or run binding",
    )
    require(
        commit(pr.get("merge_commit_sha")) == context.target_sha
        and git.merge_sha == context.target_sha
        and git.head_sha == head_sha
        and git.parents == (base_sha, head_sha),
        "PR merge object binding mismatch",
    )
    if head_repo_id == context.repository_id:
        require(repository_matches(head_repo, context), "PR head repository mismatch")
        if git.workflow_equal is not True:
            permission = record(api.permission)
            require(
                actor_matches(
                    permission.get("user"),
                    context.actor,
                    context.actor_id,
                )
                and permission.get("permission") in {"write", "maintain", "admin"},
                "workflow edits require current repository write permission",
            )
    else:
        # Native GitHub all_external_contributors approval remains a prerequisite
        # for starting this job; repository permissions never replace that gate.
        require(
            git.workflow_equal is True,
            "external PR workflow controls differ from protected origin/main",
        )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise AdmissionDeniedError("GitHub API request failed")


class GitHub:
    def __init__(self, token: str) -> None:
        require(bool(token) and "\n" not in token and "\r" not in token, "GitHub token required")
        self.token = token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"https://api.github.com{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "fdai-ci-source-admission",
            },
        )
        try:
            with self.opener.open(request, timeout=15) as response:
                require(response.status == 200, "GitHub API request failed")
                data = response.read(2_000_001)
            require(len(data) <= 2_000_000, "invalid GitHub API evidence")
            return record(json.loads(data))
        except (OSError, ValueError, urllib.error.HTTPError):
            raise AdmissionDeniedError("GitHub API request failed") from None


class Git:
    def __init__(self, directory: str, token: str) -> None:
        self.directory = directory
        auth = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
        self.env = {
            "PATH": os.defpath,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {auth}",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
        self.call("init", "--bare", "--template=")

    def call(
        self, *args: str, allow_difference: bool = False
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            result = subprocess.run(  # noqa: S603 - fixed plumbing, validated refs, no shell
                [
                    "/usr/bin/git",
                    "-c",
                    "credential.helper=",
                    "-c",
                    "http.followRedirects=false",
                    "-c",
                    f"core.hooksPath={os.devnull}",
                    "-C",
                    self.directory,
                    *args,
                ],
                env=self.env,
                capture_output=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            raise AdmissionDeniedError("git evidence unavailable") from None
        require(
            result.returncode == 0 or allow_difference and result.returncode == 1,
            "git evidence unavailable",
        )
        return result

    def resolve(self, ref: str) -> str:
        output = self.call("rev-parse", "--verify", f"{ref}^{{commit}}").stdout
        return commit(output.decode().strip())

    def evidence(self, context: Context) -> GitEvidence:
        refs = ["+refs/heads/main:refs/admission/main", context.target_sha]
        if context.event_name == "pull_request":
            prefix = context.ref.removesuffix("/merge")
            refs.extend(
                [
                    f"+{prefix}/merge:refs/admission/merge",
                    f"+{prefix}/head:refs/admission/head",
                ]
            )
        elif context.ref.startswith("refs/tags/"):
            refs.append(f"+{context.ref}:refs/admission/release")
        self.call("fetch", "--force", "--no-tags", "--", context.origin_url, *refs)
        target = self.resolve(context.target_sha)
        main = self.resolve("refs/admission/main")
        # Reading blob bytes rejects a missing workflow instead of treating two
        # missing paths as equality. No worktree or candidate config is loaded.
        equal = (
            self.call("cat-file", "blob", f"{target}:{context.workflow_path}").stdout
            == self.call("cat-file", "blob", f"{main}:{context.workflow_path}").stdout
        )
        ancestor = (
            self.call("merge-base", "--is-ancestor", target, main, allow_difference=True).returncode
            == 0
        )
        parents = tuple(
            commit(parent)
            for parent in self.call("rev-list", "--parents", "-n", "1", target)
            .stdout.decode()
            .split()[1:]
        )
        is_pr = context.event_name == "pull_request"
        return GitEvidence(
            main,
            target,
            equal,
            ancestor,
            parents,
            self.resolve("refs/admission/head") if is_pr else None,
            self.resolve("refs/admission/merge") if is_pr else None,
            self.resolve("refs/admission/release")
            if context.ref.startswith("refs/tags/")
            else None,
        )


def verify(context: Context, client: GitHub, git: Git) -> None:
    context.validate()
    prefix = f"/repos/{context.repository}"
    repository = client.get(prefix)
    run = client.get(f"{prefix}/actions/runs/{context.run_id}")
    workflow = client.get(f"{prefix}/actions/workflows/{identifier(run.get('workflow_id'))}")
    main = client.get(f"{prefix}/branches/main")
    evidence = git.evidence(context)
    pr = permission = None
    if context.event_name == "pull_request":
        # Read current PR state after fetching refs, so old queued runs cannot
        # admit a superseded head. Any API/git race is a denial, never a retry.
        pr = client.get(f"{prefix}/pulls/{context.ref.split('/')[2]}")
        if (
            identifier(record(record(pr.get("head")).get("repo")).get("id"))
            == context.repository_id
            and not evidence.workflow_equal
        ):
            # Re-runs retain github.actor's privileges, not the re-run initiator's.
            permission = client.get(f"{prefix}/collaborators/{context.actor}/permission")
    admit(context, ApiEvidence(repository, run, workflow, main, pr, permission), evidence)


def deadline_expired(signum: int, frame: Any) -> None:
    raise AdmissionDeniedError("source admission deadline exceeded")


def main() -> int:
    previous_handler = signal.signal(signal.SIGALRM, deadline_expired)
    signal.alarm(180)
    try:
        context = Context.from_env()
        client = GitHub(os.environ.get("CI_GITHUB_TOKEN", ""))
        with tempfile.TemporaryDirectory(
            prefix="ci-admission-", dir=Path(__file__).parent
        ) as directory:
            verify(context, client, Git(directory, client.token))
    except AdmissionDeniedError as error:
        print(f"CI source admission denied: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("CI source admission denied: evidence unavailable", file=sys.stderr)
        return 1
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
    print("CI source admission verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
