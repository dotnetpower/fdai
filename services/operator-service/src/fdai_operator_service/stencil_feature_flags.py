"""Fail-closed Stencil feature-flag enforcement for deactivated Console menus and loops.

Responsibility:
Parse Stencil menu/loop feature flags and block HTTP requests to deactivated Operator surfaces.

Boundary:
Wrap the non-privileged Operator ASGI application and evaluate request paths before route dispatch.

Authority and state:
Hold immutable startup feature-flag state only; never grant execution, approval, or RBAC authority.

Dependencies:
Use standard-library parsing and Starlette JSONResponse/ASGI primitives only.

Deployment:
Run inside the non-privileged Operator Service container when Stencil env flags are configured.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fdai_operator_service.contracts import AsgiApplication

STENCIL_FEATURE_FLAGS_SCHEMA: Final[Literal["fdai.stencil-feature-flags.v1"]] = (
    "fdai.stencil-feature-flags.v1"
)
LOCKED_STENCIL_PANELS: Final[frozenset[str]] = frozenset({"audit", "dashboard", "settings-general"})
LOCKED_STENCIL_LOOPS: Final[frozenset[str]] = frozenset(
    {
        "anomaly-analyzer",
        "inventory-reconciliation",
        "notification-dispatch",
        "saga-audit",
    }
)

_KEBAB_ID_RE: Final = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\Z", re.ASCII)
_STENCIL_ID_RE: Final = re.compile(r"^[a-z][a-z0-9-]{0,62}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class StencilRouteRule:
    """Bind an Operator HTTP path prefix or exact path to required Console panels and loops."""

    prefix: str
    exact: bool
    any_panels: tuple[str, ...] = ()
    required_loops: tuple[str, ...] = ()


STENCIL_ROUTE_RULES: Final[tuple[StencilRouteRule, ...]] = (
    StencilRouteRule("/aks-commerce", exact=False, any_panels=("aks-commerce",)),
    StencilRouteRule(
        "/cost-governance",
        exact=False,
        any_panels=("cost-governance",),
        required_loops=("cost-governance",),
    ),
    StencilRouteRule(
        "/code-security",
        exact=False,
        any_panels=("code-security",),
        required_loops=("code-security",),
    ),
    StencilRouteRule(
        "/assurance-twin",
        exact=False,
        any_panels=("assurance-twin",),
        required_loops=("assurance-twin",),
    ),
    StencilRouteRule(
        "/hil-queue",
        exact=False,
        any_panels=("hil-queue",),
        required_loops=("remediation-execution",),
    ),
    StencilRouteRule(
        "/hil",
        exact=False,
        any_panels=("hil-queue",),
        required_loops=("remediation-execution",),
    ),
    StencilRouteRule("/rca", exact=False, any_panels=("rca",)),
    StencilRouteRule("/reports", exact=False, any_panels=("reports",)),
    StencilRouteRule("/browser-evidence", exact=False, any_panels=("browser-evidence",)),
    StencilRouteRule("/kpi/llm-cost", exact=True, any_panels=("llm-cost",)),
    StencilRouteRule(
        "/kpi/autonomy",
        exact=True,
        any_panels=("operating-outcomes", "trust-routing"),
    ),
    StencilRouteRule(
        "/kpi/outcome-assurance",
        exact=True,
        any_panels=("control-assurance", "operating-outcomes"),
    ),
    StencilRouteRule("/capabilities", exact=True, any_panels=("capabilities",)),
    StencilRouteRule(
        "/configuration-baselines",
        exact=True,
        any_panels=("configuration-baselines",),
    ),
    StencilRouteRule(
        "/conversation-delivery",
        exact=True,
        any_panels=("conversation-delivery",),
    ),
    StencilRouteRule("/forecast-learning", exact=True, any_panels=("forecast-learning",)),
    StencilRouteRule(
        "/onboarding",
        exact=True,
        any_panels=("onboarding", "settings-environment"),
    ),
    StencilRouteRule("/operator-memory", exact=True, any_panels=("settings-memory",)),
    StencilRouteRule("/scheduler-runs", exact=True, any_panels=("scheduler-runs",)),
    StencilRouteRule("/skills", exact=True, any_panels=("skills",)),
    StencilRouteRule("/scope", exact=True, any_panels=("scope",)),
    StencilRouteRule("/simulate/blast-radius", exact=True, any_panels=("blast-radius",)),
    StencilRouteRule("/stewardship", exact=False, any_panels=("handover",)),
    StencilRouteRule("/handover", exact=False, any_panels=("handover",)),
    StencilRouteRule("/assignments", exact=False, any_panels=("handover",)),
    StencilRouteRule("/scoped-duties", exact=False, any_panels=("handover",)),
    StencilRouteRule("/reporting-lines", exact=False, any_panels=("handover",)),
    StencilRouteRule(
        "/automation-blueprints",
        exact=False,
        any_panels=("automation-blueprints",),
    ),
    StencilRouteRule("/views/workflow-apps", exact=True, any_panels=("workflow-apps",)),
    StencilRouteRule("/views/process", exact=False, any_panels=("processes",)),
    StencilRouteRule(
        "/workflows",
        exact=False,
        any_panels=("workflow-builder", "processes"),
    ),
    StencilRouteRule(
        "/context-selection-comparisons",
        exact=True,
        any_panels=("context-selection-comparisons",),
    ),
    StencilRouteRule(
        "/knowledge/github/sources",
        exact=True,
        any_panels=("github", "knowledge"),
    ),
    StencilRouteRule(
        "/ontology",
        exact=False,
        any_panels=("ontology", "architecture"),
    ),
    StencilRouteRule(
        "/inventory/graph",
        exact=True,
        any_panels=("architecture", "ontology", "live"),
    ),
    StencilRouteRule(
        "/pantheon",
        exact=False,
        any_panels=("pantheon", "agents"),
    ),
    StencilRouteRule(
        "/agents",
        exact=False,
        any_panels=("agent-activity", "agents", "pantheon"),
    ),
    StencilRouteRule("/alert-quality", exact=False, any_panels=("alert-quality",)),
    StencilRouteRule(
        "/detection-coverage",
        exact=True,
        any_panels=("detection-readiness",),
    ),
    StencilRouteRule(
        "/detection-readiness",
        exact=True,
        any_panels=("detection-readiness",),
    ),
    StencilRouteRule(
        "/incidents",
        exact=False,
        any_panels=("incidents", "live"),
    ),
    StencilRouteRule(
        "/live/stream",
        exact=True,
        any_panels=("live", "gpu"),
    ),
    StencilRouteRule(
        "/provision/stream",
        exact=True,
        any_panels=("provision", "settings-environment"),
    ),
    StencilRouteRule(
        "/observer-deployment-proposals",
        exact=True,
        any_panels=("provision", "settings-environment"),
    ),
    StencilRouteRule(
        "/policy-administration",
        exact=False,
        any_panels=("settings-runtime",),
    ),
)


@dataclass(frozen=True, slots=True)
class StencilRouteDecision:
    """Result of evaluating an Operator HTTP request path against active Stencil feature flags."""

    allowed: bool
    blocked_panels: tuple[str, ...] = ()
    blocked_loops: tuple[str, ...] = ()


def _parse_id_csv(raw: str, *, label: str) -> frozenset[str]:
    items: set[str] = set()
    for token in raw.split(","):
        cleaned = token.strip()
        if not cleaned:
            continue
        if _KEBAB_ID_RE.fullmatch(cleaned) is None:
            raise ValueError(f"Invalid {label} identifier: {cleaned!r}")
        items.add(cleaned)
    return frozenset(items)


def _validate_id_collection(values: Iterable[object], *, label: str) -> frozenset[str]:
    items: set[str] = set()
    for item in values:
        if not isinstance(item, str) or _KEBAB_ID_RE.fullmatch(item) is None:
            raise ValueError(f"Invalid {label} identifier: {item!r}")
        items.add(item)
    return frozenset(items)


@dataclass(frozen=True, slots=True)
class StencilFeatureFlagConfig:
    """Immutable Stencil feature-flag configuration parsed from environment or manifest JSON."""

    active: bool
    stencil_id: str | None = None
    enforcement_mode: Literal["fail-closed", "unscoped"] = "unscoped"
    enabled_panel_ids: frozenset[str] | None = None
    disabled_panel_ids: frozenset[str] = frozenset()
    enabled_loops: frozenset[str] | None = None
    disabled_loops: frozenset[str] = frozenset()

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> StencilFeatureFlagConfig:
        """Parse and validate Stencil feature-flag environment variables fail-closed."""

        raw_json = environ.get("FDAI_STENCIL_FEATURE_FLAGS_JSON", "").strip()
        raw_enabled_panels = environ.get("FDAI_STENCIL_ENABLED_PANELS", "").strip()
        raw_disabled_panels = environ.get("FDAI_STENCIL_DISABLED_PANELS", "").strip()
        raw_enabled_loops = environ.get("FDAI_STENCIL_ENABLED_LOOPS", "").strip()
        raw_disabled_loops = environ.get("FDAI_STENCIL_DISABLED_LOOPS", "").strip()
        raw_stencil_id = environ.get("FDAI_STENCIL_ID", "").strip()
        raw_enforce = environ.get("FDAI_STENCIL_ENFORCE_INACTIVE_MENUS", "").strip().lower()

        if (
            not raw_json
            and not raw_enabled_panels
            and not raw_disabled_panels
            and not raw_enabled_loops
            and not raw_disabled_loops
            and not raw_stencil_id
            and raw_enforce not in {"1", "true", "yes", "on"}
        ):
            return cls(active=False)

        stencil_id: str | None = None
        enabled_panels: set[str] | None = None
        disabled_panels: set[str] = set()
        enabled_loops: set[str] | None = None
        disabled_loops: set[str] = set()

        if raw_json:
            try:
                parsed = json.loads(raw_json)
            except json.JSONDecodeError as exc:
                raise ValueError("FDAI_STENCIL_FEATURE_FLAGS_JSON must be valid JSON") from exc
            if not isinstance(parsed, dict):
                raise ValueError("FDAI_STENCIL_FEATURE_FLAGS_JSON must be a JSON object")
            schema_version = parsed.get("schema_version", STENCIL_FEATURE_FLAGS_SCHEMA)
            if schema_version != STENCIL_FEATURE_FLAGS_SCHEMA:
                raise ValueError("Unsupported Stencil feature-flags schema_version")
            mode = parsed.get("enforcement_mode", "fail-closed")
            if mode != "fail-closed":
                raise ValueError("Stencil feature_flags enforcement_mode must be fail-closed")
            if "stencil_id" in parsed and parsed["stencil_id"] is not None:
                raw_sid = parsed["stencil_id"]
                if not isinstance(raw_sid, str) or _STENCIL_ID_RE.fullmatch(raw_sid) is None:
                    raise ValueError("Stencil feature_flags stencil_id is invalid")
                stencil_id = raw_sid
            if "enabled_panel_ids" in parsed and isinstance(parsed["enabled_panel_ids"], list):
                enabled_panels = set(
                    _validate_id_collection(
                        parsed["enabled_panel_ids"], label="Stencil enabled_panel_ids"
                    )
                )
            if "disabled_panel_ids" in parsed and isinstance(parsed["disabled_panel_ids"], list):
                disabled_panels.update(
                    _validate_id_collection(
                        parsed["disabled_panel_ids"], label="Stencil disabled_panel_ids"
                    )
                )
            if "panel_flags" in parsed and isinstance(parsed["panel_flags"], dict):
                panel_flags_map = parsed["panel_flags"]
                if enabled_panels is None:
                    enabled_panels = set()
                for k, v in panel_flags_map.items():
                    if (
                        not isinstance(k, str)
                        or _KEBAB_ID_RE.fullmatch(k) is None
                        or type(v) is not bool
                    ):
                        raise ValueError("Stencil panel_flags entry is invalid")
                    if v:
                        enabled_panels.add(k)
                    else:
                        disabled_panels.add(k)
            if "enabled_loops" in parsed and isinstance(parsed["enabled_loops"], list):
                enabled_loops = set(
                    _validate_id_collection(parsed["enabled_loops"], label="Stencil enabled_loops")
                )
            if "disabled_loops" in parsed and isinstance(parsed["disabled_loops"], list):
                disabled_loops.update(
                    _validate_id_collection(
                        parsed["disabled_loops"], label="Stencil disabled_loops"
                    )
                )
            if "loop_flags" in parsed and isinstance(parsed["loop_flags"], dict):
                loop_flags_map = parsed["loop_flags"]
                if enabled_loops is None:
                    enabled_loops = set()
                for k, v in loop_flags_map.items():
                    if (
                        not isinstance(k, str)
                        or _KEBAB_ID_RE.fullmatch(k) is None
                        or type(v) is not bool
                    ):
                        raise ValueError("Stencil loop_flags entry is invalid")
                    if v:
                        enabled_loops.add(k)
                    else:
                        disabled_loops.add(k)

        if raw_stencil_id:
            if _STENCIL_ID_RE.fullmatch(raw_stencil_id) is None:
                raise ValueError(f"Invalid FDAI_STENCIL_ID: {raw_stencil_id!r}")
            stencil_id = raw_stencil_id

        if raw_enabled_panels:
            parsed_ep = _parse_id_csv(raw_enabled_panels, label="FDAI_STENCIL_ENABLED_PANELS")
            enabled_panels = (
                set(parsed_ep) if enabled_panels is None else (enabled_panels & set(parsed_ep))
            )

        if raw_disabled_panels:
            disabled_panels.update(
                _parse_id_csv(raw_disabled_panels, label="FDAI_STENCIL_DISABLED_PANELS")
            )

        if raw_enabled_loops:
            parsed_el = _parse_id_csv(raw_enabled_loops, label="FDAI_STENCIL_ENABLED_LOOPS")
            enabled_loops = (
                set(parsed_el) if enabled_loops is None else (enabled_loops & set(parsed_el))
            )

        if raw_disabled_loops:
            disabled_loops.update(
                _parse_id_csv(raw_disabled_loops, label="FDAI_STENCIL_DISABLED_LOOPS")
            )

        if disabled_panels & LOCKED_STENCIL_PANELS:
            locked_hit = ", ".join(sorted(disabled_panels & LOCKED_STENCIL_PANELS))
            raise ValueError(f"Cannot disable locked safety-core Stencil panel(s): {locked_hit}")

        if disabled_loops & LOCKED_STENCIL_LOOPS:
            locked_loop_hit = ", ".join(sorted(disabled_loops & LOCKED_STENCIL_LOOPS))
            raise ValueError(
                f"Cannot disable locked safety-core Stencil loop(s): {locked_loop_hit}"
            )

        if enabled_panels is not None:
            enabled_panels.update(LOCKED_STENCIL_PANELS)
            enabled_panels -= disabled_panels

        if enabled_loops is not None:
            enabled_loops.update(LOCKED_STENCIL_LOOPS)
            enabled_loops -= disabled_loops

        return cls(
            active=True,
            stencil_id=stencil_id,
            enforcement_mode="fail-closed",
            enabled_panel_ids=(frozenset(enabled_panels) if enabled_panels is not None else None),
            disabled_panel_ids=frozenset(disabled_panels),
            enabled_loops=(frozenset(enabled_loops) if enabled_loops is not None else None),
            disabled_loops=frozenset(disabled_loops),
        )

    def is_panel_enabled(self, panel_id: str) -> bool:
        """Return whether a Console panel ID is enabled under this Stencil configuration."""

        if panel_id in LOCKED_STENCIL_PANELS:
            return True
        if not self.active:
            return True
        if panel_id in self.disabled_panel_ids:
            return False
        if self.enabled_panel_ids is not None:
            return panel_id in self.enabled_panel_ids
        return True

    def is_loop_enabled(self, loop_id: str) -> bool:
        """Return whether a runtime control-plane loop ID is enabled under this Stencil."""

        if loop_id in LOCKED_STENCIL_LOOPS:
            return True
        if not self.active:
            return True
        if loop_id in self.disabled_loops:
            return False
        if self.enabled_loops is not None:
            return loop_id in self.enabled_loops
        return True

    def evaluate_path(self, path: str) -> StencilRouteDecision:
        """Evaluate whether an Operator HTTP path is permitted by the active Stencil flags."""

        if not self.active:
            return StencilRouteDecision(allowed=True)

        normalized = "/" + path.strip("/") if path.strip("/") else "/"
        for rule in STENCIL_ROUTE_RULES:
            matched = (
                normalized == rule.prefix
                if rule.exact
                else (normalized == rule.prefix or normalized.startswith(f"{rule.prefix}/"))
            )
            if not matched:
                continue

            blocked_panels: list[str] = []
            if rule.any_panels and not any(self.is_panel_enabled(p) for p in rule.any_panels):
                blocked_panels.extend(rule.any_panels)

            blocked_loops = [
                loop_id for loop_id in rule.required_loops if not self.is_loop_enabled(loop_id)
            ]

            if blocked_panels or blocked_loops:
                return StencilRouteDecision(
                    allowed=False,
                    blocked_panels=tuple(blocked_panels),
                    blocked_loops=tuple(blocked_loops),
                )
            return StencilRouteDecision(allowed=True)

        return StencilRouteDecision(allowed=True)

    def to_payload(self) -> dict[str, Any]:
        """Serialize the active Stencil feature-flag state for read-only inspection."""

        return {
            "schema_version": STENCIL_FEATURE_FLAGS_SCHEMA,
            "active": self.active,
            "stencil_id": self.stencil_id,
            "enforcement_mode": self.enforcement_mode,
            "enabled_panel_ids": (
                sorted(self.enabled_panel_ids) if self.enabled_panel_ids is not None else None
            ),
            "disabled_panel_ids": sorted(self.disabled_panel_ids),
            "enabled_loops": (
                sorted(self.enabled_loops) if self.enabled_loops is not None else None
            ),
            "disabled_loops": sorted(self.disabled_loops),
            "locked_panels": sorted(LOCKED_STENCIL_PANELS),
            "locked_loops": sorted(LOCKED_STENCIL_LOOPS),
        }


class StencilFeatureFlagsMiddleware:
    """ASGI middleware enforcing fail-closed Stencil feature flags on deactivated menu routes."""

    def __init__(self, app: ASGIApp, config: StencilFeatureFlagConfig) -> None:
        self._app = app
        self._config = config

    def __getattr__(self, name: str) -> Any:
        return getattr(self._app, name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path = str(scope.get("path") or "/")
        method = str(scope.get("method") or "GET").upper()

        if method == "GET" and path.rstrip("/") == "/system/stencil-feature-flags":
            response = JSONResponse(self._config.to_payload(), status_code=200)
            await response(scope, receive, send)
            return

        if not self._config.active or method == "OPTIONS":
            await self._app(scope, receive, send)
            return

        decision = self._config.evaluate_path(path)
        if not decision.allowed:
            error_body = {
                "error": {
                    "status": 403,
                    "code": "stencil_feature_flag_disabled",
                    "message": (
                        "This feature is disabled by the active Stencil feature-flag configuration."
                    ),
                    "stencil_id": self._config.stencil_id,
                    "blocked_panels": list(decision.blocked_panels),
                    "blocked_loops": list(decision.blocked_loops),
                }
            }
            response = JSONResponse(
                error_body,
                status_code=403,
                headers=self._stencil_headers(),
            )
            await response(scope, receive, send)
            return

        extra_headers = [
            (k.encode("latin-1"), v.encode("latin-1")) for k, v in self._stencil_headers().items()
        ]

        async def send_with_stencil_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", ()))
                headers.extend(extra_headers)
                message["headers"] = headers
            await send(message)

        await self._app(scope, receive, send_with_stencil_headers)

    def _stencil_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"x-fdai-stencil-enforcement": self._config.enforcement_mode}
        if self._config.stencil_id:
            headers["x-fdai-stencil-id"] = self._config.stencil_id
        return headers


def wrap_with_stencil_feature_flags(
    app: AsgiApplication,
    environ: Mapping[str, str],
) -> AsgiApplication:
    """Wrap an Operator ASGI application with fail-closed Stencil feature-flag gating."""

    config = StencilFeatureFlagConfig.from_environ(environ)
    if isinstance(app, Starlette):
        app.add_middleware(StencilFeatureFlagsMiddleware, config=config)
        return app
    if not callable(app):
        return app
    return StencilFeatureFlagsMiddleware(app, config)


__all__ = [
    "LOCKED_STENCIL_LOOPS",
    "LOCKED_STENCIL_PANELS",
    "STENCIL_FEATURE_FLAGS_SCHEMA",
    "STENCIL_ROUTE_RULES",
    "StencilFeatureFlagConfig",
    "StencilFeatureFlagsMiddleware",
    "StencilRouteDecision",
    "StencilRouteRule",
    "wrap_with_stencil_feature_flags",
]
