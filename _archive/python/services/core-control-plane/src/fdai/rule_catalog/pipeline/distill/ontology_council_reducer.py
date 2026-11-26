"""Deterministic validation and exact reduction of ontology council votes."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

from fdai.rule_catalog.pipeline.distill.ontology_models import stable_digest
from fdai.shared.providers.ontology_council import (
    CouncilAgreedField,
    CouncilClaimPacket,
    CouncilDisposition,
    CouncilFieldAlternative,
    CouncilFieldDifference,
    CouncilModelIdentity,
    CouncilOutcome,
    CouncilTargetKind,
    CouncilVote,
)


@dataclass(frozen=True, slots=True)
class CouncilRoundDecision:
    outcome: CouncilOutcome
    consensus_vote: CouncilVote | None
    differences: tuple[CouncilFieldDifference, ...]
    reason_codes: tuple[str, ...]


def validate_council_vote(
    vote: CouncilVote,
    *,
    expected_model: CouncilModelIdentity,
    packet: CouncilClaimPacket,
) -> CouncilVote:
    """Reject invented context and canonicalize configured aliases."""
    if vote.model_identity != expected_model:
        raise ValueError("council vote model identity MUST match its binding")
    if vote.claim_id != packet.claim_id or vote.citation_digest != packet.citation_digest:
        raise ValueError("council vote MUST cite the exact claim packet")
    if vote.disposition is not CouncilDisposition.PROPOSE:
        return vote
    if vote.authority != packet.authority:
        raise ValueError("council vote MUST preserve the claim authority")

    object_declarations = {item.name: item for item in packet.object_types}
    link_declarations = {item.name: item for item in packet.links}
    entity_types = {item.identity: item.object_type for item in packet.entities}
    aliases = _alias_index(packet)

    if vote.target_kind is None or vote.target_type is None or vote.target_identity is None:
        raise ValueError("council proposal vote MUST include its complete target")
    property_names = {item.name for item in vote.properties}
    if vote.target_kind is CouncilTargetKind.OBJECT:
        object_declaration = object_declarations.get(vote.target_type)
        if object_declaration is None:
            raise ValueError("council vote MUST select an existing object type")
        target_identity = _resolve_identity(
            vote.target_identity,
            expected_type=vote.target_type,
            entity_types=entity_types,
            aliases=aliases,
        )
        if not property_names.issubset(object_declaration.properties):
            raise ValueError("council vote MUST select allowed object properties")
        return replace(vote, target_identity=target_identity)

    link_declaration = link_declarations.get(vote.target_type)
    if link_declaration is None:
        raise ValueError("council vote MUST select an existing link type")
    if vote.from_identity is None or vote.to_identity is None:
        raise ValueError("council link vote MUST include endpoint identities")
    from_identity = _resolve_identity(
        vote.from_identity,
        expected_type=link_declaration.from_type,
        entity_types=entity_types,
        aliases=aliases,
    )
    to_identity = _resolve_identity(
        vote.to_identity,
        expected_type=link_declaration.to_type,
        entity_types=entity_types,
        aliases=aliases,
    )
    target_identity = _resolve_any_identity(vote.target_identity, entity_types, aliases)
    if target_identity != from_identity:
        raise ValueError("link vote target identity MUST equal its canonical from identity")
    if not property_names.issubset(link_declaration.properties):
        raise ValueError("council vote MUST select allowed link properties")
    return replace(
        vote,
        target_identity=target_identity,
        from_identity=from_identity,
        to_identity=to_identity,
    )


def reduce_council_votes(
    votes: tuple[CouncilVote, CouncilVote, CouncilVote],
) -> CouncilRoundDecision:
    """Require unanimity and never choose a majority proposal."""
    dispositions = tuple(vote.disposition for vote in votes)
    if all(item is CouncilDisposition.UNSUPPORTED for item in dispositions):
        return CouncilRoundDecision(
            outcome=CouncilOutcome.UNSUPPORTED,
            consensus_vote=None,
            differences=(),
            reason_codes=("all_unsupported",),
        )
    fingerprints = tuple(vote.semantic_fingerprint for vote in votes)
    if (
        all(item is CouncilDisposition.PROPOSE for item in dispositions)
        and len(set(fingerprints)) == 1
    ):
        return CouncilRoundDecision(
            outcome=CouncilOutcome.CONSENSUS,
            consensus_vote=votes[0],
            differences=(),
            reason_codes=("unanimous_proposal",),
        )
    differences = _field_differences(votes)
    if any(item is CouncilDisposition.PROPOSE for item in dispositions):
        return CouncilRoundDecision(
            outcome=CouncilOutcome.CONTESTED,
            consensus_vote=None,
            differences=differences,
            reason_codes=("non_unanimous",),
        )
    return CouncilRoundDecision(
        outcome=CouncilOutcome.UNRESOLVED,
        consensus_vote=None,
        differences=differences,
        reason_codes=("no_proposal_quorum",),
    )


def validate_council_revision(
    initial_votes: tuple[CouncilVote, CouncilVote, CouncilVote],
    revised_votes: tuple[CouncilVote, CouncilVote, CouncilVote],
    disputed_fields: frozenset[str],
) -> None:
    """Reject revision changes outside the deterministic field-difference set."""
    for initial, revised in zip(initial_votes, revised_votes, strict=True):
        if initial.model_identity != revised.model_identity:
            raise ValueError("revised council vote MUST preserve model identity")
        initial_payload = _semantic_payload(initial)
        revised_payload = _semantic_payload(revised)
        if any(
            initial_payload[field_name] != revised_payload[field_name]
            for field_name in initial_payload.keys() - disputed_fields
        ):
            raise ValueError("revised council vote MUST change only disputed fields")


def council_agreed_fields(
    votes: tuple[CouncilVote, CouncilVote, CouncilVote],
) -> tuple[CouncilAgreedField, ...]:
    payloads = tuple(_semantic_payload(vote) for vote in votes)
    agreed: list[CouncilAgreedField] = []
    for field_name in sorted(payloads[0]):
        values_by_digest = {
            stable_digest(payload[field_name]): payload[field_name] for payload in payloads
        }
        if len(values_by_digest) == 1:
            digest, value = next(iter(values_by_digest.items()))
            agreed.append(
                CouncilAgreedField(
                    field_name=field_name,
                    alternative=_field_alternative(digest, value),
                )
            )
    return tuple(agreed)


def _field_differences(
    votes: tuple[CouncilVote, CouncilVote, CouncilVote],
) -> tuple[CouncilFieldDifference, ...]:
    payloads = tuple(_semantic_payload(vote) for vote in votes)
    differences: list[CouncilFieldDifference] = []
    for name in sorted(payloads[0]):
        values_by_digest = {stable_digest(payload[name]): payload[name] for payload in payloads}
        value_digests = tuple(sorted(values_by_digest))
        if len(value_digests) > 1:
            differences.append(
                CouncilFieldDifference(
                    name,
                    value_digests,
                    tuple(
                        _field_alternative(digest, values_by_digest[digest])
                        for digest in value_digests
                    ),
                )
            )
    return tuple(differences)


def _field_alternative(digest: str, value: object) -> CouncilFieldAlternative:
    return CouncilFieldAlternative(
        digest=digest,
        value_json=json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )


def _semantic_payload(vote: CouncilVote) -> dict[str, object]:
    return {
        "authority": vote.authority,
        "comparators": vote.semantics.comparators,
        "disposition": vote.disposition.value,
        "effective_from": vote.semantics.effective_from,
        "effective_to": vote.semantics.effective_to,
        "from_identity": vote.from_identity,
        "negated": vote.semantics.negated,
        "numbers": vote.semantics.numbers,
        "operation": vote.operation.value if vote.operation is not None else None,
        "properties": tuple((item.name, item.value) for item in vote.properties),
        "target_identity": vote.target_identity,
        "target_kind": vote.target_kind.value if vote.target_kind is not None else None,
        "target_type": vote.target_type,
        "to_identity": vote.to_identity,
        "units": vote.semantics.units,
    }


def _alias_index(packet: CouncilClaimPacket) -> dict[str, tuple[str, ...]]:
    aliases: dict[str, set[str]] = {}
    for item in packet.aliases:
        aliases.setdefault(_normalize_alias(item.alias), set()).add(item.identity)
    return {key: tuple(sorted(values)) for key, values in aliases.items()}


def _resolve_identity(
    supplied: str,
    *,
    expected_type: str,
    entity_types: dict[str, str],
    aliases: dict[str, tuple[str, ...]],
) -> str:
    if entity_types.get(supplied) == expected_type:
        return supplied
    matches = tuple(
        identity
        for identity in aliases.get(_normalize_alias(supplied), ())
        if entity_types.get(identity) == expected_type
    )
    if len(matches) != 1:
        raise ValueError("council vote identity MUST resolve to one existing typed entity")
    return matches[0]


def _resolve_any_identity(
    supplied: str,
    entity_types: dict[str, str],
    aliases: dict[str, tuple[str, ...]],
) -> str:
    if supplied in entity_types:
        return supplied
    matches = aliases.get(_normalize_alias(supplied), ())
    if len(matches) != 1:
        raise ValueError("council vote identity MUST resolve to one existing entity")
    return matches[0]


def _normalize_alias(value: str) -> str:
    return " ".join(value.split()).casefold()


__all__ = [
    "CouncilRoundDecision",
    "council_agreed_fields",
    "reduce_council_votes",
    "validate_council_revision",
    "validate_council_vote",
]
