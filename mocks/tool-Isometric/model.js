export const WORLD = { width: 18, height: 12, grid: 0.5 };
export const RESOURCE_FOOTPRINT = { width: 1.08, depth: 0.8 };

export const CATEGORIES = {
  edge:     { name: "Edge",     color: "#e56855", description: "Public ingress" },
  security: { name: "Security", color: "#d99a3e", description: "Policy and inspection" },
  network:  { name: "Network",  color: "#27989b", description: "Routing and delivery" },
  compute:  { name: "Compute",  color: "#397fba", description: "Application runtime" },
  data:     { name: "Data",     color: "#8a62b7", description: "State and persistence" },
};

export const CATALOG = {
  frontdoor: { label: "FD", name: "Front Door", category: "edge" },
  waf:       { label: "WAF", name: "Application Gateway", category: "security" },
  firewall:  { label: "FW", name: "Azure Firewall", category: "security" },
  loadbalancer: { label: "L4", name: "Load Balancer", category: "network" },
  nat:       { label: "NAT", name: "NAT Gateway", category: "network" },
  appservice: { label: "APP", name: "App Service", category: "compute" },
  function:  { label: "FN", name: "Function App", category: "compute" },
  aks:       { label: "AKS", name: "AKS Cluster", category: "compute" },
  containerapp: { label: "CA", name: "Container App", category: "compute" },
  postgres:  { label: "PG", name: "PostgreSQL", category: "data" },
  storage:   { label: "ST", name: "Storage Account", category: "data" },
  redis:     { label: "RD", name: "Managed Redis", category: "data" },
  keyvault:  { label: "KV", name: "Key Vault", category: "security" },
};

export const FILTERS = {
  scopes:      { name: "Scope boundaries", color: "#697586", description: "Subscription and resource groups" },
  network:     { name: "Network zones", color: "#347f86", description: "VNet and subnets" },
  security:    { name: "Security", color: CATEGORIES.security.color, description: "WAF, firewall and secrets" },
  compute:     { name: "Compute", color: CATEGORIES.compute.color, description: "Application runtimes" },
  data:        { name: "Data", color: CATEGORIES.data.color, description: "Databases and storage" },
  connections: { name: "Connections", color: "#4e6577", description: "Traffic and dependencies" },
};

const initialRegions = [
  { id: "sub-prod", kind: "subscription", filter: "scopes", name: "Production subscription", subtitle: "00000000-0000-0000-0000-000000000000", x: 0.35, y: 0.35, w: 17.3, h: 11.3, parentId: null },
  { id: "rg-network", kind: "resource-group", filter: "scopes", name: "rg-network", subtitle: "Connectivity", x: 0.9, y: 1.25, w: 6.2, h: 9.5, parentId: "sub-prod", tone: "teal" },
  { id: "rg-app", kind: "resource-group", filter: "scopes", name: "rg-app", subtitle: "Application", x: 7.4, y: 1.25, w: 5.2, h: 9.5, parentId: "sub-prod", tone: "blue" },
  { id: "rg-data", kind: "resource-group", filter: "scopes", name: "rg-data", subtitle: "Data services", x: 12.9, y: 1.25, w: 4.2, h: 9.5, parentId: "sub-prod", tone: "violet" },
  { id: "vnet-hub", kind: "vnet", filter: "network", name: "vnet-hub", subtitle: "10.10.0.0/16", x: 1.35, y: 2.15, w: 5.25, h: 7.8, parentId: "rg-network", tone: "teal" },
  { id: "snet-ingress", kind: "subnet", filter: "network", name: "snet-ingress", subtitle: "10.10.1.0/24", x: 1.75, y: 2.85, w: 4.45, h: 2.45, parentId: "vnet-hub", tone: "cyan" },
  { id: "snet-private", kind: "subnet", filter: "network", name: "snet-private", subtitle: "10.10.2.0/24", x: 1.75, y: 5.75, w: 4.45, h: 3.6, parentId: "vnet-hub", tone: "green" },
];

const initialResources = [
  { id: "fd-prod", type: "frontdoor", name: "fd-prod", x: 1.0, y: 1.0, parentId: "sub-prod", status: "healthy" },
  { id: "agw-prod", type: "waf", name: "agw-prod", x: 2.35, y: 3.55, parentId: "snet-ingress", status: "healthy" },
  { id: "lb-internal", type: "loadbalancer", name: "lb-internal", x: 4.75, y: 4.0, parentId: "snet-ingress", status: "healthy" },
  { id: "fw-hub", type: "firewall", name: "fw-hub", x: 2.45, y: 7.0, parentId: "snet-private", status: "healthy" },
  { id: "nat-hub", type: "nat", name: "nat-hub", x: 4.85, y: 8.1, parentId: "snet-private", status: "healthy" },
  { id: "web-api", type: "appservice", name: "web-api", x: 8.45, y: 3.0, parentId: "rg-app", status: "healthy" },
  { id: "worker", type: "containerapp", name: "event-worker", x: 10.65, y: 3.9, parentId: "rg-app", status: "healthy" },
  { id: "scheduler", type: "function", name: "scheduler", x: 8.65, y: 6.1, parentId: "rg-app", status: "warning" },
  { id: "aks-ops", type: "aks", name: "aks-ops", x: 10.6, y: 7.55, parentId: "rg-app", status: "healthy" },
  { id: "kv-prod", type: "keyvault", name: "kv-prod", x: 8.35, y: 9.0, parentId: "rg-app", status: "healthy" },
  { id: "pg-prod", type: "postgres", name: "pg-prod", x: 13.65, y: 3.15, parentId: "rg-data", status: "healthy" },
  { id: "redis-prod", type: "redis", name: "redis-prod", x: 15.45, y: 5.35, parentId: "rg-data", status: "healthy" },
  { id: "stprod", type: "storage", name: "stprod", x: 13.8, y: 7.8, parentId: "rg-data", status: "healthy" },
];

const initialConnections = [
  { id: "e1", source: "fd-prod", target: "agw-prod", kind: "ingress", label: "HTTPS :443" },
  { id: "e2", source: "agw-prod", target: "lb-internal", kind: "ingress", label: "WAF policy" },
  { id: "e3", source: "lb-internal", target: "web-api", kind: "internal", label: "Private ingress" },
  { id: "e4", source: "web-api", target: "worker", kind: "internal", label: "Events" },
  { id: "e5", source: "scheduler", target: "worker", kind: "internal", label: "Jobs" },
  { id: "e6", source: "web-api", target: "pg-prod", kind: "data", label: "PostgreSQL :5432" },
  { id: "e7", source: "web-api", target: "redis-prod", kind: "data", label: "Cache" },
  { id: "e8", source: "worker", target: "stprod", kind: "private", label: "Private endpoint" },
  { id: "e9", source: "aks-ops", target: "kv-prod", kind: "private", label: "Workload identity" },
  { id: "e10", source: "fw-hub", target: "nat-hub", kind: "internal", label: "Egress" },
];

export function createInitialScene() {
  return {
    regions: structuredClone(initialRegions),
    resources: structuredClone(initialResources),
    connections: structuredClone(initialConnections),
  };
}

export function categoryFor(resource) {
  return CATALOG[resource.type]?.category ?? "compute";
}

export function findRegionAt(scene, x, y) {
  return scene.regions
    .filter((region) => x >= region.x && x <= region.x + region.w && y >= region.y && y <= region.y + region.h)
    .sort((a, b) => a.w * a.h - b.w * b.h)[0] ?? null;
}

export function serializeScene(scene) {
  return JSON.stringify({ version: 1, world: WORLD, ...scene }, null, 2);
}