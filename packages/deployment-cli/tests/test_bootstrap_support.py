from __future__ import annotations

from types import SimpleNamespace

import pytest

from fdai_deployment_cli import bootstrap_support as support
from fdai_deployment_cli.hub_image_trust import key_id


def signed_catalog(monkeypatch, catalog):
    raw, signature = catalog.export()
    monkeypatch.setattr(
        support,
        "hub_request",
        lambda origin, path: (
            200,
            {
                "x-fdai-export-signature": signature,
                "x-fdai-export-key-id": key_id(catalog.key.public_key()),
            },
            raw,
        ),
    )


def test_default_hub_verifies_signature_before_only_exact_official_commit_fetch(
    tmp_path,
    monkeypatch,
    hub_image_catalog,
):
    catalog = hub_image_catalog
    signed_catalog(monkeypatch, catalog)
    calls = []

    def run(command, **kwargs):
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert kwargs["env"]["GIT_CONFIG_GLOBAL"] == "/dev/null"
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(support.subprocess, "run", run)
    monkeypatch.setattr(
        support,
        "inspect_source",
        lambda root, **kwargs: calls.append(("inspect", str(root), kwargs["expected_commit"])),
    )
    area = tmp_path / "executor"
    area.mkdir(mode=0o700)
    source, selection = support.resolve_hub_source(area, catalog.pem.decode(), None)
    fetches = [call for call in calls if "fetch" in call]
    assert len(fetches) == 1
    assert fetches[0][-2:] == (support.OFFICIAL_SOURCE, selection.source_commit)
    assert "--depth=1" in fetches[0] and "--no-tags" in fetches[0]
    assert source == area / "support-source"
    assert selection.document["hub_url"] == "https://hub.msfdai.com"
    assert selection.document["channel"] == "RELEASE"
    assert selection.path.stat().st_mode & 0o777 == 0o600


def test_invalid_catalog_never_fetches_source_or_falls_back(
    tmp_path, monkeypatch, hub_image_catalog
):
    catalog = hub_image_catalog
    raw, signature = catalog.export()
    monkeypatch.setattr(
        support,
        "hub_request",
        lambda *_: (
            200,
            {
                "x-fdai-export-signature": signature,
                "x-fdai-export-key-id": key_id(catalog.key.public_key()),
            },
            raw + b" ",
        ),
    )
    monkeypatch.setattr(
        support.subprocess, "run", lambda *_a, **_k: pytest.fail("unverified fetch")
    )
    with pytest.raises(ValueError):
        support.resolve_hub_source(tmp_path, catalog.pem.decode(), None)
    assert not (tmp_path / "support-source").exists()


def test_source_retrieval_failure_is_not_service_image_build_fallback(
    tmp_path,
    monkeypatch,
    hub_image_catalog,
):
    signed_catalog(monkeypatch, hub_image_catalog)
    calls = []

    def fail(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(support.subprocess, "run", fail)
    with pytest.raises(ValueError, match="no fallback"):
        support.resolve_hub_source(tmp_path, hub_image_catalog.pem.decode(), None)
    assert len(calls) == 1
    assert not (tmp_path / "deployment").exists()


def test_supplied_hub_source_is_checked_at_exact_signed_commit_without_fetch(
    tmp_path,
    monkeypatch,
    hub_image_catalog,
):
    signed_catalog(monkeypatch, hub_image_catalog)
    commits = []
    monkeypatch.setattr(
        support, "inspect_source", lambda _root, **kwargs: commits.append(kwargs["expected_commit"])
    )
    monkeypatch.setattr(
        support.subprocess, "run", lambda *_a, **_k: pytest.fail("supplied source fetched")
    )
    _, selection = support.resolve_hub_source(
        tmp_path, hub_image_catalog.pem.decode(), "/example/checkout"
    )
    assert commits == [selection.source_commit]
