"""Bounded content critique: explicit uncertainties, not invented live validation."""
# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from wara_guidance_reliability import localized as text
from wara_guidance_resolutions import RESOLUTIONS, resolution_report

# Source concerns that triggered deeper authoring; resolutions are recorded below.
UNCERTAIN = {
    "e7dbd21f": "Title says Disabled Fallback Route but description warns against disabling fallback. Action polarity requires manual source interpretation.",
    "98bd7098": "Source overgeneralizes resource-group metadata region into resource placement. Universal relocation is not justified.",
    "ee4dc309": "Title concerns SAP shared-file replication or backup, but description discusses monitoring. Required protection method is not established by that description.",
    "a18d60f8": "Delta time-travel title is specific, but description does not define retained-version selection, recovery semantics or supported ETL repair procedure.",
    "c15b2b73": "Source says standard FSLogix configuration without naming supported baseline values. No universal configuration values are invented.",
    "c041d596": "The 4000 VDA source limit concerns Citrix Managed Azure subscriptions, not all Azure subscriptions; current vendor limit and catalog scope need confirmation.",
    "1c6c97d7": "Direct Internet routing for trusted AVD control-plane traffic requires current service destinations and security review. It does not justify blanket inspection bypass.",
    "38721758": "Disabled source describes ASR as replication or backup and mentions region or zone. Exact supported replication topology must be confirmed; ASR is not an independent backup.",
    "63491f70": "Pinned ACR metadata describes an optional zone setting; current tier and region service behavior must be checked before prescribing an explicit toggle.",
    "84636c6c": "Pinned Event Hubs metadata contrasts portal and IaC defaults. Current namespace and tier behavior is not established by those historical defaults.",
    "b376281d": "AI Search replica count and zone distribution vary with service support and generation. A replica count alone cannot prove current zone placement.",
    "9ec5b4c8": "AVS stretched-cluster creation, quota, SLA and synchronous vSAN claims are source-specific. Current eligibility and application-level recovery need separate verification.",
    "740f2c1c": "APIM source describes gateway and control-plane zone replication together. Current tier and platform scope must be verified before extending a gateway claim to every management component.",
    "4884cada": "SAP and ANF timeout values depend on the supported application, OS and client stack. The source does not supply a universal numeric timeout.",
    "6648fe61": "Source requests correct HANA Pacemaker parameters without enumerating the supported cluster contract. A complete current vendor HA configuration is still needed.",
    "9d8f6678": "Source requests correct ASCS Pacemaker parameters without enumerating the supported cluster contract. A complete current vendor HA configuration is still needed.",
}

CORRECTED_BINDINGS = {
    "8aa63c34": "Regional isolation here means Databricks workspace/control-plane locality, not a secondary workspace or regional traffic failover.",
    "89928e61": "Regional Application Insights resources provide monitoring coverage, not model-request traffic failover.",
    "611c7c96": "ML registry replication distributes artifacts; it is not gateway routing or automatic training-job failover.",
    "b14ee8ed": "Image-version regional replicas protect deployable artifacts, not running VM or application state.",
    "36ea6c09": "Registry geo-replication distributes image artifacts and pull availability, not workload-state recovery.",
    "a3058909": "Domain Services replica sets are explicit replicas with network prerequisites, not a generic customer gateway failover mechanism.",
    "b49a39fd": "The three-image-replica source recommendation concerns parallel deployment capacity and throttling, not a three-instance application HA guarantee.",
    "41f0d88e": "SAP backup and ASR are distinct choices in a component recovery plan, not equivalent independent backups.",
    "ee4dc309": "SAP shared-file protection needs an explicit recovery choice; the source description only addresses monitoring.",
}

