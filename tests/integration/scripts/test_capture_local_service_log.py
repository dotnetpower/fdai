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


def test_form_path_decision_fields_reach_the_plain_log_as_closed_tokens() -> None:
    module = _load_module()
    line = json.dumps(
        {
            "level": "INFO",
            "logger": "fdai.core.conversation.semantic_compiled_answers",
            "message": "semantic_form_sample_declined",
            "result": "declined",
            "decline_reason": "not_released",
            "released": False,
            "review": "unfaithful",
            "review_reasons": ["review_uncovered:resource_type", "free text, not a token"],
            "pass_dispositions": ["invalid"],
            "model_calls": 3,
            "unlisted": "dropped",
        }
    )

    rendered = module._render_line(line, "json-plain")

    assert rendered == (
        "INFO: fdai.core.conversation.semantic_compiled_answers: semantic_form_sample_declined "
        '[result="declined", decline_reason="not_released", released=false, '
        'review="unfaithful", review_reasons=["review_uncovered:resource_type","~"], '
        'pass_dispositions=["invalid"], model_calls=3]'
    )


def test_decision_fields_stay_hidden_for_other_loggers() -> None:
    module = _load_module()
    line = json.dumps(
        {
            "level": "INFO",
            "logger": "fdai.other",
            "message": "event",
            "result": "free text result",
            "decision": "deny",
        }
    )

    assert module._render_line(line, "json-plain") == "INFO: fdai.other: event"


def test_free_text_scalar_is_not_rendered_for_the_scoped_logger() -> None:
    module = _load_module()
    line = json.dumps(
        {
            "level": "INFO",
            "logger": "fdai.core.conversation.semantic_compiled_answers",
            "message": "semantic_typed_only_outcome",
            "reason": "semantic reading unverified because of free text",
            "decision": "unverified",
        }
    )

    assert module._render_line(line, "json-plain") == (
        "INFO: fdai.core.conversation.semantic_compiled_answers: semantic_typed_only_outcome "
        '[decision="unverified"]'
    )
