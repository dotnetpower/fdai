#!/usr/bin/env python3
"""Check and run one official CyberGym-E2E task with FDAI boundaries."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmarking.cybergym_runtime import (
    CyberGymDockerRuntime,
    CyberGymPaths,
    CyberGymRuntimeError,
    load_task,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run-cybergym")
    parser.add_argument("command", choices=("check", "run"))
    parser.add_argument("task", help="Official project/task path, for example curl/arvo_66012")
    parser.add_argument("--mode", choices=("e2e", "patch-only"), default="e2e")
    parser.add_argument(
        "--harness-root",
        type=Path,
        default=_environment_path("CYBERGYM_E2E_ROOT"),
        help="CyberGym-E2E Git checkout; defaults to CYBERGYM_E2E_ROOT",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=_environment_path("CYBERGYM_DATA_ROOT"),
        help="Downloaded dataset projects directory; defaults to CYBERGYM_DATA_ROOT",
    )
    parser.add_argument("--output-root", type=Path, default=Path(".fdai/cybergym"))
    parser.add_argument("--copilot-root", type=Path, default=None)
    parser.add_argument("--agent-timeout", type=int, default=5_400)
    parser.add_argument("--validation-timeout", type=int, default=7_200)
    return parser


def _environment_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser().resolve() if value else None


def _copilot_root(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    expected = Path("lib/node_modules/@github/copilot/npm-loader.js")
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        executable = Path(directory) / "copilot"
        if not executable.is_file():
            continue
        resolved = executable.resolve()
        for parent in resolved.parents:
            if resolved == parent / expected:
                return parent
    raise CyberGymRuntimeError(
        "Copilot CLI npm installation could not be inferred; pass --copilot-root"
    )


def _required_root(value: Path | None, option: str, environment: str) -> Path:
    if value is None:
        raise CyberGymRuntimeError(f"{option} or {environment} is required")
    return value.expanduser().resolve(strict=True)


def _composition(args: argparse.Namespace) -> tuple[CyberGymDockerRuntime, CyberGymPaths]:
    paths = CyberGymPaths(
        harness_root=_required_root(args.harness_root, "--harness-root", "CYBERGYM_E2E_ROOT"),
        data_root=_required_root(args.data_root, "--data-root", "CYBERGYM_DATA_ROOT"),
        output_root=args.output_root.expanduser().resolve(),
        copilot_root=_copilot_root(args.copilot_root),
    )
    return (
        CyberGymDockerRuntime(
            paths=paths,
            agent_timeout_seconds=args.agent_timeout,
            validation_timeout_seconds=args.validation_timeout,
        ),
        paths,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        runtime, paths = _composition(args)
        if args.command == "check":
            checks = runtime.readiness(args.task, mode=args.mode)
            payload = {
                "adapter_id": "cybergym",
                "task_path": args.task,
                "ready": all(checks.values()),
                "checks": checks,
                "shadow_only": True,
            }
            print(json.dumps(payload, sort_keys=True))
            return 0 if payload["ready"] else 2
        result = runtime.run(load_task(paths, args.task, mode=args.mode))
        print(json.dumps(result, sort_keys=True))
        return 0 if result["success"] else 1
    except Exception as exc:  # noqa: BLE001 - process boundary hides sensitive detail
        print(
            json.dumps(
                {
                    "adapter_id": "cybergym",
                    "ready": False,
                    "reason_code": "cybergym_runner_failed",
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