SPECIFICS = {
    "8aa63c34": (
        "The source concerns an in-region Databricks control plane and regional isolation, not deployment of a recovery workspace.",
        "Identify workspace and control-plane locality using approved read-only evidence and review a supported migration to an available in-region control plane.",
        "Compare workspace region with control-plane location evidence and validate the supported migration's isolation effect; do not claim a secondary workspace or regional failover was created.",
    ),
    "89928e61": (
        "Regional Application Insights resources support primary and secondary ML monitoring; this does not route model requests between regions.",
        "Prepare instrumentation and collection for both workspaces and review retention in the associated Log Analytics workspaces independently.",
        "Inspect recent endpoint and workspace telemetry in each regional monitoring path and verify retention and notification coverage.",
    ),
    "611c7c96": (
        "ML registry regional replication makes supported assets accessible to workspaces; it does not automatically resubmit failed training jobs.",
        "Configure supported registry replication regions and prepare workspace access to required model, environment and component versions.",
        "Read replica readiness and validate exact asset versions can be consumed from required workspaces; check compute and workspace recovery separately.",
    ),
    "b14ee8ed": (
        "Compute Gallery image-version replication protects deployment artifacts, not the OS or data state of already running VMs.",
        "Select the required target regions for the exact image version and wait for supported replication completion before depending on recovery-region deployment.",
        "Verify per-region replication status and a supported VM deployment from that image version; assess VM data recovery independently.",
    ),
    "36ea6c09": (
        "Container Registry geo-replication distributes image artifacts and regional pull paths; application state and runtime traffic remain separate.",
        "Configure eligible Premium registry replicas and review dependent image pull identities, network paths and regional replication behavior.",
        "Validate exact image digests are available from the intended alternate-region path and inspect replication health without declaring application failover.",
    ),
    "a3058909": (
        "Domain Services replica sets require supported target regions and peered virtual network access for application authentication.",
        "Plan a supported replica set in an eligible peered VNet and preserve the managed domain's DNS and authentication reachability from each application location.",
        "Inspect replica-set location and health and verify domain resolution and authentication from required networks; do not assume peering alone creates DNS or access.",
    ),
    "b49a39fd": (
        "The source recommends at least three production image replicas to distribute concurrent deployments and reduce replica throttling.",
        "Size per-region image-version replicas for expected parallel deployments using the source's minimum as a planning baseline, with quota and cost reviewed.",
        "Inspect actual per-region replica counts and replication completion and compare concurrent VM deployment behavior with expected demand.",
    ),
    "1b8a3051": (
        "The source concerns the temporary prefer location constraint created by a Pacemaker migrate operation, not arbitrary permanent placement or safety constraints.",
        "After the authorized maintenance or test is complete, identify the exact temporary migration constraint and review supported cleanup while preserving permanent placement, quorum and fencing rules.",
        "Compare constraint identities before and after the approved cleanup and verify the intended cluster placement and failover behavior; do not remove unrelated constraints.",
    ),
    "932d45d6": (
        "Workspace asset export is not a backup of all externally stored Databricks data.",
        "Export supported workspace assets with reviewed tooling and protect referenced external data using its own supported mechanism; prepare workspace recreation from the export.",
        "Recreate a representative job, notebook and dependency reference from retained exports and verify access to independently protected data.",
    ),
    "72827434": (
        "ANF volume snapshots and independent long-term backup have different storage and failure coverage.",
        "Configure the supported volume snapshot policy and retention; review off-volume backup separately rather than presenting a snapshot as regional backup.",
        "Restore a selected retained snapshot and compare file contents and application consistency; record that loss of the source volume can affect snapshot availability.",
    ),
    "b2fb3e60": (
        "ANF backup is separate from local volume snapshots and replication.",
        "Select the supported ANF backup policy and verify completed retained backup copies independently of the snapshot schedule.",
        "Validate restore from an actual backup copy, its age and destination requirements, not only snapshot creation.",
    ),
    "e30317d2": (
        "The pinned ANF cross-region source describes asynchronous replication and manual failover.",
        "Plan a supported destination volume and explicit break, mount, traffic-switch and resynchronization procedure; do not promise automatic failover.",
        "Inspect replication lag and destination readiness and verify the authorized failover and resync sequence with application consistency checks.",
    ),
    "e3d742e1": (
        "The pinned ANF cross-zone source also describes asynchronous replication and manual failover, not synchronous managed HA.",
        "Prepare supported source and destination zones and a controlled application failover procedure with known possible data loss.",
        "Compare last synchronized state, lag and post-failover application data; verify the manual recovery path separately from replication health.",
    ),
    "41f0d88e": (
        "SAP component backup and ASR replication are alternatives with different retention and recovery behavior.",
        "Select and document the supported protection method per SAP component. If using ASR, describe replication, recovery points and test failover without relabeling it an independent backup.",
        "Verify each component's chosen recovery evidence and dependent state, including (A)SCS, application servers and WebDispatchers, rather than one generic backup-job result.",
    ),
    "ee4dc309": (
        "SAP shared-file protection needs a selected backup or replication mechanism; the source description alone only establishes a monitoring concern.",
        "Resolve the title and description mismatch with the workload owner, choose a supported shared-file protection method and document separate monitoring and recovery steps.",
        "Inspect an actual recovery copy or replication relationship and validate shared-file recovery independently of monitoring alerts.",
    ),
    "38721758": (
        "ASR provides a supported replication and recovery workflow; it is not an independently retained backup.",
        "Keep this disabled recommendation historical and confirm the exact supported AVD session-host replication topology before proposing any recovery architecture.",
        "Check actual replication health, recovery-point age, profile dependencies and an isolated test failover; do not infer backup retention or zone support from the title.",
    ),
    "783c6c18": (
        "Device-identity export protects device registration state, not all IoT Hub configuration, telemetry or automatically working device connections.",
        "Protect and refresh the supported device-identity export for the intended secondary hub and document enrollment, endpoint and device reconnect behavior separately.",
        "Validate identity completeness and authorized import or reconciliation without revealing keys, then inspect independent device reprovisioning and reconnect evidence.",
    ),
    "1f25a3d8": (
        "The HCX source specifically names a pre-change snapshot of HCX Manager using the supported Run command.",
        "Prepare the supported HCX Manager snapshot before the maintenance or critical operation and document vendor-supported restore and snapshot cleanup.",
        "Inspect the snapshot target, successful completion and pre-change timestamp; confirm restore prerequisites rather than claiming that a snapshot is a complete AVS backup.",
    ),
    "bcfe71f1": (
        "Multiple application replicas improve instance availability but cannot guarantee application availability by themselves.",
        "Configure multiple ready replicas with scheduling, readiness, disruption and dependency requirements reviewed together; do not repeat the source's guarantee as an operational promise.",
        "Observe ready and actually serving replicas across failure domains and check application requests during a controlled replica loss.",
    ),
    "c041d596": (
        "The pinned description limits its VDA count statement to a Citrix Managed Azure subscription and excludes other machines such as Cloud Connectors.",
        "Confirm the current Citrix-managed subscription and catalog limits, count only the intended VDA population and plan a supported additional subscription if appropriate.",
        "Compare the scoped VDA count and vendor dashboard warning with the confirmed limit; do not apply 4000 as a universal Azure VM or VDA quota.",
    ),
    "1c6c97d7": (
        "The source's direct path concerns trusted AVD control-plane destinations, not all session-host traffic.",
        "Review current supported AVD destinations, protocol requirements and security policy before proposing a narrowly scoped route; do not add a blanket Internet route or disable inspection globally.",
        "Inspect effective routes for the exact permitted AVD destinations and verify control-plane connectivity while unrelated traffic retains its intended security path.",
    ),
    "7d9c96a6": (
        "App attach packages belong on a share separate from FSLogix profiles; the source also calls for backup and same-region placement with session hosts.",
        "Plan the dedicated app-attach share, required package capacity and supported backup or DR protection without merging it into the profile share.",
        "Verify share separation, regional placement, application package access and recoverability of the required package set.",
    ),
    "768a5b06": (
        "Data Guard observer availability is a separate failure domain from the production database, not automatic database replication created by observer placement.",
        "Place supported observer nodes so an observer remains available after production-zone loss; coordinate the supported Data Guard configuration and quorum or failover prerequisites.",
        "Inspect observer and database placements and retained failover records; verify observer availability independently of database replication health.",
    ),
    "15e2712c": (
        "ZRS or GZRS here describes SQL MI backup-storage redundancy, not the live instance's HA setting.",
        "Select a supported backup redundancy mode for the exact service tier and region and review regional restoration eligibility separately.",
        "Read backup-storage redundancy and usable recovery-point evidence, then distinguish a restored database from a zone-redundant live managed instance.",
    ),
}


