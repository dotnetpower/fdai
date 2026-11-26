from copy import deepcopy

import pytest
from fdai_operator_service.code_security_review_projection import read_code_security_projection
from fdai_operator_service.knowledge_github_projection import knowledge_github_projection


def row():
    return {
        "key": "runtime:code-security-repository:example-app",
        "value": {
            "kind": "code-security-repository",
            "repository_alias": "example-app",
            "provider": "github",
            "location": "example/app",
            "default_ref": "main",
            "exposure": "unknown",
            "enabled": False,
            "registered_at": "2026-10-09T00:00:00+00:00",
            "registered_by": "owner",
            "revision": 1,
            "knowledge_source": {
                "credential_reference": "public",
                "knowledge_read_enabled": True,
                "repository_id": 123,
                "private": False,
                "observed_commit": "a" * 40,
                "readme_digest": "b" * 64,
                "observed_at": "2026-10-09T00:00:00+00:00",
                "request_id": "operator-" + "c" * 32,
            },
        },
    }


def test_projection_preserves_independent_permissions_and_exact_observation():
    projection = knowledge_github_projection([row()])
    (source,) = projection["sources"]
    assert source["enabled"] is False and source["knowledge_source"]["knowledge_read_enabled"]
    assert source["knowledge_source"]["observed_commit"] == "a" * 40
    assert "request_id" not in source["knowledge_source"]
    assert "registered_by" not in source
    assert projection["indexed"] is False and projection["complete"] is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(key="runtime:code-security-repository:other"),
        lambda r: r["value"].update(revision=True),
        lambda r: r["value"]["knowledge_source"].update(knowledge_read_enabled="true"),
        lambda r: r["value"]["knowledge_source"].update(credential_reference="raw-token"),
        lambda r: r["value"]["knowledge_source"].update(private=True),
        lambda r: r["value"]["knowledge_source"].update(observed_at="2026-10-09"),
        lambda r: r["value"]["knowledge_source"].update(enabled=True),
    ],
)
def test_bad_evidence_is_withheld_and_never_becomes_connected(mutate):
    record = deepcopy(row())
    mutate(record)
    projection = knowledge_github_projection([record])
    assert projection["sources"] == [] and not projection["complete"] and projection["gaps"]


def test_legacy_scan_registration_is_not_a_verified_knowledge_connection():
    record = row()
    del record["value"]["knowledge_source"]
    projection = knowledge_github_projection([record])
    assert projection["sources"][0]["knowledge_source"] is None


async def test_reader_uses_existing_bounded_repository_prefix_not_a_broad_knowledge_scan():
    calls = []

    async def fetch(sql, parameters):
        calls.append((sql, parameters))
        return [row()]

    projection = await read_code_security_projection("knowledge.github.sources", fetch)
    assert projection["sources"]
    assert calls[0][1] == ("runtime:code-security-repository:%",)
    assert "LIMIT 201" in calls[0][0]
