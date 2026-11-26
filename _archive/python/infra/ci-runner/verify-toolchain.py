#!/usr/bin/env python3
"""Verify that a self-hosted CI runner matches the declared toolchain manifest.

The runner never installs anything here. It reports every missing or drifted item at once
so a new or rebuilt runner fails before it accepts regression jobs, not mid-suite.
Executables must resolve the way the repository's own trusted-tool lookup does: a regular,
root- or self-owned file under a fixed installation root that is not group/world writable.
"""

from __future__ import annotations

import argparse
import ctypes.util
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TRUSTED_ROOTS = (Path("/usr/bin"), Path("/usr/local/bin"))
DEFAULT_MANIFEST = Path(__file__).with_name("toolchain.json")


def trusted_executable(name: str, roots: tuple[Path, ...] = TRUSTED_ROOTS) -> str | None:
    """Return the resolved executable only when it passes the trusted-tool rules."""
    for root in roots:
        try:
            resolved = (root / name).resolve(strict=True)
            details = resolved.stat()
        except OSError:
            continue
        if (
            stat.S_ISREG(details.st_mode)
            and not details.st_mode & 0o022
            and details.st_uid in {0, os.getuid()}
            and os.access(resolved, os.X_OK)
        ):
            return str(resolved)
    return None


def load_manifest(path: Path) -> dict[str, object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "fdai.ci-runner-toolchain.v1":
        raise ValueError("unsupported toolchain manifest schema")
    return manifest


def version_output(executable: str, arguments: list[str]) -> str:
    environment = {**os.environ, "HOME": os.environ.get("HOME") or tempfile.gettempdir()}
    result = subprocess.run(  # noqa: S603 - fixed manifest arguments, trusted executable
        [executable, *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result.stdout + result.stderr


def verify(manifest: dict[str, object], roots: tuple[Path, ...] = TRUSTED_ROOTS) -> list[str]:
    """Return stable, secret-free findings; an empty list means the runner conforms."""
    findings: list[str] = []
    for name in manifest["system_tools"]:  # type: ignore[union-attr]
        if trusted_executable(str(name), roots) is None:
            findings.append(f"missing-tool:{name}")
    for name, spec in manifest["pinned_tools"].items():  # type: ignore[union-attr]
        executable = trusted_executable(name, roots)
        if executable is None:
            findings.append(f"missing-tool:{name}")
            continue
        try:
            output = version_output(executable, list(spec["version_args"]))
        except (OSError, subprocess.SubprocessError):
            findings.append(f"unrunnable-tool:{name}")
            continue
        if str(spec["version"]) not in output:
            findings.append(f"version-drift:{name}:expected-{spec['version']}")
    for library in manifest["libraries"]:  # type: ignore[union-attr]
        if ctypes.util.find_library(str(library)) is None:
            findings.append(f"missing-library:{library}")
    for timezone in manifest.get("timezones", []):  # type: ignore[union-attr]
        try:
            ZoneInfo(str(timezone))
        except ZoneInfoNotFoundError:
            findings.append(f"missing-timezone:{timezone}")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    arguments = parser.parse_args(argv)
    findings = verify(load_manifest(arguments.manifest))
    if findings:
        print("runner toolchain drift: " + ", ".join(findings), file=sys.stderr)
        print(
            "re-run infra/ci-runner/provision-toolchain.sh as root on this runner", file=sys.stderr
        )
        return 1
    print("runner toolchain conforms to the manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
