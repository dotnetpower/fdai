import { afterEach, describe, expect, test } from "vitest";

import { setLocale } from "../i18n";
import { KNOWLEDGE_SOURCE_DEFINITIONS } from "./knowledge-sources";
import { knowledgeText } from "./knowledge-sources.i18n";

afterEach(() => setLocale("en"));

describe("Knowledge sources", () => {
  test("keeps the managed document source ahead of repository connectors", () => {
    expect(KNOWLEDGE_SOURCE_DEFINITIONS.map((source) => source.id)).toEqual([
      "documents",
      "github",
      "gitlab",
      "azure-devops",
    ]);
    expect(KNOWLEDGE_SOURCE_DEFINITIONS[0]).toMatchObject({
      panelId: "documents",
      connector: false,
    });
    expect(KNOWLEDGE_SOURCE_DEFINITIONS.slice(1).map((source) => source.panelId)).toEqual([
      "github",
      "gitlab",
      "azure-devops",
    ]);
    expect(KNOWLEDGE_SOURCE_DEFINITIONS.slice(1).every((source) => source.connector)).toBe(true);
  });

  test("assigns one unique panel to every source", () => {
    const panelIds = KNOWLEDGE_SOURCE_DEFINITIONS.map((source) => source.panelId);
    expect(new Set(panelIds).size).toBe(panelIds.length);
  });

  test("renders the route catalog in English and Korean", () => {
    expect(knowledgeText("sourcesTitle")).toBe("Knowledge sources");
    setLocale("ko");
    expect(knowledgeText("sourcesTitle")).toBe("지식 원본");
  });
});
