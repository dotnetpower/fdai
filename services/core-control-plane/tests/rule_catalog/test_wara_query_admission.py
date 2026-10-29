from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest
from fdai.rule_catalog.schema.wara_assessment import (
    QuerySafetyClassification,
    WaraApplicabilityMapping,
    classify_wara_query,
)

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    "query",
    [
        "// soft delete must be enabled\nresources | project id",
        "/* create/update/delete */ resources | project id",
        "/* outer /* nested delete */ create */ resources | project id",
        "resources | extend note = 'delete create update drop alter patch'",
        'resources | extend note = "delete \\" create // /*"',
        "resources | extend note = @'delete '' create /*'",
        'resources | extend note = @"delete "" create //", id=id',
        "resources | extend note = ```delete ' \" // /*```",
        "resources | extend ['delete'] = 'create' | project ['delete']",
        "resources | extend create = properties.delete",
        "resources | where isempty(properties.cluster) | project database=properties.database",
        "resources | extend note = 'cluster(\"example.com\") externaldata http_request'",
        "resources | extend note = 'join union set execute invoke'",
        "// microsoft.other/other\nresources | where type == 'microsoft.compute/virtualmachines'",
        "resources | extend label='Microsoft.Network/virtualNetworks'",
        "resources | where properties.targetResourceId contains "
        "'Microsoft.Network/virtualNetworks'",
        "resources | extend value=properties['type'] == 'Microsoft.Network/virtualNetworks'",
    ],
)
def test_comments_literals_and_property_identifiers_are_inert(query: str) -> None:
    classification, reasons, tables, _ = classify_wara_query(
        query, declared_provider_type="microsoft.compute/virtualmachines"
    )
    assert classification is QuerySafetyClassification.READ_ONLY_BOUNDED
    assert reasons == ()
    assert tables == ("resources",)


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        (".delete table resources records", "mutation_command"),
        ("/* comment */ .create table resources (x:string)", "mutation_command"),
        ("resources | delete", "mutation_command"),
        ("resources;\n.drop table resources", "mutation_command"),
        ("resources // comment\r.delete table resources", "mutation_command"),
        ("resources\n/* leading comment */ .delete table resources", "mutation_command"),
        ("resources /* multiline\ncomment */ .delete table resources", "mutation_command"),
        ("resources\n.show tables", "control_command"),
        ("resources | invoke f()", "control_command"),
        ("/* comment */ set x=1", "control_command"),
        ("resources | execute f()", "control_command"),
        ("resources | extend x=cluster /* comment */ ('example.com')", "dynamic_endpoint"),
        ("resources | extend x=database('db')", "dynamic_endpoint"),
        ("resources | extend x=['cluster']('example.com')", "dynamic_endpoint"),
        ("resources | extend x=['clu\\u0073ter']('example.com')", "dynamic_endpoint"),
        ("resources | extend x=['\\x63luster']('example.com')", "dynamic_endpoint"),
        ("externaldata(x:string)['example.com']", "dynamic_endpoint"),
        ("resources | evaluate http_request('example.com')", "dynamic_endpoint"),
        ("resources | join /* comment */ (resources) on id", "unsupported_join"),
        ("resources | union (resources)", "unsupported_join"),
        ("resources; resources", "multiple_statements"),
        ("unreviewedresources | project id", "missing_declared_table"),
        ("// resources\nunreviewedresources | project id", "missing_declared_table"),
        ("resources | extend x='unterminated", "malformed_query"),
        ('resources | extend x="unterminated', "malformed_query"),
        ("resources /* unterminated", "malformed_query"),
        ("resources /* nested /* comment */", "malformed_query"),
        ("resources | extend x=@'unterminated", "malformed_query"),
        ("resources | extend x=```unterminated", "malformed_query"),
        ("resources | extend x='trailing\\", "malformed_query"),
        ("resources | extend x='bad\\u12'", "malformed_query"),
        ("resources | extend x='bad\\xq1'", "malformed_query"),
        ("resources | extend x='bad\\UFFFFFFFF'", "malformed_query"),
        ("resources | where (id == 'x'", "malformed_query"),
        ("resources | extend x=dynamic([1,2})", "malformed_query"),
        ("resources | project id)", "malformed_query"),
        ("resources | extend x=\\u0063luster('example.com')", "malformed_query"),
        ("resources |", "malformed_query"),
    ],
)
def test_harmful_dynamic_or_malformed_syntax_stays_blocked(query: str, reason: str) -> None:
    classification, reasons, _, _ = classify_wara_query(query)
    assert classification is QuerySafetyClassification.BLOCKED
    assert reason in reasons


@pytest.mark.parametrize(
    "predicate",
    [
        "type == 'Microsoft.Network/virtualNetworks'",
        "['type'] =~ 'Microsoft.Network/virtualNetworks'",
        "type in~ ('Microsoft.Compute/virtualMachines', 'Microsoft.Network/virtualNetworks')",
        "type in~ ('Microsoft.Compute/virtualMachines', '|', 'Microsoft.Network/virtualNetworks')",
        "type == 'Micros\\u006fft.Network/virtualNetworks'",
    ],
)
def test_related_source_type_predicates_remain_blocked(predicate: str) -> None:
    classification, reasons, _, resource_types = classify_wara_query(
        f"resources | where {predicate}",
        declared_provider_type="microsoft.compute/virtualmachines",
    )
    assert classification is QuerySafetyClassification.BLOCKED
    assert "undeclared_resource_type" in reasons
    assert "microsoft.network/virtualnetworks" in resource_types


def test_actual_published_mutation_false_positives_are_corrected() -> None:
    raw = json.loads(
        (ROOT / "rule-catalog/collected/wara-aprl/assessment/queries.json").read_text()
    )
    corrected = 0
    for item in raw["queries"]:
        body = base64.b64decode(item["body_base64"]).decode()
        if re.search(r"\b(delete|drop|alter|create|update|patch)\b", body, re.IGNORECASE):
            corrected += 1
            _, reasons, _, _ = classify_wara_query(body)
            assert "mutation_command" not in reasons
    assert corrected == 6


@pytest.mark.parametrize(
    "overrides",
    [
        {"canonical_resource_types": ("compute.web-app", "compute.function")},
        {"canonical_resource_type": "compute.function"},
        {"canonical_resource_types": ()},
        {"provider_resource_types": ()},
    ],
)
def test_candidate_unions_cannot_choose_an_arbitrary_subtype(overrides: dict) -> None:
    material = {
        "normalized_provider_type": "microsoft.web/sites",
        "disposition": "canonical",
        "canonical_resource_type": None,
        "canonical_resource_types": ("compute.function", "compute.web-app"),
        "provider_resource_types": ("microsoft.web/sites",),
        "parent_provider_type": None,
        "requires_exact_child_scope": False,
    }
    with pytest.raises(ValueError):
        WaraApplicabilityMapping.model_validate({**material, **overrides})
