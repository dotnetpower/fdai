#!/usr/bin/env python3
"""Read-only identities for verify.sh's explicitly cacheable local pure gates.

This helper never runs checks, installs dependencies, or grants a pass. Callers
must bind gate name and exact argv to the returned identity, retain successful
receipts only, and recheck context before accepting cached outcomes or publishing
new receipts. Unknown, external, or authority-bearing gates remain uncached.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.local_validation_inputs import (  # noqa: E402
    TOOLS,
    dependency_digest,
    digest,
    git,
    installed_digest,
    tracked_snapshot,
)


def _checked_environment(root: Path, environment: dict[str, str]) -> Path:
    if any(environment.get(name, "").lower() in {"true", "1"} for name in ("CI", "GITHUB_ACTIONS")):
        raise ValueError("local cache cannot satisfy CI")
    if environment.get("UV_NO_SYNC") != "1" or environment.get("UV_NO_CONFIG") != "1":
        raise ValueError("cache requires frozen uv execution without external uv configuration")
    if environment.get("PYTHONNOUSERSITE") != "1":
        raise ValueError("cache requires Python user-site isolation")
    if any(environment.get(name) for name in ("BASH_ENV", "ENV", "PYTHONHOME", "NODE_PATH")):
        raise ValueError("unbounded external code inputs")
    for name in ("PYTHONPATH", "MYPYPATH"):
        for item in environment.get(name, "").split(os.pathsep):
            if item and not (root / item).resolve().is_relative_to(root):
                raise ValueError("external source path cannot certify this checkout")
    venv = Path(environment.get("UV_PROJECT_ENVIRONMENT", str(root / ".venv")))
    if not venv.is_absolute():
        venv = root / venv
    venv = Path(os.path.abspath(venv))
    configuration = (venv / "pyvenv.cfg").read_text(encoding="utf-8")
    if "include-system-site-packages = false" not in configuration:
        raise ValueError("unverified system Python packages")
    for path in venv.rglob("direct_url.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("invalid installed source metadata")
        directory = record.get("dir_info")
        if isinstance(directory, dict) and directory.get("editable") is True:
            source = urlparse(str(record.get("url", "")))
            if source.scheme != "file" or not Path(unquote(source.path)).resolve().is_relative_to(
                root
            ):
                raise ValueError("editable dependency points outside this committed checkout")
    return venv


def _no_untracked_inputs(root: Path, venv: Path) -> None:
    # Include ignored files: ignored local models and generated source are inputs,
    # not proof of a clean committed tree. Only the separately hashed venv is exempt.
    for raw_path in git(root, "ls-files", "--others", "-z").split(b"\0"):
        if raw_path and not (root / os.fsdecode(raw_path)).is_relative_to(venv):
            raise ValueError("untracked or ignored local inputs disable gate reuse")
    git(root, "diff-index", "--quiet", "--cached", "HEAD", "--")


def validation_context(
    root: Path,
    *,
    revisions: str | None = None,
    tools: tuple[str, ...] = TOOLS,
    environment: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return content/history keys for a clean, locally frozen execution context.

    The content key excludes commit metadata. History-dependent gates must use
    the history key and pass their comparison revision expression explicitly.
    All inherited environment values are hashed, never returned. This deliberately
    favors misses over reusing an unproven external dependency or dirty checkout.
    """
    root = root.resolve()
    environment = dict(os.environ if environment is None else environment)
    venv = _checked_environment(root, environment)
    _no_untracked_inputs(root, venv)
    tree, files = tracked_snapshot(root)
    tool_inputs = {}
    for name in tools:
        executable = shutil.which(name, path=environment.get("PATH", os.defpath))
        if executable is None:
            raise ValueError(f"required tool is missing: {name}")
        resolved = Path(executable).resolve()
        tool_inputs[name] = (str(resolved), hashlib.sha256(resolved.read_bytes()).hexdigest())
    common = Path(git(root, "rev-parse", "--git-common-dir").decode().strip())
    if not common.is_absolute():
        common = root / common
    local_git_inputs = {
        relative: hashlib.sha256((common / relative).read_bytes()).hexdigest()
        if (common / relative).is_file()
        else None
        for relative in ("info/exclude", "info/attributes", "info/grafts", "shallow")
    }
    configuration = git(root, "config", "--null", "--list")
    for entry in configuration.split(b"\0"):
        config_name, _, raw_value = entry.partition(b"\n")
        if config_name.lower() in {b"core.excludesfile", b"core.attributesfile"}:
            path = Path(os.fsdecode(raw_value)).expanduser()
            if not path.is_absolute():
                path = root / path
            local_git_inputs[os.fsdecode(config_name)] = (
                hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            )
    content = digest(
        {
            "schema_version": 1,
            "scope": "local-pure-gate",
            "tree": tree,
            "dependency": dependency_digest(files),
            "installed": installed_digest(venv),
            "tools": tool_inputs,
            "environment": environment,
            "platform": platform.platform(),
            "git_config": configuration.hex(),
            "local_git_inputs": local_git_inputs,
        }
    )
    resolved_revisions = git(
        root,
        "rev-parse",
        "--revs-only",
        "--end-of-options",
        revisions or "HEAD",
    ).decode()
    if not resolved_revisions.strip():
        raise ValueError("comparison revisions could not be resolved")
    history = digest(
        {
            "content": content,
            "head": git(root, "rev-parse", "--verify", "HEAD").decode().strip(),
            "revisions": resolved_revisions,
            "refs": git(root, "show-ref").decode(),
        }
    )
    return {"content": content, "history": history}


def main() -> int:
    """Print JSON identities, or fail without a key when reuse is not justified."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", help="Exact Git comparison expression used by history gates")
    parser.add_argument("--format", choices=("json", "keys"), default="json")
    parser.add_argument(
        "--tool", action="append", default=[], help="Additional required executable"
    )
    arguments = parser.parse_args()
    try:
        context = validation_context(
            Path.cwd(),
            revisions=arguments.history,
            tools=tuple(dict.fromkeys((*TOOLS, *arguments.tool))),
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        print("local-validation-context: unavailable; run gates without cache", file=sys.stderr)
        return 1
    if arguments.format == "keys":
        print(context["content"], context["history"])
    else:
        print(json.dumps(context, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
