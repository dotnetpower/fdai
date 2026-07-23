import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  EmptyState,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { routeHref } from "../router";
import { displayValue, formatNumber, t } from "./i18n/governance";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

interface SkillReference {
  readonly path: string;
  readonly sha256: string;
  readonly size_bytes: number;
  readonly media_type: string;
}

interface RuntimeSkillItem {
  readonly name: string;
  readonly version: string;
  readonly description: string;
  readonly source: string;
  readonly enabled: boolean;
  readonly required_tools: readonly string[];
  readonly missing_tools: readonly string[];
  readonly allowed_agents: readonly string[];
  readonly agent_eligible: boolean;
  readonly eligible: boolean;
  readonly eligibility_reason: string;
  readonly body_sha256: string;
  readonly references: readonly SkillReference[];
}

interface SkillDiagnostic {
  readonly operation: string;
  readonly name: string | null;
  readonly reference: string | null;
  readonly status: string;
  readonly reason: string;
  readonly digests: Readonly<Record<string, string>>;
}

interface RuntimeSkillBundleMember {
  readonly name: string;
  readonly version: string;
}

interface RuntimeSkillBundleItem {
  readonly name: string;
  readonly version: string;
  readonly description: string;
  readonly source: string;
  readonly digest: string;
  readonly enabled: boolean;
  readonly members: readonly RuntimeSkillBundleMember[];
  readonly required_tools: readonly string[];
  readonly missing_tools: readonly string[];
  readonly allowed_agents: readonly string[];
  readonly agent_eligible: boolean;
  readonly compatible: boolean;
  readonly missing_members: readonly string[];
  readonly disabled_members: readonly string[];
  readonly incompatible_members: readonly string[];
  readonly trust_status: string;
  readonly eligible: boolean;
}

export interface RuntimeSkillsResponse {
  readonly source: string;
  readonly execution_eligibility: boolean;
  readonly trust_rechecked_on_load: boolean;
  readonly agent: string;
  readonly available_tools: readonly string[];
  readonly installed_count: number;
  readonly eligible_count: number;
  readonly skills: readonly RuntimeSkillItem[];
  readonly installed_bundle_count: number;
  readonly eligible_bundle_count: number;
  readonly bundles: readonly RuntimeSkillBundleItem[];
  readonly diagnostics: readonly SkillDiagnostic[];
  readonly mutation_controls: boolean;
}

