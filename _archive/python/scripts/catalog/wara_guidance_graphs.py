"""Mechanism-specific graphs; no generic configuration-to-success fallback."""
# ruff: noqa: E501

from __future__ import annotations

from typing import Any


def graph(
    nodes: str, edges: str
) -> tuple[list[tuple[str, str, str, str]], list[tuple[str, str, str, str]]]:
    node_rows = []
    for row in nodes.split(";"):
        identity, label, role = row.split("|")
        node_rows.append((identity, label, "", role))
    edge_rows = []
    for row in edges.split(";"):
        endpoints, label, style = row.split("|")
        start, end = endpoints.split(">")
        edge_rows.append((start, end, label, style))
    return node_rows, edge_rows


GRAPHS: dict[str, Any] = {
    "health-probe": graph(
        "workload|Backend or resource|subject;setting|Probe or lifecycle-state definition|configuration;signal|Health transition|dependency;consumer|Routing or lifecycle consumer|outcome;evidence|Request and state observations|evidence",
        "setting>workload|samples defined condition|solid;workload>signal|reports observed state|solid;signal>consumer|informs supported handling|solid;evidence>workload|compares actual request behavior|dashed;evidence>consumer|checks reaction separately|dashed",
    ),
    "capacity": graph(
        "workload|Peak and recovery demand|subject;setting|Quota or capacity plan|configuration;limit|Effective service or SKU limit|dependency;allocation|Usable allocated capacity|dependency;evidence|Usage and headroom measurements|evidence",
        "workload>allocation|consumes capacity|solid;setting>limit|requests or reserves specific limit|solid;limit>allocation|constrains, does not guarantee supply|dashed;evidence>allocation|measures remaining headroom|dashed;evidence>workload|compares peak and failure demand|dashed",
    ),
    "autoscale": graph(
        "workload|Serving units or instances|subject;signal|Demand or pending-work signal|dependency;setting|Scaling bounds and cooldown|configuration;limit|Quota and startup constraints|dependency;evidence|Scale and application observations|evidence",
        "workload>signal|emits load or queue measurements|solid;signal>setting|drives supported scaling decision|solid;setting>workload|adjusts units within bounds|solid;limit>setting|limits feasible scale-out|dashed;evidence>workload|checks growth, drain and remaining readiness|dashed",
    ),
    "eligibility": graph(
        "workload|Required workload capability|subject;setting|Selected SKU or tier|configuration;matrix|Service support matrix|dependency;migration|Supported resize or migration|outcome;evidence|Effective feature and load observations|evidence",
        "workload>setting|requires a specific capability|solid;matrix>setting|establishes eligibility, not configuration|dashed;setting>migration|may require replacement or downtime|solid;evidence>setting|reads tier and enabled feature separately|dashed;evidence>migration|checks compatibility after change|dashed",
    ),
    "patch-workflow": graph(
        "workload|Eligible maintenance target|subject;setting|Scope and assigned schedule|configuration;drain|Workload preparation|dependency;update|Supported update operation|outcome;evidence|Assignment and completion records|evidence",
        "setting>workload|assigns scope-specific window|solid;workload>drain|prepares before eligible update|solid;drain>update|permits coordinated maintenance|solid;update>workload|changes supported update layer|solid;evidence>setting|checks complete assignments|dashed;evidence>update|checks completion and post-update health|dashed",
    ),
    "event-drain": graph(
        "event|Infrastructure maintenance event|dependency;setting|Guest event consumer|configuration;workload|Affected guest workload|subject;drain|Supported drain or failover procedure|outcome;evidence|Event receipt and timing|evidence",
        "event>setting|publishes event and affected resources|solid;setting>workload|matches actual target|solid;setting>drain|maps event type to bounded handling|solid;drain>workload|prepares workload before interruption|solid;evidence>setting|checks polling and acknowledgement|dashed;evidence>drain|measures handling latency and continuity|dashed",
    ),
    "supported-migration": graph(
        "workload|Current platform or version|subject;setting|Supported target selection|configuration;notice|Support and retirement notice|dependency;candidate|Tested replacement|outcome;evidence|Compatibility and cutover records|evidence",
        "notice>setting|constrains supported target and timing|dashed;workload>candidate|supported migration, not arbitrary upgrade|solid;setting>candidate|pins compatible replacement|solid;candidate>workload|rollback only when supported|dashed;evidence>candidate|validates requests and dependent features|dashed",
    ),
    "staged-deployment": graph(
        "workload|Serving workload|subject;setting|Versioned candidate configuration|configuration;candidate|Prepared candidate or slot|dependency;route|Controlled replacement or traffic switch|outcome;evidence|Warmup, regression and rollback records|evidence",
        "setting>candidate|creates reproducible candidate|solid;candidate>route|eligible only after readiness checks|solid;route>workload|replaces or switches under separate approval|solid;workload>candidate|retains rollback relationship where supported|dashed;evidence>candidate|checks state, identity and configuration|dashed;evidence>route|observes cutover and recovery|dashed",
    ),
    "bounded-recovery": graph(
        "workload|Instance or cluster resource|subject;signal|Supported health signal|dependency;setting|Repair, fencing and retry bounds|configuration;repair|Supported recovery action|outcome;evidence|Repair and application observations|evidence",
        "workload>signal|reports health|solid;signal>setting|triggers reviewed recovery condition|solid;setting>repair|limits action and repeated attempts|solid;repair>workload|repairs, restarts or fails over|solid;evidence>repair|checks completion and loop prevention|dashed;evidence>workload|checks recovered requests and state ownership|dashed",
    ),
    "bounded-retry": graph(
        "workload|Client or job operation|subject;service|Dependency response|dependency;setting|Retry classifier and total deadline|configuration;result|Committed output or terminal failure|outcome;evidence|Attempt, delay and duplicate records|evidence",
        "workload>service|attempts request|solid;service>setting|error and server delay hint|solid;setting>workload|bounded retry with backoff|solid;workload>result|commits once or exposes exhaustion|solid;evidence>setting|checks attempt and timeout bounds|dashed;evidence>result|checks idempotency and terminal failure|dashed",
    ),
    "connection-drain": graph(
        "workload|Serving backend or pod|subject;setting|Drain timeout or disruption budget|configuration;new|New work assignment|dependency;active|In-flight requests or sessions|dependency;evidence|Removal and completion observations|evidence",
        "new>workload|routes only to eligible ready capacity|solid;setting>new|constrains removal or stops new assignment|solid;workload>active|finishes existing work within limits|solid;setting>active|bounds disruption or drain interval|dashed;evidence>workload|checks remaining ready capacity|dashed;evidence>active|checks completion before shutdown|dashed",
    ),
    "cache": graph(
        "workload|API request|subject;setting|Cache key and expiry policy|configuration;cache|Cached response|dependency;backend|Origin backend|dependency;evidence|Hit, miss and freshness observations|evidence",
        "workload>setting|looks up scoped cache key|solid;setting>cache|valid hit|solid;setting>backend|miss or supported failure fallback|dashed;backend>cache|stores only eligible response|solid;evidence>cache|checks freshness and user isolation|dashed;evidence>backend|checks miss load and rate protection|dashed",
    ),
    "log-delivery": graph(
        "workload|Service event source|subject;setting|Diagnostic categories and destination|configuration;transport|Destination access and delivery path|dependency;records|Retained log records|outcome;evidence|Known event and ingestion timestamps|evidence",
        "workload>setting|emits supported categories|solid;setting>transport|exports selected events|solid;transport>records|delivers with controlled retention|solid;evidence>records|correlates source event to delivered record|dashed;evidence>transport|checks delivery failures and missing categories|dashed",
    ),
    "dns-cache": graph(
        "workload|Authoritative DNS record|subject;setting|Record TTL|configuration;resolver|Recursive resolver cache|dependency;client|Client cached address|outcome;evidence|Measured answer expiry and target health|evidence",
        "setting>workload|defines authoritative cache lifetime|solid;workload>resolver|answer and TTL|solid;resolver>client|may retain or forward cached answer|solid;evidence>client|measures last use of old answer|dashed;evidence>workload|checks publication separately from backend health|dashed",
    ),
    "network-path": graph(
        "workload|Actual source traffic|subject;setting|Effective route or connection mode|configuration;hop|Supported next hop or endpoint|dependency;target|Intended destination|outcome;return|Return path and security policy|dependency;evidence|Effective routes and request observations|evidence",
        "workload>setting|selects forwarding or service path|solid;setting>hop|uses supported route semantics|solid;hop>target|forwards permitted traffic|solid;target>return|response requires valid reverse path|solid;return>workload|returns allowed response|solid;evidence>setting|reads effective configuration|dashed;evidence>target|checks real request and fallback behavior|dashed",
    ),
    "network-capacity": graph(
        "workload|Peak connection or scale demand|subject;setting|Subnet, SNAT or bandwidth budget|configuration;reserved|Service reservations and growth|dependency;usable|Available network allocations|outcome;evidence|Address, port and bandwidth measurements|evidence",
        "reserved>setting|reduces usable headroom|dashed;setting>usable|supplies specific constrained resource|solid;workload>usable|consumes addresses, ports or bandwidth|solid;evidence>usable|compares allocated capacity with peak demand|dashed;evidence>workload|checks exhaustion before connection failures|dashed",
    ),
    "identity-boundary": graph(
        "workload|Intended principal|subject;setting|Authentication mode and access policy|configuration;directory|Supported identity sources|dependency;service|Protected operation|outcome;evidence|Allowed, denied and source-loss observations|evidence",
        "workload>directory|authenticates through intended source|solid;directory>setting|supplies supported identity evidence|solid;setting>service|permits only intended access|solid;evidence>service|tests authorized and unauthorized paths|dashed;evidence>directory|checks continuity without exposing credentials|dashed",
    ),
    "security-boundary": graph(
        "workload|Incoming operation or traffic|subject;setting|Effective rules and protected scope|configuration;inheritance|Inherited policy and exceptions|dependency;decision|Allowed or denied operation|outcome;evidence|Rule match and legitimate-traffic records|evidence",
        "inheritance>setting|contributes effective restrictions|solid;workload>setting|evaluates exact protected operation|solid;setting>decision|applies supported protection mode|solid;evidence>decision|checks legitimate and prohibited operations|dashed;evidence>setting|attributes false positives to exact rule|dashed",
    ),
    "key-lifecycle": graph(
        "workload|Encrypted data or TLS connection|subject;setting|Key, certificate or protocol policy|configuration;key|Required active and historical key material|dependency;recovery|Authorized rotation or recovery|outcome;evidence|Negotiation, version and recovery observations|evidence",
        "setting>workload|selects supported encryption contract|solid;workload>key|requires usable key and access|solid;key>recovery|retained versions enable supported recovery|solid;evidence>workload|checks negotiated protocol or active version|dashed;evidence>recovery|checks replacement and historical decryptability|dashed",
    ),
    "storage-dependencies": graph(
        "workload|Stateful application|subject;setting|Supported disk or share layout|configuration;persistent|Required persistent state|dependency;temporary|Explicitly disposable state|dependency;evidence|Mount, permission and recovery observations|evidence",
        "workload>setting|uses workload-specific layout|solid;setting>persistent|places durable state on supported storage|solid;setting>temporary|isolates state safe to recreate|dashed;evidence>persistent|checks sharing, fencing and persistence|dashed;evidence>temporary|checks no sole persistent copy is lost|dashed",
    ),
    "isolation-boundary": graph(
        "workload|Protected workload or owner|subject;setting|Resource or placement boundary|configuration;peer|Independent workload boundary|dependency;shared|Explicit shared dependencies|dependency;evidence|Placement and interference observations|evidence",
        "setting>workload|assigns ownership and capacity boundary|solid;setting>peer|separates lifecycle or policy effects|solid;workload>shared|retains reviewed required access|solid;peer>shared|shared dependency remains explicit|dashed;evidence>workload|checks actual placement and isolation|dashed;evidence>shared|checks cross-boundary access and coupling|dashed",
    ),
    "configuration-contract": graph(
        "workload|Deployed application or cluster|subject;setting|Effective scoped setting|configuration;artifact|Runtime, host or deployment artifact|dependency;lifecycle|Restart, swap or attachment operation|outcome;evidence|Readback and runtime observations|evidence",
        "artifact>setting|constrains supported values|dashed;setting>workload|controls exact runtime behavior|solid;lifecycle>workload|may change inherited or effective state|solid;evidence>setting|reads nonsecret effective value|dashed;evidence>lifecycle|checks behavior before and after operation|dashed",
    ),
    "durable-workflow": graph(
        "workload|Input, query or task|subject;setting|Progress and replay contract|configuration;checkpoint|Durable progress or continuation state|dependency;output|Committed output or failure destination|outcome;evidence|Input-to-output reconciliation|evidence",
        "workload>checkpoint|records supported progress|solid;checkpoint>setting|identifies restart or remaining work|solid;setting>workload|resumes or replays bounded work|solid;workload>output|commits output or exposes failure|solid;evidence>output|checks no silent loss or duplicate side effects|dashed;evidence>checkpoint|checks retention and access|dashed",
    ),
    "data-lineage": graph(
        "workload|Authoritative source data|subject;setting|Quality, schema and ownership boundary|configuration;accepted|Accepted governed dataset|outcome;quarantine|Invalid or unexpected records|dependency;copies|Controlled derived copies|dependency;evidence|Quality and lineage observations|evidence",
        "workload>setting|ingests with explicit contract|solid;setting>accepted|accepts valid transactional data|solid;setting>quarantine|retains or rejects invalid data explicitly|dashed;accepted>copies|derives with known ownership and freshness|solid;evidence>accepted|checks consistency and lineage|dashed;evidence>quarantine|checks no required records disappear silently|dashed",
    ),
    "data-export": graph(
        "workload|Selected supported log tables|subject;setting|Export rule and scope|configuration;destination|Independent storage destination|dependency;redundancy|GRS or GZRS destination policy|configuration;evidence|Exported records and delivery lag|evidence",
        "workload>setting|selects exportable new records|solid;setting>destination|delivers authorized exported copy|solid;redundancy>destination|defines separate storage failure coverage|solid;evidence>destination|matches known source records|dashed;evidence>setting|checks table coverage and failures|dashed",
    ),
    "recovery-objectives": graph(
        "workload|Business-critical outcome|subject;impact|Outage and data-loss impact|dependency;setting|Approved SLO, RTO and RPO|configuration;design|Architecture and recovery budget|outcome;evidence|Incidents and exercise measurements|evidence",
        "workload>impact|defines business consequence|solid;impact>setting|informs measurable target|solid;setting>design|constrains design and recovery time|solid;evidence>setting|compares actual results with target boundaries|dashed;evidence>workload|measures complete business flow|dashed",
    ),
    "critical-flows": graph(
        "workload|User or system outcome|subject;setting|Flow map and business ranking|configuration;required|Required dependencies|dependency;optional|Optional or degraded behavior|dependency;evidence|Owner review and retained flow traces|evidence",
        "workload>setting|identifies critical flow|solid;setting>required|maps blocking dependencies|solid;setting>optional|records tolerable degradation|dashed;evidence>required|checks hidden shared dependencies|dashed;evidence>setting|validates criticality with business owner|dashed",
    ),
    "data-partition": graph(
        "workload|Data access and load pattern|subject;setting|Partition key and routing strategy|configuration;first|Partition A|dependency;second|Partition B|dependency;cross|Cross-partition operation|outcome;evidence|Skew, consistency and recovery observations|evidence",
        "workload>setting|maps key to partition|solid;setting>first|routes matching key range|solid;setting>second|routes different key range|solid;first>cross|participates only with supported semantics|dashed;second>cross|cross-boundary coupling remains explicit|dashed;evidence>setting|checks hot keys and resharding cost|dashed;evidence>cross|checks consistency after partial failure|dashed",
    ),
    "failure-modes": graph(
        "workload|Critical workload flow|subject;fault|Credible dependency fault|dependency;setting|Impact and propagation analysis|configuration;mitigation|Detection, mitigation and recovery owners|outcome;evidence|Incident or approved exercise evidence|evidence",
        "fault>workload|can propagate business impact|solid;workload>setting|defines effect and criticality|solid;setting>mitigation|prioritizes controls and residual risk|solid;evidence>fault|challenges assumed independence|dashed;evidence>mitigation|compares predicted and observed recovery|dashed",
    ),
    "model-throughput": graph(
        "workload|Token and concurrency demand|subject;setting|Supported model and provisioned units|configuration;quota|Quota and approved geography|dependency;serving|Model-serving capacity|outcome;evidence|Latency, utilization and throttling|evidence",
        "workload>serving|consumes purchased serving capacity|solid;setting>serving|configures compatible provisioned model|solid;quota>setting|constrains eligibility, not request success|dashed;evidence>serving|measures sustained and peak behavior|dashed;evidence>quota|checks processing-policy review|dashed",
    ),
    "model-routing": graph(
        "workload|PAYG model requests|subject;setting|Global Standard deployment mapping|configuration;placement|Service-managed request placement|dependency;policy|Approved processing geography|configuration;evidence|Type, quota and route observations|evidence",
        "workload>setting|selects compatible model deployment|solid;setting>placement|uses documented Global processing model|solid;policy>setting|constrains acceptable deployment type|dashed;evidence>setting|reads actual type and model version|dashed;evidence>placement|does not infer customer regional failover|dashed",
    ),
    "model-overflow": graph(
        "workload|Model requests|subject;primary|Provisioned deployment|dependency;setting|Explicit bounded overflow policy|configuration;alternate|Compatible PAYG deployment|dependency;evidence|Route, quota and throttling observations|evidence",
        "workload>primary|normal provisioned request|solid;primary>setting|eligible throttling or error condition|dashed;setting>alternate|routes only policy-approved compatible overflow|solid;evidence>setting|checks deadlines and retry bounds|dashed;evidence>alternate|checks separate quota and geography eligibility|dashed",
    ),
    "model-batch": graph(
        "workload|Offline request items|subject;setting|Supported Global Batch submission|configuration;job|Asynchronous batch job|dependency;results|Completed and failed result items|outcome;evidence|Deadline and count reconciliation|evidence",
        "workload>setting|validates batch-compatible inputs|solid;setting>job|submits under supported model and geography|solid;job>results|completes asynchronously, not online failover|solid;evidence>results|reconciles all submitted items|dashed;evidence>job|checks status, deadline and cancellation|dashed",
    ),
    "model-geography": graph(
        "workload|Model request and data policy|subject;setting|Data Zone Standard deployment|configuration;zone|Documented processing data zone|dependency;alternate|Separately approved alternate route|dependency;evidence|Type, model, quota and policy evidence|evidence",
        "workload>setting|requires compatible reviewed deployment|solid;setting>zone|uses documented processing boundary|solid;workload>alternate|only if same constraints remain satisfied|dashed;evidence>setting|checks actual type, not account region alone|dashed;evidence>alternate|checks residency and model eligibility separately|dashed",
    ),
    "recovery-plan": graph(
        "workload|Critical business flow|subject;setting|Ordered recovery and failback runbook|configuration;state|Recoverable data and identity|dependency;target|Prepared target network and capacity|dependency;evidence|Measured flow recovery and data loss|evidence",
        "setting>state|restores prerequisites in dependency order|solid;state>target|makes state usable at recovery target|solid;target>workload|resumes validated business flow|solid;setting>workload|defines activation, stop and failback decisions|dashed;evidence>workload|compares actual RTO and RPO|dashed;evidence>target|records blocked dependency steps|dashed",
    ),
}
