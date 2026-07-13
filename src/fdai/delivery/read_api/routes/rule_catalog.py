"""Read-only ``GET /rules`` route - the rule-catalog explorer.

Serves a paginated, faceted projection of the rules the system knows so
the console's Knowledge > Rules panel can browse them without
hand-grepping ``rule-catalog/**``. Two tiers are exposed and tagged with
an ``origin``:

- ``active`` - the curated catalog under ``rule-catalog/catalog/`` that
  T0 evaluates today (canonical vocabulary, executable rego + tftpl
  remediation).
- ``collected`` - the imported upstream corpus under
  ``rule-catalog/collected/`` (Azure Policy built-ins, kube-bench). Much
  larger and not all normalized to the canonical vocabulary yet; it is
  the source material the living-rules discovery pipeline draws from.

Because the collected tier is thousands of rules, the route paginates
server-side (``limit`` / ``offset``) and computes facet counts over the
full corpus so the FE renders dropdowns and totals without buffering
every rule. Registered by :func:`~fdai.delivery.read_api.main.build_app`
only when at least one tier is wired. Reader-role gate; GET-only. Like
every console route this is a pure projection - it never mutates state
(see ``app-shape.instructions.md`` § Operator console).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.shared.contracts.models import Rule

DEFAULT_ROUTE_PATH = "/rules"
DETAIL_ROUTE_PATH = "/rules/{rule_id}"
FINDINGS_ROUTE_PATH = "/rules/{rule_id}/findings"
FINDINGS_SUMMARY_ROUTE_PATH = "/rules/findings-summary"

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_FINDINGS = 200

# A findings provider maps (rule_id, origin) -> the resources currently
# violating that rule, each with the specific attribute at fault. It is
# an injected seam: upstream ships none (the section shows an honest
# "not evaluated here" state), a fork wires an inventory-evaluation
# source (assurance_twin / T0 engine over real inventory).
FindingsProvider = Callable[[str, str], Awaitable[Sequence[Mapping[str, Any]]]]

# A findings-summary provider returns ``rule_id -> violating-resource
# count`` for every rule it can evaluate (active tier only). It powers
# the at-a-glance count badge on the list. Same opt-in contract as
# :data:`FindingsProvider`; upstream ships none.
FindingsSummaryProvider = Callable[[], Awaitable[Mapping[str, int]]]

# Cap a resolved policy / template body so a pathological file cannot
# force the API to buffer megabytes into one JSON response.
MAX_BODY_BYTES = 512_000

# Origin tags. ``active`` = curated executable catalog; ``collected`` =
# imported upstream corpus (candidate / reference material).
ORIGIN_ACTIVE = "active"
ORIGIN_COLLECTED = "collected"

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _serialize_rule(rule: Rule, origin: str) -> dict[str, object]:
    """Project one :class:`Rule` to the operator-facing summary shape.

    Only the fields the panel renders are exposed; the check-logic body
    (Rego) and full parameter map stay server-side. ``check_logic`` and
    ``remediation`` carry the *references* an operator follows to the
    policy / template, not their contents.
    """

    return {
        "id": rule.id,
        "origin": origin,
        "version": str(rule.version),
        "source": rule.source.value,
        "severity": rule.severity.value,
        "category": rule.category.value,
        "resource_type": rule.resource_type,
        "check_logic": {
            "kind": rule.check_logic.kind.value,
            "reference": rule.check_logic.reference,
        },
        "remediation": {
            "template_ref": rule.remediation.template_ref,
            "cost_impact_monthly_usd": rule.remediation.cost_impact_monthly_usd,
        },
        "remediates": rule.remediates,
        "provenance": {
            "source_url": rule.provenance.source_url,
            "license": rule.provenance.license,
            "redistribution": rule.provenance.redistribution.value,
        },
    }


class _IndexedRule:
    """A serialized rule plus lowercase filter keys (precomputed once)."""

    __slots__ = ("payload", "origin", "category", "severity", "source", "search")

    def __init__(self, rule: Rule, origin: str) -> None:
        self.payload = _serialize_rule(rule, origin)
        self.origin = origin
        self.category = rule.category.value
        self.severity = rule.severity.value
        self.source = rule.source.value
        # Match id OR resource_type so a free-text box narrows either.
        self.search = f"{rule.id}\n{rule.resource_type}".lower()


def _sorted_counts(counter: Counter[str]) -> dict[str, int]:
    # Count-desc then key-asc so the FE facet list is deterministic.
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))


def _serialize_detail(rule: Rule, origin: str) -> dict[str, object]:
    """Full projection for the single-rule detail view.

    Adds the fields the summary omits - parameters, applies_to, and the
    complete provenance - so the drawer can render a code-review-style
    breakdown. File bodies are attached by the handler, not here.
    """

    prov = rule.provenance
    return {
        "id": rule.id,
        "origin": origin,
        "schema_version": str(rule.schema_version),
        "version": str(rule.version),
        "source": rule.source.value,
        "severity": rule.severity.value,
        "category": rule.category.value,
        "resource_type": rule.resource_type,
        "check_logic": {
            "kind": rule.check_logic.kind.value,
            "reference": rule.check_logic.reference,
        },
        "remediation": {
            "template_ref": rule.remediation.template_ref,
            "cost_impact_monthly_usd": rule.remediation.cost_impact_monthly_usd,
        },
        "remediates": rule.remediates,
        "alternatives": list(rule.alternatives),
        "parameters": dict(rule.parameters),
        "applies_to": dict(rule.applies_to),
        "provenance": {
            "source_url": prov.source_url,
            "source_version": prov.source_version,
            "resolved_ref": prov.resolved_ref,
            "content_hash": prov.content_hash,
            "license": prov.license,
            "redistribution": prov.redistribution.value,
            "retrieved_at": prov.retrieved_at.isoformat(),
            "mapped_by": prov.mapped_by,
        },
    }


def _parse_rego_metadata(body: str) -> dict[str, Any] | None:
    """Extract the OPA ``# METADATA`` annotation block from a Rego body.

    OPA policies carry a leading comment block::

        # METADATA
        # title: ...
        # description: |
        #   ...
        # custom:
        #   severity: critical

    which is YAML once the ``# `` comment prefix is stripped. We parse it
    so the console can show the authored ``title`` / ``description`` (the
    "why it matters / risk" text) that already lives next to the code -
    no separate authoring, fully grounded in the shipped policy file.
    Returns ``None`` when the block is absent or unparseable.
    """

    lines = body.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() in ("# METADATA", "#METADATA"):
            start = i + 1
            break
    if start is None:
        return None

    collected: list[str] = []
    for line in lines[start:]:
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            break
        # Drop the leading '#' and at most one following space so YAML
        # indentation inside the block scalar is preserved.
        content = stripped[1:]
        if content.startswith(" "):
            content = content[1:]
        collected.append(content)

    if not collected:
        return None
    try:
        parsed = yaml.safe_load("\n".join(collected))
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _build_explanation(rule: Rule, check_logic_body: str | None) -> dict[str, Any]:
    """Assemble a human-readable "why it matters" block for a rule.

    Grounded, never invented:
    - active rules -> the Rego ``# METADATA`` (title + description);
    - Azure Policy -> the built-in display name + effect + category;
    - kube-bench -> the CIS control id + the audit command it runs.

    ``title``/``description`` are ``None`` when the source carries none;
    the FE falls back to the rule id rather than fabricating prose.
    """

    if check_logic_body:
        meta = _parse_rego_metadata(check_logic_body)
        if meta and (meta.get("title") or meta.get("description")):
            return {
                "title": meta.get("title"),
                "description": meta.get("description"),
                "source": "rego_metadata",
                "details": {},
            }

    params = rule.parameters or {}
    if "azure_policy_display_name" in params:
        details = {
            k: params[k]
            for k in ("azure_policy_effect_default", "azure_policy_category")
            if params.get(k) is not None
        }
        return {
            "title": params.get("azure_policy_display_name"),
            "description": None,
            "source": "azure_policy",
            "details": details,
        }
    if "kube_bench_id" in params:
        ruleset = params.get("kube_bench_ruleset", "")
        control = params.get("kube_bench_id", "")
        details = {
            k: params[k]
            for k in ("kube_bench_audit", "kube_bench_scored")
            if params.get(k) is not None
        }
        return {
            "title": f"CIS {ruleset} {control}".strip(),
            "description": None,
            "source": "kube_bench",
            "details": details,
        }

    return {"title": None, "description": None, "source": None, "details": {}}


def _read_sandboxed(root: Path | None, reference: str, prefix: str) -> str | None:
    """Return the text of a rule-referenced file, or ``None``.

    Resolves ``reference`` (e.g. ``policies/disk/unattached.rego``)
    against ``root.parent`` and returns the file body ONLY when the
    resolved path stays inside ``root`` - a path-traversal or
    non-file / oversized reference yields ``None`` rather than an error,
    so the detail view degrades gracefully. Non-file references
    (``azure-policy://...``) never match ``prefix`` and return ``None``.
    """

    if root is None or not reference.startswith(prefix):
        return None
    try:
        root_resolved = root.resolve()
        candidate = (root.parent / reference).resolve()
        if not candidate.is_relative_to(root_resolved):
            return None
        if not candidate.is_file():
            return None
        body = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        return body[:MAX_BODY_BYTES] + "\n... [truncated]"
    return body


def make_rule_catalog_routes(
    *,
    active_rules: Sequence[Rule] = (),
    collected_rules: Sequence[Rule] = (),
    authorize: Callable[[Request], Awaitable[str]],
    policies_root: Path | None = None,
    remediation_root: Path | None = None,
    findings_provider: FindingsProvider | None = None,
    findings_summary_provider: FindingsSummaryProvider | None = None,
    path: str = DEFAULT_ROUTE_PATH,
    detail_path: str = DETAIL_ROUTE_PATH,
    findings_path: str = FINDINGS_ROUTE_PATH,
    findings_summary_path: str = FINDINGS_SUMMARY_ROUTE_PATH,
) -> list[Route]:
    """Return the list + detail routes serving the rule catalog.

    ``active_rules`` and ``collected_rules`` are loaded at
    composition-root time. The routes hold an immutable, pre-serialized
    snapshot - they do not reload from disk per request. ``policies_root``
    / ``remediation_root`` let the detail route resolve a rule's check
    logic (Rego) and remediation template bodies for the drawer; leave
    them ``None`` to serve metadata only. ``findings_provider`` backs
    ``GET /rules/{id}/findings`` (affected resources + the attribute at
    fault); ``None`` serves an honest "not evaluated here" response.
    """

    indexed: list[_IndexedRule] = [_IndexedRule(r, ORIGIN_ACTIVE) for r in active_rules]
    indexed.extend(_IndexedRule(r, ORIGIN_COLLECTED) for r in collected_rules)

    # Deterministic order: severity desc, then id asc. Stable across
    # reloads regardless of file iteration order.
    indexed.sort(key=lambda ir: (-_SEVERITY_RANK.get(ir.severity, 0), str(ir.payload["id"])))

    # Detail lookup. ``by_key`` is exact (origin+id); ``by_id`` is a
    # fallback when the caller does not pass an origin. Active is added
    # first so an id shared across tiers resolves to the active rule.
    by_key: dict[str, tuple[Rule, str]] = {}
    by_id: dict[str, tuple[Rule, str]] = {}
    for rule in active_rules:
        by_key[f"{ORIGIN_ACTIVE}:{rule.id}"] = (rule, ORIGIN_ACTIVE)
        by_id.setdefault(rule.id, (rule, ORIGIN_ACTIVE))
    for rule in collected_rules:
        by_key[f"{ORIGIN_COLLECTED}:{rule.id}"] = (rule, ORIGIN_COLLECTED)
        by_id.setdefault(rule.id, (rule, ORIGIN_COLLECTED))

    total = len(indexed)
    facets = {
        "by_origin": _sorted_counts(Counter(ir.origin for ir in indexed)),
        "by_category": _sorted_counts(Counter(ir.category for ir in indexed)),
        "by_severity": _sorted_counts(Counter(ir.severity for ir in indexed)),
        "by_source": _sorted_counts(Counter(ir.source for ir in indexed)),
    }
    resource_type_count = len({ir.payload["resource_type"] for ir in indexed})

    def _bad_request(message: str) -> Response:
        return JSONResponse({"error": {"status": 400, "message": message}}, status_code=400)

    async def list_handler(request: Request) -> Response:
        await authorize(request)
        params = request.query_params

        origin = params.get("origin", "").strip().lower()
        category = params.get("category", "").strip().lower()
        severity = params.get("severity", "").strip().lower()
        source = params.get("source", "").strip().lower()
        needle = params.get("q", "").strip().lower()

        try:
            limit = int(params.get("limit", str(DEFAULT_LIMIT)))
            offset = int(params.get("offset", "0"))
        except ValueError:
            return _bad_request("limit and offset MUST be integers")
        if limit < 1 or limit > MAX_LIMIT:
            return _bad_request(f"limit MUST be between 1 and {MAX_LIMIT}")
        if offset < 0:
            return _bad_request("offset MUST be >= 0")

        matched = [
            ir
            for ir in indexed
            if (not origin or ir.origin == origin)
            and (not category or ir.category == category)
            and (not severity or ir.severity == severity)
            and (not source or ir.source == source)
            and (not needle or needle in ir.search)
        ]
        page = matched[offset : offset + limit]

        return JSONResponse(
            {
                "total": total,
                "filtered_total": len(matched),
                "offset": offset,
                "limit": limit,
                "resource_type_count": resource_type_count,
                "facets": facets,
                "rules": [ir.payload for ir in page],
            }
        )

    async def detail_handler(request: Request) -> Response:
        await authorize(request)
        rule_id = request.path_params["rule_id"]
        origin = request.query_params.get("origin", "").strip().lower()

        entry: tuple[Rule, str] | None = None
        if origin:
            entry = by_key.get(f"{origin}:{rule_id}")
        else:
            entry = by_id.get(rule_id)
        if entry is None:
            return JSONResponse(
                {"error": {"status": 404, "message": f"unknown rule id {rule_id!r}"}},
                status_code=404,
            )

        rule, rule_origin = entry
        payload = _serialize_detail(rule, rule_origin)
        check_body = _read_sandboxed(policies_root, rule.check_logic.reference, "policies/")
        payload["check_logic_body"] = check_body
        payload["remediation_body"] = _read_sandboxed(
            remediation_root, rule.remediation.template_ref, "remediation/"
        )
        payload["explanation"] = _build_explanation(rule, check_body)
        return JSONResponse(payload)

    async def summary_handler(request: Request) -> Response:
        await authorize(request)
        if findings_summary_provider is None:
            return JSONResponse({"evaluated": False, "counts": {}})
        counts = dict(await findings_summary_provider())
        return JSONResponse({"evaluated": True, "rule_count": len(counts), "counts": counts})

    async def findings_handler(request: Request) -> Response:
        await authorize(request)
        rule_id = request.path_params["rule_id"]
        origin = request.query_params.get("origin", "").strip().lower()

        entry: tuple[Rule, str] | None = None
        if origin:
            entry = by_key.get(f"{origin}:{rule_id}")
        else:
            entry = by_id.get(rule_id)
        if entry is None:
            return JSONResponse(
                {"error": {"status": 404, "message": f"unknown rule id {rule_id!r}"}},
                status_code=404,
            )

        _, rule_origin = entry
        if findings_provider is None:
            # No inventory-evaluation source wired: be honest, do not
            # fabricate affected resources.
            return JSONResponse(
                {"rule_id": rule_id, "origin": rule_origin, "evaluated": False, "findings": []}
            )

        raw = await findings_provider(rule_id, rule_origin)
        findings = [dict(f) for f in list(raw)[:MAX_FINDINGS]]
        return JSONResponse(
            {
                "rule_id": rule_id,
                "origin": rule_origin,
                "evaluated": True,
                "finding_count": len(findings),
                "findings": findings,
            }
        )

    return [
        Route(path, endpoint=list_handler, methods=["GET"]),
        Route(findings_summary_path, endpoint=summary_handler, methods=["GET"]),
        Route(findings_path, endpoint=findings_handler, methods=["GET"]),
        Route(detail_path, endpoint=detail_handler, methods=["GET"]),
    ]
