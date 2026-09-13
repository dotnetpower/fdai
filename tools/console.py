"""One-command launcher: boot the Operator API, then open the operator-console CLI.

Starts the local Azure CLI-authenticated independent Operator Service
(``fdai_operator_service.main:create_app``) in the background, waits for
``/healthz``, then runs the interactive Ink CLI wired to it with
``--source=api``. On exit it tears the server back down. If a compatible read
API is already listening on the port, it is reused (and left running).

Usage::

    uv run python -m tools.console
    uv run python -m tools.console --port 8010 --mode all-clear
    python tools/console.py                 # system python is fine - this
                                            # module only shells out to uv/npx

Exit codes: ``0`` clean, ``2`` bad prerequisites (missing uv/npx or the CLI
failed to install), ``3`` the Operator API never became healthy.

This is a developer convenience wrapper - not a shipped entrypoint. It imports
no ``fdai`` code; it only orchestrates ``uv`` and ``npx`` subprocesses so it
runs under any Python.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import cast

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLI_DIR = _REPO_ROOT / "cli"
_DEFAULT_PORT = 8010
_HEALTH_TIMEOUT_S = 45.0
_LOCAL_OPERATOR_ENV = _REPO_ROOT / ".fdai" / "local-operator-service.env"
_VENV_PYTHON = _REPO_ROOT / ".venv" / "bin" / "python"


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


def _wait_for_operator_api(
    process: subprocess.Popen[bytes],
    port: int,
    timeout: float,
) -> bool:
    """Wait for health while failing immediately when the child exits."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if _health_ok(port, timeout=0.5):
            return True
    return False


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    """Terminate and reap one owned child, escalating after a bounded grace period."""
    if process.poll() is not None:
        process.wait()
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _operator_api_usable(port: int) -> bool:
    """Return whether the API allows a CLI-authenticated or open read path."""
    base_url = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{base_url}/local-auth/me", timeout=2) as resp:  # noqa: S310
            token = resp.headers.get("X-FDAI-Local-Session")
            if cast(int, resp.status) != 200 or not token:
                return False
        request = urllib.request.Request(  # noqa: S310
            f"{base_url}/kpi",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=2) as resp:  # noqa: S310
            return cast(int, resp.status) == 200
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            return False
        try:
            with urllib.request.urlopen(f"{base_url}/kpi", timeout=2) as resp:  # noqa: S310
                return cast(int, resp.status) == 200
        except (urllib.error.URLError, ConnectionError, OSError):
            return False
    except (urllib.error.URLError, ConnectionError, OSError):
        return False


def _available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _select_operator_api_port(requested_port: int) -> tuple[int, bool]:
    """Return the API port and whether a compatible server can be reused."""
    if not _health_ok(requested_port, timeout=1.0):
        return requested_port, False
    if _operator_api_usable(requested_port):
        return requested_port, True
    return _available_loopback_port(), False


def _local_operator_api_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("FDAI_OPERATOR_API_DEV_MODE", None)
    env.pop("FDAI_OPERATOR_API_LOCAL_ENTRA", None)
    env["FDAI_OPERATOR_API_LOCAL_AZURE_CLI"] = "1"
    return env


def _require(tool: str) -> None:
    if shutil.which(tool) is None:
        print(
            f"error: '{tool}' is not on PATH - it is required to run the console.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _require_local_operator_environment() -> None:
    """Fail with setup guidance when the independent service is not prepared."""
    if _LOCAL_OPERATOR_ENV.is_file() and _VENV_PYTHON.is_file():
        return
    print(
        "error: the local Operator Service is not prepared; run "
        "'bash scripts/deployment/local/prepare-console-full-stack.sh' first.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _operator_api_command(port: int) -> list[str]:
    """Build the current service command without copying environment values."""
    script = """
set -a
source "$1"
set +a
unset FDAI_OPERATOR_API_DEV_MODE FDAI_OPERATOR_API_LOCAL_ENTRA
export FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1
export PYTHONPATH="$2/services/operator-service/src:\
$2/packages/service-contracts/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$2/.venv/bin/python" -m uvicorn fdai_operator_service.main:create_app \
  --factory --host 127.0.0.1 --port "$3" --no-access-log
""".strip()
    return [
        "bash",
        "-c",
        script,
        "fdai-console",
        str(_LOCAL_OPERATOR_ENV),
        str(_REPO_ROOT),
        str(port),
    ]


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
        description="Boot the Operator API and open the operator-console CLI.",
    )
    parser.add_argument(
        "--port", type=int, default=_DEFAULT_PORT, help="Operator API port (default 8010)"
    )
    parser.add_argument("--surface", default="cli", choices=["cli", "text", "slack", "teams"])
    parser.add_argument("--mode", default="needs-me", choices=["needs-me", "all-clear"])
    args = parser.parse_args(argv)

    _require("bash")
    _require("npm")
    _require("npx")
    _ensure_cli_deps()

    started_server: subprocess.Popen[bytes] | None = None
    log_path = _REPO_ROOT / ".console-operator-api.log"
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def interrupt_for_termination(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt_for_termination)

    try:
        # Reuse a compatible API; an authenticated browser API needs its own port.
        api_port, reuse_server = _select_operator_api_port(args.port)
        if reuse_server:
            print(f"reusing Operator API already listening on :{api_port}", file=sys.stderr)
        else:
            _require_local_operator_environment()
            if api_port != args.port:
                print(
                    f"Operator API on :{args.port} is not usable by the CLI; "
                    f"using :{api_port} instead",
                    file=sys.stderr,
                )
            for attempt in range(2):
                print(
                    f"starting Operator API on :{api_port} (log: {log_path.name})...",
                    file=sys.stderr,
                )
                with log_path.open("wb") as log_file:
                    started_server = subprocess.Popen(
                        _operator_api_command(api_port),
                        cwd=_REPO_ROOT,
                        env=_local_operator_api_env(),
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                    )
                if _wait_for_operator_api(started_server, api_port, _HEALTH_TIMEOUT_S):
                    break
                _terminate_process(started_server)
                started_server = None
                if attempt == 0:
                    api_port = _available_loopback_port()
                    print(
                        f"Operator API startup did not complete; retrying on :{api_port}",
                        file=sys.stderr,
                    )
            if started_server is None:
                print(
                    f"error: Operator API did not become healthy. See {log_path}.",
                    file=sys.stderr,
                )
                return 3

        cli = subprocess.run(
            [
                "npx",
                "tsx",
                "src/cli.tsx",
                f"--surface={args.surface}",
                "--source=api",
                f"--api=http://127.0.0.1:{api_port}",
                f"--mode={args.mode}",
            ],
            cwd=_CLI_DIR,
        )
        return cli.returncode
    except KeyboardInterrupt:
        return 0
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        if started_server is not None:
            print("\nstopping Operator API...", file=sys.stderr)
            _terminate_process(started_server)


if __name__ == "__main__":
    raise SystemExit(main())
