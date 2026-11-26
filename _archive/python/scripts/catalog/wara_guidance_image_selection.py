"""Apply human-reviewed official Learn images to the WARA image review manifest.

The reviewed decisions live in ``reference-image-reviews.json``. This module collects the machine
evidence for each decision from public sources only (the Learn article, its public source
repository and that repository's license files), verifies it, ships the exact PNG bytes and records
the result in the manifest. Candidate discovery alone never approves an image.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

if __package__:
    from . import wara_guidance_images as images
    from .wara_guidance_image_manifest import expand_compact_manifest
else:
    import wara_guidance_images as images
    from wara_guidance_image_manifest import expand_compact_manifest

_REVIEWS_PATH = images._ROOT / "rule-catalog/guidance/azure-wara/reference-image-reviews.json"
_ASSET_DIRECTORIES = (
    "packages/service-contracts/src/fdai_service_contracts/data/wara-guidance-assets",
    "console/public/wara-guidance-assets",
)
_USER_AGENT = "fdai-image-review/1.0 (public documentation review)"
_TIMEOUT_SECONDS = 30
_PAUSE_SECONDS = 0.4
_MAXIMUM_PAGE_BYTES = 2_097_152
_MAXIMUM_IMAGE_BYTES = 2_097_152
_MAXIMUM_LICENSE_BYTES = 262_144
# Approved before this review file existed; its record carries its own rights review.
_PREVIOUSLY_APPROVED = frozenset({"1981f704-97b9-b645-9c57-33f8ded9261a"})
_FEEDBACK = re.compile(
    r"^https://github\.com/MicrosoftDocs/(?P<repo>azure-[a-z-]*docs)/blob/main/(?P<path>articles/.+\.md)$"
)
_REVIEWED_SCOPE = (
    "The public Learn article identifies its public source repository, whose license files grant "
    "the documentation and other content under CC BY 4.0. The article embeds this image, and "
    "byte-identical content (sha256 {digest}) is published in that repository at {raw_path}. "
    "The image was visually reviewed: no third-party credit, customer data or personal data is "
    "displayed. Reuse illustrates {illustrates} only and does not imply Microsoft endorsement or "
    "trademark rights."
)


class Evidence(NamedTuple):
    title: str
    revision: str
    repository: str
    article_path: str
    raw_path: str
    content: bytes


def _get(url: str, maximum: int) -> tuple[str, bytes]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "learn.microsoft.com",
        "raw.githubusercontent.com",
    }:
        raise ValueError(
            "WARA image evidence is limited to public Learn and public repository URLs"
        )
    request = Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310 - allowlisted hosts.
    with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
        final = urlsplit(response.geturl())
        if final.hostname != parsed.hostname:
            raise ValueError("WARA image evidence request was redirected to another host")
        body = response.read(maximum + 1)
    if len(body) > maximum:
        raise ValueError("WARA image evidence response exceeds its byte limit")
    time.sleep(_PAUSE_SECONDS)
    return response.geturl(), body


def _meta(html: str, name: str) -> str | None:
    found = re.search(rf'<meta name="{re.escape(name)}" content="([^"]*)"', html)
    return found.group(1) if found else None


def _repository_license_is_cc_by(repository: str) -> None:
    base = f"https://raw.githubusercontent.com/MicrosoftDocs/{repository}/main/"
    _, license_text = _get(base + "LICENSE", _MAXIMUM_LICENSE_BYTES)
    _, notice = _get(base + "ThirdPartyNotices.md", _MAXIMUM_LICENSE_BYTES)
    if b"Attribution 4.0 International" not in license_text:
        raise ValueError(f"{repository} LICENSE is not Creative Commons Attribution 4.0")
    if b"Creative Commons Attribution 4.0" not in notice:
        raise ValueError(f"{repository} notice does not license its documentation under CC BY 4.0")


def collect_evidence(review: dict[str, Any], licensed: set[str]) -> Evidence:
    """Collect and verify the public evidence for one reviewed image."""

    _, page = _get(review["source_document_url"], _MAXIMUM_PAGE_BYTES)
    html = page.decode("utf-8", "replace")
    heading = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    feedback = _FEEDBACK.fullmatch(_meta(html, "github_feedback_content_git_url") or "")
    revision = _meta(html, "git_commit_id") or ""
    if heading is None or feedback is None or not images._REVISION.fullmatch(revision):
        raise ValueError("the Learn article does not identify its public source and revision")
    title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", heading.group(1))).strip()
    if '"' in title or "<" in title:
        raise ValueError("the Learn article title is not safe to quote")
    repository = feedback.group("repo")
    media = urlsplit(review["image_url"]).path.split("/media/", 1)
    if len(media) != 2:
        raise ValueError("the reviewed image is not Learn media")
    raw_path = str(PurePosixPath(feedback.group("path")).parent / "media" / media[1])
    if repository not in licensed:
        _repository_license_is_cc_by(repository)
        licensed.add(repository)
    _, learn_image = _get(review["image_url"], _MAXIMUM_IMAGE_BYTES)
    _, repository_image = _get(
        f"https://raw.githubusercontent.com/MicrosoftDocs/{repository}/main/{raw_path}",
        _MAXIMUM_IMAGE_BYTES,
    )
    if learn_image != repository_image:
        raise ValueError("the Learn image is not byte-identical to its public repository copy")
    return Evidence(title, revision, repository, feedback.group("path"), raw_path, learn_image)


def build_record(
    review: dict[str, Any], notice: dict[str, str], evidence: Evidence
) -> dict[str, Any]:
    from fdai_service_contracts.reference_image_assets import verify_reference_image_bytes
    from fdai_service_contracts.wara_guidance import ReferenceImage

    digest = hashlib.sha256(evidence.content).hexdigest()
    reference = {
        "alt": review["alt"],
        "asset_id": f"sha256-{digest}",
        "attribution": (
            f"Microsoft and contributors, {evidence.title}. CC BY 4.0. Original image, "
            "unchanged. Microsoft trademarks remain with their owners."
        ),
        "caption": review["caption"],
        "digest": f"sha256:{digest}",
        "english_in_image_notice": notice,
        "image_url": review["image_url"],
        "license": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_document_url": review["source_document_url"],
        "source_revision": evidence.revision,
    }
    verify_reference_image_bytes(ReferenceImage.model_validate(reference), evidence.content)
    repository = f"https://github.com/MicrosoftDocs/{evidence.repository}/blob/main/"
    return {
        "decision": "selected",
        "reference_image": reference,
        "rights_review": {
            "license_evidence_url": repository + "ThirdPartyNotices.md",
            "reviewed_scope": _REVIEWED_SCOPE.format(
                digest=digest, raw_path=evidence.raw_path, illustrates=review["illustrates"]
            ),
            "source_repository_url": repository + evidence.article_path,
        },
    }


def load_reviews() -> tuple[dict[str, str], list[dict[str, Any]]]:
    value = json.loads(_REVIEWS_PATH.read_text(encoding="utf-8"))
    if value.get("schema_version") != "1.0.0" or not isinstance(value.get("reviews"), list):
        raise ValueError("WARA image reviews have an invalid envelope")
    identities = [item["recommendation_id"] for item in value["reviews"]]
    if len(identities) != len(set(identities)):
        raise ValueError("WARA image reviews contain a duplicate recommendation")
    return value["english_in_image_notice"], value["reviews"]


def _asset_path(root: str, asset_id: str) -> Path:
    return images._ROOT / root / f"{asset_id}.png"


def apply_reviews(*, fetch: bool) -> int:
    """Record every reviewed image; fetch evidence first when requested, else use shipped bytes."""

    notice, reviews = load_reviews()
    manifest = expand_compact_manifest(
        json.loads(images._MANIFEST_PATH.read_text(encoding="utf-8"))
    )
    records = {item["recommendation_id"]: item for item in manifest["recommendations"]}
    groups = {item["source_document_url"]: item for item in manifest["document_groups"]}
    licensed: set[str] = set()
    updated = 0
    for review in reviews:
        record = records.get(review["recommendation_id"])
        if record is None:
            raise ValueError("a reviewed image names an unknown recommendation")
        cited = [url for url in record["learn_document_urls"] if url in groups]
        if not any(
            candidate["image_url"] == review["image_url"]
            for url in cited
            for candidate in groups[url]["candidates"]
        ):
            raise ValueError(
                "a reviewed image is not a candidate of its recommendation's citations"
            )
        if record.get("decision") == "selected" and not fetch:
            continue
        if not fetch:
            raise ValueError("a reviewed image has no recorded evidence; run with --fetch")
        evidence = collect_evidence(review, licensed)
        built = build_record(review, notice, evidence)
        record.update(built)
        for root in _ASSET_DIRECTORIES:
            path = _asset_path(root, built["reference_image"]["asset_id"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(evidence.content)
        updated += 1
    if updated:
        images._save_manifest(manifest)
    return updated


def reviews_match_manifest() -> list[str]:
    """Return the problems between the reviewed decisions and the recorded manifest."""

    notice, reviews = load_reviews()
    manifest = images.load_image_review_manifest()
    problems: list[str] = []
    for review in reviews:
        record = manifest["recommendation_records"].get(review["recommendation_id"])
        image = (record or {}).get("reference_image")
        if record is None or record.get("decision") != "selected" or image is None:
            problems.append(f"{review['recommendation_id']}: not selected in the manifest")
            continue
        for key, expected in (
            ("alt", review["alt"]),
            ("caption", review["caption"]),
            ("english_in_image_notice", notice),
            ("image_url", review["image_url"]),
            ("source_document_url", review["source_document_url"]),
        ):
            if image[key] != expected:
                problems.append(f"{review['recommendation_id']}: {key} differs from its review")
        if review["illustrates"] not in record["rights_review"]["reviewed_scope"]:
            problems.append(f"{review['recommendation_id']}: rights scope differs from its review")
    reviewed = {review["recommendation_id"] for review in reviews}
    for identity, record in manifest["recommendation_records"].items():
        if (
            record.get("decision") == "selected"
            and identity not in reviewed
            and identity not in _PREVIOUSLY_APPROVED
        ):
            problems.append(f"{identity}: selected without a recorded review")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="collect public evidence and ship the image bytes (bounded public requests)",
    )
    arguments = parser.parse_args()
    count = apply_reviews(fetch=arguments.fetch)
    problems = reviews_match_manifest()
    for problem in problems:
        print(f"wara-image-selection: {problem}")
    print(f"wara-image-selection: {count} image(s) recorded; {len(problems)} problem(s)")
    if problems:
        raise SystemExit(1)


__all__ = ["apply_reviews", "collect_evidence", "reviews_match_manifest"]

if __name__ == "__main__":
    main()
