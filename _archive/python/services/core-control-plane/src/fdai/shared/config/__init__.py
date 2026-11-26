"""Config schema and startup validation (fail-fast).

Public API. Re-exports the *interfaces* and *data models* that core modules
depend on. Concrete implementations (``EnvVarConfigProvider``) are
intentionally not re-exported here - they must be imported from their
submodules by the composition root only, so ``core/`` cannot accidentally
depend on a concrete adapter.
"""

from .errors import ConfigError, ConfigIssue
from .loader import load_config_from_env, load_from_mapping
from .models import (
    AppConfig,
    AzureConfig,
    KafkaConfig,
    PostgresConfig,
    RuleCatalogConfig,
    RuntimeConfig,
    RuntimeEnv,
)
from .provider import ConfigProvider

__all__ = [
    "AppConfig",
    "AzureConfig",
    "ConfigError",
    "ConfigIssue",
    "ConfigProvider",
    "KafkaConfig",
    "PostgresConfig",
    "RuleCatalogConfig",
    "RuntimeConfig",
    "RuntimeEnv",
    "load_config_from_env",
    "load_from_mapping",
]
