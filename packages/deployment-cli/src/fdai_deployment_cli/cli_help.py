"""Plain command discovery for fdaictl, without invoking deployment or inspection handlers."""

from __future__ import annotations

import argparse
import shutil
import sys
import textwrap
from collections.abc import Iterable
from typing import Any, NoReturn

ROOT_DESCRIPTION = (
    "Deploy FDAI to Azure and verify signed deployment artifacts.\n"
    "Help never signs in, downloads a kit, or deploys resources."
)
ROOT_EPILOG = (
    "Quick start:\n"
    "  az login\n"
    "  fdaictl doctor\n"
    "  fdaictl provision azure --online\n\n"
    "Learn more: fdaictl COMMAND --help\n"
    "Deployment requires explicit approval; help grants no authority."
)
AZURE_DESCRIPTION = (
    "Deploy from the active Azure CLI human account using one verified signed kit.\n"
    "Choose --online or --offline-kit. Exact plans still require human approval.\n"
    "New installations can start observation-only without a capability token.\n"
    "Omitting a token does not revoke one previously installed."
)
AZURE_EPILOG = (
    "Examples (after az login):\n"
    "  fdaictl provision azure --online \\\n"
    "    --region koreacentral\n\n"
    "  fdaictl provision azure \\\n"
    "    --offline-kit /media/fdai-kit.tar.gz\n\n"
    "  fdaictl provision azure --online \\\n"
    "    --progress plain\n\n"
    "Offline refers to artifact delivery; Azure connectivity is still required.\n"
    "CLI source updates do not change scripts inside the signed release kit."
)

# Common meanings only; a command-specific help string always takes precedence.
_ARGUMENT_HELP = {
    "--output": "Result format: text or machine-readable json (default: text)",
    "--offline-kit": "Path to the complete signed deployment kit; no public artifact fallback",
    "--release-root": "Path to the trusted release public key, not a private signing key",
    "--bundle-public-key": "Path to the trusted deployment-bundle public key",
    "--public-key": "Path to the trusted public verification key",
    "--profile": "Path to a private deployment profile; see provision init --help",
    "--source-commit": "Exact source revision (40-character git commit SHA)",
    "--work-dir": "Private local work directory; ownership and mode checks apply",
    "--directory": "Existing local input directory for this operation",
    "--settings": "Path to deployment-owned Console settings JSON",
    "--region": "Azure region for the selected deployment profile",
    "--environment": "Deployment environment; this value grants no execution authority",
    "--target-binding": "Reviewed target binding as a lowercase SHA-256 digest",
    "--connectivity": "Artifact connectivity profile: online or offline",
    "--host": "Execution host: %(choices)s",
    "--transport": "Execution transport for the profile (manual only)",
    "--access-method": "Private-host access route: %(choices)s",
    "--approval-quorum": "Number of required human approvers (default: 1)",
    "--monthly-cost-ceiling": "Monthly cost review input in USD (default: %(default)s); not a billing cap",
    "--force": "Replace an existing local profile; does not approve Azure changes",
    "--variables-file": "Path to private, target-bound Terraform input JSON",
    "--stage": "Terraform root selection: platform or foundation (default: platform)",
    "--ops-resource-group": "Exact operations resource group in the target subscription",
    "--app-resource-group": "Exact application resource group in the target subscription",
    "--state-storage-account": "Exact private Terraform state storage account name",
    "--output-plan": "New private file for the expiring reconciliation plan",
    "--ttl-seconds": "Reconciliation plan lifetime in seconds (default: 3600)",
    "--bundle": "Path to the signed deployment bundle to verify",
    "--token": "Path to the private capability-token file, never the token value",
    "--image-digest": "Optional expected runtime image SHA-256 binding",
    "--tenant-binding": "Optional expected deployment binding digest",
    "--run-id": "Run identifier for the local simulation journal",
    "--journal": "Path to the local hash-chained simulation journal",
    "--simulate": "Required for guided rehearsal; never starts a live deployment",
    "--interrupt-after": "Stop the simulation after this stage to exercise recovery",
    "--local-state": "Path to the private local Terraform state copy",
    "--remote-state": "Path to the independently obtained remote state copy",
    "--plan-json": "Path to the independently obtained zero-change plan JSON",
    "--output-receipt": "New private comparison receipt; does not authorize cache deletion",
    "--expected-review-digest": "Expected saved-plan review SHA-256 digest",
}

