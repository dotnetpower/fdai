from __future__ import annotations

import subprocess

from fdai_deployment_cli import doctor


def test_azure_authentication_is_read_only_and_redacted(monkeypatch: object) -> None:
    calls: list[list[str]] = []

    def which(name: str) -> str:
        assert name == "az"
        return "/usr/bin/az"

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(doctor.shutil, "which", which)  # type: ignore[attr-defined]
    monkeypatch.setattr(doctor.subprocess, "run", run)  # type: ignore[attr-defined]

    assert doctor.azure_cli_authenticated()
    assert calls == [
        [
            "/usr/bin/az",
            "account",
            "show",
            "--output",
            "none",
            "--only-show-errors",
        ]
    ]


def test_azure_authentication_fails_closed_without_login(monkeypatch: object) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/az")  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        doctor.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1),
    )

    assert not doctor.azure_cli_authenticated()


def test_doctor_readiness_requires_azure_authentication() -> None:
    checks = (
        doctor.ToolCheck(name="az", available=True, version="test"),
        doctor.ToolCheck(name="terraform", available=True, version="test"),
        doctor.ToolCheck(name="gh", available=True, version="test"),
    )

    unavailable = doctor.doctor_json(checks, azure_authenticated=False)
    available = doctor.doctor_json(checks, azure_authenticated=True)

    assert '"ready":false' in unavailable
    assert "azure_authentication_missing" in unavailable
    assert '"ready":true' in available


def test_active_target_binding_is_stable_and_identifier_free(monkeypatch: object) -> None:
    subscription = "00000000-0000-0000-0000-000000000001"
    tenant = "00000000-0000-0000-0000-000000000002"
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/az")  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        doctor.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [],
            0,
            stdout=f'{{"subscription":"{subscription}","tenant":"{tenant}"}}',
        ),
    )

    binding = doctor.azure_active_target_binding()
    assert binding is not None
    assert len(binding) == 64
    assert subscription not in binding
    assert tenant not in binding