export function SkillsRoute({ client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<RuntimeSkillsResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    client.panel<unknown>("/skills")
      .then((value) => {
        if (!cancelled) setState({ status: "ready", data: decodeRuntimeSkills(value) });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      });
    return () => { cancelled = true; };
  }, [client]);
  return (
    <div class="stack skills-route">
      <PageHeader title={t("route.skills")} subtitle={t("nav.panelSub.skills")} />
      <AsyncBoundary state={state} resourceLabel={t("governance.skills.resourceLabel")}>
        {(data) => <SkillsBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export function decodeRuntimeSkills(value: unknown): RuntimeSkillsResponse {
  const root = panelRecord(value, "skills");
  const skills = panelArray(root["skills"], "skills.items").map(decodeSkill);
  const diagnostics = panelArray(root["diagnostics"], "skills.diagnostics")
    .map(decodeDiagnostic);
  const bundles = panelArray(root["bundles"], "skills.bundles").map(decodeBundle);
  const installedCount = panelNonNegativeInteger(root, "installed_count", "skills");
  const eligibleCount = panelNonNegativeInteger(root, "eligible_count", "skills");
  const installedBundleCount = panelNonNegativeInteger(root, "installed_bundle_count", "skills");
  const eligibleBundleCount = panelNonNegativeInteger(root, "eligible_bundle_count", "skills");
  if (installedCount !== skills.length) {
    throw new Error(t("governance.skills.error.installedCount"));
  }
  if (eligibleCount !== skills.filter((item) => item.eligible).length) {
    throw new Error(t("governance.skills.error.eligibleCount"));
  }
  const names = skills.map((item) => item.name);
  if (new Set(names).size !== names.length) {
    throw new Error(t("governance.skills.error.uniqueNames"));
  }
  if (installedBundleCount !== bundles.length) {
    throw new Error(t("governance.skills.error.installedBundleCount"));
  }
  if (eligibleBundleCount !== bundles.filter((item) => item.eligible).length) {
    throw new Error(t("governance.skills.error.eligibleBundleCount"));
  }
  const bundleNames = bundles.map((item) => item.name);
  if (new Set(bundleNames).size !== bundleNames.length) {
    throw new Error(t("governance.skills.error.uniqueBundleNames"));
  }
  return {
    source: panelNonEmptyString(root, "source", "skills"),
    execution_eligibility: panelBoolean(root, "execution_eligibility", "skills"),
    trust_rechecked_on_load: panelBoolean(root, "trust_rechecked_on_load", "skills"),
    agent: panelNonEmptyString(root, "agent", "skills"),
    available_tools: panelStringArray(root["available_tools"], "skills.available_tools"),
    installed_count: installedCount,
    eligible_count: eligibleCount,
    skills,
    installed_bundle_count: installedBundleCount,
    eligible_bundle_count: eligibleBundleCount,
    bundles,
    diagnostics,
    mutation_controls: panelBoolean(root, "mutation_controls", "skills"),
  };
}

function decodeBundle(value: unknown, index: number): RuntimeSkillBundleItem {
  const label = `skills.bundles[${index}]`;
  const item = panelRecord(value, label);
  return {
    name: panelNonEmptyString(item, "name", label),
    version: panelNonEmptyString(item, "version", label),
    description: panelNonEmptyString(item, "description", label),
    source: panelNonEmptyString(item, "source", label),
    digest: panelNonEmptyString(item, "digest", label),
    enabled: panelBoolean(item, "enabled", label),
    members: panelArray(item["members"], `${label}.members`).map((raw, memberIndex) => {
      const memberLabel = `${label}.members[${memberIndex}]`;
      const member = panelRecord(raw, memberLabel);
      return {
        name: panelNonEmptyString(member, "name", memberLabel),
        version: panelNonEmptyString(member, "version", memberLabel),
      };
    }),
    required_tools: panelStringArray(item["required_tools"], `${label}.required_tools`),
    missing_tools: panelStringArray(item["missing_tools"], `${label}.missing_tools`),
    allowed_agents: panelStringArray(item["allowed_agents"], `${label}.allowed_agents`),
    agent_eligible: panelBoolean(item, "agent_eligible", label),
    compatible: panelBoolean(item, "compatible", label),
    missing_members: panelStringArray(item["missing_members"], `${label}.missing_members`),
    disabled_members: panelStringArray(item["disabled_members"], `${label}.disabled_members`),
    incompatible_members: panelStringArray(
      item["incompatible_members"],
      `${label}.incompatible_members`,
    ),
    trust_status: panelNonEmptyString(item, "trust_status", label),
    eligible: panelBoolean(item, "eligible", label),
  };
}

function decodeSkill(value: unknown, index: number): RuntimeSkillItem {
  const label = `skills.items[${index}]`;
  const item = panelRecord(value, label);
  return {
    name: panelNonEmptyString(item, "name", label),
    version: panelNonEmptyString(item, "version", label),
    description: panelNonEmptyString(item, "description", label),
    source: panelNonEmptyString(item, "source", label),
    enabled: panelBoolean(item, "enabled", label),
    required_tools: panelStringArray(item["required_tools"], `${label}.required_tools`),
    missing_tools: panelStringArray(item["missing_tools"], `${label}.missing_tools`),
    allowed_agents: panelStringArray(item["allowed_agents"], `${label}.allowed_agents`),
    agent_eligible: panelBoolean(item, "agent_eligible", label),
    eligible: panelBoolean(item, "eligible", label),
    eligibility_reason: panelNonEmptyString(item, "eligibility_reason", label),
    body_sha256: panelNonEmptyString(item, "body_sha256", label),
    references: panelArray(item["references"], `${label}.references`).map((raw, refIndex) => {
      const refLabel = `${label}.references[${refIndex}]`;
      const reference = panelRecord(raw, refLabel);
      return {
        path: panelNonEmptyString(reference, "path", refLabel),
        sha256: panelNonEmptyString(reference, "sha256", refLabel),
        size_bytes: panelNonNegativeInteger(reference, "size_bytes", refLabel),
        media_type: panelNonEmptyString(reference, "media_type", refLabel),
      };
    }),
  };
}

function decodeDiagnostic(value: unknown, index: number): SkillDiagnostic {
  const label = `skills.diagnostics[${index}]`;
  const item = panelRecord(value, label);
  const digests = panelRecord(item["digests"], `${label}.digests`);
  if (!Object.values(digests).every((digest) => typeof digest === "string")) {
    throw new Error(t("governance.skills.error.digestStrings", { label }));
  }
  return {
    operation: panelNonEmptyString(item, "operation", label),
    name: nullableString(item["name"], `${label}.name`),
    reference: nullableString(item["reference"], `${label}.reference`),
    status: panelNonEmptyString(item, "status", label),
    reason: panelNonEmptyString(item, "reason", label),
    digests: digests as Readonly<Record<string, string>>,
  };
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null) return null;
  if (typeof value !== "string") {
    throw new Error(t("governance.skills.error.nullableString", { label }));
  }
  return value;
}

function skillColumns(): readonly Column<RuntimeSkillItem>[] {
  return [
  { key: "name", header: t("governance.skills.column.skill"), render: (item) => <div><strong>{item.name}</strong><small>{item.description}</small></div> },
  { key: "version", header: t("governance.common.version"), render: (item) => <code>{item.version}</code> },
  { key: "source", header: t("governance.skills.column.publisher"), render: (item) => item.source },
  { key: "dependencies", header: t("governance.skills.column.requiredTools"), render: (item) => item.required_tools.join(", ") || t("governance.common.none") },
  { key: "agents", header: t("governance.skills.column.allowedAgents"), render: (item) => item.allowed_agents.join(", ") || t("governance.common.all") },
  { key: "references", header: t("governance.skills.column.references"), render: (item) => item.references.length },
  {
    key: "eligibility",
    header: t("governance.skills.column.loadEligibility"),
    render: (item) => (
      <StatusPill
        kind={item.eligible ? "success" : item.enabled ? "warning" : "shadow"}
        label={item.eligible ? t("governance.common.eligible") : displayValue("eligibility", item.eligibility_reason)}
      />
    ),
  },
];
}

function diagnosticColumns(): readonly Column<SkillDiagnostic>[] {
  return [
  { key: "operation", header: t("governance.skills.column.operation"), render: (item) => item.operation },
  { key: "skill", header: t("governance.skills.column.skillReference"), render: (item) => [item.name, item.reference].filter(Boolean).join(" / ") || "-" },
  { key: "status", header: t("governance.common.status"), render: (item) => <StatusPill kind={item.status === "selected" ? "success" : "warning"} label={displayValue("status", item.status)} /> },
  { key: "reason", header: t("governance.skills.column.reason"), render: (item) => item.reason },
  { key: "digests", header: t("governance.skills.column.verifiedDigests"), render: (item) => Object.keys(item.digests).length },
];
}

function bundleColumns(): readonly Column<RuntimeSkillBundleItem>[] {
  return [
  { key: "name", header: t("governance.skills.column.bundle"), render: (item) => <div><strong>{item.name}</strong><small>{item.description}</small></div> },
  { key: "version", header: t("governance.common.version"), render: (item) => <code>{item.version}</code> },
  { key: "members", header: t("governance.skills.column.orderedMembers"), render: (item) => item.members.map((member) => `${member.name} ${member.version}`).join(", ") },
  { key: "tools", header: t("governance.skills.column.requiredTools"), render: (item) => item.required_tools.join(", ") || t("governance.common.none") },
  { key: "trust", header: t("governance.skills.column.trust"), render: (item) => displayValue("trust", item.trust_status) },
  {
    key: "compatibility",
    header: t("governance.skills.column.compatibility"),
    render: (item) => <StatusPill kind={item.compatible ? "success" : "warning"} label={displayValue("compatibility", item.compatible ? "compatible" : "blocked")} />,
  },
  {
    key: "eligibility",
    header: t("governance.skills.column.loadEligibility"),
    render: (item) => <StatusPill kind={item.eligible ? "success" : item.enabled ? "warning" : "shadow"} label={item.eligible ? t("governance.common.eligible") : displayValue("status", item.enabled ? "blocked" : "disabled")} />,
  },
];
}

function SkillsBody({ data }: { readonly data: RuntimeSkillsResponse }) {
  usePublishViewContext(
    () => ({
      routeId: "skills",
      routeLabel: t("governance.skills.context.routeLabel"),
      purpose: t("governance.skills.context.purpose"),
      glossary: composeGlossary([], [{
        term: t("governance.skills.context.runtimeSkillTerm"),
        plain: t("governance.skills.context.runtimeSkillPlain"),
        tech: "RuntimeSkill",
      }]),
      headline: t("governance.skills.context.headline", {
        skills: data.installed_count,
        bundles: data.installed_bundle_count,
        agent: data.agent,
      }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "source", value: data.source, group: "provenance" },
        { key: "installed_count", value: data.installed_count, group: "skills" },
        { key: "eligible_count", value: data.eligible_count, group: "skills" },
        { key: "installed_bundle_count", value: data.installed_bundle_count, group: "bundles" },
        { key: "eligible_bundle_count", value: data.eligible_bundle_count, group: "bundles" },
        { key: "execution_eligibility", value: data.execution_eligibility, group: "safety" },
        { key: "mutation_controls", value: data.mutation_controls, group: "safety" },
      ],
      records: {
        skills: data.skills.map((item) => ({ ...item })),
        bundles: data.bundles.map((item) => ({ ...item })),
        diagnostics: data.diagnostics.map((item) => ({ ...item })),
      },
    }),
    [data],
  );
  const skillsHref = `${routeHref("skills")}#runtime-skills`;
  const bundlesHref = `${routeHref("skills")}#runtime-skill-bundles`;
  const diagnosticsHref = `${routeHref("skills")}#runtime-skill-diagnostics`;
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("governance.skills.banner.title")}</strong>
        <span>{t("governance.skills.banner.body")}</span>
      </div>
      <KpiGrid>
        <KpiCard href={skillsHref} label={t("governance.skills.kpi.installed")} value={formatNumber(data.installed_count)} />
        <KpiCard href={skillsHref} label={t("governance.skills.kpi.eligible")} value={formatNumber(data.eligible_count)} />
        <KpiCard href={bundlesHref} label={t("governance.skills.kpi.bundles")} value={formatNumber(data.installed_bundle_count)} />
        <KpiCard href={bundlesHref} label={t("governance.skills.kpi.eligibleBundles")} value={formatNumber(data.eligible_bundle_count)} />
        <KpiCard href={diagnosticsHref} label={t("governance.skills.kpi.diagnostics")} value={formatNumber(data.diagnostics.length)} />
      </KpiGrid>
      <section id="runtime-skills" class="stack-section" aria-label={t("governance.skills.section.installedAria")}>
        <header class="section-header"><div><h3>{t("governance.skills.section.installedTitle")}</h3><p>{t("governance.skills.section.installedDescription", { agent: data.agent })}</p></div></header>
        <DataTable rows={data.skills} columns={skillColumns()} keyOf={(item) => item.name} empty={<EmptyState title={t("governance.skills.empty.skills")} />} />
      </section>
      <section id="runtime-skill-bundles" class="stack-section" aria-label={t("governance.skills.section.bundlesAria")}>
        <header class="section-header"><div><h3>{t("governance.skills.section.bundlesTitle")}</h3><p>{t("governance.skills.section.bundlesDescription")}</p></div></header>
        <DataTable rows={data.bundles} columns={bundleColumns()} keyOf={(item) => item.name} empty={<EmptyState title={t("governance.skills.empty.bundles")} />} />
      </section>
      <section id="runtime-skill-diagnostics" class="stack-section" aria-label={t("governance.skills.section.diagnosticsAria")}>
        <header class="section-header"><div><h3>{t("governance.skills.section.diagnosticsTitle")}</h3><p>{t("governance.skills.section.diagnosticsDescription")}</p></div></header>
        <DataTable rows={data.diagnostics} columns={diagnosticColumns()} keyOf={(item, index) => `${index}:${item.operation}:${item.name ?? "none"}`} empty={<EmptyState title={t("governance.skills.empty.diagnostics")} />} />
      </section>
    </div>
  );
}
