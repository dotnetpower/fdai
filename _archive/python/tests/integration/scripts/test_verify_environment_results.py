"""Environment faults remain distinct from code failures in the local gate summary."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("codes", [(125,), (125, 1), (1, 125)])
def test_missing_toolchain_cannot_be_reported_as_pass(codes: tuple[int, ...]) -> None:
    source = (ROOT / "scripts/verify.sh").read_text(encoding="utf-8")
    helper = source[source.index("run_gate() {") : source.index("\nchanged_matches()")]
    script = (
        "set -uo pipefail\nNAMES=(); RESULTS=(); PENDING_CACHE=(); overall=0\n"
        'cache_identity=""; cache_content=""; cache_history=""\n'
        + helper
        + "\n"
        + "\n".join(
            f"run_gate test-{index} bash -c 'exit {code}'" for index, code in enumerate(codes)
        )
        + '\nprintf "\\nresult=%s %s\\n" "$overall" "${RESULTS[*]}"\n'
    )
    result = subprocess.run(  # noqa: S603 - extracted tracked helper, fixed synthetic failures
        ["/usr/bin/bash", "-c", script], capture_output=True, text=True, check=True
    )
    assert "result=125" in result.stdout
    assert "ENVIRONMENT_FAULT" in result.stdout
    assert "PASS" not in result.stdout
