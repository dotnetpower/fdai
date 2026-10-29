import type { ArchitectureLayer, ArchitectureResourceColorToken } from "./architecture-map.model";

export const WARA_ARCHITECTURE_COLOR_TOKENS = {
  "managed-domain": { label: "Managed directory", color: "#1988D9" },
  "application-configuration": { label: "Application configuration", color: "#0078D4" },
  automation: { label: "Automation", color: "#697586" },
  "private-virtualization": { label: "Private virtualization", color: "#1490DF" },
  "batch-compute": { label: "Batch compute", color: "#0078D4" },
  "content-delivery": { label: "Content delivery", color: "#5EA0EF" },
  "image-gallery": { label: "Image gallery", color: "#0078D4" },
  analytics: { label: "Analytics workspace", color: "#005BA1" },
  "virtual-desktop": { label: "Virtual desktop", color: "#0078D4" },
  "iot-hub": { label: "Device messaging", color: "#32BEDD" },
  "event-topic": { label: "Event topic", color: "#32BEDD" },
  "machine-learning": { label: "Machine learning", color: "#0078D4" },
  "private-connectivity": { label: "Private connectivity", color: "#5E9624" },
  "ddos-protection": { label: "DDoS protection", color: "#E62323" },
  "vpn-gateway": { label: "VPN gateway", color: "#5E9624" },
  "traffic-routing": { label: "Traffic routing", color: "#5E9624" },
  "network-hub": { label: "Transit hub and router", color: "#5E9624" },
  "vpn-site": { label: "VPN site", color: "#5E9624" },
  backup: { label: "Backup and recovery", color: "#37C2B1" },
  "realtime-messaging": { label: "Real-time messaging", color: "#32BEDD" },
  "stream-analytics": { label: "Stream analytics", color: "#005BA1" },
} as const;

export const WARA_ARCHITECTURE_RESOURCE_VISUALS = {
  "directory.managed-domain": { layer: "security", colorToken: "managed-domain", abbreviation: "aadds" },
  "application-configuration": { layer: "runtime", colorToken: "application-configuration", abbreviation: "appcs" },
  "automation-account": { layer: "runtime", colorToken: "automation", abbreviation: "aa" },
  "compute.private-virtualization-cloud": { layer: "runtime", colorToken: "private-virtualization", abbreviation: "avs" },
  "compute.batch-account": { layer: "runtime", colorToken: "batch-compute", abbreviation: "ba" },
  "network.cdn-profile": { layer: "network", colorToken: "content-delivery", abbreviation: "cdnp" },
  "network.cdn-origin-group": { layer: "network", colorToken: "content-delivery", abbreviation: "cdnog" },
  "compute.image-gallery": { layer: "runtime", colorToken: "image-gallery", abbreviation: "gal" },
  "compute.gallery-image-version": { layer: "runtime", colorToken: "image-gallery", abbreviation: "galver" },
  "compute.gallery-image": { layer: "runtime", colorToken: "image-gallery", abbreviation: "galimg" },
  "analytics.workspace": { layer: "data", colorToken: "analytics", abbreviation: "dbw" },
  "compute.desktop-host-pool": { layer: "runtime", colorToken: "virtual-desktop", abbreviation: "vdpool" },
  "compute.desktop-scaling-plan": { layer: "runtime", colorToken: "virtual-desktop", abbreviation: "vdsc" },
  "iot-hub": { layer: "messaging", colorToken: "iot-hub", abbreviation: "iot" },
  "event-topic": { layer: "messaging", colorToken: "event-topic", abbreviation: "egt" },
  "activity-log-alert": { layer: "observability", colorToken: "azure-monitor", abbreviation: "ala" },
  "ml-model-registry": { layer: "data", colorToken: "machine-learning", abbreviation: "mlr" },
  "ml-workspace": { layer: "runtime", colorToken: "machine-learning", abbreviation: "mlw" },
  "file-volume": { layer: "data", colorToken: "file-share", abbreviation: "anfvol" },
  "storage.file-account": { layer: "data", colorToken: "file-share", abbreviation: "anfa" },
  "storage.file-capacity-pool": { layer: "data", colorToken: "file-share", abbreviation: "anfpool" },
  "network.connection": { layer: "network", colorToken: "private-connectivity", abbreviation: "con" },
  "network.ddos-protection-plan": { layer: "security", colorToken: "ddos-protection", abbreviation: "ddos" },
  "network.private-circuit": { layer: "network", colorToken: "private-connectivity", abbreviation: "erc" },
  "network.private-circuit-gateway": { layer: "network", colorToken: "private-connectivity", abbreviation: "ergw" },
  "network.private-peering-port": { layer: "network", colorToken: "private-connectivity", abbreviation: "erd" },
  "observability.network-flow-log": { layer: "observability", colorToken: "azure-monitor", abbreviation: "nwfl" },
  "network.user-vpn-gateway": { layer: "network", colorToken: "vpn-gateway", abbreviation: "vpng" },
  "network.dns-routing-profile": { layer: "network", colorToken: "traffic-routing", abbreviation: "traf" },
  "network.virtual-hub": { layer: "network", colorToken: "network-hub", abbreviation: "vhub" },
  "network.virtual-router": { layer: "network", colorToken: "network-hub", abbreviation: "vrt" },
  "network.site-vpn-gateway": { layer: "network", colorToken: "vpn-gateway", abbreviation: "vpng" },
  "network.vpn-site": { layer: "network", colorToken: "vpn-site", abbreviation: "vst" },
  "observability.traffic-collector": { layer: "observability", colorToken: "azure-monitor", abbreviation: "atc" },
  "backup-vault": { layer: "data", colorToken: "backup", abbreviation: "rsv" },
  "realtime-messaging-service": { layer: "messaging", colorToken: "realtime-messaging", abbreviation: "sigr" },
  "sql-managed-instance": { layer: "data", colorToken: "database", abbreviation: "sqlmi" },
  "stream-analytics-job": { layer: "data", colorToken: "stream-analytics", abbreviation: "asa" },
  "compute.image-template": { layer: "runtime", colorToken: "image-gallery", abbreviation: "it" },
  "compute.app-slot": { layer: "runtime", colorToken: "app-service", abbreviation: "slot" },
  "database.dedicated-infrastructure": { layer: "data", colorToken: "database", abbreviation: "dbinfra" },
  "database.vm-cluster": { layer: "data", colorToken: "database", abbreviation: "dbcl" },
} as const satisfies Readonly<Record<string, {
  readonly layer: ArchitectureLayer;
  readonly colorToken: ArchitectureResourceColorToken;
  readonly abbreviation: string;
}>>;

export const WARA_ARCHITECTURE_LAYERS = Object.fromEntries(
  Object.entries(WARA_ARCHITECTURE_RESOURCE_VISUALS).map(([type, value]) => [type, value.layer] as const),
);
export const WARA_ARCHITECTURE_COLORS = Object.fromEntries(
  Object.entries(WARA_ARCHITECTURE_RESOURCE_VISUALS).map(([type, value]) => [type, value.colorToken] as const),
);
export const WARA_ARCHITECTURE_ABBREVIATIONS = Object.fromEntries(
  Object.entries(WARA_ARCHITECTURE_RESOURCE_VISUALS).map(([type, value]) => [type, value.abbreviation] as const),
);
