/** Presentation-only graph and scenario types. None of these records grants execution authority. */
export type Locale = "en" | "ko";
export type Copy = Readonly<Record<Locale, string>>;
export type AgentId = "Odin" | "Thor" | "Forseti" | "Huginn" | "Heimdall" | "Vidar"
  | "Var" | "Bragi" | "Saga" | "Mimir" | "Muninn" | "Norns" | "Njord" | "Freyr" | "Loki";
export type Family = "observe" | "reason" | "act" | "remember";
export type CameraMode = "orbit" | "follow" | "tour" | "manual";

export interface Agent {
  readonly id: AgentId;
  readonly family: Family;
  readonly role: Copy;
  readonly capabilities: readonly Copy[];
  readonly position: readonly [number, number, number];
}

export interface Activity {
  readonly at: number;
  readonly duration: number;
  readonly agent: AgentId;
  readonly from?: AgentId;
  readonly title: Copy;
  readonly detail: Copy;
  readonly stage: "observe" | "reason" | "review" | "verify" | "remember";
}

export interface Scenario {
  readonly id: string;
  readonly source: "synthetic-demo";
  readonly title: Copy;
  readonly description: Copy;
  readonly duration: number;
  readonly events: readonly Activity[];
}

export const copy = (en: string, ko: string): Copy => ({ en, ko });
export const localized = (value: Copy, locale: Locale): string => value[locale] || value.en;

export const FAMILY_COLORS: Readonly<Record<Family, string>> = {
  observe: "#6ee7df",
  reason: "#b2a2ff",
  act: "#ffc78f",
  remember: "#89bfe9",
};
