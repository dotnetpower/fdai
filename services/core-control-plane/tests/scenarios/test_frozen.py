"""Frozen scenario-set integrity + balance + validity tests.

W2.4 exit criterion: no customer values, ASCII machine identifiers and paths,
English or Korean natural-language values, complete expectations, and domain balance.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from ipaddress import ip_address
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import pytest
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator
from jsonschema import Draft202012Validator

SCENARIO_DIR = Path(__file__).resolve().parent / "v2026.07"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"
MANIFEST_SCHEMA_PATH = Path(__file__).resolve().parent / "manifest.schema.json"
MANIFEST_PATH = Path(__file__).resolve().parent / "manifests" / "v2026.07.json"
CONFLICT_DIR = Path(__file__).resolve().parent / "cross-objective"
CONFLICT_SCHEMA_PATH = CONFLICT_DIR / "schema.json"
ENRICHMENT_DIR = Path(__file__).resolve().parent / "enrichment" / "v2026.07"

# ── Guard patterns ──────────────────────────────────────────────────────────
# Any GUID whose first four groups are non-zero is a real customer identifier
# and MUST NOT appear in a committed scenario file. The synthetic pattern
# `00000000-0000-0000-0000-XXXXXXXXXXXX` (used to keep scenario event_ids
# unique) is exempt.
_NONZERO_GUID = re.compile(
    r"\b(?!00000000-0000-0000-0000-[0-9a-fA-F]{12}\b)"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_AZURE_RESOURCE_ID = re.compile(r"(?i)/subscriptions/([^/\s]+)/")
_EMAIL = re.compile(r"(?i)(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@([^@\s,;<>()[\]]+)")
_URI = re.compile(r"(?i)[a-z][a-z0-9+.-]*://[^\s<>()]+")
_IP_ADDRESS = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
_IPV6_CANDIDATE = re.compile(r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{0,4}:){2,}[0-9a-f:]{0,4}")
_SENSITIVE_KEYS = frozenset(
    {
        "accesskey",
        "accesstoken",
        "apikey",
        "clientsecret",
        "connectionstring",
        "credential",
        "password",
        "privatekey",
        "refreshtoken",
        "sas",
        "sastoken",
        "secret",
        "token",
    }
)
_SYNTHETIC_GUID = "00000000-0000-0000-0000-000000000000"
_ALLOWED_HOSTS = frozenset({"example.com", "localhost"})
_MACHINE_FIELD = re.compile(r"(?:^|_)(?:id|ids|ref|refs|path|paths|type|version|key)$")
_MACHINE_FIELDS = frozenset(
    {
        "capability",
        "citing_rule_ids",
        "decision",
        "domain",
        "source",
        "tags",
        "tier",
    }
)


def _load_scenario_schema() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _nonzero_test_guid(digit: str) -> str:
    return f"{digit * 8}-{digit * 4}-{digit * 4}-{digit * 4}-{digit * 12}"


def _load_scenarios() -> list[tuple[Path, dict[str, Any]]]:
    files = sorted(path for path in SCENARIO_DIR.glob("*.json") if path.name != "manifest.json")
    return [
        (p, cast(dict[str, Any], _load_json_without_duplicates(p.read_text(encoding="utf-8"))))
        for p in files
    ]


def _load_manifest() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def _conflict_id_to_filename(conflict_id: str) -> str:
    """Return the frozen filename convention `<set-version>-<capability>.json`."""

    capability, _, remainder = conflict_id.partition(".")
    _dimension, _, set_version = remainder.rpartition(".")
    return f"{set_version.replace('-', '.')}-{capability}.json"


def _load_conflict_specs() -> list[tuple[Path, dict[str, Any]]]:
    """Load every frozen cross-objective artifact, excluding its own schema."""

    files = sorted(path for path in CONFLICT_DIR.glob("*.json") if path.name != "schema.json")
    return [
        (p, cast(dict[str, Any], _load_json_without_duplicates(p.read_text(encoding="utf-8"))))
        for p in files
    ]


def _manifest_conflict_spec_ids() -> list[str]:
    return [
        str(conflict_id)
        for pack in _load_manifest()["capability_packs"].values()
        for conflict_id in pack["conflict_spec_ids"]
    ]


_FAIL_CLOSED_EVIDENCE_CLASSES = ("missing", "stale", "incomplete", "conflicting")
_DISPATCH_RECEIPT_KEYS = (
    "pr_ref",
    "pr_url",
    "receipt_ref",
    "execution_outcome",
    "effect_verified",
)


def _load_effect_evidence() -> list[tuple[Path, dict[str, Any]]]:
    """Load every frozen independent effect-evidence block from the overlays."""

    found: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(ENRICHMENT_DIR.glob("*.json")):
        overlay = cast(
            dict[str, Any], _load_json_without_duplicates(path.read_text(encoding="utf-8"))
        )
        evidence = overlay.get("effect_evidence")
        if isinstance(evidence, dict):
            found.append((path, cast(dict[str, Any], evidence)))
    return found


def _load_json_without_duplicates(text: str) -> object:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("scenario JSON contains a duplicate key")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=unique_object)


def _test_ref_exists(test_ref: str) -> bool:
    relative_path, separator, test_name = test_ref.partition("::")
    if not separator:
        return False
    path = Path(__file__).resolve().parents[4] / relative_path
    if not path.is_file():
        return False
    pattern = re.compile(rf"^(?:async )?def {re.escape(test_name)}\(", re.MULTILINE)
    return pattern.search(path.read_text(encoding="utf-8")) is not None


def _non_ascii_machine_fields(
    value: object,
    *,
    path: tuple[str, ...] = (),
    machine_context: bool = False,
) -> tuple[str, ...]:
    invalid: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_path = (*path, str(key))
            if not str(key).isascii():
                invalid.append(".".join(key_path))
            machine_field = machine_context or bool(
                str(key) in _MACHINE_FIELDS or _MACHINE_FIELD.search(str(key))
            )
            invalid.extend(
                _non_ascii_machine_fields(
                    item,
                    path=key_path,
                    machine_context=machine_field,
                )
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            invalid.extend(
                _non_ascii_machine_fields(
                    item,
                    path=(*path, str(index)),
                    machine_context=machine_context,
                )
            )
    elif machine_context and isinstance(value, str) and not value.isascii():
        invalid.append(".".join(path))
    return tuple(dict.fromkeys(invalid))


def _customer_data_findings(
    value: object,
    *,
    path: tuple[str, ...] = (),
) -> tuple[str, ...]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_path = (*path, str(key))
            findings.extend(_string_customer_findings(str(key), ".".join(key_path), field=None))
            if _is_sensitive_key(str(key)) and item not in (None, False, "", "<redacted>"):
                findings.append(f"{'.'.join(key_path)}:sensitive_value")
            findings.extend(_customer_data_findings(item, path=key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_customer_data_findings(item, path=(*path, str(index))))
    elif isinstance(value, str):
        location = ".".join(path)
        findings.extend(
            _string_customer_findings(
                value,
                location,
                field=path[-1] if path else None,
            )
        )
    return tuple(dict.fromkeys(findings))


def _string_customer_findings(
    value: str,
    location: str,
    *,
    field: str | None,
) -> tuple[str, ...]:
    findings: list[str] = []
    normalized_field = re.sub(r"[^a-z0-9]", "", (field or "").casefold())
    for subscription in _AZURE_RESOURCE_ID.findall(value):
        if subscription.casefold() != _SYNTHETIC_GUID:
            findings.append(f"{location}:azure_subscription")
    findings.extend(_azure_resource_name_findings(value, location))
    for domain in _EMAIL.findall(value):
        if domain.casefold().rstrip(".!?") != "example.com":
            findings.append(f"{location}:email")

    parsed_uris = tuple(urlsplit(match.rstrip(".,;!?")) for match in _URI.findall(value))
    network_field = normalized_field.endswith(("endpoint", "host", "hostname", "url", "uri"))
    candidates = parsed_uris or ((urlsplit(f"//{value}"),) if network_field else ())
    for candidate in candidates:
        host = candidate.hostname
        if host is None or not _allowed_host(host):
            findings.append(f"{location}:url")

    ip_candidates = {
        *(_IP_ADDRESS.findall(value)),
        *(_IPV6_CANDIDATE.findall(value)),
        *(candidate.hostname for candidate in candidates if candidate.hostname is not None),
    }
    for candidate in ip_candidates:
        try:
            address = ip_address(candidate.strip("[]"))
        except ValueError:
            continue
        if not address.is_loopback:
            findings.append(f"{location}:ip_address")

    if normalized_field in {"tenantid", "subscriptionid"} and value != _SYNTHETIC_GUID:
        findings.append(f"{location}:cloud_account_id")
    if normalized_field in {"resourcegroup", "resourcegroupname", "resourcename"} and (
        not _synthetic_resource_name(value)
    ):
        findings.append(f"{location}:azure_resource_name")
    return tuple(dict.fromkeys(findings))


def _allowed_host(host: str) -> bool:
    normalized = host.casefold().rstrip(".")
    if normalized in _ALLOWED_HOSTS or normalized.endswith(".example.local"):
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _is_sensitive_key(key: str) -> bool:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    parts = tuple(part for part in re.split(r"[^a-z0-9]+", separated.casefold()) if part)
    normalized = "".join(parts)
    if normalized in _SENSITIVE_KEYS:
        return True
    if "password" in parts or "credential" in parts:
        return True
    if "secret" in parts and not {"store", "name", "ref", "id", "type", "count"} & set(parts):
        return True
    pairs = set(zip(parts, parts[1:], strict=False))
    return bool(
        pairs
        & {
            ("access", "key"),
            ("access", "token"),
            ("api", "key"),
            ("client", "secret"),
            ("connection", "string"),
            ("private", "key"),
            ("refresh", "token"),
            ("sas", "token"),
        }
    )


def _azure_resource_name_findings(value: str, location: str) -> tuple[str, ...]:
    if "/subscriptions/" not in value.casefold():
        return ()
    segments = tuple(segment for segment in value.split("/") if segment)
    lowered = tuple(segment.casefold() for segment in segments)
    findings: list[str] = []
    if "resourcegroups" in lowered:
        index = lowered.index("resourcegroups")
        if index + 1 >= len(segments) or not _synthetic_resource_name(segments[index + 1]):
            findings.append(f"{location}:azure_resource_name")
    for index, segment in enumerate(lowered):
        if segment != "providers" or index + 3 >= len(segments):
            continue
        for name_index in range(index + 3, len(segments), 2):
            if not _synthetic_resource_name(segments[name_index]):
                findings.append(f"{location}:azure_resource_name")
                break
    return tuple(dict.fromkeys(findings))


def _synthetic_resource_name(value: str) -> bool:
    normalized = value.casefold()
    return (
        "example" in normalized
        or "acme" in normalized
        or (normalized.startswith("<") and normalized.endswith(">"))
    )


# ---------------------------------------------------------------------------
# Schema validity
# ---------------------------------------------------------------------------


def test_scenario_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(_load_scenario_schema())


def test_capability_manifest_is_schema_valid() -> None:
    schema = cast(dict[str, Any], json.loads(MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8")))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_load_manifest())


def test_capability_manifest_assigns_every_scenario_exactly_once() -> None:
    scenarios = {raw["id"]: raw for _, raw in _load_scenarios()}
    manifest = _load_manifest()
    assigned: list[str] = []
    for capability, pack in manifest["capability_packs"].items():
        for scenario_id in pack["scenario_ids"]:
            assert scenarios[scenario_id]["capability"] == capability
            assigned.append(scenario_id)
    assert sorted(assigned) == sorted(scenarios)
    assert len(assigned) == len(set(assigned))


def test_capability_coverage_references_owned_scenarios_and_tests() -> None:
    manifest = _load_manifest()
    for pack in manifest["capability_packs"].values():
        scenario_ids = set(pack["scenario_ids"])
        for evidence_records in pack["coverage"].values():
            for evidence in evidence_records:
                assert evidence["scenario_id"] in scenario_ids
                assert _test_ref_exists(evidence["test_ref"])


def test_complete_pack_requires_every_coverage_dimension() -> None:
    manifest = _load_manifest()
    for pack in manifest["capability_packs"].values():
        expected_pack_status = (
            "missing"
            if not pack["scenario_ids"]
            else "complete"
            if all(pack["coverage"].values())
            else "partial"
        )
        assert pack["status"] == expected_pack_status
        if pack["status"] == "complete":
            assert all(pack["coverage"].values())
    expected_status = (
        "complete"
        if all(pack["status"] == "complete" for pack in manifest["capability_packs"].values())
        else "incomplete"
    )
    assert manifest["status"] == expected_status


# ---------------------------------------------------------------------------
# Cross-objective conflict artifacts
# ---------------------------------------------------------------------------
#
# A frozen cross-objective artifact composes several frozen scenarios into one
# conflict, so it cannot live inside the per-scenario hierarchy that the
# scenario schema and the one-pack-per-scenario assignment govern. It is still
# frozen: it carries its own id, so the manifest inventories that id directly,
# and every immutability guard applied to a scenario is applied to it here.


def test_capability_manifest_inventories_every_conflict_spec_exactly_once() -> None:
    """Every frozen conflict artifact MUST be registered by its own id."""

    specs = {raw["id"]: (path, raw) for path, raw in _load_conflict_specs()}
    manifest = _load_manifest()
    registered: list[str] = []
    for capability, pack in manifest["capability_packs"].items():
        for conflict_id in pack["conflict_spec_ids"]:
            assert conflict_id in specs, f"{conflict_id} is registered but has no frozen artifact"
            path, raw = specs[conflict_id]
            assert raw["capability"] == capability
            assert raw["scenario_set_version"] == manifest["scenario_set_version"]
            assert path.name == _conflict_id_to_filename(conflict_id), (
                f"{path.name} does not follow the frozen conflict filename convention"
            )
            registered.append(conflict_id)
    assert sorted(registered) == sorted(specs), (
        "every frozen conflict artifact MUST be inventoried by exactly one capability pack"
    )
    assert len(registered) == len(set(registered))


@pytest.mark.parametrize(("path", "raw"), _load_conflict_specs())
def test_conflict_spec_passes_its_schema(path: Path, raw: dict[str, Any]) -> None:
    schema = cast(dict[str, Any], json.loads(CONFLICT_SCHEMA_PATH.read_text(encoding="utf-8")))
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(raw), key=lambda e: list(e.path))
    assert not errors, f"{path.name}: {[e.message for e in errors[:5]]}"


@pytest.mark.parametrize(("path", "raw"), _load_conflict_specs())
def test_conflict_spec_composes_only_scenarios_its_pack_owns(
    path: Path, raw: dict[str, Any]
) -> None:
    pack = _load_manifest()["capability_packs"][raw["capability"]]
    owned = set(pack["scenario_ids"])
    composed = {str(option["scenario_id"]) for option in raw["options"]}
    assert composed <= owned, f"{path.name} composes scenarios its pack does not own: {composed}"
    assert raw["id"] in pack["conflict_spec_ids"], (
        f"{path.name} is not inventoried by the pack it claims"
    )


@pytest.mark.parametrize(("path", "raw"), _load_conflict_specs())
def test_conflict_spec_carries_no_non_zero_guid(path: Path, raw: dict[str, Any]) -> None:
    matches = _NONZERO_GUID.findall(json.dumps(raw))
    assert not matches, f"{path.name} contains customer-identifying GUIDs: {matches[:3]}"


@pytest.mark.parametrize(("path", "raw"), _load_conflict_specs())
def test_conflict_spec_carries_no_customer_data(path: Path, raw: dict[str, Any]) -> None:
    findings = _customer_data_findings(raw)
    assert not findings, f"{path.name} contains customer data: {findings}"


@pytest.mark.parametrize(("path", "raw"), _load_conflict_specs())
def test_conflict_spec_machine_fields_are_ascii(path: Path, raw: dict[str, Any]) -> None:
    invalid = _non_ascii_machine_fields(raw)
    assert not invalid, f"{path.name} contains non-ASCII machine fields: {invalid}"


# ---------------------------------------------------------------------------
# Frozen independent effect evidence
# ---------------------------------------------------------------------------
#
# The `successful_full_loop` dimension may close only from an independent
# authoritative observation. Its frozen inputs therefore get the same
# customer-agnosticness guards as the scenarios, plus a completeness guard that
# keeps every fail-closed evidence class covered and keeps dispatch receipts
# out of the artifact.


@pytest.mark.parametrize(("path", "raw"), _load_effect_evidence())
def test_effect_evidence_carries_no_customer_data(path: Path, raw: dict[str, Any]) -> None:
    findings = _customer_data_findings(raw)
    assert not findings, f"{path.name} effect evidence contains customer data: {findings}"
    guids = _NONZERO_GUID.findall(json.dumps(raw))
    assert not guids, f"{path.name} effect evidence contains customer GUIDs: {guids[:3]}"
    invalid = _non_ascii_machine_fields(raw)
    assert not invalid, f"{path.name} effect evidence has non-ASCII machine fields: {invalid}"


@pytest.mark.parametrize(("path", "raw"), _load_effect_evidence())
def test_effect_evidence_covers_every_fail_closed_class(path: Path, raw: dict[str, Any]) -> None:
    """Positive closure needs an in-window observation; every deficiency is pinned."""

    window_start = datetime.fromisoformat(str(raw["predicted_at"]))
    deadline = datetime.fromisoformat(str(raw["observation_deadline"]))
    observation = raw["authoritative_observation"]
    observed_at = datetime.fromisoformat(str(observation["observed_at"]))
    assert window_start <= observed_at <= deadline, (
        f"{path.name} authoritative observation falls outside its effect window"
    )
    assert raw["acceptable_min"] <= observation["value"] <= raw["acceptable_max"], (
        f"{path.name} authoritative observation cannot satisfy its own prediction"
    )

    kinds = [case["kind"] for case in raw["negative_cases"]]
    assert sorted(kinds) == sorted(_FAIL_CLOSED_EVIDENCE_CLASSES), (
        f"{path.name} must pin exactly the fail-closed evidence classes"
    )
    for case in raw["negative_cases"]:
        assert case["expected_verification_status"] in {"hold", "mismatch"}
        assert case["expected_verification_reason"]
        assert case["expected_response_label"] in {"unscorable", "mismatch"}

    body = json.dumps(raw)
    for forbidden in _DISPATCH_RECEIPT_KEYS:
        assert forbidden not in body, (
            f"{path.name} effect evidence must not carry {forbidden!r}; "
            "closure may not restate dispatch"
        )


@pytest.mark.parametrize(("path", "raw"), _load_scenarios())
def test_scenario_passes_its_schema(path: Path, raw: dict[str, Any]) -> None:
    validator = Draft202012Validator(_load_scenario_schema())
    errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.path))
    assert not errors, f"{path.name}: {[e.message for e in errors[:5]]}"


@pytest.mark.parametrize(("path", "raw"), _load_scenarios())
def test_scenario_event_passes_event_schema(path: Path, raw: dict[str, Any]) -> None:
    """Every scenario event MUST validate against Event schema."""
    registry = PackageResourceSchemaRegistry()
    contract_v = JsonSchemaContractValidator(registry)
    contract_v.validate("event", raw["event"])


# ---------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------


def test_scenarios_balanced_within_10_percent_of_mean() -> None:
    per_domain: dict[str, int] = {}
    for _, raw in _load_scenarios():
        per_domain[raw["domain"]] = per_domain.get(raw["domain"], 0) + 1

    assert set(per_domain) == {"change", "dr", "finops"}, f"Missing a domain: {set(per_domain)}"
    mean = sum(per_domain.values()) / len(per_domain)
    for domain, count in per_domain.items():
        deviation = abs(count - mean) / mean
        assert deviation <= 0.10, (
            f"Domain {domain} deviates {deviation:.0%} from the mean count {mean:.1f}"
        )


# ---------------------------------------------------------------------------
# Customer-agnosticness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("path", "raw"), _load_scenarios())
def test_scenario_carries_no_non_zero_guid(path: Path, raw: dict[str, Any]) -> None:
    """Every UUID literal in a committed scenario MUST be the all-zero placeholder."""
    body = json.dumps(raw)
    matches = _NONZERO_GUID.findall(body)
    assert not matches, f"{path.name} contains customer-identifying GUIDs: {matches[:3]}"


@pytest.mark.parametrize(("path", "raw"), _load_scenarios())
def test_scenario_carries_no_customer_data(path: Path, raw: dict[str, Any]) -> None:
    findings = _customer_data_findings(raw)
    assert not findings, f"{path.name} contains customer data: {findings}"


@pytest.mark.parametrize(("path", "raw"), _load_scenarios())
def test_scenario_machine_fields_are_ascii(path: Path, raw: dict[str, Any]) -> None:
    invalid = _non_ascii_machine_fields(raw)
    assert not invalid, f"{path.name} contains non-ASCII machine fields: {invalid}"


def test_scenario_schema_allows_korean_values_but_not_identifiers() -> None:
    schema = _load_scenario_schema()
    scenario = dict(_load_scenarios()[0][1])
    event = dict(scenario["event"])
    event["payload"] = {"summary": "복구 상태를 확인합니다"}
    scenario["event"] = event

    assert not list(Draft202012Validator(schema).iter_errors(scenario))
    JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate("event", event)
    assert _non_ascii_machine_fields(scenario) == ()

    scenario["id"] = "복구.시나리오"
    errors = list(Draft202012Validator(schema).iter_errors(scenario))
    assert any(tuple(error.path) == ("id",) for error in errors)

    for machine_path, mutation in (
        ("event.source", ("event", "source", "관찰기")),
        ("event.payload.resource_ref", ("payload", "resource_ref", "리소스:예제")),
        ("expected.citing_rule_ids.0", ("expected", "citing_rule_ids", ["규칙.예제"])),
    ):
        candidate = json.loads(json.dumps(scenario))
        candidate["id"] = _load_scenarios()[0][1]["id"]
        section, key, mutated_value = mutation
        if section == "payload":
            candidate["event"]["payload"][key] = mutated_value
        else:
            candidate[section][key] = mutated_value
        assert machine_path in _non_ascii_machine_fields(candidate)

    nested_candidate = json.loads(json.dumps(scenario))
    nested_candidate["id"] = _load_scenarios()[0][1]["id"]
    nested_candidate["event"]["payload"]["resource_ref"] = {"value": "리소스:예제"}
    assert "event.payload.resource_ref.value" in _non_ascii_machine_fields(nested_candidate)


def test_customer_data_scrubber_rejects_each_prohibited_class() -> None:
    prohibited = (
        ({"tenant_id": _nonzero_test_guid("1")}, "cloud_account_id"),
        ({"subscription_id": _nonzero_test_guid("2")}, "cloud_account_id"),
        (
            {"resource_ref": (f"/subscriptions/{_nonzero_test_guid('3')}/resourceGroups/x")},
            "azure_subscription",
        ),
        ({"endpoint": "https://private.contoso.invalid/resource"}, "url"),
        ({"endpoint": "amqps://private.contoso.invalid/resource"}, "url"),
        ({"endpoint": "https://example.com@private.contoso.invalid/resource"}, "url"),
        ({"owner_email": "operator@contoso.invalid"}, "email"),
        ({"owner_email": "operator@corp"}, "email"),
        ({"address": "10.1.2.3"}, "ip_address"),
        ({"address": "2001:4860:4860::8888"}, "ip_address"),
        ({"client_secret": "not-a-real-secret"}, "sensitive_value"),
        ({"clientSecret": "not-a-real-secret"}, "sensitive_value"),
        ({"client-secret": "not-a-real-secret"}, "sensitive_value"),
        ({"secret": "not-a-real-secret"}, "sensitive_value"),
        ({"api_key": "not-a-real-secret"}, "sensitive_value"),
        ({"database_password": "not-a-real-secret"}, "sensitive_value"),
        ({"azure_client_secret_value": "not-a-real-secret"}, "sensitive_value"),
        ({"operator@contoso.invalid": True}, "email"),
        ({"10.1.2.3": "healthy"}, "ip_address"),
        ({"resource_group": "customer-prod"}, "azure_resource_name"),
        ({"resource_name": "customer-vm"}, "azure_resource_name"),
        (
            {
                "resource_ref": (
                    f"/subscriptions/{_SYNTHETIC_GUID}/resourceGroups/customer-prod/"
                    "providers/Microsoft.Compute/virtualMachines/customer-vm"
                )
            },
            "azure_resource_name",
        ),
    )

    for value, expected in prohibited:
        assert any(finding.endswith(f":{expected}") for finding in _customer_data_findings(value))


def test_customer_data_scrubber_allows_documented_synthetic_values() -> None:
    synthetic = {
        "tenant_id": _SYNTHETIC_GUID,
        "subscription_id": _SYNTHETIC_GUID,
        "resource_ref": f"/subscriptions/{_SYNTHETIC_GUID}/resourceGroups/rg-example",
        "documentation": "https://example.com/reference",
        "documentation_sentence": "See https://example.com/reference for details.",
        "local_endpoint": "https://service.example.local/status",
        "ipv4_endpoint": "http://127.0.0.1:8080/status",
        "ipv6_endpoint": "http://[::1]:8080/status",
        "owner_email": "user@example.com",
        "email_sentence": "Contact user@example.com; then continue.",
        "loopback": "127.0.0.1",
        "client_secret": "<redacted>",
    }

    assert _customer_data_findings(synthetic) == ()


def test_customer_data_scrubber_checks_every_uri_and_email() -> None:
    value = {
        "documentation": (
            "https://example.com/reference then https://private.contoso.invalid/secret"
        ),
        "owners": "user@example.com,operator@corp",
    }

    findings = _customer_data_findings(value)
    assert "documentation:url" in findings
    assert "owners:email" in findings


def test_scenario_json_loader_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="duplicate key"):
        _load_json_without_duplicates(
            '{"owner_email":"operator@corp","owner_email":"user@example.com"}'
        )


# ---------------------------------------------------------------------------
# Coverage - success + guard together
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("path", "raw"), _load_scenarios())
def test_every_scenario_declares_both_success_and_guard(path: Path, raw: dict[str, Any]) -> None:
    expected = raw["expected"]
    # Success side (routing decision).
    assert expected["tier"] in ("t0", "t1", "t2"), path.name
    assert expected["decision"] in ("auto", "hil", "abstain", "deny"), path.name
    # Guard side.
    guard = expected["guard"]
    for k in ("should_execute", "should_rollback", "should_trigger_policy_violation"):
        assert isinstance(guard[k], bool), f"{path.name}: guard.{k} must be bool"


@pytest.mark.parametrize(("path", "raw"), _load_scenarios())
def test_scenario_id_matches_filename(path: Path, raw: dict[str, Any]) -> None:
    """Filename MUST derive from id (dots → dashes) so grep / audit are easy."""
    expected = raw["id"].replace(".", "-") + ".json"
    assert path.name == expected, f"{path.name} does not match id-derived filename {expected}"
