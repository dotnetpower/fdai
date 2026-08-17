"""Local semantic topic partition preparation tests."""

from __future__ import annotations

import fcntl
import os
import stat
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts/deployment/local/ensure-semantic-topic-partitions.sh"


def _fake_docker(tmp_path: Path, *, partitions: int | None) -> tuple[Path, Path]:
    executable = tmp_path / "docker"
    log = tmp_path / "docker.log"
    rows = (
        "" if partitions is None else "\n".join(f"{index}  0  0  0" for index in range(partitions))
    )
    describe_status = 1 if partitions is None else 0
    executable.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$FDAI_TEST_DOCKER_LOG"\n'
        "if [[ \"$*\" == *'topic describe'* ]]; then\n"
        f"  printf '%s\\n' 'PARTITION  LEADER  EPOCH  HIGH-WATERMARK' $'{rows}'\n"
        f"  exit {describe_status}\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable, log


@pytest.mark.parametrize(
    ("partitions", "expected"),
    (
        (None, "topic create aw.pantheon.objects -p 2 --if-not-exists"),
        (1, "topic add-partitions aw.pantheon.objects --num 1"),
        (2, None),
    ),
)
def test_ensure_semantic_topic_partitions_is_idempotent(
    tmp_path: Path,
    partitions: int | None,
    expected: str | None,
) -> None:
    _executable, log = _fake_docker(tmp_path, partitions=partitions)
    completed = subprocess.run(  # noqa: S603 - test-controlled executable and environment
        [str(_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "FDAI_TEST_DOCKER_LOG": str(log),
        },
    )

    assert completed.returncode == 0, completed.stderr
    calls = log.read_text(encoding="utf-8")
    if expected is None:
        assert "topic create" not in calls
        assert "topic add-partitions" not in calls
    else:
        assert expected in calls


def test_ensure_semantic_topic_partitions_serializes_reconciliation(tmp_path: Path) -> None:
    _executable, log = _fake_docker(tmp_path, partitions=1)
    lock_path = tmp_path / "fdai-semantic-topic-fdai-redpanda-aw.pantheon.objects.lock"
    lock_path.touch()
    with lock_path.open("r+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        process = subprocess.Popen(  # noqa: S603 - test-controlled executable and environment
            [str(_SCRIPT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={
                **os.environ,
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "TMPDIR": str(tmp_path),
                "FDAI_TEST_DOCKER_LOG": str(log),
            },
        )
        assert process.poll() is None
        assert not log.exists()
        fcntl.flock(lock, fcntl.LOCK_UN)

    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stderr or stdout
    assert "topic add-partitions aw.pantheon.objects --num 1" in log.read_text(encoding="utf-8")
