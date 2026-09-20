#!/usr/bin/env python3
"""Retire empty introspection groups belonging to stopped local processes."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable

GROUP = re.compile(r"fdai-agent-introspection-server\.local-([1-9][0-9]*)\.[0-9a-f]{12}")
MAX_GROUPS = 32


def process_exists(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OverflowError):
        return True
    return True


def candidates(output: str, *, alive: Callable[[int], bool] = process_exists) -> list[str]:
    lines = output.splitlines()
    if not lines or lines[0].split() != ["BROKER", "GROUP", "STATE"]:
        raise ValueError("unexpected local broker group listing")
    selected: set[str] = set()
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 3 or not fields[0].isdigit():
            raise ValueError("invalid local broker group row")
        match = GROUP.fullmatch(fields[1])
        if match and fields[2] == "Empty" and not alive(int(match.group(1))):
            selected.add(fields[1])
    return sorted(selected)[:MAX_GROUPS]


def cleanup(
    *, apply: bool, run: Callable[..., str], alive: Callable[[int], bool]
) -> dict[str, int]:
    selected = candidates(run("exec", "fdai-redpanda", "rpk", "group", "list"), alive=alive)
    removed = 0
    for group in selected if apply else ():
        current = candidates(run("exec", "fdai-redpanda", "rpk", "group", "list"), alive=alive)
        if group not in current:
            continue
        result = run("exec", "fdai-redpanda", "rpk", "group", "delete", group)
        rows = [line.split() for line in result.splitlines() if line.strip()]
        if rows != [["GROUP", "STATUS"], [group, "OK"]]:
            raise ValueError("local broker did not confirm group deletion")
        remaining = candidates(
            run("exec", "fdai-redpanda", "rpk", "group", "list"), alive=lambda _pid: False
        )
        if group in remaining:
            raise ValueError("local broker group deletion was not observed")
        removed += 1
    return {"candidates": len(selected), "removed": removed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    docker = shutil.which("docker")
    if docker is None or not os.path.isdir("/proc"):
        parser.error("local Linux Docker is required")
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        parser.error("Docker endpoint overrides are not accepted")
    deadline = time.monotonic() + 30

    def run(*parts: str) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("local broker cleanup deadline exceeded")
        return subprocess.run(
            [docker, *parts],
            check=True,
            capture_output=True,
            text=True,
            timeout=min(5, remaining),
        ).stdout

    try:
        contexts = json.loads(run("context", "inspect"))
        if len(contexts) != 1 or not contexts[0]["Endpoints"]["docker"]["Host"].startswith(
            "unix://"
        ):
            raise ValueError("Docker must use a local Unix socket")
        result = cleanup(apply=arguments.apply, run=run, alive=process_exists)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("local-broker-cleanup: unavailable; no further groups changed")
        return 1
    print(f"local-broker-cleanup: {json.dumps(result, sort_keys=True)} apply={arguments.apply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
