"""Trusted source for the minimal isolated pipeline child process."""

CHILD_RUNTIME_SOURCE = r"""from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import resource
import sys


def _limit_resources() -> None:
    cpu_seconds = int(os.environ["FDAI_PIPELINE_CPU_SECONDS"])
    memory_bytes = int(os.environ["FDAI_PIPELINE_MEMORY_BYTES"])
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))


def _load_pipeline():
    pipeline_path = os.path.join(os.environ["FDAI_PIPELINE_SOURCE_DIR"], "pipeline.py")
    spec = importlib.util.spec_from_file_location("reviewed_pipeline", pipeline_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("reviewed pipeline could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    _limit_resources()
    sys.path.insert(0, os.environ["FDAI_PIPELINE_SOURCE_DIR"])
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        from fdai_pipeline_client import PipelineClient

        module = _load_pipeline()
        inputs = [json.loads(value) for value in json.loads(os.environ["FDAI_PIPELINE_INPUTS"])]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = module.main(PipelineClient(), inputs)
        final_json = json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        envelope = {
            "status": "succeeded",
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "final_json": final_json,
        }
    except BaseException as exc:
        envelope = {
            "status": "failed",
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "final_json": None,
            "detail": type(exc).__name__,
        }
    sys.stdout.write(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
    return 0 if envelope["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
"""


__all__ = ["CHILD_RUNTIME_SOURCE"]
