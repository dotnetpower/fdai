"""Real builders/readers against private publication venues and fresh CLI processes."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from fdai_deployment_cli import lifecycle_configuration_publication as journal
from fdai_deployment_cli import lifecycle_configuration_package as package_builder
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_configuration_artifact import configuration_artifact_bytes
from fdai_deployment_cli.lifecycle_configuration_cli import _execute
from fdai_deployment_cli.lifecycle_configuration_package import SignedConfigurationPackage

from . import test_lifecycle_configuration_cli as cli_cases
from .test_lifecycle_configuration_cli import Case, _multi_entity, _write
from .test_lifecycle_configuration_cli import case as case


def arguments(
    case: Case, history: Sequence[SignedConfigurationPackage], operation: str
) -> argparse.Namespace:
    return argparse.Namespace(
        configuration_operation=operation,
        release_input=case.root / "release.json",
        configuration_key=case.root / "configuration.pem",
        installation_key=case.root / "installation.pem",
        signing_key=case.root / "signing.pem",
        input=case.root / "source.json",
        history=[],
        initial_revision=not history,
        expected_predecessor=history[-1].digest if history else None,
    )


def build(case: Case, history: Sequence[SignedConfigurationPackage]) -> SignedConfigurationPackage:
    return _execute(
        arguments(case, history, "build"), retained_history=history, persist_output=False
    )


def verify(
    case: Case, history: Sequence[SignedConfigurationPackage], package: SignedConfigurationPackage
) -> None:
    _execute(
        arguments(case, history, "verify"),
        retained_history=history,
        retained_package=package,
        persist_output=False,
    )


@pytest.fixture
def venue(tmp_path: Path) -> Path:
    result = tmp_path / "venue"
    result.mkdir(mode=0o700)
    return result


def publish(case: Case, venue: Path, head: str | None = None) -> journal.Publication:
    return journal.publish(
        venue,
        str(case.source["revision_id"]),
        lambda history: build(case, history),
        lambda history, package: verify(case, history, package),
        initial=head is None,
        expected_head=head,
    )


def inspect(case: Case, venue: Path, revision: str = "a" * 40) -> tuple[journal.Publication, str]:
    return journal.inspect_publication(
        venue, revision, lambda history, package: verify(case, history, package)
    )


def command(case: Case, venue: Path, operation: str = "publish", *extra: str) -> list[str]:
    result = [
        "configuration",
        operation,
        "--state-dir",
        str(venue),
        "--release-input",
        str(case.root / "release.json"),
        "--configuration-key",
        str(case.root / "configuration.pem"),
        "--installation-key",
        str(case.root / "installation.pem"),
        "--output",
        "json",
    ]
    if operation == "publish":
        result += [
            "--input",
            str(case.root / "source.json"),
            "--signing-key",
            str(case.root / "signing.pem"),
        ]
    else:
        result += ["--revision-id", "a" * 40]
    return [*result, *extra]


@pytest.mark.parametrize("multi", [False, True])
def test_original_retry_chain_and_reader(case: Case, venue: Path, multi: bool) -> None:
    if multi:
        _multi_entity(case)
    first = publish(case, venue)
    assert publish(case, venue) == first
    assert inspect(case, venue) == (first, "present")
    assert first.receipt()["predecessor_digest"] is None
    case.source["revision_id"] = "b" * 40
    _write(case.root / "source.json", case.source)
    second = publish(case, venue, first.package.digest)
    assert second.sequence == 2
    assert second.receipt()["predecessor_digest"] == first.package.digest
    assert publish(case, venue, first.package.digest) == second
    case.source["revision_id"] = "a" * 40
    _write(case.root / "source.json", case.source)
    assert publish(case, venue) == first
    for path in venue.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.stat().st_nlink == 1
        content = path.read_bytes()
        assert b"https://example.com/private-identifier" not in content
        assert (case.root / "signing.pem").read_bytes() not in content
        assert (case.root / "source.json").read_bytes() not in content


def test_conflicting_input_and_stale_head_leave_original(case: Case, venue: Path) -> None:
    first = publish(case, venue)
    before = (venue / journal._DATABASE).read_bytes()
    case.source["sealed"] = {"endpoint": "https://example.com/changed-private-identifier"}
    _write(case.root / "source.json", case.source)
    with pytest.raises(ValueError):
        publish(case, venue)
    assert (venue / journal._DATABASE).read_bytes() == before
    case.source["revision_id"] = "b" * 40
    _write(case.root / "source.json", case.source)
    with pytest.raises(ValueError, match="head changed"):
        publish(case, venue, "f" * 64)
    with pytest.raises(ValueError, match="initial publication"):
        publish(case, venue)
    assert inspect(case, venue)[0] == first


@pytest.mark.parametrize("multi", [False, True])
def test_crash_boundary_retains_receipt_and_exact_bytes(
    case: Case,
    venue: Path,
    monkeypatch: pytest.MonkeyPatch,
    multi: bool,
) -> None:
    if multi:
        _multi_entity(case)
    original = journal._artifact_state

    def interrupted(path: Path, record: journal.Publication, *, materialize: bool) -> str:
        if materialize:
            raise OSError("synthetic post-commit interruption")
        return original(path, record, materialize=False)

    with monkeypatch.context() as patch:
        patch.setattr(journal, "_artifact_state", interrupted)
        with pytest.raises(OSError, match="post-commit"):
            publish(case, venue)
    before = {path.name: path.read_bytes() for path in venue.iterdir()}
    retained, state = inspect(case, venue)
    assert state == "missing"
    assert {path.name: path.read_bytes() for path in venue.iterdir()} == before
    recovered = publish(case, venue)
    assert recovered == retained
    assert recovered.receipt() == retained.receipt()
    assert (venue / recovered.artifact_name).read_bytes() == retained.artifact
    assert inspect(case, venue) == (retained, "present")


def test_conflicting_previous_copy_holds_before_next_commit(case: Case, venue: Path) -> None:
    first = publish(case, venue)
    _write(venue / first.artifact_name, b"conflicting copy")
    before = (venue / journal._DATABASE).read_bytes()
    case.source["revision_id"] = "b" * 40
    _write(case.root / "source.json", case.source)
    with pytest.raises(ValueError, match="will not be overwritten"):
        publish(case, venue, first.package.digest)
    assert (venue / journal._DATABASE).read_bytes() == before
    assert (venue / first.artifact_name).read_bytes() == b"conflicting copy"


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "empty",
        "corrupt",
        "schema",
        "receipt",
        "sequence",
        "orphan",
        "pending-journal",
        "wal",
    ],
)
def test_damaged_state_is_not_reset(case: Case, venue: Path, damage: str) -> None:
    publish(case, venue)
    database = venue / journal._DATABASE
    if damage == "missing":
        database.unlink()
    elif damage in {"empty", "corrupt"}:
        _write(database, b"" if damage == "empty" else b"not a SQLite database")
    elif damage == "orphan":
        _write(venue / "unbound.json", b"unbound retained artifact")
    elif damage == "pending-journal":
        _write(venue / (journal._DATABASE + "-journal"), b"unresolved transaction journal")
    else:
        with sqlite3.connect(database) as connection:
            if damage == "wal":
                connection.execute("PRAGMA journal_mode=WAL")
            elif damage == "schema":
                connection.execute("PRAGMA user_version=99")
            elif damage == "receipt":
                connection.execute("UPDATE packages SET receipt=?", (b"{}",))
            else:
                connection.execute("UPDATE packages SET sequence=2")
    before = {path.name: path.read_bytes() for path in venue.iterdir()}
    for operation in (lambda: publish(case, venue), lambda: inspect(case, venue)):
        with pytest.raises((ValueError, OSError, sqlite3.Error)):
            operation()
        assert {path.name: path.read_bytes() for path in venue.iterdir()} == before


@pytest.mark.parametrize("target", ["database", "artifact"])
@pytest.mark.parametrize("damage", ["mode", "symlink", "hardlink"])
def test_private_state_and_copies_are_not_unsafe_links(
    case: Case,
    venue: Path,
    target: str,
    damage: str,
) -> None:
    first = publish(case, venue)
    path = venue / (journal._DATABASE if target == "database" else first.artifact_name)
    if damage == "mode":
        path.chmod(0o644)
    elif damage == "hardlink":
        (case.root / "outside-copy").hardlink_to(path)
    else:
        outside = case.root / "outside-copy"
        path.rename(outside)
        path.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        publish(case, venue)
    with pytest.raises((ValueError, OSError)):
        inspect(case, venue)


def test_competing_fresh_process_cannot_publish_while_writer_holds_venue(
    case: Case, venue: Path
) -> None:
    started, release = Event(), Event()

    def held(history: Sequence[SignedConfigurationPackage]) -> SignedConfigurationPackage:
        started.set()
        assert release.wait(10)
        return build(case, history)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            journal.publish,
            venue,
            "a" * 40,
            held,
            lambda history, package: verify(case, history, package),
            initial=True,
        )
        try:
            assert started.wait(5)
            refused = case.invoke(*command(case, venue, "publish", "--initial-publication"))
            assert refused.returncode == 3, refused.stderr
            assert "not confirmed" in refused.stderr
        finally:
            release.set()
        first = future.result(timeout=10)
    assert inspect(case, venue) == (first, "present")
    assert publish(case, venue) == first


@pytest.mark.parametrize("multi", [False, True])
def test_fresh_process_publish_and_readonly_inspection(
    case: Case, venue: Path, multi: bool
) -> None:
    if multi:
        _multi_entity(case)
    args = command(case, venue, "publish", "--initial-publication")
    first = case.invoke(*args)
    assert first.returncode == 0, first.stderr
    result = json.loads(first.stdout)
    assert json.loads(case.invoke(*args).stdout) == result
    assert result["local_only"] and result["verified"]
    assert result["publication_confirmed"] is True
    assert result["git_review"] == result["global_publisher_identity"] == "unverified"
    for name in ("trust_registered", "hub_accepted", "deployment_activated", "execution_authority"):
        assert result[name] is False
    (case.root / "source.json").unlink()
    (case.root / "signing.pem").unlink()
    before = {path.name: path.read_bytes() for path in venue.iterdir()}
    observed = case.invoke(*command(case, venue, "inspect-publication"))
    assert observed.returncode == 0, observed.stderr
    assert json.loads(observed.stdout)["receipt"] == result["receipt"]
    assert {path.name: path.read_bytes() for path in venue.iterdir()} == before


def test_real_process_exit_after_commit_is_inspectable(
    case: Case, venue: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    interrupted_entry = cli_cases.ENTRY.replace(
        "raise SystemExit(main())",
        "from fdai_deployment_cli import lifecycle_configuration_publication as journal\n"
        "original = journal._artifact_state\n"
        "def interrupted(venue, record, *, materialize):\n"
        "    if materialize:\n"
        "        import os\n"
        "        os._exit(67)\n"
        "    return original(venue, record, materialize=False)\n"
        "journal._artifact_state = interrupted\n"
        "raise SystemExit(main())",
    )
    args = command(case, venue, "publish", "--initial-publication")
    with monkeypatch.context() as patch:
        patch.setattr(cli_cases, "ENTRY", interrupted_entry)
        interrupted = case.invoke(*args)
    assert interrupted.returncode == 67
    retained = case.invoke(*command(case, venue, "inspect-publication"))
    assert retained.returncode == 0, retained.stderr
    receipt = json.loads(retained.stdout)
    assert receipt["artifact_state"] == "missing"
    assert receipt["publication_confirmed"] is False
    recovered = case.invoke(*args)
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout)["receipt"] == receipt["receipt"]
    assert json.loads(recovered.stdout)["publication_confirmed"] is True


@pytest.mark.parametrize("field", ["configuration.pem", "installation.pem", "release.json"])
def test_independent_context_mismatch_does_not_advance(case: Case, venue: Path, field: str) -> None:
    first = publish(case, venue)
    before = (venue / journal._DATABASE).read_bytes()
    _write(case.root / field, b"invalid independent public context")
    with pytest.raises(ValueError):
        inspect(case, venue)
    with pytest.raises(ValueError):
        publish(case, venue)
    assert (venue / journal._DATABASE).read_bytes() == before
    assert (venue / first.artifact_name).read_bytes() == first.artifact


@pytest.mark.parametrize("operation", ["inspect", "current", "historical"])
def test_independent_reader_rejects_resummarized_signature_tampering(
    case: Case,
    venue: Path,
    operation: str,
) -> None:
    first = publish(case, venue)
    case.source["revision_id"] = "b" * 40
    _write(case.root / "source.json", case.source)
    second = publish(case, venue, first.package.digest)
    signature = second.package.signature
    invalid = SignedConfigurationPackage(
        second.package.payload, bytes([signature[0] ^ 1]) + signature[1:]
    )
    forged = replace(second, package=invalid, artifact=configuration_artifact_bytes(invalid))
    with sqlite3.connect(venue / journal._DATABASE) as connection:
        connection.execute(
            "UPDATE packages SET receipt=?, artifact=? WHERE sequence=2",
            (canonical_bytes(forged.receipt()), forged.artifact),
        )
    _write(venue / second.artifact_name, forged.artifact)
    before = (venue / journal._DATABASE).read_bytes()
    if operation == "historical":
        case.source["revision_id"] = "a" * 40
        _write(case.root / "source.json", case.source)
    with pytest.raises(ValueError):
        if operation == "inspect":
            inspect(case, venue)
        else:
            publish(case, venue, None if operation == "historical" else first.package.digest)
    assert (venue / journal._DATABASE).read_bytes() == before


@pytest.mark.parametrize("revision", ["main", "A" * 40, "a" * 39, "a" * 41])
def test_fresh_process_invalid_revision_is_redacted_before_state(
    case: Case,
    venue: Path,
    revision: str,
) -> None:
    case.source["revision_id"] = revision
    _write(case.root / "source.json", case.source)
    result = case.invoke(*command(case, venue, "publish", "--initial-publication"))
    assert result.returncode == 3
    assert not result.stdout and "not confirmed" in result.stderr
    assert "Traceback" not in result.stderr
    assert "PRIVATE KEY" not in result.stderr
    assert "private-identifier" not in result.stderr
    assert not list(venue.iterdir())


def test_current_and_historical_retry_do_not_encrypt_again(
    case: Case,
    venue: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = publish(case, venue)
    case.source["revision_id"] = "b" * 40
    _write(case.root / "source.json", case.source)
    second = publish(case, venue, first.package.digest)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("an exact retry must return retained bytes without encryption")

    monkeypatch.setattr(package_builder, "seal_identifiers", forbidden)
    assert publish(case, venue, first.package.digest) == second
    case.source["revision_id"] = "a" * 40
    _write(case.root / "source.json", case.source)
    assert publish(case, venue) == first


@pytest.mark.parametrize("operation", ["publish", "inspect-publication"])
def test_new_help_is_available_without_inputs_or_tools(case: Case, operation: str) -> None:
    result = case.invoke("configuration", operation, "--help")
    assert result.returncode == 0
    assert "--state-dir" in result.stdout
    assert "unverified" in result.stdout
    assert (
        "--signing-key" in result.stdout
        if operation == "publish"
        else "--signing-key" not in result.stdout
    )
