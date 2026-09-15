"""Command discovery is successful, read-only, and distinct from malformed invocations."""

from __future__ import annotations

import argparse
import json
import sys

import pytest

from fdai_deployment_cli import cli

GROUPS = ((), ("offline",), ("provision",), ("bundle",), ("license",), ("onboard",))


def _invoke(arguments: list[str]) -> int:
    try:
        return cli.main(arguments)
    except SystemExit as exc:
        return int(exc.code)


@pytest.mark.parametrize(
    "path", GROUPS, ids=["root", "offline", "provision", "bundle", "license", "onboard"]
)
def test_empty_group_matches_explicit_help(path, capsys) -> None:
    assert _invoke(list(path)) == 0
    bare = capsys.readouterr()
    assert bare.err == ""
    assert "Commands:" in bare.out
    assert f"usage: fdaictl{' ' if path else ''}{' '.join(path)} " in bare.out
    assert _invoke([*path, "--help"]) == 0
    explicit = capsys.readouterr()
    assert explicit.out == bare.out
    assert explicit.err == ""


def test_root_help_explains_commands_and_next_steps(capsys) -> None:
    assert _invoke(["-h"]) == 0
    output = capsys.readouterr()
    assert "Azure" in output.out
    assert "Quick start:" in output.out
    assert "az login" in output.out
    assert "fdaictl doctor" in output.out
    assert "fdaictl provision azure --online" in output.out
    assert "fdaictl COMMAND --help" in output.out
    for description in ("signed", "simulation", "authentication", "version"):
        assert description in output.out.lower()


def test_azure_help_groups_and_explains_inputs(capsys) -> None:
    assert _invoke(["provision", "azure", "--help"]) == 0
    output = capsys.readouterr()
    for label in ("Artifact source", "Deployment settings", "Output", "Advanced"):
        assert label in output.out
    for value in ("koreacentral", "1000", "seconds", "14400", "observation-only"):
        assert value in output.out
    assert "--offline-kit" in output.out
    assert "no public artifact" in output.out.lower()
    assert "~/" in output.out
    assert "--progress plain" in output.out
    assert output.err == ""


def test_version_alias_preserves_existing_json_contract(capsys) -> None:
    assert _invoke(["--version"]) == 0
    alias = capsys.readouterr()
    assert _invoke(["version"]) == 0
    assert capsys.readouterr().out == alias.out
    assert _invoke(["version", "--output", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert alias.out.strip() == payload["version"]
    assert payload["schema_version"] == "fdai.version.v1"


@pytest.mark.parametrize(
    "arguments",
    [
        ["unknown"],
        ["provision", "unknown"],
        ["--unknown"],
        ["provision", "--unknown"],
        ["provision", "azure"],
        ["offline", "prepare"],
        ["bundle", "verify"],
        ["license", "inspect"],
        ["onboard", "guided"],
        ["provision", "azure", "--online", "--offline-kit", "example.tar.gz"],
        ["provision", "azure", "--online", "--source", "."],
        ["provision", "azure", "--offline-kit", "example.tar.gz", "--source", "."],
        ["provision", "azure", "--online", "--region"],
    ],
)
def test_invalid_input_still_fails_without_dispatch(arguments, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli, "deploy_azure_foundation", lambda **_kwargs: pytest.fail("unexpected deployment")
    )
    assert _invoke(arguments) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "error:" in output.err
    assert "usage:" in output.err


def test_none_argv_uses_process_arguments(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["fdaictl"])
    assert cli.main() == 0
    assert "Commands:" in capsys.readouterr().out


def test_source_preparation_never_enters_kit_or_azure_paths(monkeypatch, capsys) -> None:
    calls = []
    monkeypatch.setattr(cli, "deploy_azure_foundation", lambda **_: pytest.fail("kit path invoked"))
    monkeypatch.setattr(
        cli,
        "prepare_source_deployment",
        lambda **kwargs: calls.append(kwargs) or {"deployment_ready": False, "state": "prepared"},
    )
    assert (
        cli.main(
            [
                "provision",
                "azure",
                "--source",
                ".",
                "--runtime",
                "aks",
                "--prepare-only",
                "--output",
                "json",
            ]
        )
        == 0
    )
    assert len(calls) == 1
    assert json.loads(capsys.readouterr().out)["deployment_ready"] is False


def test_prepare_only_rejects_kit_mode(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli, "deploy_azure_foundation", lambda **_: pytest.fail("unexpected deployment")
    )
    assert cli.main(["provision", "azure", "--online", "--prepare-only"]) == 3
    assert "requires --source" in capsys.readouterr().err


def test_source_preflight_reports_blockers_without_deploying(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli, "deploy_azure_foundation", lambda **_: pytest.fail("kit or apply invoked")
    )
    monkeypatch.setattr(cli, "prepare_source_deployment", lambda **_: {"state": "prepared"})
    monkeypatch.setattr(
        cli,
        "inspect_aks_target",
        lambda **_: {
            "state": "blocked",
            "blockers": ["quota_cores_insufficient"],
            "deployment_ready": False,
        },
    )
    assert (
        cli.main(
            [
                "provision",
                "azure",
                "--source",
                ".",
                "--runtime",
                "aks",
                "--preflight-only",
                "--output",
                "json",
            ]
        )
        == 3
    )
    assert json.loads(capsys.readouterr().out)["blockers"] == ["quota_cores_insufficient"]


def _parsers(parser: argparse.ArgumentParser):
    yield parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                yield from _parsers(child)


def test_every_registered_command_is_described() -> None:
    for parser in _parsers(cli._parser()):
        assert parser.description, parser.prog
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                descriptions = {item.dest: item.help for item in action._choices_actions}
                assert set(descriptions) == set(action.choices), parser.prog
                assert all(descriptions.values()), parser.prog
            elif action.option_strings:
                assert action.help, (parser.prog, action.option_strings)
