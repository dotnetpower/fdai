---
title: Network Topology Visualization
---
# Network Topology Visualization

This document owns the shared network meaning and presentation contract used by generated FDAI
architecture diagrams and the read-only Console Architecture route. It keeps authored design intent
separate from observed inventory evidence while giving both surfaces one stable vocabulary for
boundaries, connections, traffic paths, routing intent, and security inspection.

> **Authority boundary:** A diagram explains expected or observed topology. It never proves
> reachability, grants network or execution authority, or turns an inferred path into an observed
> fact.
>
> **Provider scope:** The vocabulary is cloud-provider-neutral. Azure is the only implemented icon
> and inventory adapter, so Azure resource types receive the first complete visual mapping.

## Design at a glance

The static compiler accepts an authored network profile with explicit topology and routing intent.
The Console derives a bounded network focus projection only from inventory resources and typed
relationships. Both surfaces import the same canonical network roles and connection semantics,
but they use separate contracts. Authored diagrams are `expected`; Console topology is `observed`,
`stale`, `partial`, or `unknown` according to its inventory receipt.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Shared network vocabulary and authored schema | implemented | `packages/network-topology-contracts`; network schema and validation; focused package and compiler tests | The dependency-free vocabulary is shared, while authored `expected` posture and observed evidence rules remain separate. |
| Network reference layout and Azure icon coverage | implemented | `layout/elk.ts`; reviewed icon mapping and 14 digest-locked official Azure SVGs; canonical bilingual fixture | The network profile adds compact compound layout without changing existing deployment layout behavior. Unknown resource types remain unmapped. |
| Console 2D focus, path tracing, and export | implemented | `architecture-network-{focus,map,tools,icons}.ts*`; route integration; focused Console and three-viewport checks | The mode consumes the existing authoritative inventory response, uses reviewed official icons when mapped, traces only typed relationships, and exports one identifier-free SVG source as SVG or PNG. |
| Console Ontology Instances network context | implemented | `ontology-instance-graph.{model.ts,tsx}`; `ontology-instance-resource-icons.ts`; focused tests; Console typecheck and production build; authenticated three-viewport checks | The selected branch presents VNet, Subnet, Private Endpoint, and NIC hierarchy without expanding a peer VNet branch. Reciprocal peering shares one occurrence while retaining both stored records. Observed `runtime_calls` links are a first-class Inspector group and remain visible in the default dense legend. Wheel zoom, native full screen, empty-canvas pan, and a collapsible Inspector preserve the graph workspace. |
| Integrity, accessibility, and visual regression | implemented | static compiler tests (`107 passed`); exact `1600x900` artifact check; sequential three-viewport Playwright (`1 passed`) | Synthetic browser evidence proves presentation mechanics only. No governed runtime validation is claimed. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-04 | implemented | Promoted observed `runtime_calls` relationships from a generic direct edge to a first-class runtime group in the Ontology Instances Inspector and default dense legend. The screen-context projection also preserves these verified links for grounded follow-up without changing relationship direction or authority. | `current change`; focused ontology instance model and view checks, Console typecheck, and production build. | Retain governed exact-source runtime-call and responsive Console evidence before claiming runtime validation. |
| 2026-08-22 | not-started | Accepted a focused owner boundary for network-topology visualization without changing runtime behavior. | `current change`; this owner document. | Implement and focused-test every scope row before raising its state. |
| 2026-08-22 | implemented | Added the shared provider-neutral vocabulary, authored network profile and annotations, reviewed official Azure icon mapping, compact network layout and integrity checks, a canonical bilingual hub-spoke reference, and an observed-only Console 2D focus with filters, typed path tracing, keyboard interaction, and sanitized SVG and PNG export. | `current change`; shared package test passed; static compiler passed 107 tests, typecheck, render, and 376-artifact check; canonical output is exactly `1600x900` with zero clipped text; Console focused checks passed 23 tests; synthetic Playwright passed `1440x900`, `993x641`, and `390x844`; catalog parity passed 17 pairs. | Retain governed exact-source desktop and mobile Console evidence before changing the Console scope to `validated`. |
| 2026-08-22 | implemented | Hardened the rendered result after direct PNG and authenticated mobile review. Resource-type icons now reserve nonzero geometry, final compound placement reroutes every network edge to its current endpoint boundary, `orthogonal-gap` uses sibling-group corridors, the deterministic font subset covers the complete bilingual diagram corpus, and Console nodes reuse the reviewed official icons with boundary-terminated halo links and 44 px mobile targets. | `current change`; canonical endpoint, collision, crossing, icon, font digest, and bilingual PNG checks; focused Console map and layout checks; Console typecheck and production build; sequential `1440x900`, `993x641`, and `390x844` Playwright; authenticated mobile measured four official icons, four 3 px attachment paths, four endpoint dots, 44.9 px node targets, 44 px controls, and zero horizontal overflow. | Retain governed exact-source desktop and mobile Console evidence before changing the Console scope to `validated`. |
| 2026-08-22 | implemented | Closed the remaining live-map and export parity gaps with a dual-VNet dense fixture. One shared obstacle-aware router now avoids unrelated node cards in both surfaces, peer VNet boundaries use a direct header corridor, peering and dependency directions retain arrowheads, attachment endpoints retain dots, and export embeds all reviewed SVG source without a runtime fetch. | `current change`; reviewed-icon embedding and sanitizer checks (`3 passed`); network route, map, focus, layout, and path checks (`71 passed`); Console typecheck and production build; sequential desktop, constrained, and mobile Playwright with five reviewed captures; downloaded SVG contained embedded official icons, typed markers, legend, and no resource names or ids; downloaded PNG exceeded the nonblank threshold. | Retain governed exact-source desktop and mobile Console evidence before changing the Console scope to `validated`. |
| 2026-08-23 | implemented | Hardened the Ontology Instances graph around the selected network branch. VNet context now includes only its direct Subnets and their attached Private Endpoints and NICs, does not recursively expand peer branches, and shares one node occurrence for reciprocal `peered_with` records. The viewport adds ordinary wheel zoom, fixed-node empty-canvas pan, and a mobile Fit overview down to 10%. | `current change`; `npm --prefix console test -- --run src/routes/ontology-instance-graph.model.test.ts src/routes/ontology-instances.model.test.ts src/routes/ontology-instance-resource-icons.test.ts` (`37 passed`); Console typecheck and production build; authenticated `1440x900`, `993x641`, and `390x844` checks measured zero duplicate resource ids, zero node collisions, zero document overflow, and the observed branch at VNet level 0, Subnet level 1, and NIC level 2. | Preserve a governed exact-source receipt before raising this bounded row to `validated`. |
| 2026-08-23 | implemented | Corrected the Private DNS zone group icon and audited the complete active Resource-type set. Seven exact V24 Azure assets now cover API Management, Disk Snapshots, NAT, SQL Database, SQL Server, Subscriptions, and Logic Apps; DNS zone groups reuse the exact DNS Zones product family, and Azure Monitor workspaces use Azure Monitor. Role assignments, data collection endpoints, and unclassified resources remain explicit generic fallbacks because the verified archive has no exact product icon or the type is intentionally unclassified. The graph toolbar now exposes one native full-screen command while ordinary wheel input owns zoom, and the selected-instance Inspector can collapse without discarding its view state. | `current change`; Azure asset integrity (`107 passed`); focused icon, view-control, and localization tests; authenticated `1440x900`, `993x641`, and `390x844` checks measured full-screen bounds matching each viewport, 44 px mobile controls, Inspector space recovery, working wheel zoom, and zero document overflow. | Preserve a governed exact-source receipt before raising this bounded row to `validated`. |

