export type NetworkBoundaryRole =
  | "external"
  | "on-premises"
  | "dmz"
  | "hub"
  | "spoke"
  | "virtual-network"
  | "subnet"
  | "private-endpoint";

export type NetworkConnectionKind =
  | "vnet-peering"
  | "vnet-connection"
  | "expressroute"
  | "vpn"
  | "private-link"
  | "service-endpoint"
  | "routing"
  | "traffic";

export type NetworkTrafficClass = "internet" | "private" | "management" | "hybrid";
export type NetworkPolicy = "allow" | "deny" | "inspect" | "bypass";
export type NetworkDirection = "forward" | "reverse" | "bidirectional";
export type NetworkEvidencePosture = "expected" | "observed" | "stale" | "partial" | "unknown";
export type NetworkPathStatus = "found" | "no_observed_path" | "unknown";
export type NetworkLayoutPreset = "hub-spoke" | "dual-ingress" | "private-endpoint-fanout";

export const NETWORK_BOUNDARY_ROLES: readonly NetworkBoundaryRole[];
export const NETWORK_CONNECTION_KINDS: readonly NetworkConnectionKind[];
export const NETWORK_TRAFFIC_CLASSES: readonly NetworkTrafficClass[];
export const NETWORK_POLICIES: readonly NetworkPolicy[];
export const NETWORK_DIRECTIONS: readonly NetworkDirection[];
export const NETWORK_EVIDENCE_POSTURES: readonly NetworkEvidencePosture[];
export const NETWORK_PATH_STATUSES: readonly NetworkPathStatus[];
export const NETWORK_LAYOUT_PRESETS: readonly NetworkLayoutPreset[];
export const NETWORK_CONNECTION_LABELS: Readonly<Record<NetworkConnectionKind, string>>;

export function networkVocabularyHas<T extends string>(values: readonly T[], value: unknown): value is T;
export function networkConnectionLabel(kind: NetworkConnectionKind): string;
