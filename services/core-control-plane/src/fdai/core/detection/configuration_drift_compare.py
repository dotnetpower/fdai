"""Pure comparison logic for frozen configuration baselines."""

from __future__ import annotations

from fdai.core.detection.configuration_drift_models import (
    ConfigurationDriftReport,
    ConfigurationObservation,
    ConfigurationResource,
    DriftFinding,
    DriftType,
    DriftVerdict,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
    plain_json_value,
)


def compare_configuration(
    baseline: FrozenConfigurationBaseline,
    observation: ConfigurationObservation,
) -> ConfigurationDriftReport:
    """Compare one frozen baseline with current evidence without inference."""

    if observation.scope != baseline.scope:
        finding = DriftFinding(
            target=observation.scope,
            field="scope",
            baseline_value=baseline.scope,
            actual_value=observation.scope,
            verdict=DriftVerdict.BLOCKED,
            drift_type=DriftType.UNAUTHORIZED,
            source=observation.source,
        )
        return _report(baseline, observation, (finding,))

    expected = {resource.key: resource for resource in baseline.resources}
    actual = {resource.key: resource for resource in observation.resources}
    findings: list[DriftFinding] = []

    for resource_key in sorted(expected.keys() | actual.keys()):
        wanted = expected.get(resource_key)
        observed = actual.get(resource_key)
        target = f"{resource_key[0]}:{resource_key[1]}"
        if wanted is None and observed is not None:
            findings.append(
                DriftFinding(
                    target=target,
                    field="presence",
                    baseline_value="absent",
                    actual_value="present",
                    verdict=DriftVerdict.FAILED,
                    drift_type=DriftType.ADDED,
                    source=observation.source,
                )
            )
            continue
        if wanted is not None and observed is None:
            complete = observation.completeness is EvidenceCompleteness.COMPLETE
            findings.append(
                DriftFinding(
                    target=target,
                    field="presence",
                    baseline_value="present",
                    actual_value="absent" if complete else "unknown",
                    verdict=DriftVerdict.FAILED if complete else DriftVerdict.BLOCKED,
                    drift_type=DriftType.REMOVED if complete else DriftType.UNKNOWN,
                    source=observation.source,
                )
            )
            continue
        if wanted is None or observed is None:  # pragma: no cover - exhaustive guard
            continue
        findings.extend(_compare_resource(wanted, observed, source=observation.source))

    expected_links = {link.key for link in baseline.links}
    actual_links = {link.key for link in observation.links}
    for link_key in sorted(expected_links | actual_links):
        target = f"{link_key[0]} {link_key[1]} {link_key[2]}"
        if link_key not in expected_links:
            findings.append(
                DriftFinding(
                    target=target,
                    field="topology",
                    baseline_value="absent",
                    actual_value="present",
                    verdict=DriftVerdict.FAILED,
                    drift_type=DriftType.ADDED,
                    source=observation.source,
                )
            )
        elif link_key not in actual_links:
            complete = observation.completeness is EvidenceCompleteness.COMPLETE
            findings.append(
                DriftFinding(
                    target=target,
                    field="topology",
                    baseline_value="present",
                    actual_value="absent" if complete else "unknown",
                    verdict=DriftVerdict.FAILED if complete else DriftVerdict.BLOCKED,
                    drift_type=DriftType.REMOVED if complete else DriftType.UNKNOWN,
                    source=observation.source,
                )
            )
        else:
            findings.append(
                DriftFinding(
                    target=target,
                    field="topology",
                    baseline_value="present",
                    actual_value="present",
                    verdict=DriftVerdict.PASSED,
                    drift_type=DriftType.UNCHANGED,
                    source=observation.source,
                )
            )

    findings.extend(_baseline_context_findings(baseline))
    return _report(baseline, observation, tuple(findings))


def _baseline_context_findings(
    baseline: FrozenConfigurationBaseline,
) -> list[DriftFinding]:
    findings: list[DriftFinding] = []
    for item in baseline.allowed_exceptions:
        findings.append(
            DriftFinding(
                target="baseline-exception",
                field="allowed_exception",
                baseline_value=item,
                actual_value="not-applicable",
                verdict=DriftVerdict.NOT_APPLICABLE,
                drift_type=DriftType.UNCHANGED,
                source=baseline.source,
            )
        )
    for item in baseline.unknown_items:
        findings.append(
            DriftFinding(
                target="baseline-unknown",
                field="unknown_item",
                baseline_value=item,
                actual_value="unknown",
                verdict=DriftVerdict.BLOCKED,
                drift_type=DriftType.UNKNOWN,
                source=baseline.source,
            )
        )
    return findings


def _compare_resource(
    baseline: ConfigurationResource,
    actual: ConfigurationResource,
    *,
    source: str,
) -> list[DriftFinding]:
    target = f"{baseline.resource_type}:{baseline.local_name}"
    findings = [_value_finding(target, "region", baseline.region, actual.region, source=source)]
    for field_name in sorted(baseline.attributes):
        baseline_value = plain_json_value(baseline.attributes[field_name])
        if field_name in actual.unauthorized_attributes:
            findings.append(
                DriftFinding(
                    target=target,
                    field=field_name,
                    baseline_value=baseline_value,
                    actual_value="unauthorized",
                    verdict=DriftVerdict.BLOCKED,
                    drift_type=DriftType.UNAUTHORIZED,
                    source=source,
                )
            )
        elif field_name in actual.unknown_attributes or field_name not in actual.attributes:
            findings.append(
                DriftFinding(
                    target=target,
                    field=field_name,
                    baseline_value=baseline_value,
                    actual_value="unknown",
                    verdict=DriftVerdict.BLOCKED,
                    drift_type=DriftType.UNKNOWN,
                    source=source,
                )
            )
        else:
            findings.append(
                _value_finding(
                    target,
                    field_name,
                    baseline_value,
                    plain_json_value(actual.attributes[field_name]),
                    source=source,
                )
            )
    return findings


def _value_finding(
    target: str,
    field_name: str,
    baseline_value: object,
    actual_value: object,
    *,
    source: str,
) -> DriftFinding:
    unchanged = baseline_value == actual_value
    return DriftFinding(
        target=target,
        field=field_name,
        baseline_value=baseline_value,
        actual_value=actual_value,
        verdict=DriftVerdict.PASSED if unchanged else DriftVerdict.FAILED,
        drift_type=DriftType.UNCHANGED if unchanged else DriftType.CHANGED,
        source=source,
    )


def _report(
    baseline: FrozenConfigurationBaseline,
    observation: ConfigurationObservation,
    findings: tuple[DriftFinding, ...],
) -> ConfigurationDriftReport:
    has_failed = any(finding.verdict is DriftVerdict.FAILED for finding in findings)
    has_blocked = any(finding.verdict is DriftVerdict.BLOCKED for finding in findings)
    if has_failed and has_blocked:
        verdict = DriftVerdict.PARTIAL
    elif has_failed:
        verdict = DriftVerdict.FAILED
    elif has_blocked:
        verdict = DriftVerdict.BLOCKED
    else:
        verdict = DriftVerdict.PASSED
    return ConfigurationDriftReport(
        baseline_version=baseline.version,
        baseline_sha256=baseline.sha256,
        scope=baseline.scope,
        observed_at=observation.observed_at,
        verdict=verdict,
        findings=findings,
    )


__all__ = ["compare_configuration"]
