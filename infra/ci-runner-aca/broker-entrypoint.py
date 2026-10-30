#!/usr/bin/env python3
"""Launch one credential-free worker from a single-use broker ticket, never a repository PAT."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise ValueError("bootstrap redirects are not accepted")


def request(origin: str, endpoint: str, payload: dict[str, object]) -> dict[str, object]:
    url = urlsplit(origin)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        raise ValueError("worker bootstrap requires an explicit HTTPS origin")
    connection = urllib.request.build_opener(NoRedirect())
    req = urllib.request.Request(  # noqa: S310 - validated HTTPS origin; redirects refused
        origin.rstrip("/") + endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with connection.open(req, timeout=30) as response:
        body = response.read(1024 * 1024 + 1)
    if len(body) > 1024 * 1024:
        raise ValueError("bootstrap response exceeds its bound")
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError("bootstrap response must be an object")
    return result


def notify_started(origin: str, auth: dict[str, object]) -> None:
    """A failed observation cannot terminate an already-running workflow child."""
    try:
        request(origin, "/started", auth)
    except (OSError, ValueError, KeyError, http.client.HTTPException) as error:
        print(
            json.dumps(
                {
                    "event": "worker_started_notification_failed",
                    "level": "warning",
                    "failure_class": type(error).__name__,
                    "child_preserved": True,
                    "retry": False,
                }
            ),
            flush=True,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    if args.config:
        data = json.loads(args.config.read_text(encoding="utf-8"))
        args.config.unlink()
    else:
        data = json.loads(os.environ.pop("FDAI_RUNNER_BOOTSTRAP"))
    origin = data["controller_url"]
    auth = {"worker_id": data["worker_id"], "ticket": data["ticket"]}
    credential = request(origin, "/bootstrap", auth)["encoded_jit_config"]
    if not isinstance(credential, str) or not credential:
        raise ValueError("broker returned no short-lived registration")
    request(origin, "/registered", auth)
    runner = Path("/opt/actions-runner")
    if runner.is_symlink():
        runner = runner.resolve()
    hook, started = runner / ".fdai-job-started.sh", runner / ".fdai-job-started"
    hook.write_text(f"#!/bin/sh\n: > '{started}'\n", encoding="utf-8")
    hook.chmod(0o555)
    environment = {
        "HOME": "/home/runner",
        "PATH": "/home/runner/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "AGENT_TOOLSDIRECTORY": "/opt/hostedtoolcache",
        "ACTIONS_RUNNER_INPUT_JITCONFIG": credential,
        "ACTIONS_RUNNER_HOOK_JOB_STARTED": str(hook),
    }
    # Runner 2.338.2 consumes/removes INPUT_JITCONFIG and masks it before job code starts.
    # Unlike --jitconfig, this never exposes registration material in a command line.
    process = subprocess.Popen(  # noqa: S603 - fixed listener command and controlled environment
        ["/usr/sbin/runuser", "-u", "runner", "--", str(runner / "run.sh")],
        cwd=runner,
        env=environment,
    )
    del credential
    environment.clear()
    notified = False
    while process.poll() is None:
        if started.exists() and not notified:
            notified = True
            notify_started(origin, auth)
        time.sleep(0.1)
    if started.exists() and not notified:
        notify_started(origin, auth)
    code = process.returncode if process.returncode is not None and process.returncode >= 0 else 1
    request(origin, "/finished", {**auth, "exit_code": min(code, 255)})
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        print("worker bootstrap/lifecycle failed; no registration retry was attempted", flush=True)
        raise SystemExit(1) from None
