"""Read-only browser, local-service, and editor-pressure diagnostics."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from itertools import islice
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from scripts.automation.developer_workflow_repository import git_common_dir

PLAYWRIGHT_POOL_SIZE = 10
LOCAL_SERVICE_ENDPOINTS = (
    ("console-frontend", "http://127.0.0.1:5273/"),
    ("operator-api", "http://127.0.0.1:8010/healthz"),
    ("document-ingestion-api", "http://127.0.0.1:8011/healthz"),
    ("document-processing-worker", "http://127.0.0.1:8012/ready"),
    ("isolated-executor", "http://127.0.0.1:8013/ready"),
)
PRESSURE_LIMITS = {
    "cpu_some_avg10": 50.0,
    "io_full_avg10": 5.0,
    "memory_some_avg10": 1.0,
}
MAX_PROCESSES = 4_096
MAX_COMMAND_BYTES = 4_096


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def browser_runner_diagnostic(
    lock_root: Path | None = None,
    *,
    is_alive: Callable[[int], bool] = _process_is_alive,
) -> dict[str, Any]:
    root = lock_root or Path(tempfile.gettempdir()) / f"fdai-playwright-port-pool-{os.getuid()}"
    held = 0
    stale = 0
    invalid = 0
    for slot in range(PLAYWRIGHT_POOL_SIZE):
        owner_path = root / f"slot-{slot}" / "owner.json"
        if not owner_path.is_file():
            continue
        try:
            if owner_path.stat().st_size > 4_096:
                raise ValueError
            owner: object = json.loads(owner_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            invalid += 1
            continue
        pid = owner.get("pid") if isinstance(owner, dict) else None
        if not isinstance(pid, int) or pid <= 0:
            invalid += 1
        elif is_alive(pid):
            held += 1
        else:
            stale += 1
    available = PLAYWRIGHT_POOL_SIZE - held - stale - invalid
    return {
        "available_slots": max(0, available),
        "held_slots": held,
        "invalid_slots": invalid,
        "stale_slots": stale,
        "status": "warning" if available == 0 or invalid or stale else "ok",
        "total_slots": PLAYWRIGHT_POOL_SIZE,
    }


def _http_ready(url: str) -> bool:
    request = Request(url, method="GET")  # noqa: S310 - endpoints are fixed loopback URLs.
    try:
        with urlopen(request, timeout=0.5) as response:  # noqa: S310
            return 200 <= response.status < 300
    except OSError:
        return False


def _process_records(proc_root: Path = Path("/proc")) -> list[tuple[Path, list[str]]]:
    records: list[tuple[Path, list[str]]] = []
    processes = (path for path in proc_root.iterdir() if path.name.isdigit())
    for process in islice(processes, MAX_PROCESSES):
        try:
            command = (process / "cmdline").read_bytes()
            if len(command) > MAX_COMMAND_BYTES:
                continue
            arguments = [part.decode(errors="replace") for part in command.split(b"\0") if part]
            cwd = (process / "cwd").resolve(strict=True)
        except OSError:
            continue
        records.append((cwd, arguments))
    return records


def _owns_core_runtime(repo_root: Path, records: list[tuple[Path, list[str]]]) -> bool:
    for cwd, arguments in records:
        if cwd != repo_root or "pytest" in arguments:
            continue
        if any(arguments[index : index + 2] == ["-m", "fdai"] for index in range(len(arguments))):
            return True
    return False


def local_services_diagnostic(
    root: Path,
    *,
    probe: Callable[[str], bool] = _http_ready,
    process_records: list[tuple[Path, list[str]]] | None = None,
) -> dict[str, Any]:
    resolved = git_common_dir(root)
    if resolved is None:
        return {"reason_code": "service_repository_unavailable", "status": "unavailable"}
    repo_root, _common_dir = resolved
    if not (repo_root / ".fdai").is_dir():
        return {"reason_code": "local_stack_not_prepared", "status": "unavailable"}
    services = [{"name": name, "ready": bool(probe(url))} for name, url in LOCAL_SERVICE_ENDPOINTS]
    core_ready = _owns_core_runtime(repo_root, process_records or _process_records())
    services.insert(0, {"name": "core-runtime", "ready": core_ready})
    unavailable = [str(service["name"]) for service in services if not service["ready"]]
    return {
        "ready_count": len(services) - len(unavailable),
        "service_count": len(services),
        "services": services,
        "status": "warning" if unavailable else "ok",
        "unavailable_services": unavailable,
    }


def _pressure_avg10(path: Path, category: str) -> float | None:
    try:
        if path.stat().st_size > 4_096:
            return None
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(rf"^{re.escape(category)}\s+avg10=([0-9.]+)", content, re.MULTILINE)
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _run_code_status() -> subprocess.CompletedProcess[str] | None:
    executable = shutil.which("code")
    if executable is None:
        return None
    try:
        return subprocess.run(  # noqa: S603 - resolved VS Code executable and fixed arguments.
            [executable, "--status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def editor_pressure_diagnostic(
    proc_root: Path = Path("/proc"),
    *,
    code_status: Callable[[], subprocess.CompletedProcess[str] | None] = _run_code_status,
) -> dict[str, Any]:
    pressure = {
        "cpu_some_avg10": _pressure_avg10(proc_root / "pressure" / "cpu", "some"),
        "io_full_avg10": _pressure_avg10(proc_root / "pressure" / "io", "full"),
        "memory_some_avg10": _pressure_avg10(proc_root / "pressure" / "memory", "some"),
    }
    exceeded = [
        name
        for name, value in pressure.items()
        if value is not None and value >= PRESSURE_LIMITS[name]
    ]
    code_result = code_status()
    if code_result is None or code_result.returncode != 0:
        client_status = "unavailable"
        extension_host_count = 0
    else:
        client_status = "ok"
        extension_host_count = sum(
            "extension-host" in line.lower()
            for line in (code_result.stdout + code_result.stderr).splitlines()[:200]
        )
    return {
        "browser_tool_payload": "upstream_bounded_by_cli_first_workflow",
        "client_status": client_status,
        "extension_host_count": extension_host_count,
        "host_pressure_exceeded": exceeded,
        "pressure": pressure,
        "status": "warning" if exceeded else "ok",
    }


def editor_pressure_for_root(root: Path) -> dict[str, Any]:
    resolved = git_common_dir(root)
    if resolved is None:
        return {"reason_code": "editor_repository_unavailable", "status": "unavailable"}
    repo_root, _common_dir = resolved
    if not (repo_root / ".fdai").is_dir():
        return {"reason_code": "local_workspace_not_prepared", "status": "unavailable"}
    return editor_pressure_diagnostic()
