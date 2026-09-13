from __future__ import annotations

from fdai_deployment_cli.standalone_deploy import _standalone_subprocess_environment


def test_standalone_subprocess_environment_drops_ambient_secrets() -> None:
    result = _standalone_subprocess_environment(
        {
            "PATH": "/usr/bin",
            "HOME": "/home/operator",
            "AZURE_CONFIG_DIR": "/home/operator/.azure",
            "ARM_CLIENT_SECRET": "do-not-copy",
            "AZURE_CLIENT_SECRET": "do-not-copy",
            "GITHUB_TOKEN": "do-not-copy",
            "GH_TOKEN": "do-not-copy",
        },
        AZURE_SUBSCRIPTION_ID="00000000-0000-0000-0000-000000000001",
    )

    assert result == {
        "PATH": "/usr/bin",
        "HOME": "/home/operator",
        "AZURE_CONFIG_DIR": "/home/operator/.azure",
        "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000001",
    }
