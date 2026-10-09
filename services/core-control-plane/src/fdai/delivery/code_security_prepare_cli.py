"""Acquire source and export a credential-free, independently digest-bound scan handoff."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlsplit

from fdai.core.security.code_findings.review_signal import ReviewSource
from fdai.delivery.code_security_acquire import GitSourceAcquirer, SourceAcquisitionError
from fdai.delivery.code_security_prepared_source import export_prepared_source
from fdai.delivery.code_security_scan_cli import default_work_root, derive_alias


def add_prepare_command(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    command = sub.add_parser("prepare-scan", help="acquire a credential-free scan handoff")
    target = command.add_mutually_exclusive_group(required=True)
    target.add_argument("--path", help="local folder")
    target.add_argument("--repository", help="Git location; never put credentials in its URL")
    command.add_argument("--revision", help="branch, tag, or full commit id of --repository")
    command.add_argument("--repo-alias")
    command.add_argument("--include-uncommitted", action="store_true")
    command.add_argument("--work-root", default=str(default_work_root()))
    command.add_argument("--out", required=True, help="new private handoff directory")


async def prepare_scan(args: argparse.Namespace) -> dict[str, object]:
    header = None
    alias = args.repo_alias
    if args.path:
        if args.revision:
            raise ValueError("--revision requires --repository")
        alias = alias or derive_alias(Path(args.path))
        source = ReviewSource(kind="local_path", provider="local", trigger="cli")
    else:
        if args.include_uncommitted or not args.revision or not alias:
            raise ValueError("repository preparation requires --revision and --repo-alias")
        location = urlsplit(args.repository)
        if location.username is not None or location.password is not None:
            raise ValueError("repository URLs cannot contain credentials")
        provider = "github" if location.hostname == "github.com" else "git"
        source = ReviewSource(kind="git_repository", provider=provider, trigger="cli")
        if provider == "github":
            import os

            from fdai_github_app_auth import GitHubAppTokenError

            from fdai.delivery.code_security_repo_cli import github_auth_header

            repository = location.path.strip("/").removesuffix(".git")
            if len(repository.split("/")) != 2:
                raise ValueError("GitHub repository URL must name one owner and repository")
            try:
                header = await github_auth_header(repository, os.environ)
            except GitHubAppTokenError as exc:
                raise SourceAcquisitionError("repository credentials are unavailable") from exc
    acquirer = GitSourceAcquirer(Path(args.work_root).resolve(), auth_header=lambda: header)
    if args.path:
        acquired = acquirer.acquire_path(
            Path(args.path), include_uncommitted=args.include_uncommitted
        )
    else:
        revision = acquirer.resolve_revision(args.repository, args.revision)
        acquired = acquirer.acquire(args.repository, revision)
    prepared = export_prepared_source(
        acquired, Path(args.out), repository_alias=alias, source=source
    )
    return {
        "ok": True,
        "repository_alias": prepared.repository_alias,
        "revision": acquired.revision,
        "revision_kind": acquired.revision_kind,
        "manifest_digest": prepared.manifest_digest,
        "tree_digest": prepared.tree_digest,
    }
