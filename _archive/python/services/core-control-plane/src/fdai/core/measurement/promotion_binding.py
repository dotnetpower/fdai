"""Authority-neutral, content-addressed subject of a production replay review."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CASE_REF = re.compile(
    r"^case-history:([a-z0-9]+(?:[._-][a-z0-9]+)*):([1-9][0-9]{0,11}):[0-9a-f]{64}$"
)
_FIELDS = frozenset(
    {
        "candidate_digest",
        "package_digest",
        "replay_first_digest",
        "replay_second_digest",
        "immutable_case_refs",
        "access_scope_digest",
        "purpose",
    }
)


@dataclass(frozen=True, slots=True)
class ReviewedReplayBinding:
    """Exact inert artifacts and scoped source revisions; never an approval."""

    candidate_digest: str
    package_digest: str
    replay_first_digest: str
    replay_second_digest: str
    immutable_case_refs: tuple[str, ...]
    access_scope_digest: str
    purpose: str

    def __post_init__(self) -> None:
        for digest in (
            self.candidate_digest,
            self.package_digest,
            self.replay_first_digest,
            self.replay_second_digest,
            self.access_scope_digest,
        ):
            if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
                raise ValueError("reviewed replay binding requires lowercase SHA-256 digests")
        if self.replay_first_digest != self.replay_second_digest:
            raise ValueError("reviewed replay binding requires deterministic replay")
        if not isinstance(self.purpose, str) or (
            not self.purpose.strip() or len(self.purpose) > 512
        ):
            raise ValueError("reviewed replay binding requires a bounded source purpose")
        refs = self.immutable_case_refs
        if not isinstance(refs, (tuple, list)) or not 1 <= len(refs) <= 100:
            raise ValueError("reviewed replay binding requires bounded immutable case refs")
        case_ids: set[str] = set()
        for reference in refs:
            match = (
                _CASE_REF.fullmatch(reference)
                if isinstance(reference, str) and len(reference) <= 384
                else None
            )
            if match is None or len(match[1]) > 256 or match[1] in case_ids:
                raise ValueError("reviewed replay binding requires unique canonical case refs")
            case_ids.add(match[1])
        object.__setattr__(self, "immutable_case_refs", tuple(sorted(refs)))

    def to_mapping(self) -> dict[str, object]:
        return {
            "candidate_digest": self.candidate_digest,
            "package_digest": self.package_digest,
            "replay_first_digest": self.replay_first_digest,
            "replay_second_digest": self.replay_second_digest,
            "immutable_case_refs": list(self.immutable_case_refs),
            "access_scope_digest": self.access_scope_digest,
            "purpose": self.purpose,
        }

    @classmethod
    def from_mapping(cls, value: object) -> ReviewedReplayBinding:
        if not isinstance(value, Mapping) or set(value) != _FIELDS:
            raise ValueError("reviewed replay binding fields do not match schema")
        texts = {key: value[key] for key in _FIELDS - {"immutable_case_refs"}}
        if any(not isinstance(text, str) for text in texts.values()):
            raise ValueError("reviewed replay binding fields MUST be text")
        refs = value["immutable_case_refs"]
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise ValueError("reviewed replay binding case refs MUST be an array of text")
        return cls(
            candidate_digest=texts["candidate_digest"],
            package_digest=texts["package_digest"],
            replay_first_digest=texts["replay_first_digest"],
            replay_second_digest=texts["replay_second_digest"],
            immutable_case_refs=tuple(refs),
            access_scope_digest=texts["access_scope_digest"],
            purpose=texts["purpose"],
        )
