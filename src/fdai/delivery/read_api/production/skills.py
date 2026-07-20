"""Production runtime skill disclosure over durable trusted artifacts."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from fdai.agents import PANTHEON_NAMES
from fdai.core.skills import RuntimeSkillDisclosure
from fdai.core.supply_chain import (
    TrustedArtifactKind,
    TrustedArtifactStore,
    load_skill_bundle_catalog,
    load_skill_catalog,
)
from fdai.delivery.persistence import (
    PostgresTrustedArtifactStore,
    PostgresTrustedArtifactStoreConfig,
)
from fdai.delivery.read_api.production.config import ProdReadApiConfigError
from fdai.delivery.read_api.routes.skills import RuntimeSkillsPanel
from fdai.delivery.read_api.skill_runtime import (
    READ_API_SKILL_TOOL_IDS,
    empty_runtime_skill_disclosure,
)
from fdai.delivery.trust import (
    Ed25519SkillBundleCatalogVerifier,
    Ed25519SkillBundleVerifierFactory,
    Ed25519SkillCatalogVerifier,
    Ed25519SkillTrustVerifierFactory,
)

TRUSTED_SKILL_PUBLISHERS_PATH_ENV = "FDAI_SKILL_TRUSTED_PUBLISHERS_PATH"


@dataclass(frozen=True, slots=True)
class ProductionSkillRuntime:
    disclosure: RuntimeSkillDisclosure
    panel: RuntimeSkillsPanel
    startup: Callable[[], Awaitable[None]]


def build_production_skill_runtime(
    *,
    env: Mapping[str, str],
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
    store: TrustedArtifactStore | None = None,
) -> ProductionSkillRuntime:
    """Create one shared disclosure and its fail-closed startup loader."""
    trusted_publishers = _load_trusted_publishers(env)
    artifact_store = store or PostgresTrustedArtifactStore(
        config=PostgresTrustedArtifactStoreConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        )
    )
    disclosure = empty_runtime_skill_disclosure()

    async def startup() -> None:
        records = await artifact_store.list(TrustedArtifactKind.SKILL)
        bundle_records = await artifact_store.list(TrustedArtifactKind.SKILL_BUNDLE)
        factory = Ed25519SkillTrustVerifierFactory(trusted_publishers)
        catalog = load_skill_catalog(
            records,
            factory,
            READ_API_SKILL_TOOL_IDS,
            frozenset(PANTHEON_NAMES),
        )
        skill_verifier = Ed25519SkillCatalogVerifier(records, trusted_publishers)
        bundle_catalog = load_skill_bundle_catalog(
            bundle_records,
            Ed25519SkillBundleVerifierFactory(trusted_publishers),
            skills=catalog,
            skill_verifier=skill_verifier,
            available_tools=READ_API_SKILL_TOOL_IDS,
            known_agents=frozenset(PANTHEON_NAMES),
        )
        disclosure.publish_snapshot(
            catalog=catalog,
            verifier=skill_verifier,
        )
        disclosure.publish_bundle_snapshot(
            catalog=bundle_catalog,
            verifier=Ed25519SkillBundleCatalogVerifier(bundle_records, trusted_publishers),
        )

    return ProductionSkillRuntime(
        disclosure=disclosure,
        panel=RuntimeSkillsPanel(disclosure),
        startup=startup,
    )


def _load_trusted_publishers(env: Mapping[str, str]) -> dict[str, bytes]:
    raw_path = env.get(TRUSTED_SKILL_PUBLISHERS_PATH_ENV, "").strip()
    if not raw_path:
        return {}
    path = Path(raw_path)
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProdReadApiConfigError(
            f"{TRUSTED_SKILL_PUBLISHERS_PATH_ENV} MUST reference valid UTF-8 JSON"
        ) from exc
    if not isinstance(decoded, dict):
        raise ProdReadApiConfigError("trusted skill publisher registry MUST be a JSON object")
    publishers: dict[str, bytes] = {}
    for source, public_key in decoded.items():
        if not isinstance(source, str) or not source.strip():
            raise ProdReadApiConfigError("trusted skill publisher source MUST be non-empty")
        if not isinstance(public_key, str) or not public_key.strip():
            raise ProdReadApiConfigError(
                f"trusted skill publisher {source!r} public key MUST be non-empty"
            )
        publishers[source] = public_key.encode("utf-8")
    return publishers


__all__ = [
    "ProductionSkillRuntime",
    "TRUSTED_SKILL_PUBLISHERS_PATH_ENV",
    "build_production_skill_runtime",
]
