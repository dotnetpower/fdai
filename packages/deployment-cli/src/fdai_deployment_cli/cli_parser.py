"""Declare the public CLI grammar without loading profiles or selecting a deployment target."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from pathlib import Path

from fdai_deployment_cli.__about__ import __version__
from fdai_deployment_cli.cli_help import (
    AZURE_DESCRIPTION,
    AZURE_EPILOG,
    ROOT_DESCRIPTION,
    ROOT_EPILOG,
    HelpParser,
    command,
    command_group,
)
from fdai_deployment_cli.foundation_plan import register_foundation_plan_command
from fdai_deployment_cli.state_handoff import register_state_handoff_command

CommandHandler = Callable[[argparse.Namespace], int]


def build_parser(handlers: Mapping[str, CommandHandler]) -> argparse.ArgumentParser:
    """Bind command handlers without calling them; empty groups show only their own help.

    Leaf requirements, types, choices, and mutually exclusive sources remain argparse
    contracts. Resolving the default work directory belongs to execution, not discovery.
    """

    parser = HelpParser(prog="fdaictl", description=ROOT_DESCRIPTION, epilog=ROOT_EPILOG)
    parser.add_argument(
        "--version", action="version", version=__version__, help="show the CLI version and exit"
    )
    subcommands = command_group(parser)

    version = command(subcommands, "version", "Show the installed CLI version")
    version.add_argument("--output", choices=("text", "json"), default="text")
    version.set_defaults(handler=handlers["version"])

    doctor = command(subcommands, "doctor", "Check local tools and Azure authentication")
    doctor.add_argument("--output", choices=("text", "json"), default="text")
    doctor.set_defaults(handler=handlers["doctor"])

    offline = command(
        subcommands,
        "offline",
        "Prepare and verify local signed-kit artifacts",
        epilog="Next: fdaictl offline prepare --help\nThese operations do not deploy Azure resources.",
    )
    offline_commands = command_group(offline)
    prepare = command(
        offline_commands, "prepare", "Verify a signed kit and create a private snapshot"
    )
    prepare.add_argument("--offline-kit", type=Path, required=True)
    prepare.add_argument("--release-root", type=Path, required=True)
    prepare.add_argument("--bundle-public-key", type=Path, required=True)
    prepare.add_argument("--profile", type=Path, required=True)
    prepare.add_argument("--source-commit", required=True)
    prepare.add_argument("--work-dir", type=Path, required=True)
    prepare.add_argument("--output", choices=("text", "json"), default="text")
    prepare.set_defaults(handler=handlers["offline_prepare"])
    configure = command(
        offline_commands, "configure-console", "Write local Console configuration; do not publish"
    )
    configure.add_argument(
        "--directory",
        type=Path,
        required=True,
        help="Private prebuilt Console directory whose shipped configuration will be replaced",
    )
    configure.add_argument("--settings", type=Path, required=True)
    configure.add_argument("--output", choices=("text", "json"), default="text")
    configure.set_defaults(handler=handlers["offline_configure_console"])
    install = command(
        offline_commands, "install-support", "Install migration support from verified local wheels"
    )
    install.add_argument("--offline-kit", type=Path, required=True)
    install.add_argument("--release-root", type=Path, required=True)
    install.add_argument("--work-dir", type=Path, required=True)
    install.add_argument("--output", choices=("text", "json"), default="text")
    install.set_defaults(handler=handlers["offline_install_support"])

    provision = command(
        subcommands,
        "provision",
        "Prepare deployment inputs or deploy FDAI to Azure",
        epilog=(
            "Start here: fdaictl provision azure --help\n"
            "Advanced profile and verification commands never replace exact approval."
        ),
    )
    provision_commands = command_group(provision)
    azure = command(
        provision_commands,
        "azure",
        "Deploy with a signed kit and exact human approvals",
        description=AZURE_DESCRIPTION,
        epilog=AZURE_EPILOG,
    )
    source_options = azure.add_argument_group("Artifact source (choose one)")
    kit_source = source_options.add_mutually_exclusive_group(required=True)
    kit_source.add_argument(
        "--online", action="store_true", help="Download and verify the versioned release kit"
    )
    kit_source.add_argument(
        "--offline-kit",
        type=Path,
        metavar="PATH",
        help="Use a local signed kit; no public artifact fallback",
    )
    settings = azure.add_argument_group("Deployment settings")
    settings.add_argument(
        "--region", default="koreacentral", help="Azure deployment region (default: %(default)s)"
    )
    settings.add_argument(
        "--monthly-cost-ceiling",
        type=int,
        default=1000,
        metavar="USD",
        help="Monthly cost review input in USD (default: %(default)s); not a billing cap",
    )
    settings.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help="Private run directory (default: ~/.local/state/fdai/azure)",
    )
    settings.add_argument(
        "--timeout-seconds",
        type=int,
        default=14_400,
        metavar="SECONDS",
        help=(
            "Foundation supervision budget in seconds (default: 14400, 4 hours); "
            "not a whole-deployment deadline"
        ),
    )
    output = azure.add_argument_group("Output")
    output.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Final result format (default: text); json disables progress",
    )
    output.add_argument(
        "--progress",
        choices=("auto", "plain", "off"),
        default="auto",
        help="Color activity stream, plain phase logs, or off (default: auto); json disables it",
    )
    advanced = azure.add_argument_group("Advanced (optional)")
    advanced.add_argument(
        "--online-url",
        metavar="URL",
        help="Override the online kit URL on an approved HTTPS release host",
    )
    advanced.add_argument(
        "--license-signing-key",
        type=Path,
        metavar="PATH",
        help="Maintainer-only private issuer key file; not an adopter prerequisite",
    )
    advanced.add_argument(
        "--trial-token",
        type=Path,
        metavar="PATH",
        help="Private pre-issued capability-token file; never pass the token value",
    )
    azure.set_defaults(handler=handlers["provision_azure"])
    register_state_handoff_command(provision_commands)
    register_foundation_plan_command(provision_commands)
    initialize = command(provision_commands, "init", "Create a private manual deployment profile")
    initialize.add_argument(
        "--profile",
        type=Path,
        required=True,
        help="Private profile file to create; replacement requires --force",
    )
    initialize.add_argument("--environment", choices=("dev", "staging", "prod"), required=True)
    initialize.add_argument("--region", required=True)
    initialize.add_argument("--target-binding", required=True)
    initialize.add_argument("--connectivity", choices=("online", "offline"), required=True)
    initialize.add_argument("--host", choices=("existing-host", "managed-vm"), required=True)
    initialize.add_argument("--transport", choices=("manual",), required=True)
    initialize.add_argument(
        "--access-method",
        choices=(
            "internal_ssh",
            "temporary_public_ssh",
            "bastion",
            "run_command",
        ),
        required=True,
    )
    initialize.add_argument("--approval-quorum", type=int, default=1)
    initialize.add_argument("--monthly-cost-ceiling", type=int, default=0)
    initialize.add_argument("--force", action="store_true")
    initialize.add_argument("--output", choices=("text", "json"), default="text")
    initialize.set_defaults(handler=handlers["provision_init"])

    inspect = command(
        provision_commands, "inspect", "Inspect a profile and local deployment prerequisites"
    )
    inspect.add_argument("--profile", type=Path, required=True)
    inspect.add_argument("--output", choices=("text", "json"), default="text")
    inspect.set_defaults(handler=handlers["provision_inspect"])

    plan = command(
        provision_commands, "plan", "Plan a verified Terraform root without applying changes"
    )
    plan.add_argument("--offline-kit", type=Path, required=True)
    plan.add_argument("--release-root", type=Path, required=True)
    plan.add_argument("--bundle-public-key", type=Path, required=True)
    plan.add_argument("--work-dir", type=Path, required=True)
    plan.add_argument("--variables-file", type=Path, required=True)
    plan.add_argument("--profile", type=Path, required=True)
    plan.add_argument("--stage", choices=("platform", "foundation"), default="platform")
    plan.add_argument(
        "--save-plan",
        action="store_true",
        help="retain a private foundation plan and review digest; does not authorize apply",
    )
    plan.add_argument("--output", choices=("text", "json"), default="text")
    plan.set_defaults(handler=handlers["provision_plan"])

    bootstrap_reconcile = command(
        provision_commands,
        "bootstrap-reconcile",
        "Read Azure Foundation state into an expiring plan",
    )
    bootstrap_reconcile.add_argument("--profile", type=Path, required=True)
    bootstrap_reconcile.add_argument("--source-commit", required=True)
    bootstrap_reconcile.add_argument("--ops-resource-group", required=True)
    bootstrap_reconcile.add_argument("--app-resource-group", required=True)
    bootstrap_reconcile.add_argument("--state-storage-account", required=True)
    bootstrap_reconcile.add_argument("--output-plan", type=Path, required=True)
    bootstrap_reconcile.add_argument("--ttl-seconds", type=int, default=3600)
    bootstrap_reconcile.add_argument("--output", choices=("text", "json"), default="text")
    bootstrap_reconcile.set_defaults(handler=handlers["provision_bootstrap_reconcile"])

    bundle = command(
        subcommands,
        "bundle",
        "Verify deployment-bundle signatures and integrity",
        epilog="Next: fdaictl bundle verify --help",
    )
    bundle_commands = command_group(bundle)
    bundle_verify = command(
        bundle_commands, "verify", "Verify signature, compatibility, files, and digests"
    )
    bundle_verify.add_argument("--bundle", type=Path, required=True)
    bundle_verify.add_argument("--public-key", type=Path, required=True)
    bundle_verify.add_argument("--output", choices=("text", "json"), default="text")
    bundle_verify.set_defaults(handler=handlers["bundle_verify"])

    license_command = command(
        subcommands,
        "license",
        "Inspect a capability token without granting authority",
        epilog="Next: fdaictl license inspect --help",
    )
    license_commands = command_group(license_command)
    license_inspect = command(
        license_commands, "inspect", "Verify a local token and report its declared capabilities"
    )
    license_inspect.add_argument("--token", type=Path, required=True)
    license_inspect.add_argument("--public-key", type=Path, required=True)
    license_inspect.add_argument("--image-digest", default=None)
    license_inspect.add_argument("--tenant-binding", default=None)
    license_inspect.add_argument("--output", choices=("text", "json"), default="text")
    license_inspect.set_defaults(handler=handlers["license_inspect"])

    onboard = command(
        subcommands,
        "onboard",
        "Run a local simulation or read its journal",
        epilog=(
            "Simulation only: fdaictl onboard guided --help\n"
            "For live deployment use fdaictl provision azure --help."
        ),
    )
    onboard_commands = command_group(onboard)
    guided = command(
        onboard_commands,
        "guided",
        "Rehearse the stage graph; requires --simulate and never deploys",
    )
    guided.add_argument("--profile", type=Path, required=True)
    guided.add_argument("--source-commit", required=True)
    guided.add_argument("--run-id", required=True)
    guided.add_argument("--journal", type=Path, required=True)
    guided.add_argument("--simulate", action="store_true")
    guided.add_argument("--interrupt-after", default=None)
    guided.add_argument("--output", choices=("text", "json"), default="text")
    guided.set_defaults(handler=handlers["onboard_guided"])
    status = command(onboard_commands, "status", "Read progress from a local simulation journal")
    status.add_argument("--journal", type=Path, required=True)
    status.add_argument("--output", choices=("text", "json"), default="text")
    status.set_defaults(handler=handlers["onboard_status"])
    return parser
