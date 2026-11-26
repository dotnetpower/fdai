"""Reviewed semantics of all 143 pinned automated APRL queries.

The eight-character selectors are unique only inside the pinned identity-set digest.
They never resolve a new query revision. The builder emits full GUID/digest review records.
These reviews prove only the stated query measurement, not a broader compliance claim.
"""

from __future__ import annotations

AUTOMATED_IDENTITIES_DIGEST = (
    "sha256:a2ff0c67023f088126acf89a9933ca4d409e145c1bb80168ff744c5885fd89fe"
)
REVIEWED_RULE_BINDINGS_DIGEST = (
    "sha256:8a9ca580865783ddff2eb66d9ed541dd8b327459a30b7f615afe8bf29876bfc8"
)


def field(path: str, kind: str = "string", **constraints: object) -> dict[str, object]:
    return {
        "path": path,
        "value_type": kind,
        **({"minimum_length": 1} if kind == "string" else {}),
        **constraints,
    }


def choices(path: str, *values: str) -> dict[str, object]:
    return field(path, allowed_values=values)


def array(path: str, minimum: int = 0) -> dict[str, object]:
    constraints: dict[str, object] = {"minimum_items": minimum}
    if path == "zones":
        constraints.update(allowed_items=("1", "2", "3"), unique_items=True)
    if path == "properties.links":
        constraints["maximum_items"] = 2
    return field(path, "array", **constraints)


def boolean(path: str, expected: bool | None = None) -> dict[str, object]:
    return field(path, "boolean", expected_boolean=expected)


def regional(*requirements: dict[str, object]) -> tuple[bool, tuple[dict[str, object], ...]]:
    return True, requirements


def every(*requirements: dict[str, object]) -> tuple[bool, tuple[dict[str, object], ...]]:
    return False, requirements


