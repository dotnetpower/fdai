"""Knowledge + code-access registration surface (SRE-agent slide 8).

The operator configuration layer that records which free-form Knowledge
Sources and Code Access repositories are connected, on top of the existing
retrieval seams (``KnowledgeSource`` + ``ChangeFeed``). No secrets are
stored inline - a code repo carries a ``secret_ref`` handle only.
"""

from __future__ import annotations

from fdai.core.knowledge.models import (
    CodeRepoProvider,
    CodeRepoRegistration,
    KnowledgeSourceKind,
    RegisteredDocument,
)
from fdai.core.knowledge.registry import (
    CodeRepoRegistry,
    CodeRepoStore,
    DuplicateRegistrationError,
    InMemoryCodeRepoStore,
    InMemoryKnowledgeRegistryStore,
    KnowledgeRegistry,
    KnowledgeRegistryStore,
    RegistrationNotFoundError,
)

__all__ = [
    "CodeRepoProvider",
    "CodeRepoRegistration",
    "CodeRepoRegistry",
    "CodeRepoStore",
    "DuplicateRegistrationError",
    "InMemoryCodeRepoStore",
    "InMemoryKnowledgeRegistryStore",
    "KnowledgeRegistry",
    "KnowledgeRegistryStore",
    "KnowledgeSourceKind",
    "RegisteredDocument",
    "RegistrationNotFoundError",
]


# ---------------------------------------------------------------------------
# Permanent G-1 facade-only layout: treat the ``knowledge`` package as the
# domain-group facade while preserving its original subsystem role. Re-export
# owned siblings so new code can write ``from fdai.core.knowledge import prompts``,
# while direct ``fdai.core.<sub>`` imports remain stable. Any physical move
# requires a separate reviewed design.
# ---------------------------------------------------------------------------

from fdai.core import (  # noqa: E402, F401 - domain-group facade re-exports
    capability_catalog,
    ontology_explorer,
    prompts,
    rule_catalog_profiles,
    tools,
    web_search,
)
