"""Local-mode provider implementations.

These are the dev-first alternatives to the Azure adapters under
`delivery/azure/`. They realize the same Protocols so composition-root
swaps between them at startup based on ``runtime.env`` / ``llm.mode``.

Design intent: a laptop with **no Azure credentials** can bind every
seam through this package and exercise the full control loop offline.
Every implementation is deterministic (no wall-clock beyond token TTL,
no network), so tests + dev runs produce reproducible audit trails.
"""

from __future__ import annotations

from fdai.shared.providers.local.document_ingestion import (
    LocalDirectoryDocumentObjectStore,
    SignatureProtectionInspector,
    StandardLibraryDocumentExtractor,
    UnavailableMalwareScanner,
)
from fdai.shared.providers.local.feasibility import (
    DenylistResourceTypeProbe,
    EgressDenylistProbe,
    ToggleResolution,
)
from fdai.shared.providers.local.identity import (
    LocalWorkloadIdentity,
    LocalWorkloadIdentityConfig,
)
from fdai.shared.providers.local.inventory import (
    FileFixtureInventory,
    load_inventory_fixture,
)
from fdai.shared.providers.local.secret import EnvSecretProvider

__all__ = [
    "DenylistResourceTypeProbe",
    "EgressDenylistProbe",
    "EnvSecretProvider",
    "FileFixtureInventory",
    "LocalWorkloadIdentity",
    "LocalWorkloadIdentityConfig",
    "LocalDirectoryDocumentObjectStore",
    "SignatureProtectionInspector",
    "StandardLibraryDocumentExtractor",
    "UnavailableMalwareScanner",
    "ToggleResolution",
    "load_inventory_fixture",
]
