#!/usr/bin/env python3
"""Reset the dedicated local FDAI broker after development database recreation."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable

_MAX_RESOURCES = 256
_STARTUP_TOPIC = "fdai.startup.probes"
_GROUP_SETTLE_SECONDS = 30
_RESET_DEADLINE_SECONDS = 45


def topics(output: str) -> tuple[str, ...]:
    lines = [line.split() for line in output.splitlines() if line.strip()]
    if not lines or lines[0] != ["NAME", "PARTITIONS", "REPLICAS"]:
        raise ValueError("unexpected local broker topic listing")
    selected = tuple(sorted(row[0] for row in lines[1:] if len(row) == 3))
    if len(selected) > _MAX_RESOURCES:
        raise ValueError("local broker topic count exceeds reset bound")
    return selected


def groups(output: str) -> tuple[str, ...]:
    lines = [line.split() for line in output.splitlines() if line.strip()]
    if not lines or lines[0] != ["BROKER", "GROUP", "STATE"]:
        raise ValueError("unexpected local broker group listing")
    rows = lines[1:]
    if any(len(row) != 3 or not row[0].isdigit() for row in rows):
        raise ValueError("invalid local broker group row")
    active = sorted(row[1] for row in rows if row[2] != "Empty")
    if active:
        raise RuntimeError("local broker reset requires every consumer group to be empty")
    selected = tuple(sorted(row[1] for row in rows))
    if len(selected) > _MAX_RESOURCES:
        raise ValueError("local broker group count exceeds reset bound")
    return selected


def reset(*, run: Callable[..., str]) -> dict[str, int]:
    selected_groups = groups(run("exec", "fdai-redpanda", "rpk", "group", "list"))
    for group in selected_groups:
        run("exec", "fdai-redpanda", "rpk", "group", "delete", group)
    selected_topics = topics(run("exec", "fdai-redpanda", "rpk", "topic", "list"))
    for topic in selected_topics:
        run("exec", "fdai-redpanda", "rpk", "topic", "delete", topic)
    run(
        "exec",
        "fdai-redpanda",
        "rpk",
        "topic",
        "create",
        _STARTUP_TOPIC,
        "--if-not-exists",
        "-p",
        "2",
        "-r",
        "1",
        "-c",
        "cleanup.policy=delete",
        "-c",
        "retention.ms=3600000",
        "-c",
        "retention.bytes=1048576",
        "-c",
        "segment.ms=600000",
    )
    return {"groups_removed": len(selected_groups), "topics_removed": len(selected_topics)}


def reset_when_idle(
    *,
    run: Callable[..., str],
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    deadline = monotonic() + _GROUP_SETTLE_SECONDS
    while True:
        try:
            return reset(run=run)
        except RuntimeError as exc:
            if "every consumer group to be empty" not in str(exc) or monotonic() >= deadline:
                raise
            sleeper(0.25)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    docker = shutil.which("docker")
    if docker is None or not os.path.isdir("/proc"):
        parser.error("local Linux Docker is required")
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        parser.error("Docker endpoint overrides are not accepted")
    deadline = time.monotonic() + _RESET_DEADLINE_SECONDS

    def run(*parts: str) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("local broker reset deadline exceeded")
        return subprocess.run(
            [docker, *parts],
            check=True,
            capture_output=True,
            text=True,
            timeout=min(5, remaining),
        ).stdout

    contexts = json.loads(run("context", "inspect"))
    if len(contexts) != 1 or not contexts[0]["Endpoints"]["docker"]["Host"].startswith("unix://"):
        raise ValueError("Docker must use a local Unix socket")
    result = reset_when_idle(run=run)
    print(f"local-broker-reset: {json.dumps(result, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
