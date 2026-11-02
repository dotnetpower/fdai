"""Tests for the standard-library Zstandard (PEP 784) codec, dictionary batching,
discovery rule bundle acceleration, and snapshot mirror Zstd transport."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fdai.rule_catalog.pipeline.snapshot_mirror import (
    SnapshotMirror,
    decode_mirrored_file_content,
)
from fdai.rule_catalog.schema.discovery_rule import (
    deserialize_discovery_rule_bundle,
    discovery_tree_sha256,
    load_discovery_rule_bundle,
    load_discovery_rule_catalog,
    write_discovery_rule_bundle,
)
from fdai.rule_catalog.schema.zstd_codec import (
    ZstdCodecError,
    ZstdDictionaryBatch,
    canonical_sha256,
    compress_bytes,
    compress_record_batch,
    decode_zstd_text_armor,
    decompress_bytes,
    decompress_json,
    decompress_record_batch,
    encode_zstd_text_armor,
    is_zstd_frame,
    read_zstd_json,
    train_record_dictionary,
    write_zstd_json,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry


def test_zstd_envelope_roundtrip_and_canonical_uncompressed_sha256() -> None:
    payload = ("fdai-operational-telemetry-sample-" * 200).encode("utf-8")
    env3 = compress_bytes(payload, level=3)
    env19 = compress_bytes(payload, level=19)

    assert is_zstd_frame(env3.compressed_bytes)
    assert env3.uncompressed_sha256 == canonical_sha256(payload)
    assert env19.uncompressed_sha256 == env3.uncompressed_sha256
    assert env3.compressed_size < env3.uncompressed_size
    assert env3.compression_ratio > 5.0
    assert 0.80 < env3.space_savings_ratio < 1.0

    restored = decompress_bytes(
        env3.compressed_bytes,
        expected_uncompressed_sha256=env3.uncompressed_sha256,
    )
    assert restored == payload


def test_zstd_decompression_bomb_and_integrity_guards_fail_closed() -> None:
    repetitive = b"A" * (512 * 1024)
    env = compress_bytes(repetitive, level=3)

    with pytest.raises(ZstdCodecError, match="exceeds max_output_size"):
        decompress_bytes(env.compressed_bytes, max_output_size=64 * 1024)

    with pytest.raises(ZstdCodecError, match="SHA-256 mismatch"):
        decompress_bytes(
            env.compressed_bytes,
            expected_uncompressed_sha256="sha256:" + ("0" * 64),
        )

    with pytest.raises(ZstdCodecError, match="magic header"):
        decompress_bytes(b"not-a-zstd-frame")

    with pytest.raises(ZstdCodecError, match="trailing bytes"):
        decompress_bytes(env.compressed_bytes + b"trailing-garbage")

    with pytest.raises(ZstdCodecError, match="truncated|decompression failed"):
        decompress_bytes(env.compressed_bytes[:-6])


def test_zstd_json_and_transparent_file_reader_writer(tmp_path: Path) -> None:
    doc = {
        "catalog_version": "1.4.0",
        "items": [{"id": f"item-{idx}", "status": "reviewed"} for idx in range(50)],
    }
    zst_path = tmp_path / "catalog.json.zst"
    plain_path = tmp_path / "catalog.json"

    env = write_zstd_json(zst_path, doc, level=9)
    plain_bytes = (
        '{"catalog_version":"1.4.0","items":['
        + ",".join(f'{{"id":"item-{idx}","status":"reviewed"}}' for idx in range(50))
        + "]}"
    ).encode("utf-8")
    plain_path.write_bytes(plain_bytes)

    assert (
        read_zstd_json(
            zst_path,
            expected_uncompressed_sha256=env.uncompressed_sha256,
        )
        == doc
    )
    assert (
        read_zstd_json(
            plain_path,
            expected_uncompressed_sha256=canonical_sha256(plain_bytes),
        )
        == doc
    )
    assert decompress_json(env.compressed_bytes) == doc


def test_zstd_text_armor_roundtrip_and_plain_fallback() -> None:
    raw_json = (
        '{"resource_type":"compute.vm","zone":"1","state":"Running","tags":{"env":"prod"}}' * 10
    )
    digest = canonical_sha256(raw_json)
    armored = encode_zstd_text_armor(raw_json, level=3)

    assert armored.startswith(f"zstd1:{digest}:")
    assert len(armored) < len(raw_json)
    assert decode_zstd_text_armor(armored, expected_uncompressed_sha256=digest) == raw_json
    assert decode_zstd_text_armor(raw_json, expected_uncompressed_sha256=digest) == raw_json

    with pytest.raises(ZstdCodecError, match="mismatch"):
        decode_zstd_text_armor(armored, expected_uncompressed_sha256="sha256:" + ("f" * 64))


def test_zstd_dictionary_training_dramatically_improves_small_record_compression() -> None:
    records = [
        (
            f'{{"question_id":"devops-sre.case-{idx:03d}","source_kind":"candidate",'
            f'"domain":"root_cause_analysis","readiness":{{"content_review":"reviewed",'
            f'"semantic_contract":"covered","runtime_binding":"bound",'
            f'"evidence_source":"contract_only","validation":"contract_passed"}},'
            f'"safety":{{"action_posture":"read_only","execution_authority":false}},'
            f'"target_kinds":["KubernetesCluster","KubernetesPod","CausalHypothesis"]}}'
        )
        for idx in range(120)
    ]
    no_dict_bytes = sum(len(compress_bytes(r.encode("utf-8")).compressed_bytes) for r in records)
    dictionary = train_record_dictionary(records, dict_size=8192)
    batch = compress_record_batch(records, dictionary=dictionary, level=3)

    assert dictionary.dict_id > 0
    assert batch.compressed_total_bytes < no_dict_bytes * 0.35
    assert batch.compression_ratio > 5.0

    restored = [r.decode("utf-8") for r in decompress_record_batch(batch)]
    assert restored == records

    tampered = ZstdDictionaryBatch(
        dict_sha256="sha256:" + ("0" * 64),
        dict_id=batch.dict_id,
        dict_bytes=batch.dict_bytes,
        record_digests=batch.record_digests,
        compressed_records=batch.compressed_records,
        uncompressed_total_bytes=batch.uncompressed_total_bytes,
        compressed_total_bytes=batch.compressed_total_bytes,
    )
    with pytest.raises(ZstdCodecError, match="dictionary SHA-256 mismatch"):
        decompress_record_batch(tampered)


def _sample_discovery_yaml(rule_id: str, severity: str = "high") -> str:
    return (
        'schema_version: "1.0.0"\n'
        f"id: {rule_id}\n"
        'version: "1.0.0"\n'
        "source: azure_policy\n"
        f"severity: {severity}\n"
        "category: security\n"
        "resource_type: object-storage\n"
        "check_logic:\n"
        "  kind: expression\n"
        "  reference: azure-policy://00000000-0000-0000-0000-000000000000\n"
        "remediation:\n"
        "  template_ref: remediation/object_storage/enforce_https_only.tftpl\n"
        "remediates: remediate.enforce-https-only\n"
        "parameters: {}\n"
        "provenance:\n"
        "  source_url: https://example.com/policy\n"
        '  source_version: "1.0.0"\n'
        "  resolved_ref: d315bc3b9c8a382e540add3562fff4a82e027635\n"
        "  content_hash: sha256:3f53cbbf1eb263c1b28f8914172e1869578868ba19007c3ea257741e3e9874df\n"
        "  license: MIT\n"
        "  redistribution: embeddable\n"
        '  retrieved_at: "2026-07-01T00:00:00Z"\n'
    )


def test_discovery_rule_bundle_roundtrip_and_invalidation_on_file_edit(tmp_path: Path) -> None:
    registry = PackageResourceSchemaRegistry()
    root = tmp_path / "collected"
    root.mkdir()
    p1 = root / "rule-a.yaml"
    p2 = root / "rule-b.yaml"
    p1.write_text(_sample_discovery_yaml("azure-builtin.sample.rule-a", "high"), encoding="utf-8")
    p2.write_text(_sample_discovery_yaml("azure-builtin.sample.rule-b", "medium"), encoding="utf-8")

    bundle_path = tmp_path / "discovery.json.zst"
    rules = load_discovery_rule_catalog(root, schema_registry=registry, bundle_path=bundle_path)
    assert len(rules) == 2
    assert bundle_path.is_file()

    tree_sha = discovery_tree_sha256(root, schema_registry=registry)
    loaded_from_bundle = load_discovery_rule_bundle(bundle_path, expected_tree_sha256=tree_sha)
    assert loaded_from_bundle == rules

    with pytest.raises(ZstdCodecError, match="tree_sha256 mismatch"):
        load_discovery_rule_bundle(bundle_path, expected_tree_sha256="sha256:" + ("a" * 64))

    # Modifying a YAML file invalidates the bundle digest and reloads from YAML
    p2.write_text(_sample_discovery_yaml("azure-builtin.sample.rule-b", "low"), encoding="utf-8")
    updated_rules = load_discovery_rule_catalog(
        root, schema_registry=registry, bundle_path=bundle_path
    )
    assert updated_rules[1].severity.value == "low"
    env = write_discovery_rule_bundle(
        updated_rules,
        bundle_path,
        tree_sha256=discovery_tree_sha256(root, schema_registry=registry),
    )
    assert deserialize_discovery_rule_bundle(env.compressed_bytes) == updated_rules


async def test_snapshot_mirror_zstd_preserves_tree_sha256_and_verifies_readback(
    tmp_path: Path,
) -> None:
    class _MemStore:
        def __init__(self) -> None:
            self.blobs: dict[str, tuple[bytes, str]] = {}

        async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool:
            assert hashlib.sha256(content).hexdigest() == digest
            if storage_ref in self.blobs:
                return False
            self.blobs[storage_ref] = (content, digest)
            return True

    snap = tmp_path / "snap"
    snap.mkdir()
    raw_content = ("policy: sample-control\n" * 200).encode("utf-8")
    (snap / "control.yaml").write_bytes(raw_content)

    plain_store = _MemStore()
    zstd_store = _MemStore()
    plain_receipt = await SnapshotMirror(store=plain_store, compress_zstd=False).mirror(
        source_id="azure_policy",
        resolved_revision="rev-1",
        snapshot_dir=snap,
    )
    zstd_receipt = await SnapshotMirror(store=zstd_store, compress_zstd=True).mirror(
        source_id="azure_policy",
        resolved_revision="rev-1",
        snapshot_dir=snap,
    )

    assert plain_receipt.tree_sha256 == zstd_receipt.tree_sha256
    zfile = zstd_receipt.files[0]
    assert zfile.storage_ref.endswith(".zst")
    assert zfile.compressed_size_bytes is not None
    assert zfile.compressed_size_bytes < zfile.size_bytes
    stored_bytes, _ = zstd_store.blobs[zfile.storage_ref]
    assert (
        decode_mirrored_file_content(
            stored_bytes,
            expected_uncompressed_digest=zfile.digest,
        )
        == raw_content
    )
