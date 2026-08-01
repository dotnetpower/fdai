"""Coverage report + stale-OID audit tests."""

from __future__ import annotations

from fdai.core.stewardship import (
    StaticIdentityDirectory,
    audit_stale_oids,
    build_coverage_report,
    load_stewardship_from_mapping,
)


def test_distinct_stewards_no_over_assigned(valid_raw: dict) -> None:
    mp = load_stewardship_from_mapping(valid_raw)
    rep = build_coverage_report(mp)
    codes = {f.code for f in rep.findings}
    assert "over_assigned" not in codes
    # Each mapped agent has exactly one accountable steward -> bus-factor 1.
    assert "bus_factor_one" in codes
    assert "duty_derived" in codes
    assert "backup_missing" in codes


def test_second_accountable_steward_satisfies_v1_backup(valid_raw: dict, oid) -> None:
    valid_raw["stewardship"]["agents"]["Thor"]["stewards"].append(
        {"kind": "user", "id": oid(700), "responsibility": "accountable"}
    )

    report = build_coverage_report(load_stewardship_from_mapping(valid_raw))

    thor_codes = {finding.code for finding in report.findings if finding.agent == "Thor"}
    assert "duty_derived" in thor_codes
    assert "backup_missing" not in thor_codes


def test_maintainer_single_warns(valid_raw: dict, oid) -> None:
    valid_raw["stewardship"]["maintainers"] = [{"oid": oid(1)}]
    mp = load_stewardship_from_mapping(valid_raw)
    rep = build_coverage_report(mp)
    assert any(f.code == "maintainer_single" for f in rep.warnings)


def test_over_assigned_warns(valid_raw: dict, oid) -> None:
    shared = oid(500)
    # Make one person accountable for 6 agents (> default threshold 5).
    for name in ("Odin", "Thor", "Forseti", "Huginn", "Heimdall", "Vidar"):
        valid_raw["stewardship"]["agents"][name] = {
            "stewards": [{"kind": "user", "id": shared, "responsibility": "accountable"}]
        }
    mp = load_stewardship_from_mapping(valid_raw)
    rep = build_coverage_report(mp)
    assert any(f.code == "over_assigned" for f in rep.warnings)


def test_autonomous_is_info_not_warn(valid_raw: dict) -> None:
    mp = load_stewardship_from_mapping(valid_raw)
    rep = build_coverage_report(mp)
    loki = [f for f in rep.findings if f.agent == "Loki"]
    assert loki and loki[0].code == "autonomous_no_steward"
    assert loki[0] not in rep.warnings


async def test_stale_oid_audit_flags_missing(valid_raw: dict, oid) -> None:
    mp = load_stewardship_from_mapping(valid_raw)
    # Only maintainer oid(1) is active; everyone else is stale.
    directory = StaticIdentityDirectory(active_oids={oid(1)})
    findings = await audit_stale_oids(mp, directory)
    codes = {f.code for f in findings}
    assert codes == {"stale_oid"}
    assert any("Maintainer" in f.message for f in findings)


async def test_stale_oid_audit_clean_when_all_active(valid_raw: dict) -> None:
    mp = load_stewardship_from_mapping(valid_raw)
    # Empty directory + assume_active -> nothing is stale.
    directory = StaticIdentityDirectory(assume_active=True)
    findings = await audit_stale_oids(mp, directory)
    assert findings == ()