### Remaining work

- [x] Validate a canonical hub-and-spoke fixture at `1600x900` with no clipped labels, node
  collisions, avoidable edge crossings, or missing Azure icons.
- [x] Render an observed Console VNet focus at desktop, constrained desktop, and
  mobile widths with source-to-destination path highlighting and no inferred reachability claim.
- [x] Export accessible SVG and PNG artifacts whose provenance and evidence posture remain visible.
- [ ] Retain governed exact-source desktop and mobile Console evidence before claiming runtime
  validation.

## Canonical vocabulary

The contract uses stable ASCII machine values and localized display labels.

Every ResourceClass the catalog vocabulary declares carries an explicit layer, colour, and
abbreviation. A type added to the catalog without them falls back to a generic shape, so the map
would keep drawing while silently losing the distinction the catalog had just made. Kubernetes
EndpointSlice, Ingress, and IngressClass entered the vocabulary that way and are now mapped.

### Boundary roles

| Role | Meaning |
|------|---------|
| `external` | Internet, partner, or another workload outside the rendered network boundary. |
| `on-premises` | A connected private estate outside the cloud network. |
| `dmz` | A boundary dedicated to controlled ingress or administration. |
| `hub` | Shared routing, security, connectivity, or DNS services. |
| `spoke` | A workload network connected through a hub or peering relationship. |
| `virtual-network` | A provider network boundary. |
| `subnet` | An address segment within a virtual network. |
| `private-endpoint` | A private data-plane endpoint attached to a subnet. |

