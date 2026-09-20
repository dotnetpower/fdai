from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "local_broker_cleanup", ROOT / "scripts/deployment/local/cleanup-local-broker.py"
)
assert SPEC is not None and SPEC.loader is not None
cleanup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cleanup)
GROUP = "fdai-agent-introspection-server.local-12345.abcdef012345"
HEADER = "BROKER GROUP STATE\n"


def test_preparation_cache_binds_cleanup_implementation() -> None:
    source = (ROOT / "scripts/deployment/local/prepare-console-full-stack.sh").read_text()
    inputs = source.split("local_state_inputs=(", 1)[1].split("\n)", 1)[0]
    assert "scripts/deployment/local/cleanup-local-broker.py" in inputs


def test_selects_only_empty_groups_for_dead_local_processes() -> None:
    output = (
        HEADER
        + f"0 {GROUP} Empty\n"
        + "0 fdai-agent-introspection-server.local-54321.abcdef012345 Empty\n"
        + "0 fdai-agent-introspection-server.local-98765.abcdef012345 Stable\n"
        + "0 startup-probe-abcdef Empty\n"
        + "0 fdai-agent-introspection-server.abcdef012345 Empty\n"
        + "0 fdai-agent-introspection-server.local-12345.invalid Empty\n"
    )
    assert cleanup.candidates(output, alive=lambda process_id: process_id == 54321) == [GROUP]


@pytest.mark.parametrize("output", ["", "GROUP STATE\n", HEADER + "invalid\n"])
def test_unknown_output_fails_closed(output: str) -> None:
    with pytest.raises(ValueError):
        cleanup.candidates(output, alive=lambda _pid: False)


def test_preview_never_deletes() -> None:
    calls: list[tuple[str, ...]] = []

    def run(*parts: str) -> str:
        calls.append(parts)
        return HEADER + f"0 {GROUP} Empty\n"

    assert cleanup.cleanup(apply=False, run=run, alive=lambda _pid: False) == {
        "candidates": 1,
        "removed": 0,
    }
    assert calls == [("exec", "fdai-redpanda", "rpk", "group", "list")]


def test_rechecks_group_and_observes_deletion() -> None:
    responses = iter(
        [
            HEADER + f"0 {GROUP} Empty\n",
            HEADER + f"0 {GROUP} Empty\n",
            f"GROUP STATUS\n{GROUP} OK\n",
            HEADER,
        ]
    )
    calls: list[tuple[str, ...]] = []

    def run(*parts: str) -> str:
        calls.append(parts)
        return next(responses)

    assert cleanup.cleanup(apply=True, run=run, alive=lambda _pid: False)["removed"] == 1
    assert calls[2] == ("exec", "fdai-redpanda", "rpk", "group", "delete", GROUP)


def test_reactivated_group_is_not_deleted() -> None:
    responses = iter([HEADER + f"0 {GROUP} Empty\n", HEADER + f"0 {GROUP} Stable\n"])
    assert cleanup.cleanup(
        apply=True, run=lambda *_parts: next(responses), alive=lambda _pid: False
    ) == {"candidates": 1, "removed": 0}


def test_broker_error_stops_cleanup() -> None:
    responses = iter(
        [
            HEADER + f"0 {GROUP} Empty\n",
            HEADER + f"0 {GROUP} Empty\n",
            f"GROUP STATUS\n{GROUP} NON_EMPTY_GROUP\n",
        ]
    )
    with pytest.raises(ValueError, match="did not confirm"):
        cleanup.cleanup(apply=True, run=lambda *_parts: next(responses), alive=lambda _pid: False)
