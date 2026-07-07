"""Rego overlay writer for ``governance.override-ceiling`` - Wave M1.4.

Emits a time-boxed Rego fragment an Owner uses to narrow (never raise)
the RiskGate ceiling for a bounded scope. The fragment lives at
``policies/action_types/<action_type_id>/<override_id>.rego`` and joins
the four-tier overlay precedence in
[action-ontology.md § 7.5](../../../../docs/roadmap/action-ontology.md#75-precedence)
at the Rego layer (tier 2, above the file overlay and below the runtime
governance action).

Design invariants
-----------------

- **Never raises autonomy**: ``target_level`` MUST be ``enforce_hil``
  or ``shadow_only`` - matches the JSON schema on the ActionType YAML
  ([rule-catalog/action-types/governance.override-ceiling.yaml](../../../../rule-catalog/action-types/governance.override-ceiling.yaml)).
- **Bounded scope**: ``scope`` MUST be ``resource`` or
  ``resource-group``. Organization-wide overrides are rejected;
  disabling a rule everywhere is a rule retirement, not an override
  ([architecture.instructions.md](../../../../.github/instructions/architecture.instructions.md)).
- **Time-boxed**: ``expires_at`` is required; the writer surfaces it
  in the fragment metadata so an OPA policy loader can hard-gate the
  overlay after expiry.
- **No self-approval**: the writer records ``approver_id`` distinct
  from ``requester_id``.
- **Pure**: this module renders a Rego document string; it does not
  touch the filesystem. The caller (composition root / delivery
  adapter) opens a PR containing the file (matches the
  ``execution_path: pr_native`` contract).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

# The five axes are the ones declared by governance.override-ceiling's
# argument_schema (see the YAML). Duplicated here so we can validate
# without loading the whole ActionType catalog.
_ALLOWED_AXES: frozenset[str] = frozenset({"ceiling", "role", "env", "static_blast", "live_blast"})

_ALLOWED_SCOPES: frozenset[str] = frozenset({"resource", "resource-group"})

# The target level enum from action-ontology + execution-model. Never
# includes ``enforce_auto`` - the override can only narrow autonomy.
_ALLOWED_TARGET_LEVELS: frozenset[str] = frozenset({"enforce_hil", "shadow_only"})

# Bounded ``action_type_id`` pattern (matches OntologyActionType.name).
_ACTION_TYPE_ID_MAX_LEN: int = 80


class OverrideWriterError(ValueError):
    """Raised when the input violates an override invariant."""


class Axis(StrEnum):
    CEILING = "ceiling"
    ROLE = "role"
    ENV = "env"
    STATIC_BLAST = "static_blast"
    LIVE_BLAST = "live_blast"


class TargetLevel(StrEnum):
    ENFORCE_HIL = "enforce_hil"
    SHADOW_ONLY = "shadow_only"


class Scope(StrEnum):
    RESOURCE = "resource"
    RESOURCE_GROUP = "resource-group"


@dataclass(frozen=True, slots=True)
class OverrideRequest:
    """One override candidate + metadata for the audit chain."""

    override_id: str
    action_type_id: str
    axis: Axis
    target_level: TargetLevel
    scope: Scope
    scope_ref: str
    expires_at: str
    justification: str
    requester_id: str
    approver_id: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RegoOverlay:
    """Rendered artifact + suggested filesystem path.

    ``path`` is a repo-relative POSIX path the caller writes the
    ``content`` to inside a PR. The writer never touches disk.
    """

    path: str
    content: str


def render_override_rego(request: OverrideRequest) -> RegoOverlay:
    """Return the Rego fragment + suggested repo path for one request.

    Fails-closed: any invariant violation raises
    :class:`OverrideWriterError` before any string is rendered.
    """

    _validate(request)

    package = _package_name(request)
    path = (
        f"policies/action_types/{_slugify(request.action_type_id)}/"
        f"{_slugify(request.override_id)}.rego"
    )

    content = _render(request=request, package=package)
    return RegoOverlay(path=path, content=content)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(request: OverrideRequest) -> None:
    if not request.override_id:
        raise OverrideWriterError("override_id MUST be non-empty")
    if ".." in request.override_id:
        raise OverrideWriterError("override_id MUST NOT contain '..' (path traversal)")
    if not request.action_type_id:
        raise OverrideWriterError("action_type_id MUST be non-empty")
    if len(request.action_type_id) > _ACTION_TYPE_ID_MAX_LEN:
        raise OverrideWriterError(f"action_type_id MUST be at most {_ACTION_TYPE_ID_MAX_LEN} chars")
    # The pattern check matches OntologyActionType.name; keep this loose
    # rather than reimport the full pydantic model.
    if not _is_ontology_id(request.action_type_id):
        raise OverrideWriterError(
            f"action_type_id {request.action_type_id!r} MUST match ^[a-z][a-z0-9_.-]*"
        )
    if request.axis.value not in _ALLOWED_AXES:
        raise OverrideWriterError(f"axis {request.axis!r} not in the ceiling override axis set")
    if request.target_level.value not in _ALLOWED_TARGET_LEVELS:
        raise OverrideWriterError(
            "target_level MUST be enforce_hil or shadow_only (override never raises autonomy)"
        )
    if request.scope.value not in _ALLOWED_SCOPES:
        raise OverrideWriterError(
            "scope MUST be resource or resource-group; org-wide overrides are prohibited"
        )
    if not request.scope_ref.strip():
        raise OverrideWriterError("scope_ref MUST be non-empty")
    _validate_iso_expiry(request.expires_at)
    if len(request.justification) < 20:
        raise OverrideWriterError("justification MUST be at least 20 chars")
    if len(request.justification) > 500:
        raise OverrideWriterError("justification MUST be at most 500 chars")
    if not request.requester_id:
        raise OverrideWriterError("requester_id MUST be non-empty")
    if not request.approver_id:
        raise OverrideWriterError("approver_id MUST be non-empty")
    if request.requester_id == request.approver_id:
        raise OverrideWriterError("no self-approval - requester_id and approver_id MUST differ")


def _validate_iso_expiry(value: str) -> None:
    if not value:
        raise OverrideWriterError("expires_at MUST be non-empty")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise OverrideWriterError(f"expires_at MUST be ISO-8601: {exc}") from exc


def _is_ontology_id(value: str) -> bool:
    if not value:
        return False
    if not (value[0].isalpha() and value[0].islower()):
        return False
    return all(c.isalnum() or c in {"_", ".", "-"} for c in value)


# ---------------------------------------------------------------------------
# Rego rendering
# ---------------------------------------------------------------------------


def _render(*, request: OverrideRequest, package: str) -> str:
    lines = [
        "# METADATA",
        "# title: Ceiling override overlay",
        "# description: |",
        f"#   Time-boxed override for {request.action_type_id!r}.",
        f"#   Narrows the {request.axis.value} axis to {request.target_level.value}",
        f"#   on scope kind={request.scope.value}, ref={_escape_comment(request.scope_ref)}.",
        f"#   Expires: {request.expires_at}.",
        f"#   Justification: {_escape_comment(request.justification)}",
        "# custom:",
        f"#   override_id: {request.override_id}",
        f"#   action_type_id: {request.action_type_id}",
        f"#   axis: {request.axis.value}",
        f"#   target_level: {request.target_level.value}",
        f"#   scope: {request.scope.value}",
        f"#   scope_ref: {_escape_comment(request.scope_ref)}",
        f"#   expires_at: {request.expires_at}",
        f"#   requester_id: {request.requester_id}",
        f"#   approver_id: {request.approver_id}",
        f"package {package}",
        "",
        "import rego.v1",
        "",
        "# Applicability guard - the RiskGate MUST evaluate `applies` before",
        "# consuming `verdict`. When `applies` is false the overlay does",
        "# not contribute; the pre-override ceiling stands.",
        "default applies := false",
        "",
        "applies if {",
        f'  input.action_type == "{request.action_type_id}"',
        f'  input.scope.kind == "{request.scope.value}"',
        f'  input.scope.ref == "{_rego_string(request.scope_ref)}"',
        f'  input.now <= "{request.expires_at}"',
        "}",
        "",
        "verdict := {",
        f'  "axis": "{request.axis.value}",',
        f'  "level": "{request.target_level.value}",',
        f'  "override_id": "{request.override_id}",',
        f'  "expires_at": "{request.expires_at}",',
        "} if applies",
        "",
    ]
    return "\n".join(lines)


def _package_name(request: OverrideRequest) -> str:
    """Rego package: ``aiopspilot.action_types.<slug>.<override_slug>``.

    OPA package identifiers use dot-separated lower-case segments; we
    map ``.`` and ``-`` in the ontology id to ``_`` so the identifier
    is valid.
    """

    at_id = _package_slug(request.action_type_id)
    ovr_id = _package_slug(request.override_id)
    return f"aiopspilot.action_types.{at_id}.{ovr_id}"


def _package_slug(value: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in value)


def _slugify(value: str) -> str:
    """Filesystem-safe slug: alphanumerics + [-._] pass through, others become '_'."""

    return "".join(c if c.isalnum() or c in {"-", "_", "."} else "_" for c in value)


def _escape_comment(value: str) -> str:
    """Trim a value so it fits on one Rego comment line."""

    cleaned = value.replace("\n", " ").replace("\r", " ").strip()
    if len(cleaned) > 200:
        return cleaned[:197] + "..."
    return cleaned


def _rego_string(value: str) -> str:
    """Escape a value for use inside a Rego double-quoted string."""

    return value.replace("\\", "\\\\").replace('"', '\\"')


__all__ = [
    "Axis",
    "OverrideRequest",
    "OverrideWriterError",
    "RegoOverlay",
    "Scope",
    "TargetLevel",
    "render_override_rego",
]
