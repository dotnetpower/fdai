"""Pinned Azure Bicep provider-schema corpus parser tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.delivery.azure.provider_schema import (
    AzureBicepProviderSchemaParser,
    GitAzureBicepProviderSchemaSource,
    LocalAzureBicepProviderSchemaSource,
)
from fdai.delivery.provider_schema import ProviderSchemaError

REVISION = "a" * 40


def _write_corpus(root: Path) -> None:
    generated = root / "generated"
    stable = generated / "microsoft.example" / "2025-01-01" / "types.md"
    preview = generated / "microsoft.example" / "2025-02-01-preview" / "types.md"
    read_only = generated / "microsoft.example" / "2024-12-01" / "types.md"
    stable.parent.mkdir(parents=True)
    preview.parent.mkdir(parents=True)
    read_only.parent.mkdir(parents=True)
    (generated / "index.md").write_text(
        "\n".join(
            (
                "# Index",
                "### Microsoft.Example/widgets",
                "* **Link**: [2025-01-01](./microsoft.example/2025-01-01/types.md#resource-widget)",
                "* **Link**: [2025-02-01-preview](./microsoft.example/2025-02-01-preview/types.md)",
                "### Microsoft.Example/widgets/parts",
                "* **Link**: [2025-01-01](./microsoft.example/2025-01-01/types.md)",
                "### Microsoft.Example/reports",
                "* **Link**: [2024-12-01](./microsoft.example/2024-12-01/types.md)",
                "### Microsoft.Example/previews",
                "* **Link**: [2025-02-01-preview](./microsoft.example/2025-02-01-preview/types.md)",
            )
        ),
        encoding="utf-8",
    )
    stable.write_text(
        "\n".join(
            (
                "# Stable",
                "## Resource Microsoft.Example/widgets@2025-01-01",
                "**Readable Scope(s):** resourceGroup, subscription",
                "**Writable Scope(s):** resourceGroup",
                "## Resource Microsoft.Example/widgets/parts@2025-01-01",
                "**Readable Scope(s):** resourceGroup",
                "**Writable Scope(s):** resourceGroup",
            )
        ),
        encoding="utf-8",
    )
    preview.write_text(
        "\n".join(
            (
                "# Preview",
                "## Resource Microsoft.Example/previews@2025-02-01-preview",
                "**Readable Scope(s):** resourceGroup",
                "**Writable Scope(s):** resourceGroup",
            )
        ),
        encoding="utf-8",
    )
    read_only.write_text(
        "\n".join(
            (
                "# Reports",
                "## Resource Microsoft.Example/reports@2024-12-01",
                "**Readable Scope(s):** subscription",
                "**Writable Scope(s):** None",
            )
        ),
        encoding="utf-8",
    )


def test_parses_complete_index_with_stable_preference_and_hierarchy(tmp_path: Path) -> None:
    _write_corpus(tmp_path)

    snapshot = AzureBicepProviderSchemaParser(min_type_count=4, max_type_count=4).parse(
        tree_root=tmp_path,
        source_revision=REVISION,
    )

    by_type = {item.resource_type: item for item in snapshot.types}
    widget = by_type["microsoft.example/widgets"]
    assert widget.stable_api_versions == ("2025-01-01",)
    assert widget.preview_api_versions == ("2025-02-01-preview",)
    assert widget.preferred_api_version == "2025-01-01"
    assert widget.writable_scopes == ("resourceGroup",)
    assert by_type["microsoft.example/widgets/parts"].parent_type == ("microsoft.example/widgets")
    assert by_type["microsoft.example/reports"].scope_evidence_available is True
    assert by_type["microsoft.example/reports"].writable_scopes == ()
    assert by_type["microsoft.example/previews"].stable_api_versions == ()


def test_rejects_partial_index_when_preferred_document_is_missing(tmp_path: Path) -> None:
    _write_corpus(tmp_path)
    missing = tmp_path / "generated" / "microsoft.example" / "2024-12-01" / "types.md"
    missing.unlink()

    with pytest.raises(ProviderSchemaError, match="unavailable bounded document"):
        AzureBicepProviderSchemaParser().parse(
            tree_root=tmp_path,
            source_revision=REVISION,
        )


def test_rejects_mutable_revision_and_type_count_truncation(tmp_path: Path) -> None:
    _write_corpus(tmp_path)
    parser = AzureBicepProviderSchemaParser(min_type_count=5)

    with pytest.raises(ProviderSchemaError, match="immutable lowercase hex"):
        parser.parse(tree_root=tmp_path, source_revision="main")
    with pytest.raises(ProviderSchemaError, match="complete-corpus bounds"):
        parser.parse(tree_root=tmp_path, source_revision=REVISION)


def test_rejects_index_path_escape(tmp_path: Path) -> None:
    _write_corpus(tmp_path)
    index = tmp_path / "generated" / "index.md"
    index.write_text(
        "### Microsoft.Example/widgets\n* **Link**: [2025-01-01](../../outside/types.md)\n",
        encoding="utf-8",
    )
    outside = tmp_path.parent / "outside" / "types.md"
    outside.parent.mkdir(exist_ok=True)
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(ProviderSchemaError, match="bounded document"):
        AzureBicepProviderSchemaParser().parse(
            tree_root=tmp_path,
            source_revision=REVISION,
        )


async def test_local_primary_mirror_and_offline_trees_produce_same_digest(
    tmp_path: Path,
) -> None:
    _write_corpus(tmp_path)
    parser = AzureBicepProviderSchemaParser(min_type_count=4, max_type_count=4)

    snapshots = [
        await LocalAzureBicepProviderSchemaSource(
            tree_root=tmp_path,
            source_revision=REVISION,
            parser=parser,
        ).collect()
        for _ in range(3)
    ]

    assert len({snapshot.schema_digest for snapshot in snapshots}) == 1


async def test_git_source_resolves_then_fetches_exact_revision(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    _write_corpus(corpus)
    calls: list[tuple[str, str]] = []

    def resolve(repo_url: str, revision_ref: str, timeout_seconds: float) -> str:
        assert timeout_seconds == 10
        calls.append((repo_url, revision_ref))
        return REVISION

    def fetch(repo_url: str, revision: str, destination: Path, timeout_seconds: float) -> Path:
        assert destination.is_dir()
        assert timeout_seconds == 10
        calls.append((repo_url, revision))
        return corpus

    source = GitAzureBicepProviderSchemaSource(
        repo_url="https://example.com/Azure/bicep-types-az.git",
        revision_ref="refs/heads/main",
        parser=AzureBicepProviderSchemaParser(min_type_count=4, max_type_count=4),
        timeout_seconds=10,
        revision_resolver=resolve,
        tree_fetcher=fetch,
    )

    snapshot = await source.collect()

    assert snapshot.source_revision == REVISION
    assert calls == [
        ("https://example.com/Azure/bicep-types-az.git", "refs/heads/main"),
        ("https://example.com/Azure/bicep-types-az.git", REVISION),
    ]


async def test_git_source_uses_configured_exact_revision_without_lookup(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    _write_corpus(corpus)
    resolved = False

    def resolve(repo_url: str, revision_ref: str, timeout_seconds: float) -> str:
        nonlocal resolved
        resolved = True
        return REVISION

    source = GitAzureBicepProviderSchemaSource(
        repo_url="https://example.com/Azure/bicep-types-az.git",
        revision_ref=REVISION,
        parser=AzureBicepProviderSchemaParser(min_type_count=4, max_type_count=4),
        revision_resolver=resolve,
        tree_fetcher=lambda _repo, _revision, _destination, _timeout: corpus,
    )

    snapshot = await source.collect()

    assert snapshot.source_revision == REVISION
    assert resolved is False


@pytest.mark.parametrize(
    "repo_url",
    [
        "http://example.com/repo.git",
        "https://user@example.com/repo.git",
        "https://example.com/repo.git?token=secret",
    ],
)
def test_git_source_rejects_insecure_or_credential_bearing_urls(repo_url: str) -> None:
    with pytest.raises(ValueError, match="credential-free HTTPS"):
        GitAzureBicepProviderSchemaSource(
            repo_url=repo_url,
            revision_ref="refs/heads/main",
            parser=AzureBicepProviderSchemaParser(),
        )
