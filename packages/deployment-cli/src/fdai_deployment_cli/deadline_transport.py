"""Bound an existing managed-host transport to one deployment deadline."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from fdai_deployment_cli.deployment_deadline import DeploymentDeadline


class DeploymentTransport(Protocol):
    """Existing authenticated transport; this wrapper never chooses identity or target."""

    def ssh(
        self, remote_arguments: Sequence[str], *, timeout: int, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run the unchanged remote command within the supplied process limit."""
        ...

    def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
        """Copy the unchanged private file within the supplied process limit."""
        ...


class DeadlineTransport:
    """Clamp every command and copy to the current budget without adding retries.

    The caller still owns the underlying tunnel's context and cleanup. An operation
    returning after expiry cannot advance the next stage or produce a ready receipt.
    """

    def __init__(self, transport: DeploymentTransport, deadline: DeploymentDeadline) -> None:
        self._transport = transport
        self._deadline = deadline

    def ssh(
        self, remote_arguments: Sequence[str], *, timeout: int, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Preserve command/stdin while enforcing the current deadline before and after I/O."""

        result = self._transport.ssh(
            remote_arguments, timeout=self._deadline.remaining(timeout), input_text=input_text
        )
        self._deadline.remaining()
        return result

    def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
        """Preserve transfer paths while enforcing the current deadline before and after I/O."""

        self._transport.copy_to(source, destination, timeout=self._deadline.remaining(timeout))
        self._deadline.remaining()
