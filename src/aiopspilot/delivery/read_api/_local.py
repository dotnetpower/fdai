"""Local dev entrypoint for the console read API.

Boots the Starlette app with :class:`UnsafeClaimsExtractor` (dev-only
JWT decoder) and an :class:`InMemoryConsoleReadModel` seeded with a few
synthetic entries so the console has something to render.

**Never wire this in production.** The env-var tripwire in
:func:`aiopspilot.delivery.read_api.main.build_app` refuses to build a
dev-mode app unless ``AIOPSPILOT_READ_API_DEV_MODE=1`` is set - this
module also asserts that at build time so a stray production revision
that boots it fails fast.

Usage (uvicorn's ``--factory`` flag calls :func:`app` at server start,
so importing this module during unrelated tooling - pytest collection,
mypy, IDE indexing - has no side effect)::

    AIOPSPILOT_READ_API_DEV_MODE=1 \\
        uv run uvicorn 'aiopspilot.delivery.read_api._local:app' \\
            --factory --port 8000
"""

from __future__ import annotations

import os

from starlette.applications import Starlette

from aiopspilot.core.rbac.resolver import GroupMapping, RoleResolver
from aiopspilot.delivery.read_api.auth import (
    UnsafeClaimsExtractor,
    build_authenticator,
)
from aiopspilot.delivery.read_api.main import ReadApiConfig, build_app
from aiopspilot.delivery.read_api.read_model import (
    HilQueueItem,
    InMemoryConsoleReadModel,
)

_DEV_ENV = "AIOPSPILOT_READ_API_DEV_MODE"


def _seed(read_model: InMemoryConsoleReadModel) -> None:
    """Seed a few audit entries + one pending HIL so the SPA renders data."""
    read_model.record_audit_entry(
        {
            "event_id": "00000000-0000-0000-0000-000000000001",
            "actor": "aiopspilot.core.control_loop",
            "action_kind": "control_loop.abstain",
            "mode": "shadow",
            "outcome": "abstained_t0",
            "reason": "no matching rule",
            "recorded_at": "2026-07-06T10:00:00+00:00",
        }
    )
    read_model.record_audit_entry(
        {
            "event_id": "00000000-0000-0000-0000-000000000002",
            "actor": "aiopspilot.core.executor.shadow",
            "action_kind": "enable-encryption",
            "mode": "shadow",
            "outcome": "shadow_pr_opened",
            "recorded_at": "2026-07-06T10:05:00+00:00",
        }
    )
    read_model.record_hil_pending(
        HilQueueItem(
            idempotency_key="hil-dev-0001",
            event_id="00000000-0000-0000-0000-000000000003",
            action_kind="restrict-network-access",
            reason="blast-radius exceeds executor cap",
            requested_at="2026-07-06T10:10:00+00:00",
            correlation_id="corr-dev-0001",
        )
    )


def app() -> Starlette:
    """Factory. uvicorn invokes this once at server start with ``--factory``."""
    if os.environ.get(_DEV_ENV) != "1":
        raise RuntimeError(
            f"aiopspilot.delivery.read_api._local requires {_DEV_ENV}=1; "
            "this module is a local dev entrypoint and MUST NOT boot in production."
        )
    read_model = InMemoryConsoleReadModel()
    _seed(read_model)
    resolver = RoleResolver(
        group_mapping=GroupMapping(
            reader_group_id="00000000-0000-0000-0000-000000000001",
            contributor_group_id="00000000-0000-0000-0000-000000000002",
            approver_group_id="00000000-0000-0000-0000-000000000003",
            owner_group_id="00000000-0000-0000-0000-000000000004",
            break_glass_group_id="00000000-0000-0000-0000-000000000005",
        )
    )
    authenticator = build_authenticator(
        verifier=UnsafeClaimsExtractor(),
        resolver=resolver,
    )
    return build_app(
        authenticator=authenticator,
        read_model=read_model,
        config=ReadApiConfig(
            dev_mode=True,
            cors_allow_origins=(
                "http://127.0.0.1:5173",
                "http://localhost:5173",
            ),
        ),
    )
