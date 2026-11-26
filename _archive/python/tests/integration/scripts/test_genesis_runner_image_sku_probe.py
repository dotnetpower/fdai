"""Bounded SKU transport tests use only synthetic responses and an injected capture."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import genesis_runner_image_sku_probe as probe  # noqa: E402
from genesis_checks import CheckError  # noqa: E402
from tests.integration.scripts.test_genesis_runner_image_skus import plan, rows  # noqa: E402

SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
BASE = f"https://management.azure.com/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Compute/skus"
PARAMS = {"api-version": "2019-04-01", "$filter": "location eq 'eastus'"}


def next_url(cursor: str = "next") -> str:
    return BASE + "?" + urlencode({**PARAMS, "$skiptoken": cursor})


def verify(capture: object, tmp_path: Path, **overrides: object) -> None:
    inputs = {
        "projection": json.dumps(plan()).encode(),
        "subscription_id": SUBSCRIPTION,
        "region": "eastus",
        "azure_cli": Path("/usr/bin/az"),
        "capture": capture,
        "cwd": tmp_path,
        "environment": {"ARM_SUBSCRIPTION_ID": SUBSCRIPTION},
        **overrides,
    }
    probe.verify_image_vm_skus(**inputs)


def test_transport_uses_exact_subscription_server_filter_and_no_convenience_scan(
    tmp_path: Path,
) -> None:
    calls = []

    def capture(command: list[str], **kwargs: object) -> str:
        calls.append(command)
        assert command[:4] == ["/usr/bin/az", "rest", "--method", "get"]
        assert command[command.index("--subscription") + 1] == SUBSCRIPTION
        url = urlsplit(command[command.index("--url") + 1])
        assert url.path == urlsplit(BASE).path
        assert parse_qs(url.query) == {key: [value] for key, value in PARAMS.items()}
        query = command[command.index("--query") + 1]
        assert "Standard_D2ds_v5" in query and "Standard_B2s" in query
        assert "restrictions:restrictions" in query and "nextLink:nextLink" in query
        assert "list-skus" not in command
        assert kwargs["cwd"] == tmp_path
        assert kwargs["env"] == {"ARM_SUBSCRIPTION_ID": SUBSCRIPTION}
        assert 0 < kwargs["timeout"] <= 30
        return json.dumps({"value": rows(), "nextLink": None})

    verify(capture, tmp_path)
    assert len(calls) == 1


def test_all_pages_are_required_even_when_first_page_has_both_sizes(tmp_path: Path) -> None:
    calls = []

    def capture(command: list[str], **_kwargs: object) -> str:
        calls.append(command)
        if len(calls) == 1:
            return json.dumps({"value": rows(), "nextLink": next_url()})
        assert command[command.index("--url") + 1] == next_url()
        return json.dumps({"value": [rows()[0]], "nextLink": None})

    with pytest.raises(CheckError, match=probe.EVIDENCE_INVALID):
        verify(capture, tmp_path)
    assert len(calls) == 2


def test_selections_can_arrive_on_different_complete_pages(tmp_path: Path) -> None:
    pages = iter(
        [
            {"value": rows()[:1], "nextLink": next_url()},
            {"value": rows()[1:], "nextLink": None},
        ]
    )
    verify(lambda *_a, **_kw: json.dumps(next(pages)), tmp_path)


@pytest.mark.parametrize(
    "link",
    [
        "https://untrusted.example.invalid/skus",
        next_url().replace("https:", "http:"),
        next_url().replace("management.azure.com", "management.azure.com:443"),
        next_url().replace("management.azure.com", "user@management.azure.com"),
        next_url().replace(SUBSCRIPTION, "00000000-0000-0000-0000-000000000002"),
        next_url().replace("/skus?", "/resources?"),
        next_url().replace("eastus", "westus"),
        next_url().replace("2019-04-01", "2021-07-01"),
        next_url() + "#fragment",
        next_url() + "&api-version=2019-04-01",
        next_url() + "&unexpected=value",
        BASE + "?api-version=2019-04-01",
        next_url(""),
        "\n" + next_url(),
        "https://[invalid",
        "x" * 8193,
        "",
        5,
        [],
    ],
)
def test_untrusted_or_unscoped_next_page_stops_before_another_request(
    tmp_path: Path, link: object
) -> None:
    calls = []

    def capture(*_args: object, **_kwargs: object) -> str:
        calls.append(1)
        return json.dumps({"value": rows(), "nextLink": link})

    with pytest.raises(CheckError, match=probe.EVIDENCE_INVALID):
        verify(capture, tmp_path)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "error",
    [
        subprocess.TimeoutExpired(["az", "private-target"], 30),
        subprocess.CalledProcessError(1, ["az", "private-target"], stderr="private-diagnostic"),
        OSError("private-diagnostic"),
        ValueError("private-diagnostic"),
    ],
)
def test_provider_failures_are_redacted_and_never_retried(tmp_path: Path, error: Exception) -> None:
    calls = []

    def capture(*_args: object, **_kwargs: object) -> str:
        calls.append(1)
        raise error

    with pytest.raises(CheckError, match=f"^{probe.EVIDENCE_INVALID}$") as caught:
        verify(capture, tmp_path)
    assert caught.value.__suppress_context__
    assert len(calls) == 1


@pytest.mark.parametrize("raw", ["{}", "{", "[]", '{"value":null}', '{"value":[],"value":[]}'])
def test_invalid_json_response_cannot_succeed(tmp_path: Path, raw: str) -> None:
    with pytest.raises(CheckError, match=probe.EVIDENCE_INVALID):
        verify(lambda *_a, **_kw: raw, tmp_path)


@pytest.mark.parametrize("before_read", [True, False])
def test_total_deadline_blocks_before_or_after_a_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, before_read: bool
) -> None:
    ticks = iter([0, 90] if before_read else [0, 1, 90])
    monkeypatch.setattr(probe, "monotonic", lambda: next(ticks))
    calls = []

    def capture(*_args: object, **_kwargs: object) -> str:
        calls.append(1)
        return json.dumps({"value": rows()})

    with pytest.raises(CheckError, match=probe.EVIDENCE_INVALID):
        verify(capture, tmp_path)
    assert len(calls) == (0 if before_read else 1)


def test_per_request_timeout_uses_remaining_total_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter([0, 1, 50, 80, 81])
    monkeypatch.setattr(probe, "monotonic", lambda: next(ticks))
    timeouts = []

    def capture(*_args: object, **kwargs: object) -> str:
        timeouts.append(kwargs["timeout"])
        return (
            json.dumps({"value": rows()[:1], "nextLink": next_url()})
            if len(timeouts) == 1
            else json.dumps({"value": rows()[1:]})
        )

    verify(capture, tmp_path)
    assert timeouts == [30, 10]


@pytest.mark.parametrize("loop", [True, False])
def test_page_loops_and_page_limit_are_incomplete(tmp_path: Path, loop: bool) -> None:
    calls = []

    def capture(*_args: object, **_kwargs: object) -> str:
        calls.append(1)
        return json.dumps({"value": [], "nextLink": next_url("loop" if loop else str(len(calls)))})

    with pytest.raises(CheckError, match=probe.EVIDENCE_INVALID):
        verify(capture, tmp_path)
    assert len(calls) == (2 if loop else 4)


@pytest.mark.parametrize("oversized", ["bytes", "rows", "cumulative_bytes"])
def test_parsed_response_budgets_cannot_be_success(tmp_path: Path, oversized: str) -> None:
    calls = []

    def capture(*_args: object, **_kwargs: object) -> str:
        calls.append(1)
        if oversized == "rows":
            return json.dumps({"value": rows() * 33})
        if oversized == "bytes":
            return json.dumps({"value": rows(), "padding": "x" * probe._MAX_BYTES})
        return json.dumps(
            {
                "value": [],
                "padding": "x" * (probe._MAX_BYTES // 2),
                "nextLink": next_url(str(len(calls))),
            }
        )

    with pytest.raises(CheckError, match=probe.EVIDENCE_INVALID):
        verify(capture, tmp_path)
    assert len(calls) == (2 if oversized == "cumulative_bytes" else 1)


@pytest.mark.parametrize(
    "overrides", [{"subscription_id": "--other"}, {"region": "bad'filter"}, {"projection": b"{}"}]
)
def test_invalid_inputs_fail_before_network(tmp_path: Path, overrides: dict[str, object]) -> None:
    def capture(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("unexpected provider call")

    with pytest.raises(CheckError):
        verify(capture, tmp_path, **overrides)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"value": []},
        {"value": None},
        {"value": [{}] * 513},
        {"value": [{}], "nextLink": "untrusted"},
    ],
)
def test_quota_probe_requires_complete_bounded_rows(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    with pytest.raises(CheckError, match=probe.EVIDENCE_INVALID):
        probe.read_vm_usage(
            subscription_id=SUBSCRIPTION,
            region="eastus",
            azure_cli=Path("/usr/bin/az"),
            capture=lambda *_a, **_kw: json.dumps(payload),
            cwd=tmp_path,
            environment={},
        )


def test_quota_probe_uses_the_same_subscription_and_region(tmp_path: Path) -> None:
    def capture(cmd: list[str], **kwargs: object) -> str:
        assert cmd[:4] == ["/usr/bin/az", "rest", "--method", "get"]
        assert cmd[cmd.index("--subscription") + 1] == SUBSCRIPTION
        assert "/locations/eastus/usages?" in cmd[cmd.index("--url") + 1]
        assert kwargs["timeout"] == 30
        return '{"value":[{"name":"cores","current":"0","limit":"100"}]}'

    assert (
        probe.read_vm_usage(
            subscription_id=SUBSCRIPTION,
            region="EASTUS",
            azure_cli=Path("/usr/bin/az"),
            capture=capture,
            cwd=tmp_path,
            environment={},
        )[0]["limit"]
        == "100"
    )


@pytest.mark.parametrize("bad_target", [True, False])
def test_quota_probe_invalid_target_stops_before_capture(tmp_path: Path, bad_target: bool) -> None:
    def fail(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("invalid target must not reach the provider")

    with pytest.raises(CheckError, match=probe.EVIDENCE_INVALID):
        probe.read_vm_usage(
            subscription_id="invalid" if bad_target else SUBSCRIPTION,
            region="eastus" if bad_target else "bad'filter",
            azure_cli=Path("/usr/bin/az"),
            capture=fail,
            cwd=tmp_path,
            environment={},
        )


def test_quota_probe_timeout_is_safe_and_not_retried(tmp_path: Path) -> None:
    calls = []

    def fail(*_args: object, **_kwargs: object) -> str:
        calls.append(1)
        raise subprocess.TimeoutExpired(["az", "private-target"], 30)

    with pytest.raises(CheckError, match=f"^{probe.EVIDENCE_INVALID}$") as caught:
        probe.read_vm_usage(
            subscription_id=SUBSCRIPTION,
            region="eastus",
            azure_cli=Path("/usr/bin/az"),
            capture=fail,
            cwd=tmp_path,
            environment={},
        )
    assert caught.value.__suppress_context__ and len(calls) == 1
