"""Transfer Foundation context and optional adoption evidence to the managed host."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class PrivateTransport(Protocol):
    """Minimum managed-host file transport used by Foundation staging."""

    def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
        """Copy one validated private file."""
        ...


@dataclass(frozen=True, slots=True)
class FoundationTransport:
    """Remote Foundation input paths and optional host CLI arguments."""

    handoff: str
    entra: str
    adoption_arguments: tuple[str, ...]


def stage_foundation_context(
    tunnel: PrivateTransport,
    handoff_path: Path,
    remote_handoff: str,
    entra_path: Path,
    remote_entra: str,
    remote_root: str,
) -> FoundationTransport:
    """Copy exact handoff inputs and return optional adoption arguments."""

    tunnel.copy_to(handoff_path, remote_handoff, timeout=120)
    tunnel.copy_to(entra_path, remote_entra, timeout=120)
    adoption = handoff_path.parent.parent / "foundation-adoption-receipt.json"
    if not adoption.exists() and not adoption.is_symlink():
        return FoundationTransport(remote_handoff, remote_entra, ())
    remote_adoption = f"{remote_root}/foundation-adoption.json"
    tunnel.copy_to(adoption, remote_adoption, timeout=120)
    return FoundationTransport(
        remote_handoff,
        remote_entra,
        ("--foundation-adoption", remote_adoption),
    )
