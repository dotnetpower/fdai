"""Read-only Azure Resource Manager readers for observer preflight."""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Mapping
from typing import Any

_MAX_BYTES = 4_000_000


class AzCliManagementReader:
    """Use the operator's existing Azure CLI login; it never receives or logs a credential."""

    def __init__(self, *, az: str = "az") -> None:
        self._az = az

    async def get(self, path: str, api_version: str) -> Mapping[str, Any]:
        if not path.startswith("/") or "?" in path or any(ch in path for ch in " \n;&|"):
            raise ValueError("management path is invalid")
        return await asyncio.to_thread(self._run, path, api_version)

    def _run(self, path: str, api_version: str) -> Mapping[str, Any]:
        done = subprocess.run(  # noqa: S603 - fixed vector, no shell
            [
                self._az,
                "rest",
                "--method",
                "get",
                "--url",
                f"https://management.azure.com{path}?api-version={api_version}",
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if done.returncode != 0 or len(done.stdout) > _MAX_BYTES:
            raise ValueError("Azure management read failed")
        value = json.loads(done.stdout)
        if not isinstance(value, dict):
            raise ValueError("Azure management response is not an object")
        return value
