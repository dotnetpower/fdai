"""Shell task artifacts stay offline, credential-free, and host-confined."""

from fdai.core.python_task.shell_validator import validate_shell_task
from fdai.shared.providers.command_runner import CommandNetworkProfile
from fdai.shared.providers.shell_task import ShellTaskFile, ShellTaskSpec


def _task(source: str, **overrides: object) -> ShellTaskSpec:
    values = {
        "task_id": "repo.verify",
        "version": "1.0.0",
        "entrypoint": "run.sh",
        "files": (ShellTaskFile(path="run.sh", content=source),),
        "required_command_ids": ("local.git.diff", "local.python.pytest"),
    }
    values.update(overrides)
    return ShellTaskSpec(**values)  # type: ignore[arg-type]


def test_accepts_local_pipeline_loop_and_heredoc() -> None:
    task = _task(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "for path in src tests; do\n"
        "  printf '%s\\n' \"$path\"\n"
        "done | jq -R .\n"
        "python - <<'PY'\n"
        "print('ok')\n"
        "PY\n"
    )

    report = validate_shell_task(task)

    assert report.valid
    assert report.artifact_hash == task.artifact_hash


def test_rejects_cloud_cli_privilege_and_metadata_access() -> None:
    task = _task(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "az account show\n"
        "sudo cat /etc/shadow\n"
        "curl http://169.254.169.254/metadata/identity/oauth2/token\n"
    )

    report = validate_shell_task(task)
    codes = {issue.code for issue in report.issues}

    assert not report.valid
    assert {"forbidden_command", "host_path", "metadata_endpoint"} <= codes


def test_rejects_absolute_cli_and_process_launch_wrappers() -> None:
    task = _task(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "/usr/bin/az account show\n"
        "env python -V\n"
        "printf '%s\\n' az | xargs -n1\n"
    )

    report = validate_shell_task(task)

    assert not report.valid
    assert sum(issue.code == "forbidden_command" for issue in report.issues) == 3


def test_rejects_network_profile_and_unsafe_shell_modes() -> None:
    task = _task(
        '#!/usr/bin/env bash\nset -x\neval "$COMMAND"\n',
        network_profile=CommandNetworkProfile.AZURE_CONTROL_PLANE,
    )

    report = validate_shell_task(task)
    codes = {issue.code for issue in report.issues}

    assert not report.valid
    assert {
        "network_profile_forbidden",
        "strict_mode_required",
        "unsafe_shell_mode",
        "dynamic_shell",
    } <= codes


def test_hash_changes_with_source_and_command_requirements() -> None:
    first = _task("#!/bin/bash\nset -euo pipefail\nprintf ok\n")
    changed_source = _task("#!/bin/bash\nset -euo pipefail\nprintf changed\n")
    changed_commands = _task(
        "#!/bin/bash\nset -euo pipefail\nprintf ok\n",
        required_command_ids=("local.jq",),
    )

    assert first.artifact_hash != changed_source.artifact_hash
    assert first.artifact_hash != changed_commands.artifact_hash
