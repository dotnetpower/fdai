"""Runtime skill bundle and bounded disclosure tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
import yaml

from fdai.core.skills import (
    RuntimeSkill,
    SkillAccessError,
    SkillCatalog,
    SkillCatalogError,
    SkillReferenceArtifact,
    SkillRejectionReason,
    skill_body_digest,
)


class _Verifier:
    def __init__(self, trusted: bool = True) -> None:
        self.trusted = trusted
        self.calls = 0

    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        self.calls += 1
        return self.trusted


def _raw_skill(
    *,
    name: str = "inventory-evidence",
    description: str = "Collect bounded inventory evidence.",
    required_tools: tuple[str, ...] = ("query_inventory",),
    allowed_agents: tuple[str, ...] = ("Bragi",),
    references: tuple[tuple[str, bytes, str], ...] = (),
    reference_entries: list[dict[str, object]] | None = None,
) -> bytes:
    body = f"Use {name} instructions completely."
    entries = reference_entries
    if entries is None:
        entries = [
            {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "media_type": media_type,
            }
            for path, content, media_type in references
        ]
    front_matter: dict[str, object] = {
        "name": name,
        "version": "1.0.0",
        "description": description,
        "source": f"source:{name}",
        "body_sha256": skill_body_digest(body),
        "required_tools": list(required_tools),
        "allowed_agents": list(allowed_agents),
    }
    if entries:
        front_matter["references"] = entries
    serialized = yaml.safe_dump(front_matter, sort_keys=False)
    return f"---\n{serialized}---\n{body}\n".encode()


def _enabled_bundle(
    *,
    references: tuple[tuple[str, bytes, str], ...] = (),
    verifier: _Verifier | None = None,
) -> tuple[SkillCatalog, _Verifier]:
    trust = verifier or _Verifier()
    raw = _raw_skill(references=references)
    bundle = {path: content for path, content, _media_type in references}
    catalog = (
        SkillCatalog()
        .install_bundle(raw, bundle, verifier=trust)
        .enable(
            "inventory-evidence",
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
    )
    return catalog, trust


def test_bundle_install_and_read_reverify_complete_artifacts() -> None:
    reference = ("references/guide.txt", b"bounded evidence", "text/plain")
    catalog, verifier = _enabled_bundle(references=(reference,))

    loaded = catalog.load_skill(
        "inventory-evidence",
        agent="Bragi",
        available_tools=frozenset({"query_inventory"}),
        verifier=verifier,
        max_chars=1_000,
    )
    read = catalog.read_skill_reference(
        "inventory-evidence",
        reference[0],
        agent="Bragi",
        available_tools=frozenset({"query_inventory"}),
        verifier=verifier,
        max_bytes=1_000,
    )
    described = catalog.describe_skill("inventory-evidence")

    assert loaded.body == "Use inventory-evidence instructions completely.\n"
    assert read.content == reference[1]
    assert read.reference.path == reference[0]
    assert described.descriptor.references == (read.reference,)
    assert "instructions completely" not in repr(described)
    assert loaded.replay.raw_markdown_sha256
    assert verifier.calls == 3


def test_index_is_deterministic_ranked_metadata_only_and_bounded() -> None:
    verifier = _Verifier()
    catalog = SkillCatalog()
    for name, description, tools in (
        ("generic-helper", "General evidence collection.", ("query_inventory",)),
        ("network-evidence", "Collect network route evidence.", ("query_network",)),
        ("private-evidence", "Collect private evidence.", ("query_private",)),
    ):
        raw = _raw_skill(name=name, description=description, required_tools=tools)
        catalog = catalog.install(raw, verifier=verifier).enable(
            name,
            available_tools=frozenset(tools),
            known_agents=frozenset({"Bragi"}),
        )

    result = catalog.list_skills(
        query="network route",
        agent="Bragi",
        available_tools=frozenset({"query_inventory", "query_network"}),
    )

    assert [entry.descriptor.name for entry in result.entries] == [
        "network-evidence",
        "generic-helper",
    ]
    assert result.entries[0].query_token_overlap == 2
    assert "instructions completely" not in repr(result)
    with pytest.raises(SkillAccessError) as caught:
        catalog.list_skills(
            query="network route",
            agent="Bragi",
            available_tools=frozenset({"query_inventory", "query_network"}),
            max_chars=1,
        )
    assert caught.value.reason is SkillRejectionReason.INDEX_BUDGET_EXCEEDED


@pytest.mark.parametrize(
    ("agent", "tools", "reason"),
    [
        ("Saga", frozenset({"query_inventory"}), SkillRejectionReason.AGENT_NOT_ALLOWED),
        ("Bragi", frozenset(), SkillRejectionReason.REQUIRED_TOOLS_UNAVAILABLE),
    ],
)
def test_load_rejects_ineligible_agent_or_tools(
    agent: str,
    tools: frozenset[str],
    reason: SkillRejectionReason,
) -> None:
    catalog, verifier = _enabled_bundle()

    with pytest.raises(SkillAccessError) as caught:
        catalog.load_skill(
            "inventory-evidence",
            agent=agent,
            available_tools=tools,
            verifier=verifier,
            max_chars=1_000,
        )

    assert caught.value.reason is reason
    assert not hasattr(caught.value, "body")


def test_disabled_skill_rejects_before_trust_or_body_disclosure() -> None:
    verifier = _Verifier()
    catalog = SkillCatalog().install(_raw_skill(), verifier=verifier)

    with pytest.raises(SkillAccessError) as caught:
        catalog.load_skill(
            "inventory-evidence",
            agent="Bragi",
            available_tools=frozenset({"query_inventory"}),
            verifier=verifier,
            max_chars=1_000,
        )

    assert caught.value.reason is SkillRejectionReason.DISABLED
    assert verifier.calls == 1


def test_each_load_rechecks_publisher_trust() -> None:
    catalog, _install_verifier = _enabled_bundle()

    with pytest.raises(SkillAccessError) as caught:
        catalog.load_skill(
            "inventory-evidence",
            agent="Bragi",
            available_tools=frozenset({"query_inventory"}),
            verifier=_Verifier(False),
            max_chars=1_000,
        )

    assert caught.value.reason is SkillRejectionReason.TRUST_VERIFICATION_FAILED


@pytest.mark.parametrize("tamper", ["body", "reference"])
def test_tampered_stored_content_fails_closed(tamper: str) -> None:
    reference = ("references/guide.txt", b"bounded evidence", "text/plain")
    catalog, verifier = _enabled_bundle(references=(reference,))
    current = catalog.get("inventory-evidence")
    if tamper == "body":
        changed = replace(current, body="tampered\n")
    else:
        stored_reference = current.references[0]
        changed = replace(
            current,
            references=(
                SkillReferenceArtifact(
                    manifest=stored_reference.manifest,
                    content=b"tampered evidence",
                ),
            ),
        )
    tampered = SkillCatalog({"inventory-evidence": changed})

    with pytest.raises(SkillAccessError) as caught:
        tampered.load_skill(
            "inventory-evidence",
            agent="Bragi",
            available_tools=frozenset({"query_inventory"}),
            verifier=verifier,
            max_chars=1_000,
        )

    assert caught.value.reason is SkillRejectionReason.STORED_ARTIFACT_INVALID


@pytest.mark.parametrize("mode", ["missing", "extra", "size", "digest"])
def test_bundle_mismatch_fails_before_trust(mode: str) -> None:
    content = b"bounded evidence"
    entry = {
        "path": "references/guide.txt",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
        "media_type": "text/plain",
    }
    supplied: dict[str, bytes] = {"references/guide.txt": content}
    if mode == "missing":
        supplied = {}
    elif mode == "extra":
        supplied["references/extra.txt"] = b"extra"
    elif mode == "size":
        entry["size_bytes"] = len(content) + 1
    elif mode == "digest":
        entry["sha256"] = "0" * 64
    verifier = _Verifier()

    with pytest.raises(SkillCatalogError):
        SkillCatalog().install_bundle(
            _raw_skill(reference_entries=[entry]),
            supplied,
            verifier=verifier,
        )

    assert verifier.calls == 0


@pytest.mark.parametrize(
    "path",
    [
        "/references/guide.txt",
        "references/../guide.txt",
        "references/./guide.txt",
        "references\\guide.txt",
    ],
)
def test_reference_path_must_be_safe_relative_posix(path: str) -> None:
    entry = {
        "path": path,
        "sha256": hashlib.sha256(b"data").hexdigest(),
        "size_bytes": 4,
        "media_type": "text/plain",
    }

    with pytest.raises(SkillCatalogError, match="safe"):
        SkillCatalog().install_bundle(
            _raw_skill(reference_entries=[entry]),
            {path: b"data"},
            verifier=_Verifier(),
        )


def test_duplicate_and_symlink_like_reference_metadata_are_rejected() -> None:
    entry = {
        "path": "references/guide.txt",
        "sha256": hashlib.sha256(b"data").hexdigest(),
        "size_bytes": 4,
        "media_type": "text/plain",
    }
    with pytest.raises(SkillCatalogError, match="duplicate"):
        SkillCatalog().install_bundle(
            _raw_skill(reference_entries=[entry, entry.copy()]),
            {"references/guide.txt": b"data"},
            verifier=_Verifier(),
        )
    with pytest.raises(SkillCatalogError, match="unknown keys"):
        SkillCatalog().install_bundle(
            _raw_skill(reference_entries=[entry | {"link_target": "references/other.txt"}]),
            {"references/guide.txt": b"data"},
            verifier=_Verifier(),
        )


def test_oversized_reference_is_rejected_from_manifest() -> None:
    entry = {
        "path": "references/large.bin",
        "sha256": "0" * 64,
        "size_bytes": 256 * 1024 + 1,
        "media_type": "application/octet-stream",
    }

    with pytest.raises(SkillCatalogError, match="256 KiB"):
        SkillCatalog().install_bundle(
            _raw_skill(reference_entries=[entry]),
            {"references/large.bin": b""},
            verifier=_Verifier(),
        )


@pytest.mark.parametrize("limit", ["count", "total"])
def test_reference_manifest_limits_fail_closed(limit: str) -> None:
    entry_count = 17 if limit == "count" else 5
    size_bytes = 1 if limit == "count" else 256 * 1024
    entries = [
        {
            "path": f"references/artifact-{index}.bin",
            "sha256": "0" * 64,
            "size_bytes": size_bytes,
            "media_type": "application/octet-stream",
        }
        for index in range(entry_count)
    ]

    with pytest.raises(SkillCatalogError, match="16 entries|1 MiB"):
        SkillCatalog().install_bundle(
            _raw_skill(reference_entries=entries),
            {},
            verifier=_Verifier(),
        )


def test_body_and_reference_budget_fail_without_partial_output() -> None:
    reference = ("references/guide.txt", b"bounded evidence", "text/plain")
    catalog, verifier = _enabled_bundle(references=(reference,))

    with pytest.raises(SkillAccessError) as body_error:
        catalog.load_skill(
            "inventory-evidence",
            agent="Bragi",
            available_tools=frozenset({"query_inventory"}),
            verifier=verifier,
            max_chars=1,
        )
    with pytest.raises(SkillAccessError) as reference_error:
        catalog.read_skill_reference(
            "inventory-evidence",
            reference[0],
            agent="Bragi",
            available_tools=frozenset({"query_inventory"}),
            verifier=verifier,
            max_bytes=1,
        )

    assert body_error.value.reason is SkillRejectionReason.BODY_BUDGET_EXCEEDED
    assert reference_error.value.reason is SkillRejectionReason.REFERENCE_BUDGET_EXCEEDED
    assert not hasattr(body_error.value, "body")
    assert not hasattr(reference_error.value, "content")
