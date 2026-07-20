"""Project explicit runtime skill selections into bounded prompt layers."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from html import escape

from fdai.core.prompts.types import (
    PromptLayer,
    SkillBundleMemberReplayRecord,
    SkillBundleReplayRecord,
    SkillDisclosureRequest,
    SkillReplayRecord,
    SkillSelectionStatus,
)
from fdai.core.skills import (
    SkillAccessError,
    SkillCatalog,
    SkillIndexResult,
    SkillRejectionReason,
    SkillReplayMetadata,
    SkillTrustVerifier,
)
from fdai.core.skills.bundle_catalog import (
    ResolvedSkillBundle,
    SkillBundleCatalog,
    SkillBundleResolutionError,
)
from fdai.core.skills.bundle_manifest import SkillBundleTrustVerifier


@dataclass(frozen=True, slots=True)
class SkillDisclosureLayer:
    """One fully rendered disclosure layer awaiting prompt assembly."""

    id: str
    layer: PromptLayer
    body: str


@dataclass(frozen=True, slots=True)
class SkillDisclosureProjection:
    """Ordered layers and replay records for one disclosure request."""

    layers: tuple[SkillDisclosureLayer, ...]
    records: tuple[SkillReplayRecord, ...]
    bundle_records: tuple[SkillBundleReplayRecord, ...] = ()


def compose_skill_disclosure(
    *,
    catalog: SkillCatalog,
    verifier: SkillTrustVerifier,
    request: SkillDisclosureRequest,
    bundle_catalog: SkillBundleCatalog | None = None,
    bundle_verifier: SkillBundleTrustVerifier | None = None,
) -> SkillDisclosureProjection:
    """Build metadata first, then complete explicitly selected artifacts."""

    index = catalog.list_skills(
        query=request.query,
        agent=request.agent,
        available_tools=request.available_tools,
        max_chars=request.index_budget_chars,
    )
    index_body = _render_skill_index(index)
    if len(index_body) > request.index_budget_chars:
        raise SkillAccessError(SkillRejectionReason.INDEX_BUDGET_EXCEEDED)
    layers = [
        SkillDisclosureLayer(
            id="skill-index",
            layer=PromptLayer.SKILL_INDEX,
            body=index_body,
        )
    ]
    records: list[SkillReplayRecord] = []
    bundle_records: list[SkillBundleReplayRecord] = []
    remaining_body_chars = request.body_budget_chars
    for name in request.selected_skill_names:
        try:
            loaded = catalog.load_skill(
                name,
                agent=request.agent,
                available_tools=request.available_tools,
                verifier=verifier,
                max_chars=max(1, remaining_body_chars),
            )
        except SkillAccessError as exc:
            records.append(_rejected_record("load_skill", name, exc))
            continue
        layers.append(
            SkillDisclosureLayer(
                id=f"skill:{loaded.descriptor.name}",
                layer=PromptLayer.SKILL_BODY,
                body=(
                    f'<skill name="{escape(loaded.descriptor.name, quote=True)}" '
                    f'version="{escape(loaded.descriptor.version, quote=True)}" '
                    f'trusted="true">\n{loaded.body}</skill>'
                ),
            )
        )
        remaining_body_chars -= len(loaded.body)
        records.append(_selected_record(loaded.replay))

    for name in request.selected_bundle_names:
        if bundle_catalog is None or bundle_verifier is None:
            bundle_records.append(
                SkillBundleReplayRecord(
                    operation="load_skill_bundle",
                    name=name,
                    version=None,
                    manifest_sha256=None,
                    digest=None,
                    members=(),
                    status=SkillSelectionStatus.REJECTED,
                    rejection_reason="skill_bundle_runtime_unavailable",
                )
            )
            continue
        try:
            resolved_bundle = bundle_catalog.resolve(
                name,
                skills=catalog,
                bundle_verifier=bundle_verifier,
                skill_verifier=verifier,
                agent=request.agent,
                available_tools=request.available_tools,
                known_agents=frozenset({request.agent}),
                max_chars=max(1, remaining_body_chars),
            )
        except SkillBundleResolutionError as exc:
            bundle_records.append(_rejected_bundle_record(bundle_catalog, name, exc))
            continue
        layers.append(
            SkillDisclosureLayer(
                id=f"skill-bundle:{name}",
                layer=PromptLayer.SKILL_BUNDLE,
                body=_render_skill_bundle(resolved_bundle),
            )
        )
        remaining_body_chars -= len(resolved_bundle.instruction or "") + sum(
            len(member.body) for member in resolved_bundle.members
        )
        bundle_records.append(_selected_bundle_record(resolved_bundle))

    if request.reference_selection is not None:
        skill_name, reference_path = request.reference_selection
        try:
            loaded_reference = catalog.read_skill_reference(
                skill_name,
                reference_path,
                agent=request.agent,
                available_tools=request.available_tools,
                verifier=verifier,
                max_bytes=request.reference_budget_bytes,
            )
        except SkillAccessError as exc:
            records.append(
                _rejected_record(
                    "read_skill_reference",
                    skill_name,
                    exc,
                    reference_path=reference_path,
                )
            )
        else:
            layers.append(
                SkillDisclosureLayer(
                    id=f"skill-reference:{skill_name}:{reference_path}",
                    layer=PromptLayer.SKILL_REFERENCE,
                    body=_render_skill_reference(
                        skill_name=skill_name,
                        path=reference_path,
                        media_type=loaded_reference.reference.media_type,
                        content=loaded_reference.content,
                    ),
                )
            )
            records.append(
                _selected_record(
                    loaded_reference.replay,
                    reference_path=reference_path,
                    reference_sha256=loaded_reference.reference.sha256,
                )
            )
    return SkillDisclosureProjection(
        layers=tuple(layers),
        records=tuple(records),
        bundle_records=tuple(bundle_records),
    )


def _render_skill_index(index: SkillIndexResult) -> str:
    lines = ['<skill-index trusted="true" content="metadata-only">']
    for entry in index.entries:
        descriptor = entry.descriptor
        lines.append(
            f'  <skill name="{escape(descriptor.name, quote=True)}" '
            f'version="{escape(descriptor.version, quote=True)}" '
            f'description="{escape(descriptor.description, quote=True)}" '
            f'trust-provenance="{escape(descriptor.source, quote=True)}" '
            f'query-token-overlap="{entry.query_token_overlap}">'
        )
        for tool_id in descriptor.required_tools:
            lines.append(f'    <required-tool id="{escape(tool_id, quote=True)}" />')
        for agent in descriptor.allowed_agents:
            lines.append(f'    <allowed-agent name="{escape(agent, quote=True)}" />')
        for reference in descriptor.references:
            lines.append(
                f'    <reference path="{escape(reference.path, quote=True)}" '
                f'sha256="{reference.sha256}" size-bytes="{reference.size_bytes}" '
                f'media-type="{escape(reference.media_type, quote=True)}" />'
            )
        lines.append("  </skill>")
    lines.append("</skill-index>")
    return "\n".join(lines)


def _render_skill_reference(
    *,
    skill_name: str,
    path: str,
    media_type: str,
    content: bytes,
) -> str:
    try:
        rendered_content = escape(content.decode("utf-8"))
        encoding = "utf-8"
    except UnicodeDecodeError:
        rendered_content = base64.b64encode(content).decode("ascii")
        encoding = "base64"
    return (
        f'<skill-reference skill="{escape(skill_name, quote=True)}" '
        f'path="{escape(path, quote=True)}" '
        f'media-type="{escape(media_type, quote=True)}" encoding="{encoding}" '
        f'trusted="false">\n{rendered_content}\n</skill-reference>'
    )


def _render_skill_bundle(bundle: ResolvedSkillBundle) -> str:
    manifest = bundle.manifest
    lines = [
        f'<skill-bundle name="{escape(manifest.name, quote=True)}" '
        f'version="{escape(manifest.version, quote=True)}" '
        f'digest="{manifest.digest}" trusted="true">'
    ]
    if bundle.instruction is not None:
        lines.extend(("<bundle-instruction>", bundle.instruction, "</bundle-instruction>"))
    for member in bundle.members:
        lines.extend(
            (
                f'<skill name="{escape(member.descriptor.name, quote=True)}" '
                f'version="{escape(member.descriptor.version, quote=True)}" trusted="true">',
                member.body,
                "</skill>",
            )
        )
    lines.append("</skill-bundle>")
    return "\n".join(lines)


def _selected_record(
    replay: SkillReplayMetadata,
    *,
    reference_path: str | None = None,
    reference_sha256: str | None = None,
) -> SkillReplayRecord:
    return SkillReplayRecord(
        operation=replay.operation,
        name=replay.skill_name,
        version=replay.skill_version,
        raw_markdown_sha256=replay.raw_markdown_sha256,
        body_sha256=replay.body_sha256,
        reference_path=reference_path,
        reference_sha256=reference_sha256,
        status=SkillSelectionStatus.SELECTED,
    )


def _rejected_record(
    operation: str,
    name: str,
    error: SkillAccessError,
    *,
    reference_path: str | None = None,
) -> SkillReplayRecord:
    replay = error.replay
    reference_sha256 = None
    if replay is not None and reference_path is not None:
        reference_sha256 = next(
            (
                reference.sha256
                for reference in replay.references
                if reference.path == reference_path
            ),
            None,
        )
    return SkillReplayRecord(
        operation=replay.operation if replay is not None else operation,
        name=replay.skill_name if replay is not None else name,
        version=replay.skill_version if replay is not None else None,
        raw_markdown_sha256=replay.raw_markdown_sha256 if replay is not None else None,
        body_sha256=replay.body_sha256 if replay is not None else None,
        reference_path=reference_path,
        reference_sha256=reference_sha256,
        status=SkillSelectionStatus.REJECTED,
        rejection_reason=error.reason.value,
    )


def _selected_bundle_record(bundle: ResolvedSkillBundle) -> SkillBundleReplayRecord:
    replay = bundle.replay
    return SkillBundleReplayRecord(
        operation="load_skill_bundle",
        name=replay.name,
        version=replay.version,
        manifest_sha256=replay.manifest_sha256,
        digest=replay.digest,
        members=tuple(
            SkillBundleMemberReplayRecord(
                name=member.name,
                version=member.version,
                raw_markdown_sha256=member.raw_markdown_sha256,
                body_sha256=member.body_sha256,
            )
            for member in replay.members
        ),
        status=SkillSelectionStatus.SELECTED,
    )


def _rejected_bundle_record(
    catalog: SkillBundleCatalog,
    name: str,
    error: SkillBundleResolutionError,
) -> SkillBundleReplayRecord:
    try:
        bundle = catalog.get(name)
    except SkillBundleResolutionError:
        return SkillBundleReplayRecord(
            operation="load_skill_bundle",
            name=name,
            version=None,
            manifest_sha256=None,
            digest=None,
            members=(),
            status=SkillSelectionStatus.REJECTED,
            rejection_reason=error.reason.value,
        )
    return SkillBundleReplayRecord(
        operation="load_skill_bundle",
        name=name,
        version=bundle.manifest.version,
        manifest_sha256=hashlib.sha256(bundle.raw_manifest).hexdigest(),
        digest=bundle.manifest.digest,
        members=(),
        status=SkillSelectionStatus.REJECTED,
        rejection_reason=error.reason.value,
    )


__all__ = ["SkillDisclosureProjection", "compose_skill_disclosure"]
