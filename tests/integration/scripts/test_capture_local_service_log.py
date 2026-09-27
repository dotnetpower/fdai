"""The plain local-service log keeps only allowlisted diagnostic fields."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "automation" / "capture-local-service-log.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capture_local_service_log", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_preflight_rejection_reason_reaches_the_plain_log() -> None:
    module = _load_module()
    line = json.dumps(
        {
            "level": "INFO",
            "logger": "fdai.core.conversation.conversation_preflight",
            "message": "conversation_preflight_operational_promotion_rejected",
            "promotion_rejection_reason": "family_absent",
            "reason": "unlisted free text",
        }
    )

    rendered = module._render_line(line, "json-plain")

    assert rendered == (
        "INFO: fdai.core.conversation.conversation_preflight: "
        "conversation_preflight_operational_promotion_rejected "
        '[promotion_rejection_reason="family_absent"]'
    )


def test_raw_format_keeps_the_original_line() -> None:
    module = _load_module()
    line = json.dumps({"level": "INFO", "logger": "x", "message": "y", "reason": "kept raw"})

    assert module._render_line(line + "\n", "raw") == line
