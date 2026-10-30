"""Semantic and provenance checks for the offline WARA illustrated corpus."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from fdai_service_contracts.wara_guidance import WaraGuidance, load_wara_guidance

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts/catalog"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "build_wara_guidance", SCRIPTS / "build_wara_guidance.py"
)
assert SPEC is not None and SPEC.loader is not None
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)
sys.path.remove(str(SCRIPTS))
SOURCE = ROOT / "rule-catalog/collected/wara-aprl/azure-wara.json"
OUTPUT = ROOT / "packages/service-contracts/src/fdai_service_contracts/data/wara-guidance.json"
REPORT = ROOT / "rule-catalog/guidance/azure-wara/coverage.json"
DNS = "a2341513-2ab8-4aa1-b100-302e54640f18"
MAINTENANCE = "52ab9e5c-eec0-3148-8bd7-b6dd9e1be870"
AI = "61187af4-7d36-4b48-b16e-de78bef143a0"


@pytest.fixture(scope="module")
def corpus() -> dict[str, Any]:
    index = json.loads(OUTPUT.read_text(encoding="utf-8"))
    shards = index.pop("shards")
    index["entries"] = [
        entry
        for shard in shards
        for entry in json.loads((OUTPUT.parent / shard["path"]).read_text(encoding="utf-8"))[
            "entries"
        ]
    ]
    return index


@pytest.fixture(scope="module")
def source_controls() -> dict[str, dict[str, Any]]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    return {control["id"]: control for area in source["areas"] for control in area["controls"]}


def _entry(corpus: dict[str, Any], prefix: str) -> dict[str, Any]:
    return next(
        entry for entry in corpus["entries"] if entry["recommendation_id"].startswith(prefix)
    )


def _prose(value: object, locale: str = "en") -> str:
    if isinstance(value, dict):
        if locale in value:
            return str(value[locale])
        return " ".join(_prose(item, locale) for item in value.values())
    if isinstance(value, list):
        return " ".join(_prose(item, locale) for item in value)
    return ""


def test_shared_diagram_nodes_describe_authored_connections_instead_of_repeating_scope() -> None:
    diagram = GENERATOR.build_diagram(
        "Zone redundancy",
        "Inspect placement and surviving capacity.",
        "zone-redundancy",
        {
            "en": "Illustrative, not an observed deployment.",
            "ko": "실제 배포를 관측한 결과가 아닌 구성 예시입니다.",
        },
        focus_ko="영역 중복성",
        observation_ko="배치와 잔여 용량을 확인합니다.",
    )
    nodes = {node["id"]: node for node in diagram["nodes"]}
    assert nodes["setting"]["detail"] == {
        "en": "Connects to: Failure domain A (supported placement), Failure domain B (supported placement).",
        "ko": "연결 대상: 장애 범위 A (지원 배치), 장애 범위 B (지원 배치).",
    }
    assert nodes["first"]["detail"]["ko"] == "연결 출발점: 영역 중복성 (지원 배치)."
    assert nodes["evidence"]["detail"]["ko"] == "배치와 잔여 용량을 확인합니다."
    assert diagram["description"]["ko"] == "실제 배포를 관측한 결과가 아닌 구성 예시입니다."


def test_entire_corpus_avoids_repeated_node_scope_boilerplate(corpus: dict[str, Any]) -> None:
    for entry in corpus["entries"]:
        for node in entry["diagram"]["nodes"]:
            assert "not a discovered environment resource" not in node["detail"]["en"]
            assert (
                "개념 요소이며 실제 환경에서 발견한 리소스가 아닙니다" not in node["detail"]["ko"]
            )
            assert "Source-specific focus:" not in node["detail"]["en"]


def test_korean_binding_source_has_exact_coverage(tmp_path: Path) -> None:
    source = tmp_path / "controls-ko.tsv"
    source.write_text(
        "# Reviewed counterparts\nbbbbbbbb|복원 점검|복원 후 파일을 확인합니다\n"
        "aaaaaaaa|백업 정책|정책과 복구 지점을 확인합니다\n",
        encoding="utf-8",
    )
    bindings = {"aaaaaaaa": {"focus": "Backup policy"}, "bbbbbbbb": {"focus": "Restore check"}}
    GENERATOR.load_korean_bindings(source, bindings)
    assert bindings["aaaaaaaa"]["focus_ko"] == "백업 정책"
    assert bindings["bbbbbbbb"]["observation_ko"] == "복원 후 파일을 확인합니다"
    assert bindings["aaaaaaaa"]["focus"] == "Backup policy"


@pytest.mark.parametrize(
    "rows",
    [
        "aaaaaaaa|백업 정책|정책 확인\n",
        "aaaaaaaa|백업 정책|정책 확인\naaaaaaaa|백업 정책|정책 확인\n",
        "aaaaaaaa|백업 정책|정책 확인\ncccccccc|복원 정책|복원 확인\n",
        "aaaaaaaa||정책 확인\nbbbbbbbb|복원 정책|복원 확인\n",
        "aaaaaaaa|백업 정책|정책 확인|추가 필드\nbbbbbbbb|복원 정책|복원 확인\n",
    ],
)
def test_korean_binding_source_rejects_incomplete_or_invalid_rows(
    tmp_path: Path, rows: str
) -> None:
    source = tmp_path / "controls-ko.tsv"
    source.write_text(rows, encoding="utf-8")
    bindings = {"aaaaaaaa": {"focus": "Backup policy"}, "bbbbbbbb": {"focus": "Restore check"}}
    with pytest.raises(ValueError):
        GENERATOR.load_korean_bindings(source, bindings)
    assert all("focus_ko" not in binding for binding in bindings.values())


def test_every_shared_mechanism_diagram_has_actual_korean_text() -> None:
    for profile in GENERATOR.PROFILES.values():
        diagram = GENERATOR.build_diagram(
            "Source-specific configuration",
            "Inspect configured state and recovery behavior",
            profile["shape"],
            {"en": "Conceptual diagram", "ko": "개념도"},
            focus_ko="원본별 구성",
            observation_ko="구성 상태와 복구 동작을 점검합니다",
        )
        GENERATOR.assert_korean_reader_text(
            [{"recommendation_id": profile["shape"], "diagram": diagram}], {profile["shape"]}
        )


def test_korean_reader_text_gate_rejects_english_and_wrapped_english() -> None:
    entry = {
        "recommendation_id": "example-guid",
        "title": {"en": "Configure backup", "ko": "한국어 설명: Configure backup"},
        "sources": [{"label": {"en": "Microsoft Learn source"}}],
    }

    with pytest.raises(ValueError, match="1 fields across 1 recommendations"):
        GENERATOR.assert_korean_reader_text([entry], {"example-guid"})

    entry["title"] = {"en": "Configure backup", "ko": "백업 구성"}
    entry["diagram"] = {
        "reference_image": {
            "alt": {"en": "Architecture diagram", "ko": "구성도"},
            "caption": {"en": "Architecture diagram"},
        }
    }
    with pytest.raises(ValueError, match="1 fields across 1 recommendations"):
        GENERATOR.assert_korean_reader_text([entry], {"example-guid"})

    entry["title"] = {"en": "Configure backup", "ko": "백업 구성"}
    entry["diagram"]["reference_image"]["caption"]["ko"] = "아키텍처 개요"
    GENERATOR.assert_korean_reader_text([entry], {"example-guid"})

    entry["title"] = {
        "en": "Configure backup for virtual machines",
        "ko": "Configure 백업 for virtual machines",
    }
    with pytest.raises(ValueError, match="1 fields across 1 recommendations"):
        GENERATOR.assert_korean_reader_text([entry], {"example-guid"})


def test_vm_backup_reader_text_covers_vault_flow_and_consistency_modes(
    corpus: dict[str, Any],
) -> None:
    entry = json.loads(json.dumps(_entry(corpus, "1981f704")))
    source = GENERATOR.load_reader_text(
        ROOT / "rule-catalog/guidance/azure-wara/reader-text-ko.json",
        framework_revision=corpus["framework_revision"],
        framework_digest=corpus["framework_digest"],
    )
    GENERATOR.apply_reader_text(entry, source)
    GENERATOR.assert_korean_reader_text([entry], {"1981f704-97b9-b645-9c57-33f8ded9261a"})

    korean = _prose(entry, "ko")
    assert "Recovery Services vault" in korean
    assert "스냅샷" in korean and "vault로 전송" in korean
    assert "임시 디스크" in korean
    assert "Windows VSS" in korean
    assert "Linux" in korean and "사전 및 사후 스크립트" in korean
    assert "agentless" in korean and "crash consistency" in korean
    assert any(
        edge["from"] == "snapshot"
        and edge["to"] == "copy"
        and "vault로 전송" in edge["label"]["ko"]
        for edge in entry["diagram"]["edges"]
    )
    entry["content_digest"] = GENERATOR.canonical_digest(
        {key: value for key, value in entry.items() if key != "content_digest"}
    )
    WaraGuidance.model_validate(entry)


def test_generated_json_is_compact_utf8_with_readable_korean() -> None:
    encoded = GENERATOR.encoded({"label": {"en": "Guide", "ko": "권고 안내"}})
    assert encoded == '{"label":{"en":"Guide","ko":"권고 안내"}}\n'.encode()


def test_packaged_corpus_passes_shared_contract(corpus: dict[str, Any]) -> None:
    loaded = load_wara_guidance(GENERATOR.encoded(corpus))
    assert len(loaded.entries) == 456
    assert loaded.catalog_digest == corpus["catalog_digest"]
    assert len(GENERATOR.encoded(corpus)) <= 8 * 1024 * 1024


def test_exact_lifecycle_accounting_and_source_identity(
    corpus: dict[str, Any], source_controls: dict[str, dict[str, Any]]
) -> None:
    entries = corpus["entries"]
    assert {entry["recommendation_id"] for entry in entries} == set(source_controls)
    assert Counter(entry["lifecycle"] for entry in entries) == {"active": 393, "disabled": 63}
    for entry in entries:
        source = source_controls[entry["recommendation_id"]]
        assert entry["source_digest"] == source["wara"]["source_digest"]
        assert entry["lifecycle"] == source["wara"]["state"].casefold()
        assert entry["source_revision"] == corpus["framework_revision"]
        if entry["lifecycle"] == "disabled":
            assert "retained for historical coverage" in _prose(entry["cautions"])


def test_build_is_byte_reproducible_without_network() -> None:
    catalog, report = GENERATOR.build(ROOT)
    outputs = GENERATOR.artifact_outputs(catalog, report, ROOT)
    assert all(content == path.read_bytes() for path, content in outputs.items())
    assert GENERATOR.build(ROOT) == (catalog, report)


def test_offline_build_cannot_open_network_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Corpus build must never open a network or model connection")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    catalog, _report = GENERATOR.build(ROOT)
    assert len(catalog["entries"]) == 456


def test_shards_have_exact_inventory_raw_digests_and_bounded_size(
    corpus: dict[str, Any],
) -> None:
    index = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert "entries" not in index
    assert len(index["shards"]) == 15
    expected_names = {shard["path"] for shard in index["shards"]}
    assert expected_names == {path.name for path in OUTPUT.parent.glob("wara-guidance-*.json")}
    flattened = []
    for number, shard in enumerate(index["shards"]):
        assert shard["path"] == f"wara-guidance-{number:02d}.json"
        body = (OUTPUT.parent / shard["path"]).read_bytes()
        assert len(body) <= 512 * 1024
        assert shard["digest"] == "sha256:" + hashlib.sha256(body).hexdigest()
        entries = json.loads(body)["entries"]
        assert len(entries) == shard["count"]
        assert len(entries) == (32 if number < 14 else 8)
        flattened.extend(entries)
    assert flattened == corpus["entries"]
    assert [entry["recommendation_id"] for entry in flattened] == sorted(
        entry["recommendation_id"] for entry in flattened
    )


def test_check_mode_rejects_orphan_shards(monkeypatch: pytest.MonkeyPatch) -> None:
    original_glob = Path.glob

    def glob(path: Path, pattern: str) -> object:
        found = list(original_glob(path, pattern))
        if path == OUTPUT.parent and pattern == "wara-guidance-*.json":
            found.append(path / "wara-guidance-99.json")
        return iter(found)

    monkeypatch.setattr(Path, "glob", glob)
    assert GENERATOR.main(["--check"]) == 1


def test_build_does_not_depend_on_working_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = GENERATOR.build(ROOT)
    monkeypatch.chdir(ROOT / ".github")
    assert GENERATOR.build(ROOT) == expected


def test_check_mode_does_not_write(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_write(*_args: object, **_kwargs: object) -> None:
        pytest.fail("--check must not write generated files")

    monkeypatch.setattr(Path, "write_bytes", reject_write)
    assert GENERATOR.main(["--check"]) == 0


def test_check_mode_detects_stale_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    real_read = Path.read_bytes

    def read(path: Path) -> bytes:
        return b"stale" if path == OUTPUT else real_read(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    assert GENERATOR.main(["--check"]) == 1


def test_framework_byte_pin_drift_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GENERATOR, "file_digest", lambda _path: "sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="framework bytes changed"):
        GENERATOR.build(ROOT)


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ("abc|zone|focus|observation\nabc|zone|focus|observation", "duplicate GUID prefix"),
        ("abc|unknown|focus|observation", "unknown mechanism"),
        ("abc|zone|missing", "four nonempty"),
        ("abc|zone||observation", "four nonempty"),
    ],
)
def test_binding_authoring_errors_fail_closed(
    monkeypatch: pytest.MonkeyPatch, body: str, error: str
) -> None:
    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: body)
    with pytest.raises(ValueError, match=error):
        GENERATOR.load_bindings(Path("unused.tsv"))


def test_no_implicit_or_keyword_fallback_for_unbound_guid(monkeypatch: pytest.MonkeyPatch) -> None:
    real_load = GENERATOR.load_bindings

    def missing(path: Path) -> dict[str, dict[str, str]]:
        bindings = real_load(path)
        bindings.pop("a2341513")
        return bindings

    monkeypatch.setattr(GENERATOR, "load_bindings", missing)
    with pytest.raises(ValueError, match="cover every source GUID"):
        GENERATOR.build(ROOT)


def test_each_guid_has_explicit_focus_and_evidence_binding(corpus: dict[str, Any]) -> None:
    bindings = GENERATOR.load_bindings(ROOT / "rule-catalog/guidance/azure-wara/controls.tsv")
    assert len(bindings) == 456
    for entry in corpus["entries"]:
        if entry["recommendation_id"] in {
            DNS,
            MAINTENANCE,
            AI,
            "1981f704-97b9-b645-9c57-33f8ded9261a",
        } or (entry["recommendation_id"][:8] in GENERATOR.RESOLUTIONS):
            continue
        binding = bindings[entry["recommendation_id"][:8]]
        assert binding["focus"] in _prose(entry["diagram"]["nodes"])
        assert binding["observation"] in _prose(entry["verification_steps"])
        assert binding["observation"] in _prose(entry["diagram"]["nodes"])
        assert entry["diagram"]["kind"] == GENERATOR.PROFILES[binding["family"]]["shape"]


def test_source_description_and_benefits_are_preserved_with_korean_reader_text(
    corpus: dict[str, Any], source_controls: dict[str, dict[str, Any]]
) -> None:
    for entry in corpus["entries"]:
        if entry["recommendation_id"] in {DNS, MAINTENANCE, AI} or (
            entry["recommendation_id"][:8] in GENERATOR.RESOLUTIONS
        ):
            continue
        source = source_controls[entry["recommendation_id"]]
        assert entry["summary"]["en"] == GENERATOR._normalize(source["description"])
        assert entry["summary"]["ko"]
        if source["wara"]["potential_benefits"]:
            assert entry["benefits"]["en"] == GENERATOR._normalize(
                source["wara"]["potential_benefits"]
            )
        assert entry["benefits"]["ko"]
        assert entry["title"]["ko"]
        assert "ko" in entry["rationale"]


def test_sources_pin_original_aprl_and_keep_original_learn_links(
    corpus: dict[str, Any], source_controls: dict[str, dict[str, Any]]
) -> None:
    for entry in corpus["entries"]:
        source = source_controls[entry["recommendation_id"]]["wara"]
        aprl = next(reference for reference in entry["sources"] if reference["kind"] == "aprl")
        assert f"/blob/{entry['source_revision']}/{source['source_path']}" in aprl["url"]
        original = source["learn_more_url"]
        if urlsplit(original).hostname == "learn.microsoft.com":
            assert urlsplit(original)._replace(query="").geturl() in {
                reference["url"] for reference in entry["sources"]
            }
        for reference in entry["sources"]:
            parsed = urlsplit(reference["url"])
            assert parsed.scheme == "https"
            assert not parsed.query
            if reference["kind"] == "vendor":
                assert entry["recommendation_id"].startswith("c041d596")
                assert reference["url"] == (
                    "https://docs.citrix.com/us/en/citrix-daas-azure/limits.html"
                )
            else:
                assert parsed.hostname in {"learn.microsoft.com", "github.com"}


def test_dns_links_do_not_imply_autoregistration_or_healthy_backend(corpus: dict[str, Any]) -> None:
    entry = _entry(corpus, DNS)
    prose = _prose(entry).lower()
    assert "nonregional" in prose
    assert "vnet regional links are not vm autoregistration" in prose
    assert "does not imply a healthy backend" in prose
    graph = entry["diagram"]
    edges = {(edge["from"], edge["to"]) for edge in graph["edges"]}
    assert {("primary", "zone"), ("secondary", "zone"), ("health", "target")} <= edges
    assert (
        next(edge for edge in graph["edges"] if edge["from"] == "registration")["style"] == "dashed"
    )


def test_maintenance_keeps_scope_prerequisites_medium_and_blocked(corpus: dict[str, Any]) -> None:
    entry = _entry(corpus, MAINTENANCE)
    prose = _prose(entry)
    assert "Medium, not High" in prose
    assert "requires automatic OS upgrades to be enabled" in prose
    assert "Dedicated Host or Isolated VM/VMSS eligibility" in prose
    assert "query joins, assignment completeness and eligibility semantics" in prose
    assert "Keep the existing blocked automated query result blocked" in prose
    assert len(entry["configuration"]["before"]) == len(entry["configuration"]["after"]) == 3
    assert [row["en"].split(":")[0] for row in entry["configuration"]["after"]] == [
        "Host",
        "OS image",
        "Guest",
    ]
    nodes = {node["id"] for node in entry["diagram"]["nodes"]}
    assert {"host", "image", "guest", "evidence", "blocked"} <= nodes
    assert all("openai" not in reference["url"] for reference in entry["sources"])


def test_ai_has_real_gateway_routes_and_eligibility_observations(corpus: dict[str, Any]) -> None:
    entry = _entry(corpus, AI)
    prose = _prose(entry)
    assert "Global, Data Zone and Regional" in prose
    for distinction in ("model version", "quota", "residency", "identity", "network"):
        assert distinction in prose
    assert "Do not guarantee automatic failover" in prose
    edges = {(edge["from"], edge["to"]) for edge in entry["diagram"]["edges"]}
    assert {
        ("clients", "gateway"),
        ("gateway", "primary"),
        ("gateway", "secondary"),
        ("eligibility", "gateway"),
        ("routes", "gateway"),
    } <= edges
    sources = {source["url"] for source in entry["sources"]}
    assert any(url.endswith("/deployment-types") for url in sources)
    assert any(url.endswith("/generative-ai-gateway-multiple-models") for url in sources)
    assert not any("virtual-machines/maintenance" in url for url in sources)


@pytest.mark.parametrize(
    ("prefix", "kind", "semantic"),
    [
        ("1981f704", "backup-restore", "isolated restore target"),
        ("a08a06a0", "connection-drain", "voluntary"),
        ("e544520b", "backup-restore", "Continuous backup"),
        ("fa0cf4f5", "zone-redundancy", "cross-region disaster recovery"),
        ("e30317d2", "replication", "asynchronous"),
        ("b89c9acc", "private-network", "correct DNS"),
        ("0c193899", "model-overflow", "explicit alternate"),
        ("ac3add17", "model-geography", "Global, Data Zone and Regional"),
        ("e93fe702", "data-lineage", "intentional backups"),
        ("094400a5", "replication", "synchronous"),
        ("3538aa48", "dns-cache", "client behavior"),
        ("60077378", "network-redundancy", "administrative and operational"),
    ],
)
def test_representative_families_preserve_important_distinctions(
    corpus: dict[str, Any], prefix: str, kind: str, semantic: str
) -> None:
    entry = _entry(corpus, prefix)
    assert entry["diagram"]["kind"] == kind
    assert semantic.lower() in _prose(entry).lower()


def test_ambiguous_source_polarity_and_location_are_not_unchecked_actions(
    corpus: dict[str, Any],
) -> None:
    fallback = _entry(corpus, "e7dbd21f")
    assert "Reconcile the historical title" in _prose(fallback["summary"])
    assert "not an instruction to disable fallback" in _prose(fallback["rationale"])
    location = _entry(corpus, "98bd7098")
    assert "do not relocate resources" in _prose(location["summary"])
    assert "contained resources may be in different regions" in _prose(location["rationale"])


def test_structural_report_does_not_claim_456_current_document_reviews() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["inventory"] == {"total": 456, "active": 393, "disabled": 63}
    assert report["authored_binding_count"] == 456
    assert len(report["mechanism_counts"]) == 45
    assert len(report["diagram_counts"]) >= 30
    assert set(report["individually_authored_pilots"]) == {DNS, MAINTENANCE, AI}
    assert "other 437" in report["review_scope"]["remaining_review"]
    assert report["review_accounting"]["live_azure_or_model_validations"] == 0
    assert report["review_accounting"]["shared_context_source_grounded_entries"] == 437
    assert report["review_accounting"]["expanded_conditional_document_reviewed_entries"] == 16
    assert report["localization"]["complete_korean_recommendations"] == 456
    assert report["localization"]["missing_korean_reader_fields"] == 0
    assert report["localization"]["per_guid_observation_bindings"] == "English and Korean"
    assert report["image_review"]["recommendation_count"] == 456
    assert report["image_review"]["document_group_count"] == 408
    assert "rule-catalog/guidance/azure-wara/controls-ko.tsv" in report["authoring_inputs"]
    assert "rule-catalog/guidance/azure-wara/reference-images.json" in report["authoring_inputs"]
    assert len(report["quality_limits"]) == 4
    critique = report["content_critique"]
    assert len(critique["source_ambiguities_and_historical_limits"]) == 16
    assert len(critique["remaining_thin_or_uncertain"]) == 0
    assert len(critique["resolved_conditional_guides"]) == 16
    assert "sixteen identified instructional gaps only" in critique["resolution_scope"]
    assert critique["true_content_blockers"] == []
    assert len(critique["manual_evidence_ids"]) == 250
    assert len(critique["blocked_automated_ids"]) == 85
    assert len(critique["subscription_classification_ids"]) == 88
    assert len(critique["corrected_mechanism_bindings"]) == 9
    assert critique["structural_review"] == {
        "explicit_guid_bindings": 456,
        "retained_source_description_and_benefit_entries": 437,
        "individually_rewritten_pilots": 3,
        "expanded_conditional_document_reviewed_entries": 16,
        "distinct_mechanism_graphs": 45,
        "generic_configuration_success_edges": 0,
    }
    assert len(report["non_allowlisted_original_references"]) == 27
    assert {gap["recommendation_id"][:8] for gap in report["semantic_review_gaps"]} == {
        "e7dbd21f",
        "98bd7098",
    }


def test_packaged_notice_preserves_aprl_mit_attribution_and_exact_license_reference() -> None:
    source = ROOT / "rule-catalog/guidance/azure-wara/NOTICE.txt"
    packaged = OUTPUT.parent / "WARA-NOTICE.txt"
    assert packaged.read_bytes() == source.read_bytes()
    notice = packaged.read_text(encoding="utf-8")
    assert "Copyright (c) Microsoft Corporation." in notice
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in notice
    assert "this permission notice shall be included in all" in notice
    assert "/blob/1f421a90c157bc8894b3a47b05ba08b8650a0bd5/LICENSE" in notice
    assert "not 456 independent technical or live-environment" in notice


def test_every_diagram_has_a_mechanism_not_a_generic_configuration_success_chain(
    corpus: dict[str, Any],
) -> None:
    banned = {
        "source-specific configuration",
        "intended behavior, not observed success",
        "requires compatible dependency",
    }
    for entry in corpus["entries"]:
        labels = {edge["label"]["en"] for edge in entry["diagram"]["edges"]}
        assert not labels & banned, entry["recommendation_id"]
        roles = {node["role"] for node in entry["diagram"]["nodes"]}
        assert {"configuration", "evidence"} <= roles


@pytest.mark.parametrize(
    ("prefix", "edges"),
    [
        ("823b0cff", {("workload", "signal"), ("signal", "setting"), ("setting", "workload")}),
        ("1ad74c3c", {("workload", "setting"), ("setting", "transport"), ("transport", "records")}),
        ("84e44da6", {("workload", "service"), ("service", "setting"), ("setting", "workload")}),
        ("0c193899", {("workload", "primary"), ("primary", "setting"), ("setting", "alternate")}),
        ("8aa9744b", {("workload", "setting"), ("setting", "job"), ("job", "results")}),
        ("1b0d0893", {("setting", "accepted"), ("setting", "quarantine"), ("accepted", "copies")}),
        ("19b6df57", {("notice", "setting"), ("workload", "candidate"), ("evidence", "candidate")}),
    ],
)
def test_specific_family_graphs_express_real_mechanism_relationships(
    corpus: dict[str, Any], prefix: str, edges: set[tuple[str, str]]
) -> None:
    graph = _entry(corpus, prefix)["diagram"]
    assert edges <= {(edge["from"], edge["to"]) for edge in graph["edges"]}


def test_backup_replication_and_snapshot_addenda_do_not_merge_protection_models(
    corpus: dict[str, Any],
) -> None:
    for prefix in ("41f0d88e", "ee4dc309"):
        assert _entry(corpus, prefix)["diagram"]["kind"] == "recovery-plan"
    assert "manual failover" in _prose(_entry(corpus, "e30317d2"))
    assert "asynchronous replication and manual failover" in _prose(_entry(corpus, "e3d742e1"))
    assert "not a backup of all externally stored Databricks data" in _prose(
        _entry(corpus, "932d45d6")
    )
    assert "not an independently retained backup" in _prose(_entry(corpus, "38721758"))
    assert "not a guarantee of application availability" in _prose(
        _entry(corpus, "bcfe71f1")["configuration"]["after"]
    )


def test_subscription_classification_is_not_fabricated_workload_target(
    corpus: dict[str, Any],
) -> None:
    entry = _entry(corpus, "0025ed2e")
    assert "actual FSLogix share backups target objects" in _prose(entry["implementation_steps"])
    assert "not a subscription setting assumed to implement" in _prose(entry["applicability"])
    assert "not an Azure-wide" in _prose(_entry(corpus, "c041d596"))
    assert "not permission to add a blanket Internet route" in _prose(
        _entry(corpus, "1c6c97d7")["summary"]
    )


def test_control_plane_locality_and_artifact_replicas_are_not_application_failover(
    corpus: dict[str, Any],
) -> None:
    locality = _entry(corpus, "8aa63c34")
    assert locality["diagram"]["kind"] == "isolation-boundary"
    assert "not deployment of a recovery workspace" in _prose(locality)
    for prefix in ("611c7c96", "b14ee8ed", "36ea6c09", "a3058909"):
        assert _entry(corpus, prefix)["diagram"]["kind"] == "replication"
    assert _entry(corpus, "b49a39fd")["diagram"]["kind"] == "capacity"
    assert _entry(corpus, "89928e61")["diagram"]["kind"] == "monitoring"
    assert "not automatically resubmit failed training jobs" in _prose(_entry(corpus, "611c7c96"))
    assert "not the OS or data state of already running VMs" in _prose(_entry(corpus, "b14ee8ed"))


def test_pacemaker_cleanup_does_not_remove_permanent_safety_constraints(
    corpus: dict[str, Any],
) -> None:
    prose = _prose(_entry(corpus, "1b8a3051"))
    assert "temporary prefer location constraint" in prose
    assert "preserving permanent placement, quorum and fencing rules" in prose
    assert "do not remove unrelated constraints" in prose


@pytest.mark.parametrize("prefix", sorted(GENERATOR.RESOLUTIONS))
def test_sixteen_conditional_guides_replace_primary_source_claims_completely(
    corpus: dict[str, Any],
    source_controls: dict[str, dict[str, Any]],
    prefix: str,
) -> None:
    entry = _entry(corpus, prefix)
    original = source_controls[entry["recommendation_id"]]
    assert entry["summary"]["en"] != GENERATOR._normalize(original["description"])
    assert entry["benefits"]["en"] != GENERATOR._normalize(original["wara"]["potential_benefits"])
    assert entry["diagram"]["id"] == f"qualified-{prefix}"
    assert len(entry["implementation_steps"]) >= 3
    assert len(entry["verification_steps"]) >= 3
    assert "Content review limit:" not in _prose(entry["cautions"])
    assert "ko" in entry["summary"] and "ko" in entry["rationale"]
    authored = GENERATOR.RESOLUTIONS[prefix]
    assert entry["rationale"]["en"] == authored["explanation"][0]
    assert [step["en"] for step in entry["implementation_steps"]] == authored["actions"]
    assert [step["en"] for step in entry["verification_steps"][:3]] == authored["checks"]
    assert all(limit in _prose(entry["cautions"]) for limit in authored["limits"])
    assert any(node["role"] == "evidence" for node in entry["diagram"]["nodes"])
    assert any(reference["kind"] == "aprl" for reference in entry["sources"])


@pytest.mark.parametrize("prefix", sorted(GENERATOR.RESOLUTIONS))
def test_qualified_diagram_nodes_have_distinct_entity_text_with_figure_budgets(
    corpus: dict[str, Any],
    prefix: str,
) -> None:
    entry = _entry(corpus, prefix)
    graph = entry["diagram"]
    details = [node["detail"]["en"] for node in graph["nodes"]]
    assert len(set(details)) == len(details)
    assert len(graph["description"]["en"]) <= 180
    assert 8 <= len(graph["title"]["en"]) <= 80
    assert 4 <= len(graph["title"]["ko"]) <= 80
    assert graph["title"]["en"] != graph["title"]["ko"]
    assert "qualified mechanism" not in graph["title"]["en"].lower()
    assert "적격 메커니즘" not in graph["title"]["ko"]
    assert entry["rationale"]["en"] not in graph["description"]["en"]
    for node in graph["nodes"]:
        detail = node["detail"]["en"]
        assert len(node["label"]["en"]) <= 72
        assert len(detail) <= 200
        assert 6 <= len(detail.split()) <= 32
        assert detail.count(".") <= 2
        assert detail.casefold() != node["label"]["en"].casefold()
        assert detail != entry["rationale"]["en"]
        assert detail != entry["summary"]["en"]
        assert "Questions to verify:" not in detail


def test_apim_node_details_explain_each_entity_instead_of_repeating_the_case(
    corpus: dict[str, Any],
) -> None:
    entry = _entry(corpus, "740f2c1c")
    details = {node["id"]: node["detail"]["en"] for node in entry["diagram"]["nodes"]}
    assert "API requests" in details["clients"]
    assert "classic or v2 tier" in details["mode"]
    assert "remaining capacity" in details["gateway"]
    assert "management plane and developer portal" in details["primary"]
    assert "not extra management or portal deployments" in details["secondary"]
    assert "observed request continuity" in details["evidence"]
    assert all("Current APIM guidance distinguishes" not in detail for detail in details.values())
    assert "Current APIM guidance distinguishes" in entry["rationale"]["en"]


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "full-rationale"])
def test_qualified_node_authoring_errors_fail_without_a_summary_fallback(
    corpus: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
) -> None:
    module = sys.modules["wara_guidance_node_details"]
    details = dict(module.NODE_DETAILS["740f2c1c"])
    if invalid == "missing":
        details.pop("clients")
        message = "must match its entities"
    elif invalid == "duplicate":
        details["clients"] = details["mode"]
        message = "must be distinct"
    else:
        details["clients"] = _entry(corpus, "740f2c1c")["rationale"]["en"]
        message = "exceeds its figure budget"
    monkeypatch.setitem(module.NODE_DETAILS, "740f2c1c", details)
    with pytest.raises(ValueError, match=message):
        GENERATOR.build(ROOT)


@pytest.mark.parametrize(
    ("prefix", "required"),
    [
        ("63491f70", ["automatic for all registry tiers", "legacy zoneRedundancy", "Tasks"]),
        ("84636c6c", ["Dedicated requires at least three", "Standard and Premium", "checkpoint"]),
        (
            "b376281d",
            ["does not guarantee exact placement", "read-only", "read-write", "Partitions"],
        ),
        ("740f2c1c", ["classic", "v2", "secondary regions", "management"]),
        ("98bd7098", ["transparent rerouting", "not a universal", "data-plane recovery"]),
        ("e7dbd21f", ["messages that match no", "not an instruction to disable", "unmatched"]),
        ("38721758", ["Disabled", "not an active", "not a synonym for independent backup"]),
        ("a18d60f8", ["VACUUM", "data files", "RESTORE", "downstream"]),
        (
            "c15b2b73",
            [
                "ProfileType",
                "VHDLocations",
                "FlipFlopProfileDirectoryName",
                "DeleteLocalProfileWhenVHDShouldApply",
            ],
        ),
        ("4884cada", ["60s", "40s", "not universal", "fencing"]),
        ("6648fe61", ["certified", "replication", "Never disable STONITH", "split brain"]),
        ("9d8f6678", ["ENSA", "simple mount", "classic", "shared"]),
        ("ee4dc309", ["not mounted NFS data", "storage-specific", "Monitoring"]),
        ("9ec5b4c8", ["reserved host quota", "not an in-place switch", "PFTT"]),
        ("1c6c97d7", ["WindowsVirtualDesktop", "FQDN", "blanket", "inbound"]),
        ("c041d596", ["4000", "historical", "5000", "Citrix DaaS Standard", "not an Azure-wide"]),
    ],
)
def test_each_resolved_guide_retains_its_specific_scope_and_mechanism_qualifications(
    corpus: dict[str, Any],
    prefix: str,
    required: list[str],
) -> None:
    prose = _prose(_entry(corpus, prefix)).lower()
    assert all(fragment.lower() in prose for fragment in required)


def test_citrix_vendor_reference_is_explicit_not_silently_removed(corpus: dict[str, Any]) -> None:
    url = "https://docs.citrix.com/us/en/citrix-daas-azure/limits.html"
    entry = _entry(corpus, "c041d596")
    assert [
        reference["url"] for reference in entry["sources"] if reference["kind"] == "vendor"
    ] == [url]
    report = json.loads(REPORT.read_text(encoding="utf-8"))["content_critique"]
    assert report["external_citation_presentation_limits"] == []
    assert report["vendor_source_cards"][0]["url"] == url
    assert "5000" in report["vendor_source_cards"][0]["reviewed_scope"]


def test_content_is_nfc_and_has_no_mislabeled_english_korean(corpus: dict[str, Any]) -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    expected_ids = {control["id"] for area in source["areas"] for control in area["controls"]}
    GENERATOR.assert_korean_reader_text(corpus["entries"], expected_ids)

    def visit(value: object) -> None:
        if isinstance(value, str):
            assert unicodedata.is_normalized("NFC", value)
            assert not set(value) & set("\u2013\u2014\u2018\u2019\u201c\u201d\u00a0")
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(corpus)
