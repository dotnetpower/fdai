"""Grounded, non-executing code artifacts extracted from narrator answers."""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass

_FENCE = re.compile(
    r"^[ \t]*```(?P<language>[A-Za-z0-9_+#.-]*)[ \t]*\n"
    r"(?P<content>.*?)"
    r"^[ \t]*```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
_PYTHON_LANGUAGES = frozenset({"py", "python", "python3"})
_PRESENTATION_LANGUAGES = frozenset({"chart"})


@dataclass(frozen=True, slots=True)
class GroundedCodePolicy:
    """Bound code copied from one untrusted narrator answer."""

    max_artifacts: int = 8
    max_artifact_bytes: int = 64 * 1024
    max_total_bytes: int = 128 * 1024

    def __post_init__(self) -> None:
        if self.max_artifacts < 1:
            raise ValueError("max_artifacts MUST be positive")
        if self.max_artifact_bytes < 1:
            raise ValueError("max_artifact_bytes MUST be positive")
        if self.max_total_bytes < self.max_artifact_bytes:
            raise ValueError("max_total_bytes MUST be at least max_artifact_bytes")


@dataclass(frozen=True, slots=True)
class GroundedCodeArtifact:
    """One inert code block with deterministic provenance and validation."""

    artifact_ref: str
    language: str
    content: str
    sha256: str
    validation_status: str
    validation_detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_ref": self.artifact_ref,
            "language": self.language,
            "content": self.content,
            "sha256": self.sha256,
            "validation_status": self.validation_status,
            "validation_detail": self.validation_detail,
        }


def extract_grounded_code(
    answer: str,
    *,
    policy: GroundedCodePolicy | None = None,
) -> tuple[GroundedCodeArtifact, ...]:
    """Extract bounded fenced code without importing or executing it."""

    resolved = policy or GroundedCodePolicy()
    artifacts: list[GroundedCodeArtifact] = []
    total_bytes = 0
    for match in _FENCE.finditer(answer):
        if len(artifacts) >= resolved.max_artifacts:
            break
        language = match.group("language").lower() or "text"
        if language in _PRESENTATION_LANGUAGES:
            continue
        content = match.group("content")
        encoded_bytes = len(content.encode("utf-8"))
        if encoded_bytes > resolved.max_artifact_bytes:
            continue
        if total_bytes + encoded_bytes > resolved.max_total_bytes:
            break
        total_bytes += encoded_bytes
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        status, detail = _validate(language, content)
        artifacts.append(
            GroundedCodeArtifact(
                artifact_ref=f"code:sha256:{digest}",
                language=language,
                content=content,
                sha256=digest,
                validation_status=status,
                validation_detail=detail,
            )
        )
    return tuple(artifacts)


def _validate(language: str, content: str) -> tuple[str, str | None]:
    if language not in _PYTHON_LANGUAGES:
        return "not_checked", None
    try:
        tree = ast.parse(content, filename="<grounded-code>")
        compile(tree, "<grounded-code>", "exec")
    except (SyntaxError, ValueError) as exc:
        return "invalid", _syntax_detail(exc)
    return "valid", None


def _syntax_detail(exc: SyntaxError | ValueError) -> str:
    if isinstance(exc, SyntaxError):
        location = f"line {exc.lineno}" if exc.lineno is not None else "unknown line"
        return f"{location}: {exc.msg}"
    return str(exc)


__all__ = [
    "GroundedCodeArtifact",
    "GroundedCodePolicy",
    "extract_grounded_code",
]
