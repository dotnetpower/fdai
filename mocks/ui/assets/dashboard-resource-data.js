// Synthetic, in-memory query adapter. Never import this fixture into the production Console.
(function () {
  "use strict";
  const snapshotTime = "2026-09-05T12:00:00+09:00";
  const baseGroups = { application: "Application", platform: "Platform", data: "Data" };
  const typeNames = { vm: "Virtual machine", web: "Web app", app: "Container app", database: "PostgreSQL", storage: "Storage", network: "Virtual network" };
  const typeCatalog = [
    ["vm", "Virtual machine", "Microsoft.Compute/virtualMachines", ["VM", "가상 머신", "가상머신"]],
    ["web", "Web app", "Microsoft.Web/sites", ["App Service", "웹앱"]],
    ["app", "Container app", "Microsoft.App/containerApps", ["ACA", "컨테이너 앱"]],
    ["database", "PostgreSQL", "Microsoft.DBforPostgreSQL/flexibleServers", ["postgres", "pg", "포스트그레스"]],
    ["storage", "Storage", "Microsoft.Storage/storageAccounts", ["storage account", "스토리지"]],
    ["network", "Virtual network", "Microsoft.Network/virtualNetworks", ["VNet", "가상 네트워크"]],
    ["vm-scale-set", "Virtual machine scale set", "Microsoft.Compute/virtualMachineScaleSets", ["VMSS"]],
    ["disk", "Managed disk", "Microsoft.Compute/disks", ["disk"]],
    ["disk-snapshot", "Disk snapshot", "Microsoft.Compute/snapshots", ["snapshot"]],
    ["image", "Compute image", "Microsoft.Compute/images", ["image"]],
    ["availability-set", "Availability set", "Microsoft.Compute/availabilitySets", []],
    ["nic", "Network interface", "Microsoft.Network/networkInterfaces", ["NIC"]],
    ["nsg", "Network security group", "Microsoft.Network/networkSecurityGroups", ["NSG"]],
    ["public-ip", "Public IP address", "Microsoft.Network/publicIPAddresses", ["PIP"]],
    ["load-balancer", "Load balancer", "Microsoft.Network/loadBalancers", ["LB"]],
    ["application-gateway", "Application Gateway", "Microsoft.Network/applicationGateways", ["AppGW"]],
    ["firewall", "Azure Firewall", "Microsoft.Network/azureFirewalls", []],
    ["private-endpoint", "Private endpoint", "Microsoft.Network/privateEndpoints", ["PE"]],
    ["private-dns", "Private DNS zone", "Microsoft.Network/privateDnsZones", []],
    ["route-table", "Route table", "Microsoft.Network/routeTables", ["UDR"]],
    ["key-vault", "Key Vault", "Microsoft.KeyVault/vaults", ["KV"]],
    ["sql-server", "SQL server", "Microsoft.Sql/servers", ["Azure SQL"]],
    ["sql-database", "SQL database", "Microsoft.Sql/servers/databases", ["Azure SQL DB"]],
    ["mysql", "MySQL server", "Microsoft.DBforMySQL/flexibleServers", ["mysql"]],
    ["cosmos", "Cosmos DB account", "Microsoft.DocumentDB/databaseAccounts", ["cosmos"]],
    ["aks", "AKS cluster", "Microsoft.ContainerService/managedClusters", ["Kubernetes", "AKS"]],
    ["container-group", "Container instance group", "Microsoft.ContainerInstance/containerGroups", ["ACI"]],
    ["container-registry", "Container registry", "Microsoft.ContainerRegistry/registries", ["ACR"]],
    ["app-plan", "App Service plan", "Microsoft.Web/serverfarms", ["ASP"]],
    ["workspace", "Log Analytics workspace", "Microsoft.OperationalInsights/workspaces", ["LAW"]],
    ["app-insights", "Application Insights", "Microsoft.Insights/components", ["App Insights"]],
    ["action-group", "Monitor action group", "Microsoft.Insights/actionGroups", []],
    ["event-hubs", "Event Hubs namespace", "Microsoft.EventHub/namespaces", ["EH"]],
    ["service-bus", "Service Bus namespace", "Microsoft.ServiceBus/namespaces", ["SB"]],
    ["recovery-vault", "Recovery Services vault", "Microsoft.RecoveryServices/vaults", ["backup vault"]],
  ].map(([key, label, nativeType, aliases]) => Object.freeze({ key, label, nativeType, aliases }));
  const definitions = {
    operation: {
      running: ["Running", "active", ">"], stopped: ["Stopped", "neutral", "II"],
      deallocated: ["Deallocated", "neutral", "D"], starting: ["Transitioning", "attention", "~"],
      unknown: ["Unknown", "unknown", "?"], na: ["Not applicable", "na", "-"],
    },
    availability: {
      available: ["Available", "positive", "+"], degraded: ["Degraded", "attention", "!"],
      unavailable: ["Unavailable", "negative", "X"], unknown: ["Unknown", "unknown", "?"],
      unsupported: ["Not supported", "na", "-"],
    },
    observation: {
      ready: ["Fresh", "positive", "+"], stale: ["Stale", "attention", "~"],
      denied: ["Read denied", "unknown", "?"], unsupported: ["Not supported", "na", "-"],
    },
  };
  const rows = [
    ["app-web-01", "web-checkout-01", "WEB1", "application", "web", "running", "unavailable", "ready", "11:58"],
    ["app-web-02", "web-api-02", "WEB2", "application", "web", "running", "available", "ready", "11:59"],
    ["app-ca-01", "ca-worker-01", "APP1", "application", "app", "running", "degraded", "ready", "11:58"],
    ["app-ca-02", "ca-preview-02", "APP2", "application", "app", "stopped", "unknown", "ready", "11:56"],
    ["app-vm-01", "vm-app-01", "VM1", "application", "vm", "running", "available", "ready", "11:59"],
    ["app-vm-02", "vm-app-02", "VM2", "application", "vm", "starting", "unknown", "ready", "11:59"],
    ["app-store-01", "store-assets-01", "ST1", "application", "storage", "na", "available", "ready", "11:58"],
    ["app-net-01", "vnet-app-01", "NET1", "application", "network", "na", "unsupported", "unsupported", null],
    ["platform-vm-01", "vm-build-01", "VM1", "platform", "vm", "deallocated", "unknown", "ready", "11:55"],
    ["platform-vm-02", "vm-build-02", "VM2", "platform", "vm", "unknown", "unknown", "denied", null],
    ["platform-vm-03", "vm-edge-01", "VM3", "platform", "vm", "running", "available", "ready", "11:59"],
    ["platform-vm-04", "vm-edge-02", "VM4", "platform", "vm", "stopped", "unavailable", "ready", "11:57"],
    ["platform-ca-01", "ca-core-01", "APP1", "platform", "app", "running", "available", "ready", "11:59"],
    ["platform-ca-02", "ca-tools-02", "APP2", "platform", "app", "running", "available", "stale", "10:20"],
    ["platform-store-01", "store-logs-01", "ST1", "platform", "storage", "na", "available", "ready", "11:58"],
    ["platform-net-01", "vnet-shared-01", "NET1", "platform", "network", "na", "unsupported", "unsupported", null],
    ["data-db-01", "db-orders-01", "DB1", "data", "database", "running", "degraded", "ready", "11:57"],
    ["data-db-02", "db-orders-02", "DB2", "data", "database", "running", "available", "ready", "11:59"],
    ["data-db-03", "db-report-01", "DB3", "data", "database", "stopped", "unknown", "ready", "11:56"],
    ["data-vm-01", "vm-etl-01", "VM1", "data", "vm", "running", "available", "ready", "11:59"],
    ["data-vm-02", "vm-etl-02", "VM2", "data", "vm", "running", "available", "stale", "10:15"],
    ["data-store-01", "store-backup-01", "ST1", "data", "storage", "na", "available", "ready", "11:58"],
    ["data-store-02", "store-archive-02", "ST2", "data", "storage", "na", "unknown", "denied", null],
    ["data-net-01", "vnet-data-01", "NET1", "data", "network", "na", "unsupported", "unsupported", null],
  ];
  function statusKey(resource, lens, snapshot) {
    if (lens === "operation" && resource.operation === "na") return "na";
    if (snapshot.mode === "stale" && resource.observation !== "unsupported") {
      return lens === "observation" ? (resource.observation === "denied" ? "denied" : "stale") : "unknown";
    }
    if (lens === "observation") return resource.observation;
    if (resource.observation === "stale" || resource.observation === "denied") return "unknown";
    return resource[lens];
  }
  function counts(resources, lens, snapshot) {
    const result = Object.fromEntries(Object.keys(definitions[lens]).map((key) => [key, 0]));
    resources.forEach((resource) => { result[statusKey(resource, lens, snapshot)] += 1; });
    return result;
  }
  /** Creates a frozen example generation. Partial inventory never exposes an inferred full count. */
  function createSnapshot(size, mode) {
    if (![24, 100, 1000, 10000].includes(size)) throw new Error("Unsupported preview size");
    if (!["complete", "partial", "stale", "loading", "error", "empty"].includes(mode)) throw new Error("Unsupported preview state");
    const length = ["empty", "loading", "error"].includes(mode) ? 0 : mode === "partial" ? Math.floor(size * 0.75) : size;
    const resources = Array.from({ length }, (_, index) => {
      const [id, name, short, baseGroup, type, operation, availability, observation, time] = rows[index % rows.length];
      const block = Math.floor(index / 100);
      const suffix = String(index + 1).padStart(5, "0");
      return Object.freeze({
        id: index < 24 ? id : `resource-${suffix}`,
        name: index < 24 ? name : `${name}-${suffix}`,
        short: index < 24 ? short : suffix,
        group: block === 0 ? baseGroup : `${baseGroup}-${block + 1}`,
        groupName: block === 0 ? baseGroups[baseGroup] : `${baseGroups[baseGroup]} ${block + 1}`,
        subscription: `subscription-${Math.floor(index / 1000) + 1}`,
        subscriptionName: size === 24 ? "Example subscription" : `Example subscription ${Math.floor(index / 1000) + 1}`,
        type, operation, availability, observation, time,
      });
    });
    const snapshot = {
      id: `demo-${size}-${mode}-20260905-1200`, time: snapshotTime, mode,
      complete: mode !== "partial", resources: Object.freeze(resources),
      byId: new Map(resources.map((resource) => [resource.id, resource])),
      subscriptions: new Map(resources.map((resource) => [resource.subscription, resource.subscriptionName])),
      groups: new Map(resources.map((resource) => [resource.group, resource.groupName])),
    };
    snapshot.operationCounts = counts(resources, "operation", snapshot);
    snapshot.availabilityCounts = counts(resources, "availability", snapshot);
    return Object.freeze(snapshot);
  }
  function matchesScope(resource, state, includeType = true) {
    return (state.subscription === "all" || resource.subscription === state.subscription)
      && (state.group === "all" || resource.group === state.group)
      && (!includeType || state.type === "all" || resource.type === state.type)
      && `${resource.name} ${resource.id}`.toLowerCase().includes(state.query);
  }
  function typeCounts(snapshot, state) {
    const result = new Map();
    snapshot.resources.filter((resource) => matchesScope(resource, state, false)).forEach((resource) => {
      result.set(resource.type, (result.get(resource.type) || 0) + 1);
    });
    return result;
  }
  /** Returns one bounded presentation page plus same-generation totals over all matching records. */
  function query(snapshot, state) {
    const eligible = snapshot.resources.filter((resource) => matchesScope(resource, state));
    const matches = eligible.filter((resource) => !state.status || statusKey(resource, state.lens, snapshot) === state.status);
    const grouping = state.subscription === "all" && state.group === "all" && snapshot.subscriptions.size > 1 ? "subscription" : "group";
    const grouped = new Map();
    if (state.view === "groups") matches.forEach((resource) => {
      const key = resource[grouping];
      if (!grouped.has(key)) grouped.set(key, { key, name: resource[grouping + "Name"], members: [] });
      grouped.get(key).members.push(resource);
    });
    const groupRows = [...grouped.values()].map(({ key, name, members }) => ({
      key, name, count: members.length, counts: counts(members, state.lens, snapshot),
    }));
    const total = state.view === "groups" ? groupRows.length : matches.length;
    const limit = state.view === "groups" ? 6
      : state.view === "honeycomb" && state.effectiveDensity === "dense" ? state.columns * 14 : 48;
    const page = Math.min(state.page, Math.max(0, Math.ceil(total / limit) - 1));
    const start = page * limit;
    const records = state.view === "groups" ? [] : matches.slice(start, start + limit);
    return {
      records, groups: groupRows.slice(start, start + limit), grouping, total, limit, page, start,
      eligibleCount: eligible.length, matchCount: matches.length, counts: counts(eligible, state.lens, snapshot),
      selectedMatches: matches.some((resource) => resource.id === state.selected),
      selectedOnPage: records.some((resource) => resource.id === state.selected),
    };
  }
  window.FdaiDashboardData = Object.freeze({ createSnapshot, query, statusKey, counts, definitions, typeNames, typeCatalog, typeCounts });
})();
