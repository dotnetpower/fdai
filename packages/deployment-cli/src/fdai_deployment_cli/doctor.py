"""Read-only local deployment prerequisite inspection."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolCheck:
    """One non-secret tool availability result."""

    name: str
    available: bool
    version: str | None


def inspect_tools(names: tuple[str, ...] = ("az", "terraform", "gh")) -> tuple[ToolCheck, ...]:
    """Inspect required executables without installing or authenticating."""

    results: list[ToolCheck] = []
    for name in names:
        executable = shutil.which(name)
        if executable is None:
            results.append(ToolCheck(name=name, available=False, version=None))
            continue
        completed = subprocess.run(
            [executable, "version" if name == "terraform" else "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (completed.stdout or completed.stderr).splitlines()
        version = output[0][:256] if completed.returncode == 0 and output else None
        results.append(ToolCheck(name=name, available=completed.returncode == 0, version=version))
    return tuple(results)


def doctor_json(checks: tuple[ToolCheck, ...]) -> str:
    """Return stable doctor output."""

    return json.dumps(
        {
            "schema_version": "fdai.doctor.v1",
            "ready": all(check.available for check in checks),
            "mutation_performed": False,
            "tools": [
                {
                    "name": check.name,
                    "available": check.available,
                    "version": check.version,
                }
                for check in checks
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
