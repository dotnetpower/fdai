"""Bounded public Learn discovery; candidates never grant redistribution approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

_MAXIMUM_PAGE_BYTES = 2_097_152
_MAXIMUM_PAGE_REQUESTS = 20
_PAGE_TIMEOUT_SECONDS = 12
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


class LearnRateLimitError(RuntimeError):
    """A public Learn response asked the bounded reviewer to stop."""


class _LearnRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):  # type: ignore[no-untyped-def]
        parsed = urlsplit(new_url)
        if parsed.scheme != "https" or parsed.hostname != "learn.microsoft.com":
            raise ValueError("cross-origin Learn redirect was rejected")
        return super().redirect_request(request, file, code, message, headers, new_url)


class _PageImages(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[dict[str, str]] = []
        self.title = ""
        self.heading = ""
        self._active_title = False
        self._active_heading = False
        self._title_parts: list[str] = []
        self._heading_parts: list[str] = []
        self.metadata: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        if tag == "title":
            self._active_title = True
        elif tag == "h1" and not self.heading:
            self._active_heading = True
        elif tag == "meta":
            key = values.get("name", "").casefold()
            content = values.get("content", "").strip()
            if key and content and key in {"ms.date", "git_commit_id", "gitcommit"}:
                self.metadata[key] = content
        elif tag == "img":
            sources = [
                values.get(name, "")
                for name in ("src", "data-src", "data-lazy-src", "data-original-src")
            ]
            srcset = values.get("srcset", "")
            if srcset:
                sources.append(srcset.split(",", 1)[0].strip().split(" ", 1)[0])
            for source in sources:
                if source:
                    self.candidates.append(
                        {
                            "src": source,
                            "alt": values.get("alt", "").strip(),
                            "title": values.get("title", "").strip(),
                        }
                    )

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._active_title = False
            self.title = " ".join(" ".join(self._title_parts).split())
        elif tag == "h1":
            self._active_heading = False
            if not self.heading:
                self.heading = " ".join(" ".join(self._heading_parts).split())

    def handle_data(self, data: str) -> None:
        if self._active_title:
            self._title_parts.append(data)
        if self._active_heading:
            self._heading_parts.append(data)


def _request_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "learn.microsoft.com":
        raise ValueError("only exact public Microsoft Learn citations can be inspected")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _image_candidates(parser: _PageImages, base_url: str) -> list[dict[str, str]]:
    candidates: dict[str, dict[str, str]] = {}
    for candidate in parser.candidates:
        resolved = urljoin(base_url, candidate["src"])
        parsed = urlsplit(resolved)
        suffix = Path(parsed.path).suffix.casefold()
        if (
            parsed.scheme != "https"
            or parsed.hostname != "learn.microsoft.com"
            or "/media/" not in parsed.path.casefold()
            or suffix not in _IMAGE_SUFFIXES
        ):
            continue
        image_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
        candidates[image_url] = {
            "image_url": image_url,
            "alt": candidate["alt"],
            "title": candidate["title"],
            "suitability": "requires_visual_and_rights_review",
        }
    return [candidates[url] for url in sorted(candidates)]


def _fetch_document(url: str) -> dict[str, object]:
    request_url = _request_url(url)
    request = Request(  # noqa: S310 - URL and every redirect are restricted to Learn HTTPS.
        request_url,
        headers={
            "Accept": "text/html",
            "User-Agent": "FDAI WARA public documentation image review",
        },
    )
    opener = build_opener(_LearnRedirectHandler())
    try:
        with opener.open(request, timeout=_PAGE_TIMEOUT_SECONDS) as response:
            status = response.status
            if status in {429, 503}:
                raise LearnRateLimitError(f"Microsoft Learn returned HTTP {status}")
            content_type = response.headers.get_content_type()
            body = response.read(_MAXIMUM_PAGE_BYTES + 1)
            final_url = response.geturl()
    except HTTPError as exc:
        if exc.code in {429, 503}:
            raise LearnRateLimitError(f"Microsoft Learn returned HTTP {exc.code}") from exc
        return {
            "inspection_status": "fetch_failed",
            "candidate_suitability": "not_assessed",
            "inspection_reason": f"The exact cited Learn URL returned HTTP {exc.code}.",
            "inspection": {"http_status": exc.code, "request_url": request_url},
            "candidates": [],
        }
    except (TimeoutError, URLError, ValueError) as exc:
        return {
            "inspection_status": "fetch_failed",
            "candidate_suitability": "not_assessed",
            "inspection_reason": (
                "The cited Learn page could not be inspected with the bounded same-origin "
                f"request ({type(exc).__name__}). No alternate transport was attempted."
            ),
            "inspection": {"request_url": request_url},
            "candidates": [],
        }
    if len(body) > _MAXIMUM_PAGE_BYTES:
        return {
            "inspection_status": "fetch_failed",
            "candidate_suitability": "not_assessed",
            "inspection_reason": "The cited Learn page exceeded the bounded response size.",
            "inspection": {"http_status": status, "request_url": request_url},
            "candidates": [],
        }
    if status != 200 or content_type != "text/html":
        return {
            "inspection_status": "fetch_failed",
            "candidate_suitability": "not_assessed",
            "inspection_reason": (
                f"The cited Learn URL returned HTTP {status} with content type {content_type}."
            ),
            "inspection": {"http_status": status, "request_url": request_url},
            "candidates": [],
        }

    parser = _PageImages()
    parser.feed(body.decode("utf-8", errors="replace"))
    candidates = _image_candidates(parser, final_url)
    if candidates:
        suitability = "potential_candidates_require_visual_and_rights_review"
        reason = (
            "The inspected cited document embeds media images listed below. Automated page "
            "metadata does not establish visual suitability or redistribution rights."
        )
    else:
        suitability = "no_embedded_candidate_found_in_cited_document"
        reason = (
            "No Learn media image was found in the inspected exact document. This does not "
            "establish that no suitable image exists in another document."
        )
    git_revision = re.search(
        rb"(?:git_commit_id|gitcommit)[\"'\\s:=]+([a-f0-9]{40})", body, re.IGNORECASE
    )
    return {
        "inspection_status": "inspected",
        "candidate_suitability": suitability,
        "inspection_reason": reason,
        "inspection": {
            "http_status": status,
            "request_url": request_url,
            "final_url": final_url,
            "title": parser.title,
            "heading": parser.heading,
            "updated_at": parser.metadata.get("ms.date"),
            "source_revision": git_revision.group(1).decode("ascii") if git_revision else None,
            "page_digest": "sha256:" + hashlib.sha256(body).hexdigest(),
            "candidate_count": len(candidates),
        },
        "candidates": candidates,
    }


def inspect_next_documents(maximum_requests: int) -> None:
    if __package__:
        from .wara_guidance_images import _save_manifest, load_image_review_manifest
    else:
        from wara_guidance_images import _save_manifest, load_image_review_manifest

    if not 1 <= maximum_requests <= _MAXIMUM_PAGE_REQUESTS:
        raise ValueError(f"Learn inspection batch must be between 1 and {_MAXIMUM_PAGE_REQUESTS}")
    manifest = load_image_review_manifest()
    groups = manifest["document_groups"]
    existing_requests: dict[str, dict[str, object]] = {}
    for group in groups:
        if group["inspection_status"] == "inspected":
            existing_requests.setdefault(
                _request_url(group["source_document_url"]),
                {
                    key: group[key]
                    for key in (
                        "inspection_status",
                        "candidate_suitability",
                        "inspection_reason",
                        "inspection",
                        "candidates",
                    )
                },
            )
    pending: dict[str, list[dict[str, Any]]] = {}
    for group in groups:
        if group["inspection_status"] == "unreviewed":
            request_url = _request_url(group["source_document_url"])
            pending.setdefault(request_url, []).append(group)
    requests_done = 0
    for request_url, same_page_groups in sorted(pending.items()):
        if request_url in existing_requests:
            inspection = existing_requests[request_url]
        else:
            if requests_done >= maximum_requests:
                break
            try:
                inspection = _fetch_document(request_url)
            except LearnRateLimitError:
                _save_manifest(manifest)
                raise
            requests_done += 1
            existing_requests[request_url] = inspection
            time.sleep(0.25)
        for group in same_page_groups:
            group.update(inspection)
        _save_manifest(manifest)


def main() -> None:
    if __package__:
        from .wara_guidance_images import load_image_review_manifest, refresh_inventory
    else:
        from wara_guidance_images import load_image_review_manifest, refresh_inventory

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-inventory",
        action="store_true",
        help="Reconcile exact Learn URLs while preserving reviewed groups.",
    )
    parser.add_argument(
        "--inspect-learn-pages",
        type=int,
        default=0,
        metavar="COUNT",
        help=f"Inspect up to {_MAXIMUM_PAGE_REQUESTS} pending Learn pages serially; no retries.",
    )
    arguments = parser.parse_args()
    if arguments.refresh_inventory:
        refresh_inventory()
    try:
        if arguments.inspect_learn_pages:
            inspect_next_documents(arguments.inspect_learn_pages)
        manifest = load_image_review_manifest()
    except LearnRateLimitError as exc:
        print(f"Stopped without retrying: {exc}")
        raise SystemExit(2) from exc
    print(json.dumps(manifest["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
