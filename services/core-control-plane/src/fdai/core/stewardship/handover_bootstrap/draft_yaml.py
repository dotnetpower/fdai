"""Render a :class:`StewardMapDraft` as a resolver-loadable draft YAML.

The output matches the ``stewardship:`` shape of
``config/agent-stewardship.yaml`` so it round-trips through
:func:`fdai.core.stewardship.resolver.load_stewardship_from_mapping`. It is a
**draft**: unresolved people keep the all-zero placeholder id and every
mapping carries an inline citation comment so a reviewer can verify the
grounding before merging the governance PR. Nothing here applies the map.

Hand-rendered (not dumped through PyYAML) so the citation comments and the
familiar file layout survive - the same reason the shipped config is
hand-authored.
"""

from __future__ import annotations

from fdai.core.stewardship.handover_bootstrap.contract import (
    ExtractedMapping,
    StewardMapDraft,
)
from fdai.core.stewardship.model import (
    AgentStewardship,
    Responsibility,
    StewardshipMap,
    StewardSubject,
)
from fdai.core.stewardship.names import AGENT_NAMES

_PLACEHOLDER_OID = "00000000-0000-0000-0000-000000000000"
_DEFAULT_HOP_TIMEOUT = 900
_DEFAULT_OVER_ASSIGNED_MAX = 5


def render_draft_yaml(draft: StewardMapDraft, *, maintainer_oids: tuple[str, ...] = ()) -> str:
    """Return the draft steward map as YAML text (never applied).

    ``maintainer_oids`` seeds the maintainer list; when empty a single
    placeholder is emitted with a TODO so the draft still satisfies the
    fail-fast maintainer floor on load.
    """
    by_agent: dict[str, list[ExtractedMapping]] = {name: [] for name in AGENT_NAMES}
    for mapping in draft.mappings:
        by_agent[mapping.agent_name].append(mapping)

    lines: list[str] = []
    lines.extend(_header(draft))
    lines.append("stewardship:")
    lines.append(f"  version: {draft.version}")
    lines.extend(_maintainers(maintainer_oids))
    lines.append("  channels: {}")
    lines.append("  escalation:")
    lines.append(f"    hop_timeout_seconds: {_DEFAULT_HOP_TIMEOUT}")
    lines.append("  thresholds:")
    lines.append(f"    over_assigned_max: {_DEFAULT_OVER_ASSIGNED_MAX}")
    lines.append("  agents:")
    for name in AGENT_NAMES:
        lines.extend(_agent_block(name, by_agent[name]))
    return "\n".join(lines) + "\n"


def render_candidate_yaml(draft: StewardMapDraft, *, base: StewardshipMap) -> str:
    """Render an additive governance candidate over the current validated map.

    Grounded draft mappings add or retag subjects. They never remove an existing
    owner automatically; a reviewer must make removals explicitly in the PR.
    """
    by_agent: dict[str, list[ExtractedMapping]] = {name: [] for name in AGENT_NAMES}
    for mapping in draft.mappings:
        by_agent[mapping.agent_name].append(mapping)

    lines = _header(draft)
    lines.extend(("# Candidate is additive: existing ownership is preserved.", "#"))
    lines.append("stewardship:")
    lines.append(f"  version: {base.version}")
    lines.extend(_maintainers(base.maintainer_oids))
    lines.append("  channels:")
    if base.channels:
        for oid, channel_id in sorted(base.channels.items()):
            lines.append(f'    "{oid}": "{channel_id}"')
    else:
        lines[-1] = "  channels: {}"
    lines.append("  escalation:")
    lines.append(f"    hop_timeout_seconds: {base.hop_timeout_seconds}")
    lines.append("  thresholds:")
    lines.append(f"    over_assigned_max: {base.over_assigned_max}")
    lines.append("  agents:")
    for name in AGENT_NAMES:
        lines.extend(_candidate_agent_block(base.agent(name), by_agent[name]))
    return "\n".join(lines) + "\n"


