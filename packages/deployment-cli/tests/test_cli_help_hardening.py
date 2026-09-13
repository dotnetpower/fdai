"""No-network critique rounds for help discovery, argument safety, and output contracts."""

from __future__ import annotations

import argparse
import io
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from fdai_deployment_cli import cli
from fdai_deployment_cli.cli_help import (
    AZURE_EPILOG,
    ROOT_EPILOG,
    HelpParser,
    command,
    command_group,
)

GROUPS = ((), ("offline",), ("provision",), ("bundle",), ("license",), ("onboard",))
LEAVES = (
    ("version",),
    ("doctor",),
    ("offline", "prepare"),
    ("offline", "configure-console"),
    ("offline", "install-support"),
    ("provision", "azure"),
    ("provision", "init"),
    ("provision", "inspect"),
    ("provision", "plan"),
    ("provision", "bootstrap-reconcile"),
    ("provision", "verify-state-handoff"),
    ("provision", "verify-foundation-plan"),
    ("bundle", "verify"),
    ("license", "inspect"),
    ("onboard", "guided"),
    ("onboard", "status"),
)


def _invoke(argv):
    try:
        return cli.main(list(argv))
    except SystemExit as exc:
        return int(exc.code)


def _deny(*_args, **_kwargs):
    pytest.fail("help must not invoke any operational dependency")


# R01-R02: Root/group help is handled by parsing, not exception-based deployment fallback.
@pytest.mark.parametrize("path", GROUPS)
def test_group_help_never_selects_a_real_handler(path, monkeypatch, capsys):
    for name in (
        "_doctor",
        "_provision_azure",
        "_provision_plan",
        "_provision_init",
        "_provision_inspect",
        "_provision_bootstrap_reconcile",
        "_offline_prepare",
        "_offline_configure_console",
        "_offline_install_support",
        "_bundle_verify",
        "_license_inspect",
        "_onboard_guided",
        "_onboard_status",
        "_version",
    ):
        monkeypatch.setattr(cli, name, _deny)
    assert _invoke(path) == 0
    assert capsys.readouterr().err == ""


# R03: A child help request must short-circuit required arguments, without acquiring evidence.
@pytest.mark.parametrize("path", LEAVES)
def test_every_leaf_help_is_side_effect_free(path, monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, "run", _deny)
    monkeypatch.setattr(subprocess, "Popen", _deny)
    monkeypatch.setattr("builtins.input", _deny)
    for name in (
        "read_plan_input",
        "load_profile",
        "read_journal",
        "write_profile",
        "write_private_output",
        "deploy_azure_foundation",
        "inspect_tools",
        "azure_cli_authenticated",
        "verify_bundle",
        "inspect_license",
        "reconcile_bootstrap",
        "prepare_offline_release",
        "install_support",
        "configure_console",
        "rehearse",
    ):
        monkeypatch.setattr(cli, name, _deny)
    assert _invoke([*path, "--help"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert "usage:" in output.out
    assert not list(tmp_path.iterdir())


# R04: argparse abbreviates long options, not command names. Both remain exact here.
@pytest.mark.parametrize(
    "arguments",
    [
        ["--ver"],
        ["prov"],
        ["provisoin"],
        ["provision", "az"],
        ["provision", "azure", "--onl"],
        ["provision", "azure", "--online", "--reg", "koreacentral"],
        ["provision", "azure", "--online", "--prog", "plain"],
        ["version", "--out", "json"],
    ],
)
def test_no_abbreviated_command_or_option_dispatch(arguments, monkeypatch, capsys):
    monkeypatch.setattr(cli, "deploy_azure_foundation", _deny)
    assert _invoke(arguments) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "error:" in output.err


# R05: Group defaults must not override the leaf's explicitly registered handler.
def test_leaf_handler_defaults_and_typed_arguments_are_preserved(tmp_path):
    path = tmp_path / "kit with spaces.tar.gz"
    args = cli._parser().parse_args(
        [
            "provision",
            "azure",
            "--offline-kit",
            str(path),
            "--progress",
            "plain",
            "--output",
            "json",
        ]
    )
    assert args.handler is cli._provision_azure
    assert args.offline_kit == path
    assert args.online is False
    assert args.monthly_cost_ceiling == 1000
    assert args.timeout_seconds == 14400
    assert args.progress == "plain"
    assert args.output == "json"


# R06: Public command registration owns documentation; hidden recovery switches stay hidden.
def test_hidden_verification_switch_is_unchanged(capsys):
    assert _invoke(["provision", "verify-foundation-plan", "--help"]) == 0
    assert "allow-expired-after-claim" not in capsys.readouterr().out
    args = cli._parser().parse_args(
        [
            "provision",
            "verify-foundation-plan",
            "--directory",
            "example",
            "--profile",
            "example.json",
            "--expected-review-digest",
            "a" * 64,
            "--allow-expired-after-claim",
        ]
    )
    assert args.allow_expired_after_claim is True
    assert args.handler.__name__ == "_verify_command"


# R07: Default-path help is generic, not an expansion of the reader's private HOME.
def test_help_does_not_expand_private_environment(monkeypatch, capsys):
    monkeypatch.setenv("HOME", "/example/private-operator-home")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "example-private-subscription")
    assert _invoke(["provision", "azure", "--help"]) == 0
    output = capsys.readouterr().out
    assert "private-operator-home" not in output
    assert "example-private-subscription" not in output
    assert "~/.local/state/fdai/azure" in output


# R08-R09: Static help remains plain and readable independently of Rich/environment coloring.
@pytest.mark.parametrize("columns", [40, 60, 80, 160])
@pytest.mark.parametrize("path", [*GROUPS, *LEAVES])
def test_help_wraps_without_ansi(columns, path, monkeypatch, capsys):
    monkeypatch.setenv("COLUMNS", str(columns))
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("TERM", "xterm-256color")
    assert _invoke([*path, "--help"]) == 0
    output = capsys.readouterr()
    assert "\x1b" not in output.out
    assert "\r" not in output.out
    assert all(len(line) <= max(40, columns) for line in output.out.splitlines())
    assert output.err == ""


# R10: New alias and help do not change the stable machine-readable version result.
def test_version_json_is_a_single_document_with_hostile_display_environment(monkeypatch, capsys):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    assert _invoke(["version", "--output", "json"]) == 0
    result = capsys.readouterr()
    assert json.loads(result.out) == {"schema_version": "fdai.version.v1", "version": "0.1.0"}
    assert len(result.out.splitlines()) == 1
    assert result.err == ""


# R11: Copyable deployment examples must parse but are never executed by the test.
def test_advertised_quickstart_and_azure_examples_parse():
    for epilog in (ROOT_EPILOG, AZURE_EPILOG):
        for line in epilog.replace("\\\n", " ").splitlines():
            if not line.startswith("  fdaictl "):
                continue
            args = cli._parser().parse_args(shlex.split(line)[1:])
            assert callable(args.handler)


# R12: Reusable helper works with an isolated parser and preserves hidden/explicit descriptions.
def test_help_helpers_do_not_change_custom_argument_contract(capsys):
    parser = HelpParser(prog="fdaictl", description="Example")
    children = command_group(parser)
    leaf = command(children, "example", "Example command", description="Detailed example")
    leaf.add_argument("--profile", required=True, help="Specific profile description")
    leaf.add_argument("--output", help=argparse.SUPPRESS)
    leaf.set_defaults(handler=lambda _args: 9)
    args = parser.parse_args(["example", "--profile", "example.json"])
    assert args.handler(args) == 9
    assert "Specific profile description" in leaf.format_help()
    assert "--output" not in leaf.format_help()
    args = parser.parse_args([])
    assert args.handler(args) == 0
    assert "Example command" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments", [[], ["--help"], ["--version"], ["provision", "azure", "--help"]]
)
def test_discovery_does_not_require_a_resolvable_home(arguments, monkeypatch, capsys):
    def missing_home():
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(Path, "home", missing_home)
    assert _invoke(arguments) == 0
    assert capsys.readouterr().err == ""


