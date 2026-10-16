from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_DOCTOR = Path(__file__).resolve().parents[3] / "tools" / "dev-access" / "scripts" / "doctor.sh"


@pytest.mark.parametrize(
    ("dns_tunneling", "direct_answer", "expected_error"),
    [
        ("true", "192.0.2.10", ""),
        ("true", None, ""),
        ("false", "192.0.2.10", ""),
        ("false", None, "manual DNS verification requires dig"),
        ("false", "192.0.2.11", "WSL DNS and Private DNS Resolver disagree"),
    ],
)
def test_doctor_checks_effective_dns_with_or_without_tunneling(
    tmp_path: Path,
    dns_tunneling: str,
    direct_answer: str | None,
    expected_error: str,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    config = tmp_path / ".wslconfig"
    config.write_text(
        f"[wsl2]\nnetworkingMode=mirrored\ndnsTunneling={dns_tunneling}\n", encoding="utf-8"
    )
    for name in ("bash", "dirname", "tr", "awk"):
        executable = shutil.which(name)
        assert executable is not None
        (fake_bin / name).symlink_to(executable)
    commands = {
        "grep": "exit 0",
        "cmd.exe": "printf 'example-profile\\r\\n'",
        "wslpath": "printf '%s\\n' \"${FDAI_TEST_WSL_CONFIG}\"",
        "terraform": "printf '192.0.2.53\\n'",
        "getent": "printf '192.0.2.10 STREAM private.example.com\\n'",
        "ip": "printf '192.0.2.10 dev vpn0\\n'",
    }
    if direct_answer is not None:
        commands["dig"] = f"printf '{direct_answer}\\n'"
    for name, body in commands.items():
        path = fake_bin / name
        path.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{body}\n", encoding="utf-8")
        path.chmod(0o755)
    bash = shutil.which("bash")
    assert bash is not None
    completed = subprocess.run(  # noqa: S603 - controlled script and command stubs.
        [bash, str(_DOCTOR), "private.example.com"],
        env={
            **os.environ,
            "PATH": str(fake_bin),
            "FDAI_TEST_WSL_CONFIG": str(config),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    if expected_error:
        assert completed.returncode == 1
        assert expected_error in completed.stderr
        assert "ok:" not in completed.stdout
    else:
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout == "ok: private.example.com -> 192.0.2.10\n"