### Connection kinds

| Kind | Meaning | Default direction |
|------|---------|-------------------|
| `vnet-peering` | Private virtual-network peering. | bidirectional |
| `vnet-connection` | Hub or virtual-WAN connection. | bidirectional |
| `expressroute` | Private circuit and gateway connection. | bidirectional |
| `vpn` | Encrypted site or point-to-site connection. | bidirectional |
| `private-link` | Private endpoint to service data plane. | forward |
| `service-endpoint` | Subnet-scoped service endpoint. | forward |
| `routing` | Next-hop or route-propagation relationship. | forward |
| `traffic` | A logical application or management traffic flow. | forward |

### Traffic and policy values

- `trafficClass`: `internet`, `private`, `management`, or `hybrid`.
- `policy`: `allow`, `deny`, `inspect`, or `bypass`.
- `direction`: `forward`, `reverse`, or `bidirectional`.
- `protocol` and `port`: optional display metadata, never reachability evidence by themselves.
- `nextHop`: an optional authored next-hop label or observed typed resource reference.
- `sourceEvidence`: `expected`, `observed`, `stale`, `partial`, or `unknown`.

The shared vocabulary contains enums and display metadata only. It owns no layout, inventory,
freshness, or authority decision. The authored and observed contracts import these values and
validate their own posture-specific rules.

## Authored diagram contract

`kind: network` selects a network-specific reference profile instead of the generic layered alias.
The authored contract fixes `posture: expected`. The YAML remains semantic rather than
pixel-authored:

- Groups can declare `networkRole`, `addressPrefixes`, `region`, and `availabilityZones`.
- Nodes can declare `networkRole` plus bounded provider-neutral address, listener, SKU, and security
  display facts. These values are documentation, not credentials or effective-policy evidence.
- Edges can declare `connectionKind`, `direction`, `trafficClass`, `policy`, `protocol`, `port`, and
  `nextHop`.
- Notes are first-class annotations with localized title and body, a policy or information tone,
  and an anchor to a group, node, edge, or canvas corner.
- A route-intent annotation can summarize Internet and private traffic handling without pretending
  to be a resource node.

The compiler provides `hub-spoke`, `dual-ingress`, and `private-endpoint-fanout` presets. Presets
select hierarchy handling, stable group placement, ports, routing corridors, and crossing
minimization. Authors can override semantic placement and edge corridors, but don't supply raw SVG
or arbitrary CSS.

The `network-azure-reference` profile targets a complete first view at `1600x900`. Larger diagrams
remain pannable, but the first frame must expose the topology title, major boundaries, connection
types, routing intent, and legend. A slide-oriented profile may reduce description detail before it
reduces service labels or hides a major boundary.

## Observed Console contract

The Console keeps the existing complete `InventoryGraphResponse` wire contract and adds an explicit
`Network` mode. The observed presentation contract wraps that response with current scope,
freshness, truncation, active filters, and an optional client-computed path result. It cannot be
serialized back as inventory. The mode is a presentation projection, not a second inventory source:

1. A VNet, subnet, gateway, firewall, private endpoint, or resource-group selection resolves the
   smallest observed network focus that contains the selected resource.
2. The 2D top view retains observed containment, `attached_to`, `depends_on`, and `peered_with`
   links. It doesn't convert layout order, resource names, or provider identifiers into traffic.
3. The focus view expands observed VNet and subnet boundaries and keeps unrelated subscription
   content outside the frame. The complete factual count and relationship index remain available.
4. A source and destination selector traces the shortest typed relationship path. Each hop shows
  its recorded relationship kind and evidence posture. The presentation result is `found`,
  `no_observed_path`, or `unknown`. A truncated, partial, stale, or relationship-incomplete graph
  cannot return `no_observed_path`; it returns `unknown`. Neither negative result reports `Blocked`
  or `Allowed` without authoritative policy or effective-route evidence.

The mode provides filters for public exposure, private-only resources, security boundaries,
gateways, DNS, and private endpoints. A selected path highlights its hops and mutes unrelated
content locally. Clearing the path restores the full focus without changing the underlying graph.