def apply_specifics(entry: dict[str, Any]) -> None:
    prefix = entry["recommendation_id"][:8]
    specific = SPECIFICS.get(prefix)
    if specific:
        mechanism, action, check = specific
        entry["applicability"].append(text(mechanism))
        entry["implementation_steps"].insert(2, text(action))
        entry["verification_steps"].insert(1, text(check))
        entry["cautions"].append(text(mechanism))
    if prefix in UNCERTAIN:
        entry["cautions"].append(text("Content review limit: " + UNCERTAIN[prefix]))
    if prefix == "bcfe71f1":
        entry["configuration"]["after"][1] = text(
            "Multiple ready replicas have reviewed placement and dependency behavior. "
            "Their count is not a guarantee of application availability."
        )


def critique_report(
    controls: list[dict[str, Any]], crosswalk: dict[str, Any], semantics: dict[str, Any]
) -> dict[str, Any]:
    by_prefix = {control["id"][:8]: control for control in controls}
    return {
        "scope": "Offline source-title, explanation, benefit, explicit binding and mechanism-graph "
        "critique across all 456 IDs, plus scoped current-public-document review and "
        "rewritten conditional guidance for sixteen cases. No claim that all 437 shared-"
        "context entries have independent latest-document review; no live validation.",
        "source_ambiguities_and_historical_limits": [
            {
                "recommendation_id": by_prefix[prefix]["id"],
                "title": by_prefix[prefix]["title"],
                "reason": reason,
            }
            for prefix, reason in sorted(UNCERTAIN.items())
        ],
        "remaining_thin_or_uncertain": [
            {"recommendation_id": by_prefix[prefix]["id"], "reason": reason}
            for prefix, reason in sorted(UNCERTAIN.items())
            if prefix not in RESOLUTIONS
        ],
        "resolved_conditional_guides": resolution_report(controls),
        "resolution_scope": "The sixteen identified instructional gaps only. Installation-specific "
        "eligibility and effect observations remain unknown until supplied. "
        "The other 437 shared-context entries do not gain independent "
        "latest-document review from these resolutions.",
        "true_content_blockers": [],
        "external_citation_presentation_limits": [],
        "vendor_source_cards": [
            {
                "recommendation_id": by_prefix["c041d596"]["id"],
                "url": RESOLUTIONS["c041d596"]["vendor_url"],
                "reviewed_scope": "Citrix DaaS Standard for Azure currently lists 5000 VDAs per subscription; "
                "the APRL 4000 figure is historical and not an Azure-wide quota.",
                "handling": "The guide includes a vendor source card for this exact public URL. "
                "No other vendor origins or paths are enabled by this record.",
            }
        ],
        "linked_vendor_support_prerequisites": [
            {
                "url": url,
                "status": "Referenced by the reviewed official Learn SAP guides; vendor entitlement "
                "and exact installed-version support remain deployment-specific and "
                "were not independently authenticated or validated.",
            }
            for url in [
                "https://launchpad.support.sap.com/#/notes/1928533",
                "https://launchpad.support.sap.com/#/notes/2015553",
                "https://documentation.suse.com/en-us/sles-sap/sap-ha-support/html/sap-ha-support/index.html",
                "https://access.redhat.com/articles/3131341",
            ]
        ],
        "specific_mechanism_addenda": sorted(by_prefix[prefix]["id"] for prefix in SPECIFICS),
        "corrected_mechanism_bindings": [
            {"recommendation_id": by_prefix[prefix]["id"], "reason": reason}
            for prefix, reason in sorted(CORRECTED_BINDINGS.items())
        ],
        "manual_evidence_ids": sorted(
            row["aprl_guid"]
            for row in crosswalk["recommendations"]
            if row["disposition"] == "manual_evidence"
        ),
        "blocked_automated_ids": sorted(
            row["aprl_guid"] for row in semantics["reviews"] if row["decision"] == "blocked"
        ),
        "assessment_boundary": "Manual and blocked dispositions are evidence limits, not automatically thin content and not changed by guidance quality.",
        "subscription_classification_ids": sorted(
            control["id"]
            for control in controls
            if control["wara"]["resource_type"].casefold() == "microsoft.subscription/subscriptions"
        ),
        "classification_limit": "Subscription-scoped specialized-workload metadata is not the actual target object type; inspect the explicit recommendation focus and workload dependencies.",
    }
