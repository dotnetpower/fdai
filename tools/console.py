"""One-command launcher: boot the read API, then open the operator-console CLI.

Starts the dev read API (``fdai.delivery.read_api._local:app``) in the
background, waits for ``/healthz``, then runs the interactive Ink CLI wired to
it with ``--source=api``. On exit it tears the server back down. If a read API
is already listening on the port, it is reused (and left running).

Usage::

    uv run python -m tools.console
    uv run python -m tools.console --port 8010 --mode all-clear
    python tools/console.py                 # system python is fine - this
                                            # module only shells out to uv/npx

Exit codes: ``0`` clean, ``2`` bad prerequisites (missing uv/npx or the CLI
failed to install), ``3`` the read API never became healthy.

This is a developer convenience wrapper - not a shipped entrypoint. It imports
no ``fdai`` code; it only orchestrates ``uv`` and ``npx`` subprocesses so it
runs under any Python.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLI_DIR = _REPO_ROOT / "cli"
_DEFAULT_PORT = 8010
_HEALTH_TIMEOUT_S = 45.0


def _health_ok(port: int, timeout: float) -> bool:
    """Return True as soon as GET /healthz answers 200, else False by deadline."""
    url = f"http://127.0.0.1:{port}/healthz"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.5)
    return False


def _require(tool: str) -> None:
    if shutil.which(tool) is None:
        print(
            f"error: '{tool}' is not on PATH - it is required to run the console.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _ensure_cli_deps() -> None:
    """Install the CLI's node deps on first run so `python -m tools.console` just works."""
    if (_CLI_DIR / "node_modules").is_dir():
        return
    print("installing CLI dependencies (first run)...", file=sys.stderr)
    result = subprocess.run(["npm", "install"], cwd=_CLI_DIR)
    if result.returncode != 0:
        print("error: `npm install` failed in cli/.", file=sys.stderr)
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Boot the read API and open the operator-console CLI.",
    )
    parser.add_argument(
        "--port", type=int, default=_DEFAULT_PORT, help="read API port (default 8010)"
    )
    parser.add_argument("--surface", default="cli", choices=["cli", "text", "slack", "teams"])
    parser.add_argument("--mode", default="needs-me", choices=["needs-me", "all-clear"])
    args = parser.parse_args(argv)

    _require("uv")
    _require("npx")
    _ensure_cli_deps()

    started_server: subprocess.Popen[bytes] | None = None
    log_path = _REPO_ROOT / ".console-readapi.log"

    # Reuse an already-running read API; otherwise start our own.
    if _health_ok(args.port, timeout=1.0):
        print(f"reusing read API already listening on :{args.port}", file=sys.stderr)
    else:
        print(f"starting read API on :{args.port} (log: {log_path.name})...", file=sys.stderr)
        with log_path.open("wb") as log_file:
            started_server = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "--with",
                    "uvicorn",
                    "uvicorn",
                    "fdai.delivery.read_api._local:app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.port),
                ],
                cwd=_REPO_ROOT,
                env={**os.environ, "FDAI_READ_API_DEV_MODE": "1"},
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        if not _health_ok(args.port, timeout=_HEALTH_TIMEOUT_S):
            print(
                f"error: read API did not become healthy on :{args.port}. See {log_path}.",
                file=sys.stderr,
            )
            if started_server is not None:
                started_server.terminate()
            return 3

    try:
        cli = subprocess.run(
            [
                "npx",
                "tsx",
                "src/cli.tsx",
                f"--surface={args.surface}",
                "--source=api",
                f"--api=http://127.0.0.1:{args.port}",
                f"--mode={args.mode}",
            ],
            cwd=_CLI_DIR,
        )
        return cli.returncode
    except KeyboardInterrupt:
        return 0
    finally:
        if started_server is not None:
            print("\nstopping read API...", file=sys.stderr)
            started_server.terminate()
            try:
                started_server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                started_server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