def _header(draft: StewardMapDraft) -> list[str]:
    lines = [
        "# FDAI agent-stewardship DRAFT - generated from ingested handover documents.",
        "# Review every mapping against its cited source before merging. This file is",
        "# NEVER applied automatically; it is a governance draft PR (console is read-only).",
        f"# outcome: {draft.outcome.value}",
    ]
    for warning in draft.warnings:
        lines.append(f"# warning: {warning}")
    for person in draft.unresolved_people:
        lines.append(
            f"# unresolved: {person.display_name!r} ({person.kind.value}) - set a real Entra id"
        )
    for mapping in draft.abstained:
        cite = mapping.citations[0] if mapping.citations else None
        where = f" {cite.doc_id}:L{cite.line}" if cite else ""
        lines.append(
            f"# below-floor: {mapping.agent_name} <- {mapping.person.display_name!r} "
            f"conf={mapping.confidence}{where} (confirm manually)"
        )
    lines.append("#")
    return lines


def _maintainers(maintainer_oids: tuple[str, ...]) -> list[str]:
    lines = ["  maintainers:"]
    if maintainer_oids:
        for oid in maintainer_oids:
            lines.append(f'    - oid: "{oid}"')
    else:
        lines.append(f'    - oid: "{_PLACEHOLDER_OID}"   # TODO: set a real FDAI maintainer OID')
    return lines


def _agent_block(name: str, mappings: list[ExtractedMapping]) -> list[str]:
    accountable = [m for m in mappings if m.responsibility is Responsibility.ACCOUNTABLE]
    lines = [f"    {name}:"]
    if mappings:
        lines.append("      stewards:")
        for mapping in mappings:
            lines.append(_steward_line(mapping))
    if not accountable:
        # No confident accountable owner: keep the draft loadable and explicit.
        reason = (
            "no accountable owner found in ingested documents; "
            "assign a steward or confirm autonomous"
        )
        lines.append("      accept_autonomous:")
        lines.append(f'        reason: "{reason}"')
    return lines


def _steward_line(mapping: ExtractedMapping) -> str:
    person = mapping.person
    oid = person.oid or _PLACEHOLDER_OID
    cite = mapping.citations[0] if mapping.citations else None
    where = f" {cite.doc_id}:L{cite.line}" if cite else ""
    flag = "" if person.oid else " UNRESOLVED"
    comment = (
        f"# {person.display_name}{flag} conf={mapping.confidence} src={mapping.source.value}{where}"
    )
    return (
        f'        - {{ kind: {person.kind.value}, id: "{oid}", '
        f"responsibility: {mapping.responsibility.value} }}   {comment}"
    )


def _candidate_agent_block(
    existing: AgentStewardship,
    additions: list[ExtractedMapping],
) -> list[str]:
    subjects: dict[tuple[str, str], StewardSubject | ExtractedMapping] = {
        (subject.kind.value, subject.id): subject for subject in existing.stewards
    }
    for mapping in additions:
        if mapping.person.oid is not None:
            subjects[(mapping.person.kind.value, mapping.person.oid)] = mapping

    lines = [f"    {existing.agent_name}:", "      stewards:"]
    for subject in subjects.values():
        if isinstance(subject, ExtractedMapping):
            lines.append(_steward_line(subject))
        else:
            lines.append(
                f'        - {{ kind: {subject.kind.value}, id: "{subject.id}", '
                f"responsibility: {subject.responsibility.value} }}"
            )
    accountable = any(
        (
            subject.responsibility is Responsibility.ACCOUNTABLE
            if isinstance(subject, ExtractedMapping)
            else subject.is_accountable
        )
        for subject in subjects.values()
    )
    if not accountable:
        reason = existing.accept_autonomous_reason or "review required: no accountable owner"
        lines.append("      accept_autonomous:")
        lines.append(f'        reason: "{reason}"')
    return lines


__all__ = ["render_candidate_yaml", "render_draft_yaml"]
