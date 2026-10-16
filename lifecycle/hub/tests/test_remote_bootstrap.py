from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy.engine import make_url

from fdai_lifecycle_hub import remote


@pytest.mark.parametrize("mode", ["verify-ca", "require", "disable"])
def test_remote_database_requires_hostname_verification(monkeypatch, mode):
    monkeypatch.setenv(
        "FDAI_RELEASE_HUB_DATABASE_URL",
        f"postgresql+psycopg://synthetic-role@database.example.com/vendor?sslmode={mode}",
    )
    with pytest.raises(ValueError, match="verified TLS"):
        remote.remote_engine("release")


def test_password_dsn_is_rejected_and_expected_startup_errors_are_sanitized(monkeypatch, capsys):
    url = make_url("postgresql+psycopg://synthetic-role@database.example.com/vendor")
    monkeypatch.setenv(
        "FDAI_RELEASE_HUB_DATABASE_URL",
        url.set(
            password="synthetic-sensitive-marker", query={"sslmode": "verify-full"}
        ).render_as_string(hide_password=False),
    )
    with pytest.raises(ValueError, match="Managed Identity"):
        remote.remote_engine("release")
    monkeypatch.setattr(sys, "argv", ["fdai-hub-remote", "serve"])
    monkeypatch.setenv("FDAI_HUB_REMOTE_CONFIG", "synthetic-sensitive-marker")
    with pytest.raises(SystemExit) as failure:
        remote.main()
    assert "synthetic-sensitive-marker" not in str(failure.value)
    assert "synthetic-sensitive-marker" not in capsys.readouterr().err


def test_managed_identity_binding_and_no_key_generation(monkeypatch):
    monkeypatch.delenv("FDAI_HUB_MANAGED_IDENTITY_CLIENT_ID", raising=False)
    monkeypatch.setenv(
        "FDAI_RELEASE_HUB_DATABASE_URL",
        "postgresql+psycopg://synthetic-role@database.example.com/vendor?sslmode=verify-full",
    )
    with pytest.raises(ValueError, match="own Managed Identity"):
        remote.remote_engine("release")
    monkeypatch.delenv("FDAI_HUB_DEVELOPMENT_SIGNING_KEY", raising=False)
    with pytest.raises(ValueError, match="Provision an independent"):
        remote.remote_key(1)
    assert "FDAI_HUB_DEVELOPMENT_SIGNING_KEY" not in os.environ
