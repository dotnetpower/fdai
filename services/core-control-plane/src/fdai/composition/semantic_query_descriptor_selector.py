"""Exact-manifest candidate retrieval without intent or operational authority."""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from threading import Lock
from typing import Any

from fdai.core.conversation.semantic_planning_judgment import _semantic_judgment_capabilities
from fdai.core.ontology_platform.query_manifest import QueryManifest
from fdai.delivery.catalog_search.generation import (
    SemanticGenerationBuild,
    build_ontology_semantic_generation,
    validate_ontology_semantic_generation,
)
from fdai.delivery.catalog_search.ranking import lexical_score, lexical_tokens

_LOGGER = logging.getLogger(__name__)


class ManifestDescriptorIndex:
    """Rank real catalog declarations while the full manifest remains authoritative."""

    def __init__(self, *, max_generations: int = 16, candidate_limit: int = 96) -> None:
        if not 1 <= max_generations <= 64 or not 1 <= candidate_limit <= 512:
            raise ValueError("descriptor index bounds are invalid")
        self._max_generations = max_generations
        self._candidate_limit = candidate_limit
        self._generations: OrderedDict[tuple[str, str], SemanticGenerationBuild] = OrderedDict()
        self._lock = Lock()

    def select(
        self, *, utterance: str, manifest: QueryManifest, limit: int
    ) -> Sequence[Mapping[str, Any]]:
        """Return an exact subset and report omissions, never infer an intent."""
        if not 1 <= limit <= 512:
            raise ValueError("descriptor selection limit is invalid")
        key = (manifest.coverage_receipt.principal_scope_digest, manifest.manifest_digest)
        with self._lock:
            build = self._generations.get(key)
            if build is None:
                build = build_ontology_semantic_generation(
                    manifest=manifest,
                    embedding_space_id="fdai-manifest-lexical-v1",
                    embedding_model_version="1",
                    embedding_dimension=1,
                )
                validate_ontology_semantic_generation(
                    build=build, manifest=manifest, validator_id="manifest-descriptor-validator-v1"
                )
                self._generations[key] = build
            self._generations.move_to_end(key)
            while len(self._generations) > self._max_generations:
                self._generations.popitem(last=False)
        available = {
            f"declaration:{item['kind']}:{item['name']}": item for item in manifest.descriptors
        }
        tokens = lexical_tokens(utterance)
        ranked = sorted(
            (document for document in build.documents if document.rule_id in available),
            key=lambda document: (-lexical_score(document, tokens), document.rule_id),
        )
        full = tuple(available[document.rule_id] for document in ranked)
        if (
            len(full) <= limit
            and len(json.dumps(full, ensure_ascii=True).encode("utf-8")) <= 262_144
        ):
            capabilities = _semantic_judgment_capabilities(full)
            if len(capabilities) == len(full):
                _LOGGER.info(
                    "semantic_descriptor_candidates_selected",
                    extra={
                        "generation_digest": build.metadata.generation_digest,
                        "candidate_count": len(full),
                        "omitted_count": 0,
                        "execution_authority": False,
                    },
                )
                return full
        selected: list[dict[str, Any]] = []
        encoded_bytes = 2
        for document in ranked:
            descriptor = available[document.rule_id]
            size = len(json.dumps(descriptor, ensure_ascii=True).encode("utf-8")) + 1
            if encoded_bytes + size > 262_144:
                continue
            capabilities = _semantic_judgment_capabilities((*selected, descriptor))
            if len(capabilities) != len(selected) + 1:
                break
            selected.append(descriptor)
            encoded_bytes += size
            if len(selected) >= min(limit, self._candidate_limit):
                break
        if not selected:
            raise ValueError("no principal-scoped descriptors fit the candidate budget")
        _LOGGER.info(
            "semantic_descriptor_candidates_selected",
            extra={
                "generation_digest": build.metadata.generation_digest,
                "candidate_count": len(selected),
                "omitted_count": len(available) - len(selected),
                "execution_authority": False,
            },
        )
        return tuple(selected)
