import type { Page, Route } from "@playwright/test";

const catalog = {
  items: [
    {
      id: "weekly-operations",
      version: "1.0.0",
      name: "Weekly Operations Review",
      description: "Bounded operational evidence for the selected scope and window.",
      tags: ["operations"],
      widget_count: 4,
      datasources: ["audit", "metric"],
      variables: [
        {
          name: "window",
          default: "7d",
          values: ["7d", "30d"],
          description: "Bounded evidence window.",
        },
        {
          name: "scope",
          default: "platform-production",
          values: [],
          description: "Authorized logical scope.",
        },
      ],
    },
    {
      id: "incident-rca-dossier",
      version: "1.0.0",
      name: "Incident RCA Dossier",
      description: "Correlation-scoped incident and root-cause evidence package.",
      tags: ["incident", "rca"],
      widget_count: 2,
      datasources: ["audit"],
      variables: [
        {
          name: "correlation_id",
          default: null,
          values: [],
          description: "Correlation id that scopes every widget in this report.",
        },
      ],
    },
    {
      id: "shadow-mode-daily",
      version: "1.0.0",
      name: "Shadow-Mode Daily Rollup",
      description: "Yesterday's bounded shadow-mode activity.",
      tags: ["shadow-mode"],
      widget_count: 1,
      datasources: ["audit"],
      variables: [],
    },
  ],
  formats: ["json", "pdf"],
};

const registry = {
  datasources: ["audit", "metric", "report_feed"],
  datasource_provenance: [
    {
      datasource: "audit",
      source: "audit_log",
      availability: "available",
      synthetic: true,
      as_of: "2026-09-16T08:45:00Z",
    },
    {
      datasource: "metric",
      source: "metric_projection",
      availability: "unavailable",
      synthetic: null,
      as_of: null,
    },
    {
      datasource: "report_feed",
      source: "report_feed",
      availability: "available",
      synthetic: true,
      as_of: "2026-09-16T08:40:00Z",
    },
  ],
  widgets: ["query_value", "bar_chart", "table"],
  formats: ["json", "pdf"],
};

interface RenderRequest {
  readonly reportId: string;
  readonly variables: Readonly<Record<string, string>>;
}

export async function installReportsFixture(page: Page): Promise<readonly RenderRequest[]> {
  const renders: RenderRequest[] = [];
  const handle = async (route: Route) => {
    const request = route.request();
    if (request.resourceType() !== "fetch" && request.resourceType() !== "xhr") {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/system/data-sources") {
      await json(route, {
        surface: "read-data-sources",
        sources: [{
          key: "reports-browser-fixture",
          source: "deterministic browser fixture",
          routes: ["/reports", "/reports/registry"],
          availability: "available",
          configured: true,
          reachable: true,
          authoritative: true,
          durable: false,
          synthetic: true,
          reason: null,
          last_observed_at: "2026-09-16T08:45:00Z",
        }],
      });
      return;
    }
    if (path === "/reports") {
      await json(route, catalog);
      return;
    }
    if (path === "/reports/registry") {
      await json(route, registry);
      return;
    }
    const renderMatch = path.match(/^\/reports\/([^/]+)\/render$/);
    if (renderMatch) {
      const reportId = decodeURIComponent(renderMatch[1]!);
      const variables = Object.fromEntries(
        [...url.searchParams.entries()].filter(([name]) => name !== "format"),
      );
      renders.push({ reportId, variables });
      await json(route, renderedReport(reportId, variables));
      return;
    }
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ error: { status: 404, message: "fixture route not found" } }),
    });
  };
  await page.route("**/api/**", handle);
  await page.route("**/system/data-sources*", handle);
  await page.route("**/reports", handle);
  await page.route("**/reports/registry", handle);
  await page.route("**/reports/*/render*", handle);
  return renders;
}

function renderedReport(
  reportId: string,
  variables: Readonly<Record<string, string>>,
): Record<string, unknown> {
  const common = {
    id: reportId,
    version: "1.0.0",
    generated_at: "2026-09-16T08:45:00Z",
    time_range: {
      from: "2026-09-09T08:45:00Z",
      to: "2026-09-16T08:45:00Z",
    },
    variables,
    tags: [],
    provenance: {
      availability: reportId === "weekly-operations" ? "partial" : "available",
      synthetic: true,
      sources: reportId === "weekly-operations"
        ? registry.datasource_provenance.slice(0, 2)
        : registry.datasource_provenance.slice(0, 1),
    },
  };
  if (reportId === "weekly-operations") {
    return {
      ...common,
      name: "Weekly Operations Review",
      description: "Bounded operational evidence for the selected scope and window.",
      widgets: [
        queryValue("auto-resolution", "Auto-resolution", "73%"),
        queryValue("pending-approvals", "Pending approvals", 8),
        queryValue("evidence-freshness", "Evidence freshness", "2 / 3"),
        {
          id: "control-posture",
          type: "table",
          title: "Control posture",
          data: {
            columns: ["control", "measured", "threshold", "state"],
            rows: [{
              control: "Effect verification",
              measured: "99.6%",
              threshold: "99%",
              state: "Pass",
            }],
            total_rows: 1,
          },
          options: {},
        },
      ],
    };
  }
  if (reportId === "incident-rca-dossier") {
    return {
      ...common,
      name: "Incident RCA Dossier",
      description: "Correlation-scoped incident and root-cause evidence package.",
      widgets: variables["correlation_id"] === "empty-evidence"
        ? []
        : [
            queryValue("evidence-record-count", "Correlated audit records", 12),
            {
              id: "incident-profile",
              type: "table",
              title: "Incident profile and document scope",
              data: {
                columns: ["incident_id", "title", "status"],
                rows: [{
                  incident_id: "incident-example",
                  title: "Example incident",
                  status: "resolved",
                }],
                total_rows: 1,
              },
              options: {},
            },
          ],
    };
  }
  return {
    ...common,
    name: "Shadow-Mode Daily Rollup",
    description: "Yesterday's bounded shadow-mode activity.",
    widgets: [queryValue("total-shadow", "Shadow-mode entries", 34)],
  };
}

function queryValue(id: string, title: string, value: string | number) {
  return {
    id,
    type: "query_value",
    title,
    data: { value },
    options: {},
  };
}

async function json(route: Route, body: object): Promise<void> {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}
