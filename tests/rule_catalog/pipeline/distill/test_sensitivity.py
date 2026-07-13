"""Tests for the deterministic sensitivity guard (secret + PII scan).

Secret-looking trigger strings are assembled at runtime via concatenation so no
full secret literal sits in the source tree - this keeps the repo's gitleaks
gate clean while still exercising the detectors on the concatenated value.
"""

from __future__ import annotations

import pytest

from fdai.rule_catalog.pipeline.distill.sensitivity import (
    SensitivityDisposition,
    SensitivityFinding,
    SensitivityKind,
    scan_sensitivity,
    scan_text,
)
from fdai.shared.providers.distiller import ManualDocument


def _doc(text: str) -> ManualDocument:
    return ManualDocument(doc_id="d", text=text, source_ref="drop://d")


def test_finding_rejects_non_positive_line() -> None:
    with pytest.raises(ValueError, match="1-based"):
        SensitivityFinding(SensitivityKind.SECRET, "email", 0)


def test_clean_manual_is_clear() -> None:
    report = scan_sensitivity(_doc("# Restart runbook\nRestart the pod, then verify.\n"))
    assert report.is_clear
    assert report.disposition is SensitivityDisposition.CLEAR
    assert report.findings == ()


def test_findings_never_carry_the_matched_value() -> None:
    secret = "AKIA" + "IOSFODNN7" + "EXAMPLE"  # synthetic AWS-shaped key
    report = scan_sensitivity(_doc(f"key = {secret}\n"))
    assert not report.is_clear
    # The report exposes only kind/label/line - never the secret text.
    for finding in report.findings:
        assert secret not in finding.label
        assert secret not in str(finding.line)


def test_detects_private_key_header() -> None:
    header = "-----BEGIN " + "PRIVATE KEY" + "-----"
    report = scan_sensitivity(_doc(f"line1\n{header}\n"))
    assert report.disposition is SensitivityDisposition.HOLD
    labels = {(f.kind, f.label, f.line) for f in report.findings}
    assert (SensitivityKind.SECRET, "private-key", 2) in labels


def test_detects_connection_string_account_key() -> None:
    conn = "DefaultEndpointsProtocol=https;" + "AccountKey=" + "abcd1234efgh5678;"
    report = scan_sensitivity(_doc(conn))
    assert any(f.label == "connection-string" for f in report.findings)


def test_detects_jwt() -> None:
    token = "eyJ" + "abcdEFGH12" + "." + "payload9876" + "." + "sigPart"
    report = scan_sensitivity(_doc(f"Authorization: Bearer {token}"))
    assert any(f.label == "jwt" for f in report.findings)


def test_detects_credential_assignment_but_skips_placeholder() -> None:
    real = scan_sensitivity(_doc("password: hunter2secret\n"))
    assert real.disposition is SensitivityDisposition.HOLD
    assert any(f.label == "credential-assignment" for f in real.findings)

    placeholder = scan_sensitivity(_doc("password: <your-password-here>\n"))
    assert placeholder.is_clear

    starred = scan_sensitivity(_doc("password: ********\n"))
    assert starred.is_clear

    bare_word = scan_sensitivity(_doc("password: example\n"))
    assert bare_word.is_clear


def test_placeholder_substring_does_not_suppress_real_secret() -> None:
    # Regression: a real credential that merely CONTAINS a placeholder word
    # (example / sample / ...) must still be flagged - the placeholder skip is
    # whole-value, never substring, so the guard stays fail-closed.
    for value in ("Sample#2024!Prod", "example-Ab12cd34XY", "changeme-butActuallyReal9"):
        report = scan_sensitivity(_doc(f"password: {value}\n"))
        assert report.disposition is SensitivityDisposition.HOLD, value
        assert any(f.label == "credential-assignment" for f in report.findings)


def test_detects_email_pii() -> None:
    report = scan_sensitivity(_doc("Escalate to jane.doe@contoso.example for approval.\n"))
    assert any(f.kind is SensitivityKind.PII and f.label == "email" for f in report.findings)


def test_detects_phone_pii() -> None:
    report = scan_sensitivity(_doc("On-call: 555-123-4567 (primary).\n"))
    assert any(f.label == "phone" for f in report.findings)


def test_detects_luhn_valid_card_but_not_random_digits() -> None:
    valid = scan_sensitivity(_doc("card 4111 1111 1111 1111 on file\n"))
    assert any(f.label == "card-number" for f in valid.findings)

    # A 16-digit run that fails Luhn is not flagged as a card.
    invalid = scan_sensitivity(_doc("order 1234 5678 9012 3456 shipped\n"))
    assert not any(f.label == "card-number" for f in invalid.findings)


def test_line_numbers_are_one_based() -> None:
    text = "clean line\nclean line\ncontact bob@acme.example now\n"
    findings = scan_text(text)
    assert findings
    assert all(f.line == 3 for f in findings)


def test_multiple_findings_aggregate_to_hold() -> None:
    text = "email a@b.example\npassword: realpassword123\n"
    report = scan_sensitivity(_doc(text))
    assert report.disposition is SensitivityDisposition.HOLD
    assert len(report.findings) >= 2
