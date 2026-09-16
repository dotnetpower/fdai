import { getLocale } from "../i18n";
import type { RcaCauseDomain, RcaTier } from "../types";
import en from "./i18n/rca.en.json";
import ko from "./i18n/rca.ko.json";

export type RcaTextKey = keyof typeof en;

export function rcaText(
  key: RcaTextKey,
  params: Readonly<Record<string, string | number>> = {},
): string {
  const template = (getLocale() === "ko" ? ko[key] : en[key]) || en[key];
  return template.replace(
    /\{(\w+)\}/g,
    (whole, name: string) => name in params ? String(params[name]) : whole,
  );
}

const CAUSE_DOMAIN_KEYS: Readonly<Record<RcaCauseDomain, RcaTextKey>> = {
  infrastructure: "causeDomainInfrastructure",
  application: "causeDomainApplication",
  shared_dependency: "causeDomainSharedDependency",
  external_provider: "causeDomainExternalProvider",
  mixed: "causeDomainMixed",
  unknown: "causeDomainUnknown",
};

const TIER_KEYS: Readonly<Record<RcaTier, RcaTextKey>> = {
  t0: "tierNameT0",
  t1: "tierNameT1",
  t2: "tierNameT2",
  unknown: "tierNameUnknown",
};

export function rcaCauseDomainText(domain: RcaCauseDomain): string {
  return rcaText(CAUSE_DOMAIN_KEYS[domain]);
}

export function rcaTierText(tier: RcaTier): string {
  return rcaText(TIER_KEYS[tier]);
}
