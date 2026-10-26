"""Environment and typed-setting wiring for the encrypted result-handle store."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fdai.core.conversation.result_handle_store import (
    ResultHandleStore,
    SecretProviderResultHandleKeyProvider,
)

_LOGGER = logging.getLogger(__name__)

RESULT_HANDLES_ENV = "FDAI_SEMANTIC_RESULT_HANDLES"
RESULT_HANDLE_MATERIAL_ENV = "FDAI_RESULT_HANDLE_MATERIAL"


def result_handle_store_from_config(
    config: Mapping[str, str], *, enabled: bool | None = None
) -> ResultHandleStore | None:
    """Build the encrypted result-handle store only when the venue opts into follow-ups.

    A follow-up such as "only the running ones" refers to the rows the operator just saw, and
    only a stored handle can bind it. ``enabled`` is the typed runtime setting, which carries an
    audited operator override; without it the environment flag alone decides. Opting in without
    a state-store DSN or key material leaves follow-ups off and says so in the log, because an
    environment default must never stop Core from starting.
    """

    if enabled is None:
        enabled = config.get(RESULT_HANDLES_ENV, "").strip().lower() in {"1", "true", "yes"}
    if not enabled:
        return None
    dsn = config.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn or not config.get(RESULT_HANDLE_MATERIAL_ENV, "").strip():
        _LOGGER.warning(
            "semantic_result_handles_unavailable",
            extra={"reason": "state_store_dsn_or_key_material_missing"},
        )
        return None
    from fdai.delivery.persistence.postgres_result_handle_store import (
        PostgresResultHandleStore,
        PostgresResultHandleStoreConfig,
    )
    from fdai.shared.providers.local import EnvSecretProvider

    return PostgresResultHandleStore(
        config=PostgresResultHandleStoreConfig(dsn=dsn),
        keys=SecretProviderResultHandleKeyProvider(EnvSecretProvider(env=config)),
    )


__all__ = ["RESULT_HANDLES_ENV", "RESULT_HANDLE_MATERIAL_ENV", "result_handle_store_from_config"]
