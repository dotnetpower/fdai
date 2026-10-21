"""Local publication commands with explicit unverified authority boundaries."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import UnsupportedAlgorithm

from fdai_deployment_cli.cli_help import command
from fdai_deployment_cli.lifecycle_configuration_package import SignedConfigurationPackage
from fdai_deployment_cli.lifecycle_configuration_publication import inspect_publication, publish
from fdai_deployment_cli.lifecycle_configuration_sealing import read_object
from fdai_deployment_cli.private_output import read_private_bytes


class ConfigurationExecutor(Protocol):
    def __call__(
        self,
        args: argparse.Namespace,
        *,
        retained_history: Sequence[SignedConfigurationPackage] | None = None,
        retained_package: SignedConfigurationPackage | None = None,
        persist_output: bool = True,
    ) -> SignedConfigurationPackage: ...


def register_publication_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    execute: ConfigurationExecutor,
) -> None:
    for operation in ("publish", "inspect-publication"):
        parser = command(
            commands,
            operation,
            f"{operation.title()} venue-scoped configuration evidence",
            epilog="Local custody only. Git review, global publisher identity and Hub acceptance are unverified.",
        )
        for name in ("release-input", "configuration-key", "installation-key"):
            parser.add_argument(f"--{name}", type=Path, required=True, metavar="PRIVATE_FILE")
        parser.add_argument(
            "--state-dir",
            type=Path,
            required=True,
            metavar="PRIVATE_DIRECTORY",
            help="Existing absolute operator-owned mode-0700 venue; no reset or destructive recovery",
        )
        if operation == "publish":
            parser.add_argument("--input", type=Path, required=True, metavar="PRIVATE_JSON_FILE")
            parser.add_argument(
                "--signing-key", type=Path, required=True, metavar="PRIVATE_PEM_FILE"
            )
            head = parser.add_mutually_exclusive_group(required=True)
            head.add_argument(
                "--initial-publication",
                action="store_true",
                help="First publication in an empty local venue or its exact retained retry",
            )
            head.add_argument(
                "--expected-publication-head", help="Retained local publication head SHA-256"
            )
        else:
            parser.add_argument(
                "--revision-id", required=True, help="Full lowercase source revision shape"
            )
        parser.add_argument("--output", choices=("text", "json"), default="text")
        parser.set_defaults(
            handler=partial(_run, execute=execute),
            configuration_operation=operation,
        )


def _arguments(
    args: argparse.Namespace,
    operation: str,
    history: Sequence[SignedConfigurationPackage],
) -> argparse.Namespace:
    return argparse.Namespace(
        **{
            **vars(args),
            "configuration_operation": operation,
            "history": [],
            "initial_revision": not history,
            "expected_predecessor": history[-1].digest if history else None,
        }
    )


def _run(args: argparse.Namespace, *, execute: ConfigurationExecutor) -> int:
    def verify(
        history: Sequence[SignedConfigurationPackage],
        package: SignedConfigurationPackage,
    ) -> None:
        execute(
            _arguments(args, "verify", history),
            retained_history=history,
            retained_package=package,
            persist_output=False,
        )

    try:
        if args.configuration_operation == "publish":
            source = read_object(read_private_bytes(args.input, max_bytes=1024 * 1024))
            revision = source.get("revision_id")
            if not isinstance(revision, str):
                raise ValueError("publication revision is required")

            def build(history: Sequence[SignedConfigurationPackage]) -> SignedConfigurationPackage:
                return execute(
                    _arguments(args, "build", history),
                    retained_history=history,
                    persist_output=False,
                )

            record = publish(
                args.state_dir,
                revision,
                build,
                verify,
                initial=args.initial_publication,
                expected_head=args.expected_publication_head,
            )
            artifact_state = "present"
        else:
            record, artifact_state = inspect_publication(args.state_dir, args.revision_id, verify)
    except (
        ValueError,
        TypeError,
        OSError,
        OverflowError,
        RecursionError,
        UnsupportedAlgorithm,
        sqlite3.Error,
    ):
        raise ValueError(
            "configuration publication not confirmed; inspect retained evidence before retrying; "
            "check the private venue, revision/head selection and independent keys/Release inputs"
        ) from None
    result = {
        "operation": args.configuration_operation,
        "receipt": record.receipt(),
        "artifact_state": artifact_state,
        "publication_confirmed": artifact_state == "present",
        "verified": True,
        "local_only": True,
        "git_revision_existence": "unverified",
        "git_review": "unverified",
        "global_publisher_identity": "unverified",
        "trust_registered": False,
        "hub_accepted": False,
        "deployment_activated": False,
        "execution_authority": False,
        "production_release_eligibility": "unverified",
    }
    print(
        json.dumps(result, sort_keys=True)
        if args.output == "json"
        else f"verified retained configuration evidence sha256={record.package.digest}; artifact={artifact_state}; "
        f"local publication confirmed={artifact_state == 'present'}; "
        "no Git review, Hub acceptance or execution authority"
    )
    return 0
