"""Config provider - the DI seam that decides *where runtime config comes from*.

Core modules never read env vars, files, or config services directly; they
receive an :class:`fdai.shared.config.models.AppConfig` handed to them
by a composition root that instantiated a :class:`ConfigProvider`.

The upstream default, :class:`EnvVarConfigProvider`, reads the well-known
upper-snake env-var names documented in
[deploy-and-onboard.md § Runtime Configuration Matrix][matrix].
A fork MAY register a config-service adapter (App Configuration, ConsulKV,
etc.) by implementing this Protocol.

[matrix]: ../../../../docs/roadmap/deployment/deploy-and-onboard.md#runtime-configuration-matrix

Fail-fast contract
------------------
Every provider MUST raise :class:`fdai.shared.config.errors.ConfigError`
with the full list of problems the moment invalid or missing config is
detected. Do not partially-return an :class:`AppConfig`; degraded startup is
prohibited by ``coding-conventions.instructions.md``.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from math import isfinite
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from .errors import ConfigError, ConfigIssue
from .loader import load_from_mapping
from .models import AppConfig


@runtime_checkable
class ConfigProvider(Protocol):
    """Return a fully-validated :class:`AppConfig` - or raise :class:`ConfigError`."""

    def get(self) -> AppConfig: ...


# Env-var → config-path lookup table. Kept as data so a mismatch is a
# straightforward diff review, not a bug hunt.
_ENV_VAR_MAP: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    # (env var, (dotted path split), is_required)
    ("AZURE_TENANT_ID", ("azure", "tenant_id"), True),
    ("AZURE_SUBSCRIPTION_ID", ("azure", "subscription_id"), True),
    ("AZURE_RESOURCE_GROUP", ("azure", "resource_group"), False),
    ("AZURE_REGION", ("azure", "region"), True),
    ("KAFKA_BOOTSTRAP_SERVERS", ("kafka", "bootstrap_servers"), True),
    ("KAFKA_SECURITY_PROTOCOL", ("kafka", "security_protocol"), False),
    ("KAFKA_SASL_MECHANISM", ("kafka", "sasl_mechanism"), False),
    ("KAFKA_TOPIC_EVENTS", ("kafka", "topic_events"), True),
    ("KAFKA_TOPIC_DLQ_SUFFIX", ("kafka", "topic_dlq_suffix"), False),
    ("POSTGRES_HOST", ("postgres", "host"), True),
    ("POSTGRES_DATABASE", ("postgres", "database"), True),
    ("RULE_CATALOG_REF", ("rule_catalog", "ref"), False),
    ("RUNTIME_ENV", ("runtime", "env"), True),
    ("AUTONOMY_MODE_DEFAULT", ("runtime", "autonomy_mode_default"), False),
    ("LLM_MODE", ("llm", "mode"), False),
    ("LLM_RESOLVED_MODELS_PATH", ("llm", "resolved_models_path"), False),
    ("T1_SIMILARITY_THRESHOLD", ("llm", "t1_similarity_threshold"), False),
    ("T1_MIN_SUCCESS_RATE", ("llm", "t1_min_success_rate"), False),
    (
        "QUALITY_GATE_CONFIDENCE_THRESHOLD",
        ("llm", "quality_gate_confidence_threshold"),
        False,
    ),
    ("QUALITY_GATE_QUORUM", ("llm", "quality_gate_quorum"), False),
    ("SELF_CONSISTENCY_SAMPLES", ("llm", "self_consistency_samples"), False),
    (
        "SELF_CONSISTENCY_SAMPLE_THRESHOLD",
        ("llm", "self_consistency_sample_threshold"),
        False,
    ),
    (
        "SELF_CONSISTENCY_STABILITY_THRESHOLD",
        ("llm", "self_consistency_stability_threshold"),
        False,
    ),
)

_FLOAT_ENV_VARS = frozenset(
    {
        "T1_SIMILARITY_THRESHOLD",
        "T1_MIN_SUCCESS_RATE",
        "QUALITY_GATE_CONFIDENCE_THRESHOLD",
        "SELF_CONSISTENCY_SAMPLE_THRESHOLD",
        "SELF_CONSISTENCY_STABILITY_THRESHOLD",
    }
)
_INT_ENV_VARS = frozenset({"QUALITY_GATE_QUORUM", "SELF_CONSISTENCY_SAMPLES"})
_MAX_CONFIG_FILE_BYTES = 1_048_576


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                None,
                None,
                "configuration YAML contains a duplicate key",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class EnvVarConfigProvider:
    """Default :class:`ConfigProvider` - reads config from process env.

    Every problem is reported in one shot: missing required vars, invalid
    enum values, schema violations, and pydantic type errors are aggregated
    into a single :class:`ConfigError`.
    """

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        # Snapshot the env at construction so the same provider yields a
        # stable result across calls even if os.environ mutates.
        self._env: Mapping[str, str] = dict(env if env is not None else os.environ)

    def get(self) -> AppConfig:
        raw: dict[str, Any] = {"schema_version": "1.0.0"}
        issues: list[ConfigIssue] = []

        for env_var, path, required in _ENV_VAR_MAP:
            value = self._env.get(env_var)
            if value is None:
                if required:
                    issues.append(ConfigIssue(key=env_var, message="required env var is unset"))
                continue
            try:
                parsed = _parse_env_value(env_var, value)
            except ValueError as exc:
                issues.append(ConfigIssue(key=env_var, message=str(exc)))
                continue
            _assign(raw, path, parsed)

        if issues:
            raise ConfigError(issues)

        llm = raw.get("llm")
        if isinstance(llm, dict):
            llm.setdefault("mode", "local-fake")

        return load_from_mapping(raw)


class YamlFileConfigProvider:
    """Load one bounded UTF-8 YAML document through the shared config validators."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._cached: AppConfig | None = None

    def get(self) -> AppConfig:
        if self._cached is not None:
            return self._cached
        try:
            descriptor = os.open(
                self._path,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
            )
        except OSError:
            raise _file_error("configuration file is unavailable") from None
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise _file_error("configuration file MUST be a regular file")
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                payload = handle.read(_MAX_CONFIG_FILE_BYTES + 1)
        except OSError:
            raise _file_error("configuration file is unavailable") from None
        finally:
            os.close(descriptor)
        if len(payload) > _MAX_CONFIG_FILE_BYTES:
            raise _file_error("configuration file exceeds the 1 MiB limit")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            raise _file_error("configuration file MUST be UTF-8") from None
        loader: _UniqueKeySafeLoader | None = None
        try:
            loader = _UniqueKeySafeLoader(text)
            loaded = loader.get_single_data()
        except (RecursionError, TypeError, ValueError, yaml.YAMLError):
            raise _file_error("configuration file is not valid YAML") from None
        finally:
            if loader is not None:
                loader.dispose()  # type: ignore[no-untyped-call]
        if not isinstance(loaded, Mapping):
            raise _file_error("configuration file root MUST be a mapping")
        if any(not isinstance(key, str) for key in loaded):
            raise _file_error("configuration file keys MUST be strings")
        self._cached = load_from_mapping(loaded)
        return self._cached


def _file_error(message: str) -> ConfigError:
    return ConfigError([ConfigIssue(key="CONFIG_FILE", message=message)])


def _parse_env_value(env_var: str, value: str) -> object:
    if env_var in _FLOAT_ENV_VARS:
        try:
            parsed = float(value)
        except ValueError as exc:
            raise ValueError("must be a finite decimal number") from exc
        if not isfinite(parsed):
            raise ValueError("must be a finite decimal number")
        return parsed
    if env_var in _INT_ENV_VARS:
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError("must be an integer") from exc
    return value


def _assign(target: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    """Nested-dict assignment for ``('kafka', 'topic_events')``-style paths."""
    cursor = target
    for key in path[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[path[-1]] = value


__all__ = ["ConfigProvider", "EnvVarConfigProvider", "YamlFileConfigProvider"]
