"""Evidence-only capture facade, hashing, custody, and in-memory stores."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from fdai.core.browser_evidence.policy import BrowserPolicyViolationError
from fdai.core.browser_evidence.redaction import (
    BrowserEvidenceUnsafeContentError,
    redact_browser_text,
    scan_prompt_injection,
)
from fdai.core.browser_evidence.storage import (
    InMemoryBrowserEvidenceArtifactStore,
    InMemoryBrowserEvidenceCustodySink,
    StateStoreBrowserEvidenceCustodySink,
    verify_stored_browser_evidence,
)
from fdai.shared.providers.browser_evidence import (
    BrowserCaptureMaterial,
    BrowserCaptureRequest,
    BrowserEvidenceArtifact,
    BrowserEvidenceArtifactStore,
    BrowserEvidenceCustodySink,
    BrowserEvidencePayload,
    BrowserEvidenceProvider,
    BrowserEvidenceReceipt,
    BrowserOriginPolicy,
    BrowserRedactionEntry,
    StoredBrowserEvidence,
)


class BrowserEvidenceUnavailableError(RuntimeError):
    """Raised when a browser capture cannot produce trustworthy evidence."""


class BrowserOriginPolicyRegistry:
    """Immutable exact-version lookup for server-owned origin policies."""

    def __init__(self, policies: tuple[BrowserOriginPolicy, ...]) -> None:
        indexed = {(policy.policy_id, policy.version): policy for policy in policies}
        if len(indexed) != len(policies):
            raise ValueError("browser origin policy id and version MUST be unique")
        self._policies = indexed

    def get(self, policy_id: str, version: int) -> BrowserOriginPolicy:
        try:
            return self._policies[(policy_id, version)]
        except KeyError as exc:
            raise BrowserPolicyViolationError("browser origin policy is not registered") from exc


class BrowserEvidenceCaptureService:
    """Submit typed evidence capture without exposing browser interaction APIs."""

    def __init__(
        self,
        *,
        provider: BrowserEvidenceProvider,
        policies: BrowserOriginPolicyRegistry,
        artifacts: BrowserEvidenceArtifactStore,
        custody: BrowserEvidenceCustodySink,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._policies = policies
        self._artifacts = artifacts
        self._custody = custody
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def capture(self, request: BrowserCaptureRequest) -> BrowserEvidenceReceipt:
        """Capture and persist evidence, returning unavailable on runtime failure."""

        try:
            policy = self._policies.get(request.policy_id, request.policy_version)
            if len(request.stable_selectors) > policy.limits.max_selectors:
                raise BrowserPolicyViolationError("browser stable selector count exceeds policy")
            material = await asyncio.wait_for(
                self._provider.capture(policy=policy, request=request),
                timeout=policy.limits.timeout_seconds,
            )
            sanitized, redactions = _sanitize_material(policy, material)
            captured_at = self._clock()
            content_digest = _content_digest(
                request=request,
                material=sanitized,
                redactions=redactions,
                captured_at=captured_at,
            )
            custody_ref = await self._custody.record_capture(
                request_id=request.request_id,
                policy_ref=f"{policy.policy_id}@{policy.version}",
                content_digest=content_digest,
                captured_at=captured_at,
                correlation_id=request.correlation_id,
            )
            artifact = _artifact(
                policy=policy,
                material=sanitized,
                redactions=redactions,
                captured_at=captured_at,
                custody_ref=custody_ref,
                content_digest=content_digest,
            )
            await self._artifacts.put(
                StoredBrowserEvidence(
                    artifact=artifact,
                    payload=BrowserEvidencePayload(
                        screenshot=sanitized.screenshot,
                        visible_text=sanitized.visible_text,
                        aria_snapshot=sanitized.aria_snapshot,
                    ),
                )
            )
            return BrowserEvidenceReceipt(
                request_id=request.request_id,
                status="captured",
                artifact_id=artifact.artifact_id,
                content_digest=artifact.content_digest,
                chain_of_custody_audit_ref=custody_ref,
                reason=None,
            )
        except BrowserPolicyViolationError:
            return _failed_receipt(request.request_id, "abstained", "policy_denied")
        except TimeoutError:
            return _failed_receipt(request.request_id, "unavailable", "capture_timeout")
        except (BrowserEvidenceUnavailableError, BrowserEvidenceUnsafeContentError):
            return _failed_receipt(request.request_id, "unavailable", "unsafe_or_unavailable")
        except Exception:
            return _failed_receipt(request.request_id, "unavailable", "adapter_failure")


def _sanitize_material(
    policy: BrowserOriginPolicy,
    material: BrowserCaptureMaterial,
) -> tuple[BrowserCaptureMaterial, tuple[BrowserRedactionEntry, ...]]:
    if not material.isolation.verified:
        raise BrowserEvidenceUnavailableError("browser runtime isolation is not verified")
    if material.response_bytes > policy.limits.max_response_bytes:
        raise BrowserEvidenceUnavailableError("browser response exceeds byte limit")
    if (
        material.screenshot is not None
        and len(material.screenshot) > policy.limits.max_screenshot_bytes
    ):
        raise BrowserEvidenceUnavailableError("browser screenshot exceeds byte limit")
    required_masks = set(policy.sensitive_region_selectors)
    if not required_masks.issubset(material.redacted_selectors):
        raise BrowserEvidenceUnavailableError("browser screenshot redaction is incomplete")
    for marker in policy.secret_canary_markers:
        if material.screenshot is not None and marker.encode() in material.screenshot:
            raise BrowserEvidenceUnavailableError("browser screenshot contains a secret canary")
    manifest = list(material.redactions)
    visible_text = material.visible_text
    if visible_text is not None:
        text = redact_browser_text(
            visible_text,
            surface="visible_text",
            patterns=policy.text_redaction_patterns,
            canary_markers=policy.secret_canary_markers,
            max_chars=policy.limits.max_text_chars,
        )
        visible_text = text.value
        manifest.extend(text.manifest)
    aria_snapshot = material.aria_snapshot
    if aria_snapshot is not None:
        snapshot = redact_browser_text(
            aria_snapshot,
            surface="aria_snapshot",
            patterns=policy.text_redaction_patterns,
            canary_markers=policy.secret_canary_markers,
            max_chars=policy.limits.max_snapshot_chars,
        )
        aria_snapshot = snapshot.value
        manifest.extend(snapshot.manifest)
    sanitized = BrowserCaptureMaterial(
        canonical_source_url=material.canonical_source_url,
        canonical_final_url=material.canonical_final_url,
        screenshot=material.screenshot,
        visible_text=visible_text,
        aria_snapshot=aria_snapshot,
        selectors=material.selectors,
        redacted_selectors=material.redacted_selectors,
        redactions=tuple(manifest),
        browser_version=material.browser_version,
        isolation=material.isolation,
        response_bytes=material.response_bytes,
    )
    return sanitized, tuple(manifest)


def _artifact(
    *,
    policy: BrowserOriginPolicy,
    material: BrowserCaptureMaterial,
    redactions: tuple[BrowserRedactionEntry, ...],
    captured_at: datetime,
    custody_ref: str,
    content_digest: str,
) -> BrowserEvidenceArtifact:
    return BrowserEvidenceArtifact(
        artifact_id=f"sha256:{content_digest}",
        policy_id=policy.policy_id,
        policy_version=policy.version,
        canonical_source_url=material.canonical_source_url,
        canonical_final_url=material.canonical_final_url,
        captured_at=captured_at,
        selectors=material.selectors,
        screenshot_hash=_optional_hash(material.screenshot),
        text_hash=_optional_hash(material.visible_text),
        snapshot_hash=_optional_hash(material.aria_snapshot),
        redaction_manifest=redactions,
        browser_version=material.browser_version,
        chain_of_custody_audit_ref=custody_ref,
        content_digest=content_digest,
        prompt_injection_findings=scan_prompt_injection(
            material.visible_text,
            material.aria_snapshot,
        ),
        isolation=material.isolation,
        expires_at=captured_at + timedelta(days=policy.retention_days),
    )


def _content_digest(
    *,
    request: BrowserCaptureRequest,
    material: BrowserCaptureMaterial,
    redactions: tuple[BrowserRedactionEntry, ...],
    captured_at: datetime,
) -> str:
    payload = {
        "policy": f"{request.policy_id}@{request.policy_version}",
        "source_url": material.canonical_source_url,
        "final_url": material.canonical_final_url,
        "captured_at": captured_at.isoformat(),
        "selectors": material.selectors,
        "screenshot_hash": _optional_hash(material.screenshot),
        "text_hash": _optional_hash(material.visible_text),
        "snapshot_hash": _optional_hash(material.aria_snapshot),
        "redactions": [asdict(entry) for entry in redactions],
        "browser_version": material.browser_version,
        "isolation": asdict(material.isolation),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _optional_hash(value: bytes | str | None) -> str | None:
    if value is None:
        return None
    encoded = value if isinstance(value, bytes) else value.encode()
    return hashlib.sha256(encoded).hexdigest()


def _failed_receipt(request_id: str, status: str, reason: str) -> BrowserEvidenceReceipt:
    return BrowserEvidenceReceipt(
        request_id=request_id,
        status=status,  # type: ignore[arg-type]
        artifact_id=None,
        content_digest=None,
        chain_of_custody_audit_ref=None,
        reason=reason,
    )


__all__ = [
    "BrowserEvidenceCaptureService",
    "BrowserEvidenceUnavailableError",
    "BrowserOriginPolicyRegistry",
    "InMemoryBrowserEvidenceArtifactStore",
    "InMemoryBrowserEvidenceCustodySink",
    "StateStoreBrowserEvidenceCustodySink",
    "verify_stored_browser_evidence",
]
