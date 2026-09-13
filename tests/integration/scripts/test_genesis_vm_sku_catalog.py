"""Full catalog acquisition must retain unlisted hardware and reject incomplete scope."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import genesis_vm_sku_catalog as catalog  # noqa: E402
from genesis_checks import CheckError  # noqa: E402
from tests.integration.scripts.test_genesis_vm_sku_choice import sku  # noqa: E402

SUB = "00000000-0000-0000-0000-000000000001"
BASE = f"https://management.azure.com/subscriptions/{SUB}/providers/Microsoft.Compute/skus"


def page_url(**values):
    return (
        BASE
        + "?"
        + urlencode(
            {
                "api-version": "2021-07-01",
                "$filter": "location eq 'eastus'",
                "$skiptoken": "second",
                **values,
            }
        )
    )


def read(capture):
    return catalog.read_vm_catalog(
        subscription_id=SUB,
        region="EastUS",
        azure_cli=Path("/usr/bin/az"),
        capture=capture,
        cwd=ROOT,
        environment={},
    )


def test_complete_pages_include_skus_outside_preference_names():
    pages = iter([{"value": [sku()], "nextLink": page_url()}, {"value": [sku("Standard_D2ds_v6")]}])
    calls = []

    def capture(command, **kwargs):
        calls.append(command)
        assert command[:4] == ["/usr/bin/az", "rest", "--method", "get"]
        assert command[command.index("--subscription") + 1] == SUB
        query = command[command.index("--query") + 1]
        assert "name ==" not in query and "vCPUs" not in query
        assert kwargs["timeout"] <= 30
        return json.dumps(next(pages))

    assert [row["name"] for row in read(capture)] == ["Standard_D2ds_v4", "Standard_D2ds_v6"]
    assert len(calls) == 2


@pytest.mark.parametrize(
    "link",
    [
        "https://example.com/data",
        page_url(**{"api-version": "2019-04-01"}),
        page_url(**{"$filter": "location eq 'westus'"}),
        page_url().replace(SUB, "00000000-0000-0000-0000-000000000002"),
        page_url() + "&api-version=2021-07-01",
        page_url() + "#fragment",
        page_url(**{"$skiptoken": ""}),
        page_url().replace("management.azure.com", "user@management.azure.com"),
    ],
)
def test_foreign_or_changed_pagination_stops_before_another_request(link):
    calls = []

    def capture(*_args, **_kwargs):
        calls.append(True)
        return json.dumps({"value": [sku()], "nextLink": link})

    with pytest.raises(CheckError, match="evidence_incomplete"):
        read(capture)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "payload", ["{", '{"value":[],"value":[]}', '{"value":[],"x":NaN}', '{"value":null}', "[1]"]
)
def test_malformed_catalog_is_not_an_empty_success(payload):
    with pytest.raises(CheckError, match="evidence_incomplete"):
        read(lambda *_a, **_k: payload)


def test_duplicate_sku_between_pages_is_incomplete():
    pages = iter([{"value": [sku()], "nextLink": page_url()}, {"value": [sku()]}])
    with pytest.raises(CheckError, match="evidence_incomplete"):
        read(lambda *_a, **_k: json.dumps(next(pages)))


@pytest.mark.parametrize(
    "error", [OSError("private-marker"), subprocess.TimeoutExpired(["private-marker"], 1)]
)
def test_capture_failure_is_value_safe_and_has_no_retry(error):
    calls = []

    def capture(*_a, **_k):
        calls.append(True)
        raise error

    with pytest.raises(CheckError) as caught:
        read(capture)
    assert "private-marker" not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize("limit", ["bytes", "rows", "pages", "deadline"])
def test_complete_catalog_requires_all_bounds_to_hold(monkeypatch, limit):
    if limit == "bytes":
        monkeypatch.setattr(catalog, "_MAX_BYTES", 5)
    elif limit == "rows":
        monkeypatch.setattr(catalog, "_MAX_ROWS", 0)
    elif limit == "pages":
        monkeypatch.setattr(catalog, "_MAX_PAGES", 1)
    else:
        monkeypatch.setattr(catalog, "_SECONDS", 0)
    with pytest.raises(CheckError, match="evidence_incomplete"):
        read(lambda *_a, **_k: json.dumps({"value": [sku()], "nextLink": page_url()}))
