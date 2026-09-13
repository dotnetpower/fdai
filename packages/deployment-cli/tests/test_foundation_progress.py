"""Exercise the presentation adapter with the actual Genesis renderer and synthetic records."""

from __future__ import annotations

import io
import runpy
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from fdai_deployment_cli.foundation_progress import (
    CHECKPOINT_LABELS,
    FoundationProgressStream,
    parse_checkpoint,
)

ROOT = Path(__file__).resolve().parents[3]
GENESIS = runpy.run_path(str(ROOT / "scripts/deployment/azure/genesis_status.py"))


def introduction(mode="apply") -> str:
    output = io.StringIO()
    with redirect_stderr(output):
        GENESIS["render_plan"](mode)
    return output.getvalue()


def record(*, number=4, completed=3, skipped=0, state="running") -> str:
    output = io.StringIO()
    with redirect_stderr(output):
        GENESIS["render_progress"](
            {
                "stages_total": 15,
                "stages_completed": completed,
                "stages_skipped": skipped,
                "progress_percent": completed * 100 // 15,
                "current_stage": GENESIS["STAGES"][number - 1][0],
                "state": state,
            }
        )
    return output.getvalue()


def adapter():
    output, checkpoints, signals, modes = [], [], [], []
    stream = FoundationProgressStream(
        output=output.append,
        checkpoint=checkpoints.append,
        heartbeat=lambda: signals.append(True),
        mode=modes.append,
    )
    return stream, output, checkpoints, signals, modes


@pytest.mark.parametrize("mode", ["apply", "inspect"])
@pytest.mark.parametrize("chunk_size", [1, 3, 17, 1024, 4096])
def test_real_producer_banner_and_records_compact_across_chunks(mode, chunk_size) -> None:
    stream, output, checkpoints, signals, modes = adapter()
    text = introduction(mode) + record() + "..\n" + record(number=5, completed=4)
    for offset in range(0, len(text), chunk_size):
        stream.feed(text[offset : offset + chunk_size])
    stream.finish()
    assert output == []
    assert [item.number for item in checkpoints] == [4, 5]
    assert checkpoints[-1].label == "Tenant policy route"
    assert checkpoints[-1].completed == 4
    assert signals
    assert modes == ["mutation-enabled preflight" if mode == "apply" else "read-only inspection"]


@pytest.mark.parametrize("number", range(1, 16))
@pytest.mark.parametrize("state", ["running", "waiting", "blocked", "failed", "complete"])
def test_every_real_stage_and_state_is_presentation_only(number, state) -> None:
    parsed = parse_checkpoint(record(number=number, state=state).rstrip("\n"))
    assert parsed is not None
    assert parsed.label == CHECKPOINT_LABELS[number - 1]
    assert parsed.state == state.upper()
    assert parsed.completed == 3
    assert not hasattr(parsed, "deployment_ready")
    assert not hasattr(parsed, "approval")


@pytest.mark.parametrize("completed", range(16))
def test_exact_counts_include_skipped_without_inventing_success(completed) -> None:
    parsed = parse_checkpoint(record(completed=completed, skipped=completed).rstrip("\n"))
    assert parsed is not None
    assert parsed.completed == parsed.skipped == completed


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (" 20%", " 21%"),
        ("done 3/15", "done 16/15"),
        ("stage 4/15", "stage 0/15"),
        ("stage 4/15", "stage 16/15"),
        ("/15", "/16"),
        ("skipped 0", "skipped 4"),
        ("remaining 12", "remaining 11"),
        ("Azure resource providers", "unrecognized provider text"),
        ("RUNNING", "APPROVED"),
        ("####", "###."),
        ("done 3", "done 03"),
    ],
)
def test_malformed_or_unknown_records_remain_native(old, new) -> None:
    stream, output, checkpoints, _signals, _modes = adapter()
    malformed = record().replace(old, new)
    assert malformed != record()
    stream.feed(introduction() + malformed)
    stream.finish()
    assert "".join(output) == malformed
    assert checkpoints == []


def test_unknown_partial_prompt_is_forwarded_without_waiting_for_newline() -> None:
    stream, output, checkpoints, _signals, _modes = adapter()
    stream.feed(introduction())
    stream.feed("WARNING: exact review required. Confirm: ")
    assert "".join(output) == "WARNING: exact review required. Confirm: "
    stream.feed("declined\n" + record())
    stream.finish()
    assert "".join(output) == "WARNING: exact review required. Confirm: declined\n"
    assert len(checkpoints) == 1


def test_dot_prefix_is_preserved_when_followed_by_a_diagnostic() -> None:
    stream, output, checkpoints, _signals, _modes = adapter()
    stream.feed(introduction())
    stream.feed("...")
    stream.feed("WARNING: review interrupted\n")
    stream.finish()
    assert "".join(output) == "...WARNING: review interrupted\n"
    assert checkpoints == []


@pytest.mark.parametrize("text", ["FDAI Azure Gen", "FDAI Azure Genesis v3\nProcedure:\n", "ERROR"])
def test_unknown_and_incomplete_introductions_are_never_hidden(text) -> None:
    stream, output, checkpoints, _signals, _modes = adapter()
    stream.feed(text)
    stream.finish()
    assert "".join(output) == text
    assert checkpoints == []


def test_oversized_and_unicode_diagnostics_are_not_retained_in_the_parser() -> None:
    stream, output, checkpoints, _signals, _modes = adapter()
    stream.feed(introduction())
    text = record().split(" | stage ")[0] + " | stage " + "검토 " * 20000
    stream.feed(text)
    assert "".join(output) == text
    assert len(stream._pending) <= 512
    stream.finish()
    assert checkpoints == []


def test_partial_progress_at_eof_remains_visible() -> None:
    stream, output, checkpoints, _signals, _modes = adapter()
    stream.feed(introduction())
    partial = record()[:35]
    stream.feed(partial)
    stream.finish()
    assert "".join(output) == partial
    assert checkpoints == []
