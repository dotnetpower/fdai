"""Fail-fast YAML configuration provider tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.shared.config import AppConfig, ConfigError, ConfigProvider
from fdai.shared.config.provider import YamlFileConfigProvider

VALID_YAML = """\
schema_version: 1.0.0
azure:
  tenant_id: 00000000-0000-0000-0000-000000000000
  subscription_id: 00000000-0000-0000-0000-000000000000
  region: krc
kafka:
  bootstrap_servers: evhns-fdai.example.local:9093
  topic_events: fdai.change.events
postgres:
  host: psql-fdai.example.local
  database: fdai
runtime:
  env: dev
"""


def _write(path: Path, body: str = VALID_YAML) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_yaml_provider_loads_the_shared_config_shape(tmp_path: Path) -> None:
    provider: ConfigProvider = YamlFileConfigProvider(_write(tmp_path / "fdai.yaml"))

    config = provider.get()

    assert isinstance(config, AppConfig)
    assert config.azure.region == "krc"
    assert config.runtime.autonomy_mode_default.value == "shadow"


def test_yaml_provider_reports_file_boundary_failures(tmp_path: Path) -> None:
    cases = (
        (tmp_path / "missing.yaml", "unavailable"),
        (_write(tmp_path / "invalid.yaml", "azure: ["), "not valid YAML"),
        (_write(tmp_path / "sequence.yaml", "- value"), "root MUST be a mapping"),
        (
            _write(
                tmp_path / "duplicate.yaml",
                VALID_YAML + "\nruntime:\n  env: prod\n",
            ),
            "not valid YAML",
        ),
        (_write(tmp_path / "complex-key.yaml", "? [one, two]\n: value\n"), "not valid YAML"),
    )

    for path, expected in cases:
        with pytest.raises(ConfigError, match=expected) as exc:
            YamlFileConfigProvider(path).get()
        assert {issue.key for issue in exc.value.issues} == {"CONFIG_FILE"}
        assert exc.value.__cause__ is None


def test_yaml_provider_rejects_symlinks_and_non_regular_files(tmp_path: Path) -> None:
    target = _write(tmp_path / "target.yaml")
    symlink = tmp_path / "linked.yaml"
    symlink.symlink_to(target)

    with pytest.raises(ConfigError, match="unavailable"):
        YamlFileConfigProvider(symlink).get()
    with pytest.raises(ConfigError, match="regular file"):
        YamlFileConfigProvider(tmp_path).get()


def test_yaml_provider_rejects_non_utf8_and_oversized_files(tmp_path: Path) -> None:
    non_utf8 = tmp_path / "non-utf8.yaml"
    non_utf8.write_bytes(b"\xff")
    oversized = tmp_path / "oversized.yaml"
    oversized.write_bytes(b"x" * 1_048_577)

    with pytest.raises(ConfigError, match="MUST be UTF-8"):
        YamlFileConfigProvider(non_utf8).get()
    with pytest.raises(ConfigError, match="exceeds the 1 MiB limit"):
        YamlFileConfigProvider(oversized).get()


def test_yaml_parse_error_does_not_retain_payload_or_path(tmp_path: Path) -> None:
    path = _write(tmp_path / "sensitive-name.yaml", "password: [")

    with pytest.raises(ConfigError) as exc:
        YamlFileConfigProvider(path).get()

    rendered = str(exc.value)
    assert "password" not in rendered
    assert path.name not in rendered
    assert exc.value.__cause__ is None


def test_yaml_reader_and_nesting_failures_are_sanitized(tmp_path: Path) -> None:
    nul = tmp_path / "nul.yaml"
    nul.write_bytes(b"schema_version: 1.0.0\nvalue: \x00\n")
    deep = _write(
        tmp_path / "deep.yaml",
        "value: " + "[" * 1_100 + "0" + "]" * 1_100,
    )

    for path in (nul, deep):
        with pytest.raises(ConfigError, match="not valid YAML") as exc:
            YamlFileConfigProvider(path).get()
        assert exc.value.__cause__ is None


def test_yaml_provider_reuses_its_validated_startup_snapshot(tmp_path: Path) -> None:
    path = _write(tmp_path / "fdai.yaml")
    provider = YamlFileConfigProvider(path)
    first = provider.get()
    path.write_text("invalid: true\n", encoding="utf-8")

    assert provider.get() is first


def test_yaml_provider_preserves_schema_and_model_errors(tmp_path: Path) -> None:
    path = _write(tmp_path / "invalid-config.yaml", VALID_YAML.replace("env: dev", "env: test"))

    with pytest.raises(ConfigError) as exc:
        YamlFileConfigProvider(path).get()

    assert any(issue.key == "runtime.env" for issue in exc.value.issues)