_ARGUMENT_METAVARS = {
    "--host": "HOST",
    "--access-method": "METHOD",
    "--monthly-cost-ceiling": "USD",
    "--ops-resource-group": "NAME",
    "--app-resource-group": "NAME",
    "--state-storage-account": "NAME",
    "--expected-review-digest": "SHA256",
}


class PlainHelpFormatter(argparse.HelpFormatter):
    """Wrap descriptions and examples without ANSI or expanded private default values."""

    def __init__(self, prog: str) -> None:
        width = max(40, min(88, shutil.get_terminal_size(fallback=(80, 24)).columns - 2))
        super().__init__(prog, width=width, max_help_position=4 if width < 58 else 26)

    def _fill_text(self, text: str, width: int, indent: str) -> str:
        fill = super()._fill_text
        return "\n".join(
            fill(line.lstrip(), width, indent + line[: len(line) - len(line.lstrip())])
            if line
            else ""
            for line in text.splitlines()
        )

    def _format_usage(
        self,
        usage: str | None,
        actions: Iterable[argparse.Action],
        groups: Iterable[argparse._MutuallyExclusiveGroup],
        prefix: str | None,
    ) -> str:
        rendered = super()._format_usage(usage, actions, groups, prefix)
        if all(len(line) <= self._width for line in rendered.splitlines()):
            return rendered
        # argparse indents continuations by the full command path, even when that
        # leaves less space than a single option. Retain the syntax with a small indent.
        return "\n".join(
            textwrap.fill(
                line.strip(),
                width=self._width,
                initial_indent="" if index == 0 else "  ",
                subsequent_indent="  ",
                break_long_words=False,
                break_on_hyphens=False,
            )
            if line
            else ""
            for index, line in enumerate(rendered.split("\n"))
        )


class HelpParser(argparse.ArgumentParser):
    """Keep argparse validation, with exact long options and plain explanatory help."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("formatter_class", PlainHelpFormatter)
        kwargs.setdefault("allow_abbrev", False)
        if sys.version_info >= (3, 14):
            kwargs.setdefault("color", False)
        super().__init__(*args, **kwargs)

    def add_argument(self, *name_or_flags: str, **kwargs: Any) -> argparse.Action:
        """Supply common option descriptions without overriding explicit or hidden help."""

        for flag in name_or_flags:
            if flag in _ARGUMENT_HELP:
                kwargs.setdefault("help", _ARGUMENT_HELP[flag])
                if flag in _ARGUMENT_METAVARS:
                    kwargs.setdefault("metavar", _ARGUMENT_METAVARS[flag])
                break
        return super().add_argument(*name_or_flags, **kwargs)

    def error(self, message: str) -> NoReturn:
        """Keep usage errors on stderr with exit 2 and an explicit next-help command."""

        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\nTry '{self.prog} --help' for details.\n")


def command_group(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction[argparse.ArgumentParser]:
    """Let a group alone show help; malformed input and required leaf arguments still fail."""

    def show_help(_args: argparse.Namespace) -> int:
        parser.print_help()
        return 0

    parser.set_defaults(handler=show_help)
    return parser.add_subparsers(title="Commands", metavar="COMMAND")


def command(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    summary: str,
    *,
    description: str | None = None,
    epilog: str | None = None,
) -> argparse.ArgumentParser:
    """Describe a real registered command, keeping its handler and argument contract separate."""

    return commands.add_parser(
        name, help=summary, description=description or summary, epilog=epilog
    )
