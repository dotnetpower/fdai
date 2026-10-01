"""Compatibility module for the shared semantic question-form contract."""

from __future__ import annotations

import sys

from fdai_service_contracts import semantic_question_form as _shared

sys.modules[__name__] = _shared