# Every admitted query has a single Resources pipeline, preserves the exact resource id,
# and returns only failures of its reviewed configuration predicate. Guards are conservative:
# an excluded region, SKU, missing field, or incomplete array means unknown, never satisfied.
EXACT = {
    "03f4a7d8": (
        "Anonymous pull enabled is the failing boolean state.",
        every(boolean("properties.anonymousPullEnabled")),
    ),
    "0bee356b": (
        "Provisioned ExpressRoute Direct bandwidth exceeding port bandwidth fails.",
        every(
            field("properties.provisionedBandwidthInGbps", "number"),
            field("properties.bandwidthInGbps", "number"),
        ),
    ),
    "10f02bc6": (
        "Every observed backend HTTP settings entry must enable connection draining.",
        every(
            array("properties.backendHttpSettingsCollection", 1),
            boolean(
                "properties.backendHttpSettingsCollection.*.properties.connectionDraining.enabled"
            ),
        ),
    ),
    "122d11d7": (
        "An explicitly null OS managed-disk association fails.",
        every(
            field(
                "properties.storageProfile.osDisk.managedDisk",
                "object",
                allow_null=True,
                required_keys=("id",),
            )
        ),
    ),
    "1549b91f": (
        "Only observed GeoRedundant vaults are eligible; disabled cross-region restore fails.",
        every(
            choices("properties.redundancySettings.standardTierStorageRedundancy", "GeoRedundant"),
            choices("properties.redundancySettings.crossRegionRestore", "Enabled", "Disabled"),
        ),
    ),
    "1cca00d2": (
        "Explicit false or null soft-delete state fails; absence remains unknown.",
        every(field("properties.enableSoftDelete", "boolean", allow_null=True)),
    ),
    "2102a57a": (
        "The query's lowercase free SKU fails; unknown casing and SKU names abstain.",
        every(choices("sku.name", "free", "standard", "premium")),
    ),
    "21fb841b": (
        "Every observed distribution must expose at least one replication region; one fails.",
        every(
            array("properties.distribute", 1),
            field(
                "properties.distribute.*.replicationRegions",
                "array",
                minimum_items=1,
                unique_items=True,
            ),
            field("properties.distribute.*.replicationRegions.*"),
        ),
    ),
    "22a769ed": (
        "Every scoped flow log needs explicit enabled and Succeeded provisioning state.",
        every(
            boolean("properties.enabled"),
            choices("properties.provisioningState", "Succeeded", "Failed", "Updating", "Deleting"),
        ),
    ),
    "281a2713": (
        "Only VPN gateways are eligible; an explicitly false activeActive value fails.",
        every(
            choices("properties.gatewayType", "Vpn", "vpn"),
            choices(
                "properties.sku.tier",
                "VpnGw1",
                "VpnGw2",
                "VpnGw3",
                "VpnGw4",
                "VpnGw5",
                "VpnGw1AZ",
                "VpnGw2AZ",
                "VpnGw3AZ",
                "VpnGw4AZ",
                "VpnGw5AZ",
            ),
            boolean("properties.activeActive"),
        ),
    ),
    "38c3bca1": (
        "Basic load-balancer SKU fails; Standard satisfies the SKU measurement.",
        every(choices("sku.name", "Basic", "Standard")),
    ),
    "43663217": (
        "Known Cosmos region entries need two regions, or three with Strong consistency.",
        every(
            array("properties.locations", 1),
            field("properties.locations.*.locationName"),
            choices(
                "properties.consistencyPolicy.defaultConsistencyLevel",
                "Strong",
                "BoundedStaleness",
                "Session",
                "ConsistentPrefix",
                "Eventual",
            ),
        ),
    ),
    "47d100a5": (
        "Only pinned supported regions are eligible; an explicitly empty zone array fails.",
        regional(array("zones")),
    ),
    "488dcc8b": (
        "Only pinned supported regions are eligible; non-ZRS image storage fails.",
        regional(
            choices(
                "properties.publishingProfile.storageAccountType",
                "Standard_LRS",
                "Standard_ZRS",
                "Premium_LRS",
            )
        ),
    ),
    "5a44bd30": (
        "Only pinned supported regions are eligible; fewer than two explicit zones fails.",
        regional(choices("properties.sku.name", "Premium"), array("zones")),
    ),
    "5b1933a6": (
        "Only VPN gateways in pinned supported regions are eligible; non-AZ tier fails.",
        regional(choices("properties.gatewayType", "Vpn"), field("properties.sku.tier")),
    ),
    "5b422a7f": (
        "An observed endpoint array with fewer than two entries fails.",
        every(array("properties.endpoints"), field("properties.endpoints.*.name")),
    ),
    "5c96afc3": (
        "Disabled MySQL geo-redundant backup fails.",
        every(choices("properties.backup.geoRedundantBackup", "Enabled", "Disabled")),
    ),
    "5cea1501": (
        "Basic public-IP SKU fails; Standard satisfies the SKU measurement.",
        every(choices("sku.name", "Basic", "Standard")),
    ),
    "60077378": (
        "Both of the two ExpressRoute Direct link admin states must be observed; Disabled fails.",
        every(
            array("properties.links", 2),
            choices("properties.links.0.properties.adminState", "Enabled", "Disabled"),
            choices("properties.links.1.properties.adminState", "Enabled", "Disabled"),
        ),
    ),
    "63491f70": (
        "Only pinned supported regions are eligible; Disabled registry zone redundancy fails.",
        regional(
            choices("sku.name", "Premium"),
            choices("properties.zoneRedundancy", "Enabled", "Disabled"),
        ),
    ),
    "740f2c1c": (
        "Only Premium APIM in pinned supported regions is eligible; fewer than two zones fails.",
        regional(choices("sku.name", "Premium"), array("zones")),
    ),
    "8176a79d": (
        "Disabled MySQL storage auto-grow fails.",
        every(choices("properties.storage.autoGrow", "Enabled", "Disabled")),
    ),
    "820f4743": (
        "Only non-AKS VMSS with complete tags are eligible; disabled automatic repair fails.",
        every(
            field("tags", "object", forbidden_keys=("aks-managed-poolName",)),
            boolean("properties.automaticRepairsPolicy.enabled"),
        ),
    ),
    "823b0cff": (
        "Observed Application Gateway autoscale minimum capacity of at most one fails.",
        every(
            choices("properties.sku.tier", "Standard_v2", "WAF_v2"),
            field("properties.autoscaleConfiguration.minCapacity", "number"),
        ),
    ),
    "847a8d88": (
        "An explicitly empty custom health-probe array fails.",
        every(array("properties.probes")),
    ),
    "88856605": (
        "Only pinned supported regions are eligible; MySQL HA mode other than ZoneRedundant fails.",
        regional(
            choices("properties.highAvailability.mode", "Disabled", "SameZone", "ZoneRedundant")
        ),
    ),
    "88cb90c2": (
        "Only supported-region Premium/Isolated plans are eligible; "
        "explicit false zone redundancy fails.",
        regional(
            choices("sku.tier", "Premium", "PremiumV2", "PremiumV3", "Isolated", "IsolatedV2"),
            boolean("properties.zoneRedundant"),
        ),
    ),
    "9cabded7": (
        "Only observed multi-region single-write accounts are eligible; "
        "disabled automatic failover fails.",
        every(
            array("properties.locations", 2),
            field("properties.locations.*.locationName"),
            boolean("properties.enableMultipleWriteLocations", False),
            boolean("properties.enableAutomaticFailover"),
        ),
    ),
    "9ec5b4c8": (
        "Only the four pinned AVS regions are eligible; non-DualZone availability fails.",
        regional(choices("properties.availability.strategy", "SingleZone", "DualZone")),
    ),
    "a3058909": (
        "At least two explicitly observed Entra Domain Services replica sets are required.",
        every(array("properties.replicaSets", 1), field("properties.replicaSets.*.location")),
    ),
    "b2113023": (
        "Explicit plan SKU tier is compared with the pinned Standard/Premium/IsolatedV2 predicate.",
        every(
            choices(
                "sku.tier",
                "Free",
                "Shared",
                "Basic",
                "Standard",
                "Premium",
                "PremiumV2",
                "PremiumV3",
                "Isolated",
                "IsolatedV2",
            )
        ),
    ),
    "b2bad57d": (
        "Disabled PostgreSQL custom maintenance window fails.",
        every(choices("properties.maintenanceWindow.customWindow", "Enabled", "Disabled")),
    ),
    "b2fb3e60": (
        "An explicitly empty NetApp backup policy id fails; omitted policy fields remain unknown.",
        every(field("properties.dataProtection.backup.backupPolicyId", minimum_length=0)),
    ),
    "b49a8653": (
        "Known MySQL replication role None is the source query's no-replica finding.",
        every(choices("properties.replicationRole", "None", "Source")),
    ),
    "b5a63aa0": (
        "Only Uniform VMSS is eligible; explicit true strict zone balance fails.",
        every(
            choices("properties.orchestrationMode", "Uniform"), boolean("properties.zoneBalance")
        ),
    ),
    "baf3bfc0": (
        "Known non-Premium APIM SKU fails the pinned Premium-tier measurement.",
        every(choices("sku.name", "Consumption", "Developer", "Basic", "Standard", "Premium")),
    ),
    "bb4c8db4": (
        "Only non-free lowercase App Configuration SKUs are eligible; "
        "explicit false/null purge protection fails.",
        every(
            choices("sku.name", "standard", "premium"),
            field("properties.enablePurgeProtection", "boolean", allow_null=True),
        ),
    ),
    "bb6deb9d": (
        "Standard Entra Domain Services SKU fails; Enterprise and Premium satisfy.",
        every(choices("properties.sku", "Standard", "Enterprise", "Premium")),
    ),
    "c0085c32": (
        "Only pinned supported regions are eligible; "
        "explicit false SQL database zone redundancy fails.",
        regional(choices("sku.tier", "Premium"), boolean("properties.zoneRedundant")),
    ),
    "c63b81fb": (
        "Only Regional public IPs in pinned supported regions are eligible; "
        "fewer than two explicit zones fails.",
        regional(choices("sku.tier", "Regional"), array("zones")),
    ),
    "c9c00f2a": (
        "Only pinned supported regions are eligible; "
        "fewer than two Application Gateway zones fails.",
        regional(array("zones")),
    ),
    "ca87914f": (
        "Only pinned supported regions are eligible; non-ZoneRedundant PostgreSQL HA fails.",
        regional(
            choices("properties.highAvailability.mode", "Disabled", "SameZone", "ZoneRedundant")
        ),
    ),
    "d40c769d": (
        "Only a directly observed ExpressRoute port association is eligible; "
        "false direct-port rate limit fails.",
        every(
            field("properties.expressRoutePort", "object", required_keys=("id",)),
            boolean("properties.enableDirectPortRateLimit"),
        ),
    ),
    "dac421ec": (
        "Classic ApplicationInsights ingestion mode fails; "
        "LogAnalytics satisfies the migration measurement.",
        every(choices("properties.IngestionMode", "ApplicationInsights", "LogAnalytics")),
    ),
    "e30317d2": (
        "Only Regular NetApp volumes are eligible; explicit remote-region state must prove CRR.",
        every(
            choices("properties.volumeType", "Regular"),
            field("location"),
            field("properties.dataProtection.replication.remoteVolumeRegion", minimum_length=0),
        ),
    ),
    "e35cf148": (
        "APIM platform stv1 fails; observed stv2 satisfies the migration measurement.",
        every(choices("properties.platformVersion", "stv1", "stv2")),
    ),
    "e48a7227": (
        "Explicit null Stream Analytics cluster id fails; "
        "an observed id satisfies; omitted fields abstain.",
        every(field("properties.cluster.id", allow_null=True)),
    ),
    "e544520b": (
        "Only single-write accounts without analytical storage are eligible; "
        "Periodic backup fails.",
        every(
            boolean("properties.enableMultipleWriteLocations", False),
            boolean("properties.enableAnalyticalStorage", False),
            choices("properties.backupPolicy.type", "Periodic", "Continuous"),
        ),
    ),
    "e6c7e1cc": (
        "Known LRS storage SKUs fail; known zone/geo-redundant SKUs satisfy.",
        every(
            choices(
                "sku.name",
                "Standard_LRS",
                "Premium_LRS",
                "Standard_GRS",
                "Standard_RAGRS",
                "Standard_ZRS",
                "Standard_GZRS",
                "Standard_RAGZRS",
                "Premium_ZRS",
            )
        ),
    ),
    "e7495e1c": (
        "Only non-AKS VMSS with complete tags are eligible; Uniform orchestration fails.",
        every(
            field("tags", "object", forbidden_keys=("aks-managed-poolName",)),
            choices("properties.orchestrationMode", "Uniform", "Flexible"),
        ),
    ),
    "e7dbd21f": (
        "Explicit false IoT Hub fallback-route enabled state fails.",
        every(boolean("properties.routing.fallbackRoute.isEnabled")),
    ),
    "e7f0fd54": (
        "Explicit disabled registry soft-delete status fails.",
        every(choices("properties.policies.softDeletePolicy.status", "enabled", "disabled")),
    ),
    "f05a3e6d": (
        "Every endpoint monitor status must be observed; a known non-Online status fails.",
        every(
            array("properties.endpoints", 1),
            choices(
                "properties.endpoints.*.properties.endpointMonitorStatus",
                "Online",
                "Degraded",
                "CheckingEndpoint",
                "Inactive",
                "Disabled",
                "Stopped",
            ),
        ),
    ),
    "f075a1bd": (
        "Known TLS 1.0/1.1 minima fail; TLS 1.2/1.3 satisfy the minimum-version measurement.",
        every(choices("properties.minimumTlsVersion", "1.0", "1.1", "1.2", "1.3")),
    ),
    "f4201965": (
        "Only pinned supported regions are eligible; "
        "explicit false environment zone redundancy fails.",
        regional(boolean("properties.zoneRedundant")),
    ),
    "fbfef3df": (
        "Only Standard Event Hub tier is eligible; explicit false auto-inflate state fails.",
        every(choices("sku.tier", "Standard"), boolean("properties.isAutoInflateEnabled")),
    ),
}