## Network resource presentation

Official Azure product icons are used only for actual Azure services and retain their product
names. The verified allowlist covers at least Virtual Network, subnet, Virtual WAN and hub, Azure
Firewall, Bastion, Application Gateway, VPN Gateway, ExpressRoute gateway and circuit, private
endpoint, public IP, route table, NSG, load balancer, network interface, and virtual machine.

The static compiler maps known provider resource types to those icon ids. An unknown type stays a
text card or stable abbreviation and never borrows a similar Azure product icon. The Console uses
the same reviewed icon files in 2D mode and falls back to its stable abbreviation only for an
unmapped type; its existing isometric mode keeps shape, color, and abbreviation redundancy.

## Layout and integrity

Network layout builds on ELK compound graphs with `INCLUDE_CHILDREN`, orthogonal routing, explicit
fixed-side ports, and layered crossing minimization. Network semantics remain additive properties
on existing group, node, and edge kinds, which preserves compatibility with non-network diagram
kinds. The compiler then validates:

- node-to-node, group-to-group, and node-to-unrelated-group overlap;
- node escape from a parent and group label clipping;
- edge and step-badge overlap with nodes, labels, and annotations;
- avoidable edge-to-edge crossings and overlapping collinear segments;
- boundary crossings without an explicit connection endpoint;
- annotation and legend containment inside the target viewport.

The integrity check may exempt intentional shared trunks, bidirectional paired markers, and edges
that meet at the same endpoint. Every exemption is structural and deterministic rather than a
diagram-specific id allowlist.

Network presets reroute every automatic edge after final compound placement so an ELK route cannot
retain stale pre-placement coordinates. `orthogonal-gap` derives its row and sibling corridors from
positioned groups. Integrity checks require both edge ends to touch their current endpoint boundary
and reject unrelated node crossings, proper edge crossings, and label collisions.

## Interaction, accessibility, and export

Static diagrams retain accessible SVG, localized alt text, node focus, connected-flow details,
pan, zoom, overview, fullscreen, and download. Network connections expose their kind, direction,
traffic class, policy, protocol, port, and evidence posture in the detail panel.

The Console provides DOM controls equivalent to every Canvas-only operation: focus selection,
source and destination selection, path result, filters, relationship list, fit, and export. Export
creates a sanitized SVG snapshot and optional PNG from the current focus. It embeds no credential,
subscription id, raw provider resource id, endpoint, or customer-specific value. Live exports show
snapshot time, source, freshness, scope, truncation, and `Read-only observed topology`.
Observed links terminate on node and region boundaries rather than at visual centers. A neutral
halo and typed endpoint dot keep short containment attachments visible across nested boundaries,
and mobile icon nodes expose at least a 44 px pointer and keyboard target.
The live map and sanitized export share one obstacle-aware orthogonal router. Peer VNet boundaries
use a direct header corridor instead of detouring around their child nodes. Dependencies keep a
forward arrow, peering keeps arrows at both ends, and attachment links keep an endpoint dot. Export
embeds the reviewed SVG source at build time and doesn't fetch a local or remote icon URL.

## Validation matrix

| Gate | Required evidence |
|------|-------------------|
| Schema | Shared-vocabulary parity plus separate positive and negative fixtures for authored diagrams and observed presentation state. |
| Layout | Canonical hub-spoke, dual-ingress, private-endpoint fan-out, and dense crossing fixtures pass integrity checks. |
| Rendering | English and Korean SVG contain every boundary, icon, connection, annotation, and accessible detail. |
| Console model | Focus selection, ambiguity, path tracing, filtering, and no-observed-path behavior pass deterministic tests. |
| Console UI | Desktop `1440x900`, constrained desktop `993x641`, and mobile `390x844` show no incoherent overlap or horizontal document overflow. |
| Provenance | Stale, partial, expected, observed, and unknown states remain distinct in UI and export. |

An adversarial contract test rejects an observed presentation that marks an inferred edge as
`observed` or reports `no_observed_path` from incomplete relationship coverage.

## Related docs

| To learn about | Read |
|----------------|------|
| Inventory authority and restricted network collection | [Restricted-network Azure inventory](../architecture/azure-inventory-network-paths.md) |
| Console evidence and map resilience | [Console Evidence and Resilience](console-evidence-and-resilience.md#architecture-map-resilience) |
| Deployment network requirements | [Network Connectivity Matrix](../deployment/network-connectivity-matrix.md) |
