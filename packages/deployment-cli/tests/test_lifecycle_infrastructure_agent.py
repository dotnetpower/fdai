from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from fdai_deployment_cli.lifecycle_installation_binding import write_installation_binding


def test_installation_binding_writer_writes_exact_private_envelope(tmp_path: Path) -> None:
    path = tmp_path / "installation-binding.json"

    write_installation_binding(
        path,
        {"event-bus.endpoint": "kafka:9093"},
        allowed_keys=frozenset({"event-bus.endpoint"}),
    )

    assert json.loads(path.read_text()) == {
        "format": "fdai.installation-binding.v1",
        "values": {"event-bus.endpoint": "kafka:9093"},
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("values", "allowed_keys", "message"),
    [
        (
            {"event-bus.endpoint": "kafka:9093", "unreviewed.output": "value"},
            frozenset({"event-bus.endpoint"}),
            "names a key",
        ),
        ({}, frozenset({"event-bus.endpoint"}), "lacks a key"),
        ({"INVALID": "value"}, frozenset({"INVALID"}), "key is invalid"),
    ],
)
def test_installation_binding_writer_requires_exact_reviewed_outputs(
    tmp_path: Path,
    values: dict[str, object],
    allowed_keys: frozenset[str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        write_installation_binding(
            tmp_path / "installation-binding.json",
            values,
            allowed_keys=allowed_keys,
        )


def test_installation_binding_writer_rejects_credentials_without_echoing_them(
    tmp_path: Path,
) -> None:
    secret = "******example.test"

    with pytest.raises(ValueError) as caught:
        write_installation_binding(
            tmp_path / "installation-binding.json",
            {"event-bus.endpoint": secret},
            allowed_keys=frozenset({"event-bus.endpoint"}),
        )

    assert secret not in str(caught.value)


def test_installation_binding_writer_never_replaces_existing_output(tmp_path: Path) -> None:
    path = tmp_path / "installation-binding.json"
    values = {"event-bus.endpoint": "kafka:9093"}
    allowed = frozenset(values)
    write_installation_binding(path, values, allowed_keys=allowed)

    with pytest.raises(FileExistsError):
        write_installation_binding(path, values, allowed_keys=allowed)
