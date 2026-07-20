from __future__ import annotations

from collections import defaultdict

import pytest

from fdai.core.browser_evidence.contracts import (
    BrowserCaptureLimits,
    BrowserOriginPolicy,
    BrowserRedirectPolicy,
    TrustedBrowserDestination,
)
from fdai.core.browser_evidence.policy import (
    BrowserPolicyViolationError,
    BrowserUrlPolicyValidator,
)


class SequencedResolver:
    def __init__(self, answers: dict[str, tuple[tuple[str, ...], ...]]) -> None:
        self._answers = answers
        self.calls: defaultdict[str, int] = defaultdict(int)

    async def resolve(self, hostname: str) -> tuple[str, ...]:
        index = self.calls[hostname]
        self.calls[hostname] += 1
        answers = self._answers[hostname]
        return answers[min(index, len(answers) - 1)]


def _policy(
    *,
    host: str = "dashboard.example",
    trusted_destinations: tuple[TrustedBrowserDestination, ...] = (),
) -> BrowserOriginPolicy:
    return BrowserOriginPolicy(
        policy_id="browser-dashboard",
        version=1,
        allowed_schemes=("https",),
        allowed_hosts=(host,),
        allowed_path_prefixes=("/evidence",),
        auth_profile_ref="dashboard-reader",
        redirect_policy=BrowserRedirectPolicy(
            max_redirects=3,
            trusted_destinations=trusted_destinations,
        ),
        limits=BrowserCaptureLimits(
            max_response_bytes=100_000,
            max_text_chars=4_000,
            max_snapshot_chars=8_000,
            timeout_seconds=5.0,
        ),
    )


async def test_unicode_hostname_is_canonicalized_to_idna() -> None:
    resolver = SequencedResolver({"xn--bcher-kva.example": (("93.184.216.34",),)})
    validator = BrowserUrlPolicyValidator(
        policy=_policy(host="xn--bcher-kva.example"),
        resolver=resolver,
    )

    result = await validator.validate_navigation("https://B\u00dcCHER.example/evidence/summary")

    assert result.url == "https://xn--bcher-kva.example/evidence/summary"
    assert result.hostname == "xn--bcher-kva.example"


@pytest.mark.parametrize(
    ("url", "addresses", "reason"),
    [
        ("file:///etc/passwd", {}, "scheme"),
        ("chrome-extension://example/page", {}, "scheme"),
        ("http://dashboard.example/evidence", {}, "scheme"),
        ("https://dashboard.example/admin", {"dashboard.example": (("93.184.216.34",),)}, "path"),
        (
            "https://dashboard.example/evidence/%2e%2e/admin",
            {"dashboard.example": (("93.184.216.34",),)},
            "path",
        ),
        ("https://127.0.0.1/evidence", {"127.0.0.1": (("127.0.0.1",),)}, "address"),
        (
            "https://metadata.example/evidence",
            {"metadata.example": (("169.254.169.254",),)},
            "address",
        ),
        (
            "https://dashboard.example/evidence",
            {"dashboard.example": (("10.0.0.4",),)},
            "address",
        ),
    ],
)
async def test_unsafe_navigation_fails_closed(
    url: str,
    addresses: dict[str, tuple[tuple[str, ...], ...]],
    reason: str,
) -> None:
    host = (
        "metadata.example"
        if "metadata" in url
        else "127.0.0.1"
        if "127.0.0.1" in url
        else "dashboard.example"
    )
    validator = BrowserUrlPolicyValidator(
        policy=_policy(host=host),
        resolver=SequencedResolver(addresses),
    )

    with pytest.raises(BrowserPolicyViolationError, match=reason):
        await validator.validate_navigation(url)


async def test_exact_trusted_cross_origin_redirect_is_allowed() -> None:
    resolver = SequencedResolver(
        {
            "dashboard.example": (("93.184.216.34",),),
            "identity.example": (("93.184.216.35",),),
        }
    )
    validator = BrowserUrlPolicyValidator(
        policy=_policy(
            trusted_destinations=(
                TrustedBrowserDestination(
                    scheme="https",
                    host="identity.example",
                    path_prefixes=("/signin/complete",),
                ),
            )
        ),
        resolver=resolver,
    )
    source = await validator.validate_navigation("https://dashboard.example/evidence")

    target = await validator.validate_redirect(
        "https://identity.example/signin/complete",
        source=source,
        redirect_count=1,
    )

    assert target.url == "https://identity.example/signin/complete"


async def test_untrusted_cross_origin_redirect_is_denied() -> None:
    resolver = SequencedResolver(
        {
            "dashboard.example": (("93.184.216.34",),),
            "other.example": (("93.184.216.35",),),
        }
    )
    validator = BrowserUrlPolicyValidator(policy=_policy(), resolver=resolver)
    source = await validator.validate_navigation("https://dashboard.example/evidence")

    with pytest.raises(BrowserPolicyViolationError, match="cross-origin"):
        await validator.validate_redirect(
            "https://other.example/evidence",
            source=source,
            redirect_count=1,
        )


async def test_dns_rebinding_is_denied_on_revalidation() -> None:
    resolver = SequencedResolver({"dashboard.example": (("93.184.216.34",), ("93.184.216.35",))})
    validator = BrowserUrlPolicyValidator(policy=_policy(), resolver=resolver)
    await validator.validate_navigation("https://dashboard.example/evidence")

    with pytest.raises(BrowserPolicyViolationError, match="rebinding"):
        await validator.validate_connection("https://dashboard.example/evidence")

    assert resolver.calls["dashboard.example"] == 2


@pytest.mark.parametrize(
    "answers",
    [
        {},
        {"dashboard.example": ((),)},
        {"dashboard.example": (("93.184.216.34", "10.0.0.4"),)},
        {"dashboard.example": (("not-an-address",),)},
    ],
)
async def test_dns_errors_empty_mixed_and_invalid_answers_fail_closed(
    answers: dict[str, tuple[tuple[str, ...], ...]],
) -> None:
    validator = BrowserUrlPolicyValidator(
        policy=_policy(),
        resolver=SequencedResolver(answers),
    )

    with pytest.raises(BrowserPolicyViolationError, match="DNS"):
        await validator.validate_navigation("https://dashboard.example/evidence")


def test_origin_policy_rejects_credential_query_keys() -> None:
    with pytest.raises(ValueError, match="credentials"):
        BrowserOriginPolicy(
            policy_id="unsafe-query",
            version=1,
            allowed_schemes=("https",),
            allowed_hosts=("dashboard.example",),
            allowed_path_prefixes=("/evidence",),
            auth_profile_ref="reader",
            redirect_policy=BrowserRedirectPolicy(max_redirects=0),
            limits=BrowserCaptureLimits(
                max_response_bytes=100,
                max_text_chars=100,
                max_snapshot_chars=100,
                timeout_seconds=1,
            ),
            allowed_query_keys=("access_token",),
        )
