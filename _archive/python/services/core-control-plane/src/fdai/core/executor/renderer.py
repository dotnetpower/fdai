"""Remediation-template renderer.

Given a rule + an executor input (action params), load the template file
referenced by ``rule.remediation.template_ref`` and substitute ``${...}``
placeholders. The output is a pure string that the delivery adapter
attaches to a shadow-mode PR.

Substitution semantics
----------------------

- **Only** ``${name}`` placeholders are substituted (``string.Template``
  behavior). Missing placeholders raise :class:`RenderError`; the
  executor converts that into a fail-close abstain rather than a
  partial patch.
- **No shell / Python evaluation**. Templates never run untrusted code.
- **String values only**. A non-string value (a nested dict, a list) is
  rejected - the renderer refuses to guess a JSON serialization that
  might diverge from what the reviewer expects to see in the PR.
- **Path safety**. The renderer refuses references outside its
  ``remediation_root`` (absolute paths and ``..`` traversal) even if
  the loader already validated the rule, so the executor is safe to
  call on an unvalidated in-memory rule (e.g. a test fixture).

Rationale
---------

Terraform / IaC patches ship as data (see
[`rule-catalog/remediation/`](../../../../rule-catalog/remediation/README.md));
substitution keeps them declarative - the renderer's only job is safe
interpolation, so a future non-Terraform template dialect (Bicep, K8s
YAML) plugs in via a different :attr:`RenderRequest.template_ref` root
without touching this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Final

from fdai.shared.contracts.models import Rule


class RenderError(RuntimeError):
    """Raised when a template cannot be rendered fail-closed."""


@dataclass(frozen=True, slots=True)
class RenderRequest:
    """Everything the renderer needs for one call.

    Frozen so a caller cannot rewrite the request between rendering and
    publishing (audit-log invariant: the rendered patch always matches
    the audited request).
    """

    rule: Rule
    resource_id: str
    """CSP-neutral resource id from the inventory graph."""

    params: dict[str, Any]
    """``Action.params`` - placeholder values keyed by placeholder name.

    Merged with the rule's ``parameters`` block (per-assignment defaults).
    Action params win on conflict; both maps MUST NOT contain secrets.
    """


class TemplateRenderer:
    """Load + substitute + validate remediation templates."""

    _MAX_TEMPLATE_BYTES: Final[int] = 64 * 1024
    """Defense in depth: refuse to load a runaway template."""

    def __init__(self, *, remediation_root: Path) -> None:
        if not remediation_root.is_dir():
            raise ValueError(
                f"remediation_root MUST be an existing directory; got {remediation_root!r}"
            )
        self._root: Final[Path] = remediation_root.resolve()

    def render(self, request: RenderRequest) -> str:
        template_ref = request.rule.remediation.template_ref
        template_path = self._resolve_template_path(template_ref)
        template_text = self._read_template(template_path, template_ref)

        # Order matters: per-rule authored defaults FIRST, per-action
        # params LAST so an action override wins. Plus a builtin
        # `resource_id` slot every template may quote.
        merged: dict[str, str] = {"resource_id": request.resource_id}
        for key, value in request.rule.parameters.items():
            merged[key] = _stringify(key, value)
        for key, value in request.params.items():
            merged[key] = _stringify(key, value)

        try:
            return Template(template_text).substitute(merged)
        except KeyError as exc:
            missing = exc.args[0] if exc.args else "?"
            raise RenderError(
                f"template {template_ref!r} references undefined placeholder {missing!r}"
            ) from exc
        except ValueError as exc:
            raise RenderError(
                f"template {template_ref!r} contains an invalid placeholder syntax: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _resolve_template_path(self, template_ref: str) -> Path:
        if not template_ref.startswith("remediation/"):
            raise RenderError(f"template_ref {template_ref!r} MUST start with 'remediation/'")
        relative = Path(template_ref[len("remediation/") :])
        if relative.is_absolute() or ".." in relative.parts:
            raise RenderError(f"template_ref {template_ref!r} MUST be repo-relative without '..'")
        # Extra guard: the resolved path stays inside the root.
        resolved = (self._root / relative).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise RenderError(f"template_ref {template_ref!r} escaped remediation_root") from exc
        return resolved

    def _read_template(self, path: Path, template_ref: str) -> str:
        if not path.is_file():
            raise RenderError(f"remediation template not found: {template_ref!r}")
        size = path.stat().st_size
        if size > self._MAX_TEMPLATE_BYTES:
            raise RenderError(
                f"remediation template {template_ref!r} exceeds "
                f"{self._MAX_TEMPLATE_BYTES} bytes; reject as untrusted"
            )
        return path.read_text(encoding="utf-8")


def _stringify(key: str, value: Any) -> str:
    """Force placeholder values to a scalar string; reject nested types."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        # `bool` is-a `int`, but we want the literal `true`/`false` in
        # Terraform, not Python's `True`/`False`.
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    raise RenderError(
        f"placeholder {key!r} MUST be a scalar (str/int/float/bool); got {type(value).__name__}"
    )


__all__ = [
    "RenderError",
    "RenderRequest",
    "TemplateRenderer",
]
