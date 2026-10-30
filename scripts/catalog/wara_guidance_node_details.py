"""Short, entity-specific descriptions for the sixteen qualified diagrams."""
# ruff: noqa: E501

from wara_guidance_node_details_ko import NODE_DETAILS_KO

NODE_DETAILS = {
    "e7dbd21f": {
        "message": "Telemetry enters IoT Hub with properties that routing conditions can evaluate.",
        "queries": "Enabled conditions select the custom endpoints that receive each matching message.",
        "custom": "Matching destinations require their own authorization, capacity and delivery checks.",
        "fallback": "This choice controls the destination of messages that match no enabled route.",
        "builtin": "Unmatched messages arrive here only when the selected fallback policy delivers them.",
        "loss": "Disabled fallback leaves unmatched messages undelivered unless another intended path exists.",
        "evidence": "Compare known matching and unmatched messages with actual destination ingestion.",
    },
    "98bd7098": {
        "operator": "Management tools submit resource changes through ARM rather than application data endpoints.",
        "arm": "ARM authorizes and routes control-plane operations independently of workload requests.",
        "metadata": "The group's selected location stores management metadata, not every resource's data.",
        "backup": "ARM can reroute management requests here when the group's primary region is unavailable.",
        "provider": "The provider applies authorized management operations to its resource type.",
        "data": "Application requests depend on the resource's own location and recovery design.",
        "evidence": "Observe management continuity and application data access as separate outcomes.",
    },
    "63491f70": {
        "registry": "Image push and pull use the registry data plane covered by regional zone behavior.",
        "region": "Actual region support determines automatic zone coverage across registry tiers.",
        "zones": "Azure manages the eligible registry's image-serving replicas across availability zones.",
        "legacy": "The historical property can show Disabled without controlling current zone protection.",
        "tasks": "Registry Tasks have a separate availability-zone scope from image push and pull.",
        "evidence": "Check regional eligibility and real push or pull behavior without trusting the legacy flag alone.",
    },
    "84636c6c": {
        "producer": "Producers send events and use bounded retries for transient request failures.",
        "namespace": "Region, tier and Dedicated capacity determine the namespace's zone eligibility.",
        "replicas": "The service synchronously replicates acknowledged events and metadata across zones.",
        "consumer": "Consumers resume from durable progress and tolerate replay without duplicate business effects.",
        "evidence": "Check eligibility, acknowledgements, reconnect behavior and checkpoint-based replay.",
    },
    "b376281d": {
        "client": "Queries and indexing writes have distinct availability and replica-count requirements.",
        "service": "Supported region, Basic-or-higher tier and replica count establish zone eligibility.",
        "primary": "The service selects a primary replica to handle write operations.",
        "reads": "Read replicas improve serving capacity; exact zone placement remains service-managed and unguaranteed.",
        "source": "Retained authoritative data supports rebuilding indexes independently of Search replicas.",
        "evidence": "Compare eligibility and query or indexing behavior without inferring exact replica placement.",
    },
    "740f2c1c": {
        "clients": "Consumers send API requests through the gateway and need transient-fault handling.",
        "mode": "The exact classic or v2 tier determines supported automatic, manual and single-zone choices.",
        "gateway": "Managed gateway units serve API traffic and determine remaining capacity after a failure.",
        "primary": "Documented primary-region zone support includes the management plane and developer portal.",
        "secondary": "Supported secondary regions contain gateway units, not extra management or portal deployments.",
        "evidence": "Check tier, zone mode, surviving gateway capacity and observed request continuity.",
    },
    "1c6c97d7": {
        "host": "Session hosts initiate connections to the required AVD and supporting services.",
        "policy": "Reviewed routes and security rules select narrow paths without a blanket inspection bypass.",
        "avd": "Current AVD endpoints use supported dynamic service or FQDN tags where applicable.",
        "support": "Identity, updates and monitoring retain separate endpoint and connectivity requirements.",
        "platform": "Required Azure platform traffic follows its documented direct handling requirements.",
        "evidence": "Use endpoint checks and effective routes to confirm each required destination path.",
    },
    "9ec5b4c8": {
        "cloud": "The supported stretched-cluster deployment spans hosts in two availability zones.",
        "quota": "Reserved paired-zone capacity enables the selected private-cloud deployment and expansion.",
        "first": "One site's hosts contribute compute and storage under the selected failure-tolerance policy.",
        "second": "The other site's hosts retain the supported mirrored storage and surviving capacity.",
        "policy": "Dual-site mirroring and local failure tolerance must match actual host capacity.",
        "paths": "Independent connectivity must reach both zones rather than share one unprotected path.",
        "evidence": "Verify storage policy, surviving connectivity and application recovery separately.",
    },
    "38721758": {
        "hosts": "Persistent state requirements distinguish reproducible hosts from hosts needing state recovery.",
        "choice": "The current recovery design chooses recreation or eligible replication; the GUID stays disabled.",
        "image": "Versioned images and deployment definitions recreate supported host configuration.",
        "asr": "Eligible VM replication supplies recovery points, not an independent backup of every dependency.",
        "target": "An isolated recovered host still needs registration and a working user access path.",
        "profiles": "Profiles, identity and application data require their own protection and recovery.",
        "evidence": "Check host registration, user sign-in, application access and profile attachment.",
    },
    "a18d60f8": {
        "job": "The failed job defines which business outputs and processing boundary require repair.",
        "history": "Table history identifies candidate versions or timestamps for read-only inspection.",
        "retention": "Required transaction logs and data files must still exist for the selected version.",
        "preview": "Read the historical version and check schema, counts and business invariants before mutation.",
        "repair": "An approved replay, corrective write or RESTORE must coordinate writers and checkpoints.",
        "outputs": "Reconcile table state and downstream results without silent loss or duplicate effects.",
    },
    "c15b2b73": {
        "hosts": "Each session host uses effective policy and registry settings for profile attachment.",
        "baseline": "The selected Standard or Cloud Cache design defines supported settings and session behavior.",
        "access": "Share and NTFS permissions must allow the intended user to open the existing container.",
        "container": "Preserve the intended profile and path when changing naming or migration-sensitive settings.",
        "session": "A valid user session attaches the expected profile instead of a temporary or new empty one.",
        "evidence": "Compare host settings with attachment logs and controlled sign-in observations.",
    },
    "4884cada": {
        "sap": "Application requests rely on responsive storage and coordinated recovery behavior.",
        "nfs": "The chosen NFS protocol and mount ownership model determine client behavior.",
        "baseline": "A versioned matrix maps each timeout to its exact OS, protocol and architecture scope.",
        "agent": "Resource start, stop and monitoring operations use their own supported limits.",
        "fence": "Supported fencing must remain effective while storage and resource operations recover.",
        "evidence": "Measure I/O, resource transitions and recovery timing without premature fencing or stalls.",
    },
    "6648fe61": {
        "client": "The virtual access path must direct requests to the current safe database owner.",
        "primary": "The active database serves writes and supplies the selected system-replication stream.",
        "secondary": "A compatible secondary receives replication and is promoted only under the supported contract.",
        "cluster": "The selected OS and HANA agents coordinate resource ownership, ordering and recovery.",
        "fence": "An independent supported mechanism excludes an unsafe owner before conflicting promotion.",
        "evidence": "Correlate replication status, current ownership, fencing and application request recovery.",
    },
    "9d8f6678": {
        "apps": "Application servers reach the active central services through the supported virtual path.",
        "ascs": "The current owner provides the central-service role protected by the cluster.",
        "ers": "Enqueue replication behavior and placement follow the selected ENSA design.",
        "shared": "The chosen filesystem architecture supplies required shared files with defined mount ownership.",
        "cluster": "OS and ENSA-specific resources and constraints coordinate ASCS and ERS transitions.",
        "fence": "Quorum and fencing prevent conflicting owners during a failure or recovery.",
        "evidence": "Verify central-service availability, enqueue behavior and application reconnects.",
    },
    "ee4dc309": {
        "sap": "SAP startup and operation depend on the required shared-directory contents.",
        "mounts": "Mounted NFS or SMB files have protection requirements separate from local VM disks.",
        "choice": "Actual storage type determines the supported replication, backup or copy strategy.",
        "copy": "The selected mechanism retains the content needed at the recovery site.",
        "target": "Recovery needs correct mount targets, ownership and permissions before SAP services start.",
        "asr": "VM and attached-disk replication does not automatically include mounted NFS data.",
        "evidence": "Check recovery-copy freshness, file consistency, target permissions and startup order.",
    },
    "c041d596": {
        "product": "The actual Citrix product and edition determine which published limits apply.",
        "model": "Managed and customer-managed subscriptions can have different service and trial conditions.",
        "vendor": "Use the current product-scoped vendor table, not a universal Azure quota.",
        "count": "Count the intended VDA population separately from other infrastructure.",
        "azure": "Regional quota and usable Azure capacity remain independent constraints.",
        "plan": "Supported expansion must satisfy product limits, licensing and actual infrastructure capacity.",
        "evidence": "Match observed counts to the exact product, subscription model and current contract.",
    },
}


def qualified_node_details(
    prefix: str, nodes: list[tuple[str, str, str, str]]
) -> dict[str, dict[str, str]]:
    """Reject missing or copy-pasted figure text rather than falling back to prose."""
    details = NODE_DETAILS[prefix]
    korean = NODE_DETAILS_KO[prefix]
    if set(details) != {identity for identity, _label, _ko, _role in nodes}:
        raise ValueError(f"{prefix}: qualified diagram node descriptions must match its entities")
    if len({detail.casefold().strip() for detail in details.values()}) != len(details):
        raise ValueError(f"{prefix}: qualified diagram node descriptions must be distinct")
    if set(korean) != set(details) or len(set(korean.values())) != len(details):
        raise ValueError(f"{prefix}: qualified Korean descriptions must cover distinct entities")
    for identity, label, _ko, _role in nodes:
        detail = details[identity]
        if (
            len(label) > 72
            or len(detail) > 200
            or not 6 <= len(detail.split()) <= 32
            or detail.casefold() == label.casefold()
        ):
            raise ValueError(
                f"{prefix}/{identity}: qualified diagram text exceeds its figure budget"
            )
    return {
        identity: {"en": detail, "ko": korean[identity]} for identity, detail in details.items()
    }
