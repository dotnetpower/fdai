"""The notifications add-on takes its recipients from one private, never-committed input."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai_deployment_cli import notification_recipients_input as module
from fdai_deployment_cli.private_output import write_private_bytes


def _write(directory: Path, payload: object, name: str = "recipients.json") -> Path:
    directory.chmod(0o700)
    path = directory / name
    write_private_bytes(path, json.dumps(payload).encode())
    return path


class _Tunnel:
    def __init__(self) -> None:
        self.copied: list[tuple[Path, str]] = []

    def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
        self.copied.append((source, destination))


def test_valid_list_is_deduplicated_sorted_and_digested(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {"recipients": ["b@contoso.io", " A@contoso.io ", "a@CONTOSO.io", "b@contoso.io"]},
    )

    value = module.load_notification_recipients(path)

    assert value.recipients == ("A@contoso.io", "b@contoso.io")
    assert len(value.input_digest) == 64
    reordered = _write(
        tmp_path, {"recipients": ["b@contoso.io", "A@contoso.io"]}, name="other.json"
    )
    assert module.load_notification_recipients(reordered).input_digest == value.input_digest


def test_repr_never_discloses_an_address(tmp_path: Path) -> None:
    value = module.load_notification_recipients(
        _write(tmp_path, {"recipients": ["person@contoso.io"]})
    )

    assert "person" not in repr(value)
    assert "contoso" not in repr(value)


@pytest.mark.parametrize(
    "payload",
    [
        {"recipients": []},
        {"recipients": "person@contoso.io"},
        {"recipients": [1]},
        {"recipients": ["not-an-address"]},
        {"recipients": ["a b@contoso.io"]},
        {"recipients": ["person@example.com"]},
        {"recipients": ["person@Example.ORG"]},
        {"recipients": [f"user{index}@contoso.io" for index in range(21)]},
        {"recipients": ["person@contoso.io"], "extra": True},
        {},
    ],
)
def test_invalid_input_fails_closed(tmp_path: Path, payload: object) -> None:
    with pytest.raises(ValueError):
        module.load_notification_recipients(_write(tmp_path, payload))


def test_input_must_be_a_private_json_object(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="MUST be a JSON object"):
        module.load_notification_recipients(_write(tmp_path, ["person@contoso.io"]))
    shared = _write(tmp_path, {"recipients": ["person@contoso.io"]}, name="shared.json")
    shared.chmod(0o644)
    with pytest.raises((ValueError, PermissionError, OSError)):
        module.load_notification_recipients(shared)


def test_staging_round_trips_and_rejects_a_changed_digest(tmp_path: Path) -> None:
    value = module.load_notification_recipients(
        _write(tmp_path, {"recipients": ["person@contoso.io"]})
    )
    prepared = tmp_path / "prepared"
    prepared.mkdir(mode=0o700)
    tunnel = _Tunnel()

    arguments = module.stage_notification_recipients(
        value, tunnel=tunnel, prepared_root=prepared, remote_root="/home/runner/.fdai-transfer-x"
    )

    assert arguments == (
        "--notification-recipients",
        "/home/runner/.fdai-transfer-x/notification-recipients-input.json",
    )
    staged = tunnel.copied[0][0]
    assert module.staged_notification_recipients_from_path(staged) == value
    tampered = json.loads(staged.read_text())
    tampered["input_digest"] = "sha256:" + "0" * 64
    staged.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="digest differs"):
        module.staged_notification_recipients_from_path(staged)
    assert (
        module.stage_notification_recipients(
            None, tunnel=tunnel, prepared_root=prepared, remote_root="/r"
        )
        == ()
    )
    assert module.staged_notification_recipients_from_path(None) is None


def test_apply_sets_only_the_terraform_recipient_list(tmp_path: Path) -> None:
    value = module.load_notification_recipients(
        _write(tmp_path, {"recipients": ["person@contoso.io"]})
    )
    values: dict[str, object] = {}

    module.apply_notification_recipients(values, None)
    assert values == {}
    module.apply_notification_recipients(values, value)
    assert values == {"notification_email_recipients": ["person@contoso.io"]}


def test_add_on_and_input_must_agree_before_any_azure_effect(tmp_path: Path) -> None:
    value = module.load_notification_recipients(
        _write(tmp_path, {"recipients": ["person@contoso.io"]})
    )

    module.require_recipients_for_notifications(notifications_selected=True, value=value)
    module.require_recipients_for_notifications(notifications_selected=False, value=None)
    with pytest.raises(ValueError, match="requires --notification-recipients"):
        module.require_recipients_for_notifications(notifications_selected=True, value=None)
    with pytest.raises(ValueError, match="requires the notifications add-on"):
        module.require_recipients_for_notifications(notifications_selected=False, value=value)


def test_retained_context_binds_once_and_rejects_drift(tmp_path: Path) -> None:
    first = module.load_notification_recipients(
        _write(tmp_path, {"recipients": ["person@contoso.io"]})
    )
    second = module.load_notification_recipients(
        _write(tmp_path, {"recipients": ["other@contoso.io"]}, name="second.json")
    )
    retained: dict[str, object] = {}
    values: dict[str, object] = {}

    assert module.reconcile_retained_notification_recipients(
        first, retained=retained, values=values
    )
    assert retained["notification_recipients_digest"] == first.input_digest
    assert values == {"notification_email_recipients": ["person@contoso.io"]}
    assert not module.reconcile_retained_notification_recipients(
        first, retained=retained, values={}
    )
    with pytest.raises(ValueError, match="retained context differs"):
        module.reconcile_retained_notification_recipients(second, retained=retained, values={})
    with pytest.raises(ValueError, match="retained context differs"):
        module.reconcile_retained_notification_recipients(None, retained=retained, values={})
    assert not module.reconcile_retained_notification_recipients(None, retained={}, values={})
    assert module.context_digest(first) == first.input_digest
    assert module.context_digest(None) == ""


def _args(*extra: str):
    from fdai_deployment_cli import cli

    return cli._parser().parse_args(
        ["provision", "azure", "--source", "checkout", "--runtime", "aks", *extra]
    )


def test_public_cli_exposes_the_private_recipients_path() -> None:
    args = _args("--notification-recipients", "recipients.json")

    assert args.notification_recipients == Path("recipients.json")


def test_cli_rejects_the_add_on_without_recipients_before_any_effect() -> None:
    from fdai_deployment_cli import cli

    with pytest.raises(ValueError, match="requires --notification-recipients"):
        cli._provision_azure(_args("--add-on", "notifications"))


def test_cli_rejects_recipients_without_the_add_on(tmp_path: Path) -> None:
    from fdai_deployment_cli import cli

    path = _write(tmp_path, {"recipients": ["person@contoso.io"]})

    with pytest.raises(ValueError, match="requires the notifications add-on"):
        cli._provision_azure(_args("--notification-recipients", str(path)))


def test_cli_rejects_recipients_outside_a_source_aks_deployment(tmp_path: Path) -> None:
    from fdai_deployment_cli import cli

    path = _write(tmp_path, {"recipients": ["person@contoso.io"]})
    args = cli._parser().parse_args(
        [
            "provision",
            "azure",
            "--offline-kit",
            "kit.tar.gz",
            "--add-on",
            "notifications",
            "--notification-recipients",
            str(path),
        ]
    )

    with pytest.raises(ValueError, match="source deployment with --runtime aks"):
        cli._provision_azure(args)
