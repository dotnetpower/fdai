"""Parse exact effect identity and PostgreSQL bindings without connecting or granting authority."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from psycopg.conninfo import conninfo_to_dict

from fdai.runtime.alert_noise_config import (
    MAX_CONFIG_BYTES,
    PRINCIPAL_SCOPES_ENV,
    SCOPE_BINDINGS_ENV,
    SOURCE_REVISION_ENV,
    WRITER_BINDINGS_ENV,
    parse_alert_noise_config,
)

EFFECT_BINDINGS_ENV = "FDAI_ALERT_NOISE_EFFECT_BINDINGS_JSON"
_FIELDS = {
    "tenant_ref",
    "scope_ref",
    "source_ref",
    "observer_ref",
    "executor_ref",
    "identities",
    "authority_class",
}
_ENV_KEYS = (
    EFFECT_BINDINGS_ENV,
    SCOPE_BINDINGS_ENV,
    PRINCIPAL_SCOPES_ENV,
    WRITER_BINDINGS_ENV,
    SOURCE_REVISION_ENV,
    "FDAI_STATE_STORE_DSN",
    "FDAI_RESOURCE_LOCK_DSN",
)
_REF = re.compile(r"[a-z][a-z0-9_.:-]{0,159}")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,511}")


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate effect binding field")
        result[key] = value
    return result


def _settings(environment: Mapping[str, str]) -> tuple[str, str, tuple[dict[str, Any], ...]]:
    """Validate private identity aliases, not authority; never read a file or connect."""
    try:
        raw = environment[EFFECT_BINDINGS_ENV]
        if type(raw) is not str or not 1 <= len(raw.encode()) <= MAX_CONFIG_BYTES:
            raise ValueError("invalid size")
        rows = json.loads(raw, object_pairs_hook=_unique)
        config = parse_alert_noise_config(environment)
        if (
            type(rows) is not list
            or not 1 <= len(rows) <= 64
            or config is None
            or config.source_revision is None
        ):
            raise ValueError("missing effect configuration")
        scopes: set[str] = set()
        aliases: dict[str, str] = {}
        for row in rows:
            if type(row) is not dict or set(row) != _FIELDS:
                raise ValueError("invalid fields")
            for key in _FIELDS - {"identities", "authority_class"}:
                if type(row[key]) is not str or _REF.fullmatch(row[key]) is None:
                    raise ValueError("invalid reference")
            scope = config.scopes.get(row["scope_ref"])
            if scope is None or scope.tenant_ref != row["tenant_ref"] or scope.scope_ref in scopes:
                raise ValueError("unbound or duplicate scope")
            scopes.add(scope.scope_ref)
            refs = {row[key] for key in ("source_ref", "observer_ref", "executor_ref")}
            identities = row["identities"]
            if (
                len(refs) != 3
                or type(identities) is not dict
                or set(identities) != refs
                or any(
                    type(value) is not str or _IDENTITY.fullmatch(value) is None
                    for value in identities.values()
                )
                or len({value.casefold() for value in identities.values()}) != 3
                or type(row["authority_class"]) is not str
                or re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", row["authority_class"]) is None
            ):
                raise ValueError("invalid independent identities")
            for ref, identity in identities.items():
                if aliases.setdefault(ref, identity.casefold()) != identity.casefold():
                    raise ValueError("identity alias changed across scopes")
            writer = config.writers.get(scope.scope_ref)
            if writer is not None and (
                writer.executor_ref != row["executor_ref"]
                or writer.principal_refs.get(identities[row["executor_ref"]]) != writer.executor_ref
            ):
                raise ValueError("executor binding mismatch")
        dsn = environment.get("FDAI_STATE_STORE_DSN", "")
        if type(dsn) is not str or not 1 <= len(dsn) <= 8192 or dsn != dsn.strip():
            raise ValueError("missing PostgreSQL DSN")
        connection = conninfo_to_dict(dsn)
        if not connection.get("dbname") or not (
            connection.get("host") or connection.get("hostaddr")
        ):
            raise ValueError("PostgreSQL target must be explicit")
        if environment.get("FDAI_RESOURCE_LOCK_DSN") not in {None, "", dsn}:
            raise ValueError("hold and dispatch lock stores differ")
        return config.source_revision, dsn, tuple(rows)
    except Exception:
        raise ValueError(
            "alert effect bindings require exact scopes, source, independent identities "
            "and PostgreSQL"
        ) from None