RULE = {
    "70fcfe6d": "Existing reviewed T0 purge-protection Rule handles absent or non-true values.",
}

BLOCKED = {
    "005ccbbd": "Taint absence is not User pool mode; null scaling/count fields disappear.",
    "0611251f": "Standard/Premium AKS requirement is production-only; typed eligibility missing.",
    "2ad78dec": "Legacy storage has valid exceptions; Consider guidance is not decisive failure.",
    "5d40d3d4": "Title/query test SKU but longDescription specifies Autoscale configuration.",
    "6cd57b65": "Grafana Standard-tier and supported-region zone capability are not proven.",
    "7893f0b3": "Source explicitly permits necessary v1 exceptions; typed exception scope missing.",
    "855ca19a": "Two-instance App Service is production-only; typed eligibility missing.",
    "ab984130": "Standard NetApp network is production-only; typed eligibility missing.",
    "b376281d": "Replica count alone does not prove AI Search region zone capability.",
    "c14de326": "Redirect is VNet-local only; public/private endpoints validly use Proxy.",
    "eeba3a49": "Non-Free IoT Hub requirement is production-only; typed eligibility missing.",
    "f8f834a9": "SQL managed-instance region/tier capability for zone redundancy is not proven.",
    "029208c8": "Alert scopes/criteria/enabled-state completeness is independently unproven.",
    "06b77be9": "Flow-log existence is not enabled logging; related-set coverage is unproven.",
    "0a535241": "Slot config inner join hides missing config; exact child lineage is unproven.",
    "0b80b67c": "App config inner join hides missing config; related-source coverage is unproven.",
    "1422c567": "Zone predicate does not prove Flexible mode; AKS eligibility is unproven.",
    "15e2712c": "GeoZone-only predicate rejects Zone although recommendation permits it.",
    "17e877f7": "Protected-item absence cannot prove complete VM replication/test coverage.",
    "1981f704": "VM-name backup join can collide across ARM ids; recovery coverage unproven.",
    "1adba190": "Public-IP result ids differ from VM target ids; exact relationship needed.",
    "23b2dfc7": "Alert scope/condition/enabled-state coverage and containment are unproven.",
    "269a9f1a": "Cluster-name backup join can collide across ARM ids; coverage unproven.",
    "273f6b30": "VMSS nonmembership does not prove production replica topology is insufficient.",
    "2ab85a67": "Fullouter replica join needs complete related inventory and exact source ids.",
    "2bd0be95": "isnull(zones) misses empty arrays; zero rows cannot prove zone assignment.",
    "302fda08": "Advisor absence is not capacity satisfaction; coverage/eligibility unproven.",
    "31f4ac4b": "Advisor absence is not configured geo backup; coverage/lineage unproven.",
    "3201dba8": "Production CPU requirements and A/B-series workload eligibility are unproven.",
    "3263a64a": "Shared disks are a review list, not failures; guest cluster controls unobserved.",
    "36ea6c09": "Replication anti-join needs complete child replicas and cross-region lineage.",
    "3c8fa7c6": "Alert coverage/enabled state unproven; recommendationId is also malformed.",
    "3e115044": "Maintenance assignment/configuration sources lack independent completeness.",
    "3f85a51c": "Autoscale join omits absent settings; complete associated set is unproven.",
    "41a22a5e": "IP forwarding is valid for NVAs; role and complete NIC relations are unproven.",
    "4232eb32": "Warning/critical alert union lacks complete enabled scopes and criteria proof.",
    "4bae5a28": "VPN/PIP inner join hides missing PIPs; complete associations are unproven.",
    "4ee5d535": "CPU alert scopes/criteria/enabled-state lack independent completeness proof.",
    "4f63619f": "Result /agentPools child ids differ from cluster scope; attribution required.",
    "52ab9e5c": "Assignment coverage unproven; substring isolated-SKU eligibility is heuristic.",
    "5ee083cd": "Selects hasCriticalAddonsOnly including empty taints, not a reliable failure.",
    "621dbc78": "Frontend/PIP union joins lack complete related sets and zone eligibility.",
    "6a8b3db9": "Premium tier alone does not prove configured SignalR zone redundancy.",
    "6d82d042": "Counts explicit addresses but omits backendIPConfigurations membership.",
    "72827434": "Advisor absence is not a snapshot policy; independent coverage is unproven.",
    "73d1bb04": "Source cannot confirm guest NIC drivers; listed rows need guest evidence.",
    "7f7ae535": "Taints do not prove System mode; minCount <3 is not the stated count test.",
    "8364fd0a": "Subnet join/mv-expand may omit prefixes; exact related-set coverage unproven.",
    "84636c6c": "Supported-region condition lacks an authoritative region capability guard.",
    "8bb4a57b": "NSG alert scopes/conditions/enabled-state and inherited coverage are unproven.",
    "8d319a05": "Outbound rules do not prove production NAT necessity; eligibility unproven.",
    "902c82ff": "Only agentPoolProfiles[0] is tested, not every eligible node pool.",
    "921631f6": "Nested region eligibility/serverless exclusion require complete capabilities.",
    "9437634c": "CDN hostname/child join lacks complete domains and canonical target lineage.",
    "94794d2a": "Extension anti-join lacks complete arrays and non-AKS/health eligibility.",
    "9729c89d": "Explicit alert rows require manual scope review; not decisive failures.",
    "98bd7098": "Pinned query is comment-only under-development; no executable measurement.",
    "9ce78192": "Disabled multi-write is a design review candidate, not an unsuitable design.",
    "9e39919b": "mv-expand targets a scalar softDeleteState; executable semantics unproven.",
    "a1d91661": "repositorySiteName slot grouping lacks exact ARM identity/child completeness.",
    "a7bfcc18": "Returns VMSS ids for cluster scope via heuristic name/resource-group joins.",
    "a8d25876": "Absent association and production migration eligibility are unproven.",
    "b002c030": "Enabled CSI drivers do not prove existing in-tree volumes were migrated.",
    "b1e1378d": "DPS hostname fullouter join lacks complete linked hubs and exact identities.",
    "b49a39fd": "Production image eligibility and complete per-region replicas are required.",
    "b60ae773": "Pinned query is comment-only under-development; no executable measurement.",
    "b72214bb": "DCR/association/extension joins lack independent completeness and lineage.",
    "b89c9acc": "Only first private-link connection tested; later failed connections omitted.",
    "bbe668b7": "Advisor absence is not zone redundancy; independent coverage is unproven.",
    "c041d596": "Bare subscription id/count requires a full census, not workload-only scope.",
    "c22db132": "Non-kubenet does not prove dynamic Azure CNI or overlay mode.",
    "c31f76a0": "Flags every non-WORLD endpoint, not absence of one All World fallback.",
    "c6c4b962": "Name-based auto-heal config inner join lacks exact lineage/completeness.",
    "c72b7fee": "Missing optional virtualHub metadata is not proven non-hub eligibility.",
    "cfe22a65": "ASR protected-item anti-join lacks complete coverage and security eligibility.",
    "d37db635": "Requires full gateway/connection/circuit visibility and peering lineage.",
    "dcaf8128": "Stringified false flags are nonempty; zero rows do not prove enabled state.",
    "df0ff862": "VM-name/managedBy disk join collides across ids and omits shared associations.",
    "dfedbeb1": "NIC inner join needs complete exact relations plus VM/OS eligibility.",
    "e3d742e1": "Advisor absence is not cross-zone replication; coverage/lineage unproven.",
    "eb005943": "Critical production workload eligibility for Premium tier is unproven.",
    "ee66ff65": "Autoscale anti-join lacks complete settings and exact non-AKS eligibility.",
    "f8c2e6d9": "VPN maintenance joins need complete assignment/configuration sources.",
    "fa0cf4f5": "Source selects ZRS/nonempty zones after LRS filtering, contradicting intent.",
    "fd049c28": "Name-based health config inner join hides missing config; lineage unproven.",
}