def test_explicit_empty_argv_never_uses_process_arguments(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["fdaictl", "doctor"])
    monkeypatch.setattr(cli, "_doctor", _deny)
    assert cli.main([]) == 0
    assert "Commands:" in capsys.readouterr().out


def test_missing_leaf_value_links_to_leaf_help(capsys):
    assert _invoke(["provision", "azure", "--online", "--region"]) == 2
    output = capsys.readouterr()
    assert "Try 'fdaictl provision azure --help'" in output.err
    assert output.out == ""


@pytest.mark.parametrize("arguments", [[], ["--help"]])
def test_closed_stdout_keeps_standard_argparse_help_behavior(arguments, monkeypatch, capsys):
    class ClosedPipe(io.StringIO):
        def write(self, _text):
            raise BrokenPipeError("output pipe closed")

    monkeypatch.setattr(sys, "stdout", ClosedPipe())
    # argparse intentionally suppresses a closed help output stream. It neither
    # dispatches a command nor turns the help result into deployment evidence.
    assert _invoke(arguments) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("explicit_directory", [False, True])
def test_execution_resolves_the_same_default_or_relative_work_directory(
    explicit_directory, monkeypatch, tmp_path, capsys
):
    received = {}

    def fake_deployment(**kwargs):
        received.update(kwargs)
        return {"deployment_ready": True}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(cli, "deploy_azure_foundation", fake_deployment)
    arguments = ["provision", "azure", "--online", "--progress", "off", "--output", "json"]
    if explicit_directory:
        arguments.extend(["--work-dir", "run with spaces"])
    assert _invoke(arguments) == 0
    expected = tmp_path / (
        "run with spaces" if explicit_directory else "home/.local/state/fdai/azure"
    )
    assert received["work_dir"] == expected
    assert json.loads(capsys.readouterr().out) == {"deployment_ready": True}


def test_help_distinguishes_local_outputs_and_capability_limits(capsys):
    assert _invoke(["provision", "init", "--help"]) == 0
    assert "profile file to create" in capsys.readouterr().out
    assert _invoke(["offline", "configure-console", "--help"]) == 0
    assert "will be replaced" in capsys.readouterr().out
    assert _invoke(["provision", "azure", "--help"]) == 0
    text = capsys.readouterr().out
    assert "does not revoke" in text
    assert "whole-deployment deadline" in text
