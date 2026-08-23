export const NETWORK_BOUNDARY_ROLES = Object.freeze([
  "external",
  "on-premises",
  "dmz",
  "hub",
  "spoke",
  "virtual-network",
  "subnet",
  "private-endpoint",
]);

export const NETWORK_CONNECTION_KINDS = Object.freeze([
  "vnet-peering",
  "vnet-connection",
  "expressroute",
  "vpn",
  "private-link",
  "service-endpoint",
  "routing",
  "traffic",
]);

export const NETWORK_TRAFFIC_CLASSES = Object.freeze([
  "internet",
  "private",
  "management",
  "hybrid",
]);

export const NETWORK_POLICIES = Object.freeze([
  "allow",
  "deny",
  "inspect",
  "bypass",
]);

export const NETWORK_DIRECTIONS = Object.freeze([
  "forward",
  "reverse",
  "bidirectional",
]);

export const NETWORK_EVIDENCE_POSTURES = Object.freeze([
  "expected",
  "observed",
  "stale",
  "partial",
  "unknown",
]);

export const NETWORK_PATH_STATUSES = Object.freeze([
  "found",
  "no_observed_path",
  "unknown",
]);

export const NETWORK_LAYOUT_PRESETS = Object.freeze([
  "hub-spoke",
  "dual-ingress",
  "private-endpoint-fanout",
]);

export const NETWORK_CONNECTION_LABELS = Object.freeze({
  "vnet-peering": "VNet peering",
  "vnet-connection": "VNet connection",
  expressroute: "ExpressRoute",
  vpn: "VPN",
  "private-link": "Private Link",
  "service-endpoint": "Service endpoint",
  routing: "Routing",
  traffic: "Traffic flow",
});

/** Returns whether a value is a canonical network vocabulary member. */
export function networkVocabularyHas(values, value) {
  return typeof value === "string" && values.includes(value);
}

/** Returns the stable English fallback label for a connection kind. */
export function networkConnectionLabel(kind) {
  return NETWORK_CONNECTION_LABELS[kind];
}
