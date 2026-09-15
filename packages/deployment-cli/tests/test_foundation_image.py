from __future__ import annotations

import json
import subprocess

import pytest

from fdai_deployment_cli.foundation_image import verify_foundation_runner_image

IMAGE_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/"
    "providers/Microsoft.Compute/images/runner"
)


def _variables() -> dict[str, object]:
    return {
        "runner_bootstrap_mode": "offline",
        "runner_marketplace_image_version": "",
        "runner_source_image_id": IMAGE_ID,
        "runner_image_toolchain_digest": "a" * 64,
        "source_commit": "b" * 40,
    }


def _run(observed: dict[str, object], *, returncode: int = 0):
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[:3] == ["az", "resource", "show"]
        assert command[command.index("--ids") + 1] == IMAGE_ID
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == 60
        return subprocess.CompletedProcess(command, returncode, json.dumps(observed), "opaque")

    return run


def _observation() -> dict[str, object]:
    return {
        "id": IMAGE_ID,
        "type": "Microsoft.Compute/images",
        "location": "koreacentral",
        "provisioningState": "Succeeded",
        "managedOsType": "Linux",
        "galleryOsType": None,
        "tags": {
            "fdai:source-commit": "b" * 40,
            "fdai:toolchain-digest": "a" * 64,
        },
    }


def test_exact_runner_image_observation_returns_only_a_digest() -> None:
    digest = verify_foundation_runner_image(
        _variables(), expected_region="koreacentral", run=_run(_observation())
    )

    assert len(digest) == 64
    assert IMAGE_ID not in digest


def test_runner_image_observation_uses_original_image_source() -> None:
    variables = _variables()
    variables["source_commit"] = "c" * 40
    variables["runner_image_source_commit"] = "b" * 40

    digest = verify_foundation_runner_image(
        variables, expected_region="koreacentral", run=_run(_observation())
    )

    assert len(digest) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", IMAGE_ID + "-other"),
        ("type", "Microsoft.Compute/virtualMachines"),
        ("location", "eastus"),
        ("provisioningState", "Creating"),
        ("managedOsType", "Windows"),
        ("tags", {}),
    ],
)
def test_runner_image_mismatch_fails_without_provider_output(field: str, value: object) -> None:
    observed = _observation()
    observed[field] = value

    with pytest.raises(ValueError, match="provenance") as raised:
        verify_foundation_runner_image(
            _variables(), expected_region="koreacentral", run=_run(observed)
        )

    assert IMAGE_ID not in str(raised.value)


def test_missing_runner_image_fails_with_stable_error() -> None:
    with pytest.raises(ValueError, match="unavailable") as raised:
        verify_foundation_runner_image(
            _variables(),
            expected_region="koreacentral",
            run=_run({}, returncode=3),
        )

    assert "opaque" not in str(raised.value)


def test_exact_marketplace_image_observation_returns_only_a_digest() -> None:
    variables = {
        "runner_bootstrap_mode": "online",
        "runner_marketplace_image_version": "24.04.202509010",
        "runner_source_image_id": "",
        "runner_image_toolchain_digest": "a" * 64,
        "source_commit": "b" * 40,
    }

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[:4] == ["az", "vm", "image", "show"]
        assert command[command.index("--urn") + 1] == (
            "Canonical:ubuntu-24_04-lts:server:24.04.202509010"
        )
        query = command[command.index("--query") + 1]
        assert "osType:osDiskImage.operatingSystem" in query
        assert "hyperVGeneration:hyperVGeneration" in query
        assert "properties." not in query
        assert kwargs["timeout"] == 60
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "version": "24.04.202509010",
                    "location": "koreacentral",
                    "osType": "Linux",
                    "hyperVGeneration": "V2",
                }
            ),
            "",
        )

    digest = verify_foundation_runner_image(
        variables,
        expected_region="koreacentral",
        run=run,
    )

    assert len(digest) == 64
    assert "24.04.202509010" not in digest


def test_marketplace_image_version_mismatch_fails_closed() -> None:
    variables = {
        "runner_bootstrap_mode": "online",
        "runner_marketplace_image_version": "24.04.202509010",
        "runner_source_image_id": "",
        "runner_image_toolchain_digest": "a" * 64,
        "source_commit": "b" * 40,
    }

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "version": "24.04.202508010",
                    "location": "koreacentral",
                    "osType": "Linux",
                    "hyperVGeneration": "V2",
                }
            ),
            "",
        )

    with pytest.raises(ValueError, match="does not match"):
        verify_foundation_runner_image(
            variables,
            expected_region="koreacentral",
            run=run,
        )
