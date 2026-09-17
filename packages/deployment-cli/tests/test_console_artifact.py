from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fdai_deployment_cli import console_artifact


def test_build_console_update_artifact_uses_clean_git_snapshot(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output_parent = tmp_path / "private"
    output_parent.mkdir(mode=0o700)
    output = output_parent / "candidate"
    source_commit = "a" * 40
    calls: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:3] == ("git", "-C", str(source)):
            if "show" in command:
                return subprocess.CompletedProcess(command, 0, stdout="1700000000\n", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout=f"{source_commit}\n", stderr="")
        if command[:2] == ("npm", "--prefix") and command[-1] == "build:offline":
            offline = Path(command[2]) / "dist/offline"
            offline.mkdir(parents=True)
            (offline / "index.html").write_text("index", encoding="utf-8")
            (offline / "fdai-config.js").write_text("config", encoding="utf-8")
        if command[0] == "tar" and "-czf" in command:
            Path(command[command.index("-czf") + 1]).write_bytes(b"console-archive")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(console_artifact.subprocess, "run", run)
    result = console_artifact.build_console_update_artifact(
        source_root=source,
        revision="HEAD",
        output_dir=output,
    )

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert result["source_commit"] == source_commit
    assert manifest["source_commit"] == source_commit
    assert manifest["archive_sha256"] == result["archive_sha256"]
    assert (output / "console.tar.gz").stat().st_mode & 0o777 == 0o600
    assert any(command[0] == "npm" and command[-1] == "build:offline" for command in calls)
    assert result["azure_mutation_performed"] is False
