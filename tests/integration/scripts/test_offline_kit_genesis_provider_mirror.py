"""Exercise bundled-root mirror staging with a local fake Terraform executable."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "scripts/deployment/release/mirror-locked-providers.sh"
ROOTS = (
    "infra",
    "infra/bootstrap",
    "infra/genesis-foundation",
    "infra/scenario-lab",
    "infra/services/core-control-plane",
    "infra/services/operator-service",
    "infra/services/document-ingestion-api",
    "infra/services/document-processing-worker",
    "infra/services/isolated-executor",
)
AZURERM = "registry.terraform.io/hashicorp/azurerm"
AZAPI = "registry.terraform.io/azure/azapi"
RANDOM = "registry.terraform.io/hashicorp/random"


def _bundle(path: Path) -> None:
    for root in ROOTS:
        directory = path / root
        directory.mkdir(parents=True)
        providers = [(AZURERM, "4.80.0" if root == "infra/bootstrap" else "4.81.0")]
        if root == "infra/genesis-foundation":
            providers.append((AZAPI, "2.12.0"))
        if root == "infra/scenario-lab":
            providers.append((RANDOM, "3.7.2"))
        (directory / ".terraform.lock.hcl").write_text(
            "".join(
                f'provider "{provider}" {{\n  version = "{version}"\n}}\n'
                for provider, version in providers
            ),
            encoding="utf-8",
        )
        (directory / "main.tf").write_text("# synthetic root\n", encoding="utf-8")
    module = path / "infra/modules/example"
    module.mkdir(parents=True)
    (module / "main.tf").write_text("# synthetic local module\n", encoding="utf-8")
    (path / "manifest.json").write_text('{"synthetic": true}\n', encoding="utf-8")


def _fake_terraform(path: Path) -> None:
    path.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json
import os
import re
import sys
from pathlib import Path

cwd = Path.cwd()
scratch = Path(os.environ["FAKE_SCRATCH"])
root = cwd.relative_to(scratch).as_posix()
args = sys.argv[1:]
with Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"root": root, "args": args, "cwd": str(cwd)}) + "\n")
if root == os.environ.get("FAKE_FAIL_ROOT") and args[0] == os.environ["FAKE_FAIL_COMMAND"]:
    print("synthetic Terraform failure", file=sys.stderr)
    sys.exit(17)
assert (scratch / "infra/modules/example/main.tf").is_file()
assert (cwd / ".terraform.lock.hcl").is_file()
if args[0] == "init":
    assert args == ["init", "-backend=false", "-input=false", "-lockfile=readonly"]
    data = Path(os.environ["TF_DATA_DIR"])
    assert data == cwd / ".terraform"
    data.mkdir()
    (data / "modules.json").write_text("{}")
elif args[:2] == ["providers", "mirror"]:
    assert args[2:4] == ["-lock-file=true", "-platform=" + os.environ["FAKE_PLATFORM"]]
    assert (cwd / ".terraform/modules.json").is_file()
    target = Path(args[-1])
    locks = re.findall(
        r'provider "([^"]+)" \{\s*version = "([^"]+)"',
        (cwd / ".terraform.lock.hcl").read_text(),
    )
    assert locks
    for provider, version in locks:
        destination = target / provider
        destination.mkdir(parents=True, exist_ok=True)
        name = provider.rsplit("/", 1)[-1]
        artifact = f"terraform-provider-{name}_{version}_{os.environ['FAKE_PLATFORM']}.zip"
        (destination / artifact).write_bytes(b"synthetic provider archive")
else:
    raise AssertionError(args)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _snapshot(path: Path) -> dict[str, bytes | None]:
    return {
        item.relative_to(path).as_posix(): item.read_bytes() if item.is_file() else None
        for item in path.rglob("*")
    }


def _run(
    work: Path,
    *,
    platform: str = "linux_amd64",
    fail_root: str = "",
    fail_command: str = "",
) -> subprocess.CompletedProcess[str]:
    terraform = work / "terraform"
    _fake_terraform(terraform)
    return subprocess.run(  # noqa: S603 - fixed repository helper and generated test fixture only
        ["/bin/bash", str(HELPER), str(work / "bundle"), str(work), str(terraform), platform],
        cwd=ROOT,
        env={
            **os.environ,
            "FAKE_LOG": str(work / "commands.jsonl"),
            "FAKE_SCRATCH": str(work / "mirror-src"),
            "FAKE_PLATFORM": platform,
            "FAKE_FAIL_ROOT": fail_root,
            "FAKE_FAIL_COMMAND": fail_command,
            # The helper must override an ambient Terraform data directory.
            "TF_DATA_DIR": str(work / "bundle/ambient-data"),
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


@pytest.mark.parametrize("platform", ["linux_amd64", "linux_arm64"])
def test_all_bundled_roots_contribute_locked_providers(tmp_path: Path, platform: str) -> None:
    bundle = tmp_path / "bundle"
    _bundle(bundle)
    before = _snapshot(bundle)

    result = _run(tmp_path, platform=platform)

    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in (tmp_path / "commands.jsonl").read_text().splitlines()]
    assert [(record["root"], record["args"][0]) for record in records] == [
        (root, command) for root in ROOTS for command in ("init", "providers")
    ]
    artifacts = {
        path.relative_to(tmp_path / "mirror").as_posix()
        for path in (tmp_path / "mirror").rglob("*.zip")
    }
    assert artifacts == {
        f"{AZURERM}/terraform-provider-azurerm_4.80.0_{platform}.zip",
        f"{AZURERM}/terraform-provider-azurerm_4.81.0_{platform}.zip",
        f"{AZAPI}/terraform-provider-azapi_2.12.0_{platform}.zip",
        f"{RANDOM}/terraform-provider-random_3.7.2_{platform}.zip",
    }
    assert _snapshot(bundle) == before
    assert not (tmp_path / "mirror-src").exists()


@pytest.mark.parametrize("root", ROOTS)
@pytest.mark.parametrize("missing", [True, False], ids=["missing", "empty"])
def test_missing_or_empty_lock_stops_before_terraform(
    tmp_path: Path, root: str, missing: bool
) -> None:
    bundle = tmp_path / "bundle"
    _bundle(bundle)
    lock = bundle / root / ".terraform.lock.hcl"
    if missing:
        lock.unlink()
    else:
        lock.write_bytes(b"")
    before = _snapshot(bundle)

    result = _run(tmp_path)

    assert result.returncode != 0
    assert f"dependency lock for {root}" in result.stderr
    assert not (tmp_path / "commands.jsonl").exists()
    assert not (tmp_path / "mirror").exists()
    assert _snapshot(bundle) == before


@pytest.mark.parametrize("command", ["init", "providers"])
def test_terraform_failure_aborts_remaining_roots_without_changing_bundle(
    tmp_path: Path, command: str
) -> None:
    bundle = tmp_path / "bundle"
    _bundle(bundle)
    before = _snapshot(bundle)

    result = _run(tmp_path, fail_root="infra/genesis-foundation", fail_command=command)

    assert result.returncode == 17
    assert "synthetic Terraform failure" in result.stderr
    records = [json.loads(line) for line in (tmp_path / "commands.jsonl").read_text().splitlines()]
    assert records[-1]["root"] == "infra/genesis-foundation"
    assert records[-1]["args"][0] == command
    assert not any(record["root"].startswith("infra/services/") for record in records)
    assert not list((tmp_path / "mirror").rglob("terraform-provider-azapi*"))
    assert _snapshot(bundle) == before
    assert not (tmp_path / "mirror-src").exists()


def test_offline_stage_invokes_the_locked_root_mirror_helper() -> None:
    stage = (ROOT / "scripts/deployment/release/stage-offline-kit.sh").read_text(encoding="utf-8")
    section = stage.split('echo "-- terraform provider mirror"', 1)[1].split(
        'echo "-- fdai deployment CLI wheel"', 1
    )[0]

    assert "set -euo pipefail" in stage
    assert "bash scripts/deployment/release/mirror-locked-providers.sh" in section
    assert '"$OUT/bundle" "$OUT" "$TERRAFORM_BIN" "$PLATFORM"' in section
    assert "providers mirror" not in section


@pytest.mark.parametrize("expire", [False, True])
def test_provider_commands_are_bounded_and_timeout_stops_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expire: bool
) -> None:
    _bundle(tmp_path / "bundle")
    tools = tmp_path / "tools"
    tools.mkdir()
    shim = tools / "timeout"
    shim.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
assert arguments[:2] == ["--signal=TERM", "--kill-after=15"]
limit = int(arguments[2])
assert 0 < limit <= (300 if arguments[4] == "init" else 600)
with Path(os.environ["FAKE_TIMEOUT_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(arguments) + "\n")
if os.environ["FAKE_TIMEOUT_EXPIRE"] == "1":
    sys.exit(124)
os.execv(arguments[3], arguments[3:])
""",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    timeout_log = tmp_path / "timeout.jsonl"
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_TIMEOUT_LOG", str(timeout_log))
    monkeypatch.setenv("FAKE_TIMEOUT_EXPIRE", "1" if expire else "0")

    result = _run(tmp_path)

    assert result.returncode == (124 if expire else 0), result.stderr
    assert len(timeout_log.read_text().splitlines()) == (1 if expire else 2 * len(ROOTS))
    assert not (tmp_path / "mirror-src").exists()
    if expire:
        assert not (tmp_path / "commands.jsonl").exists()
