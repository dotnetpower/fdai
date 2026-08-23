import type { ErrorObject } from "ajv";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";
import {
  NETWORK_BOUNDARY_ROLES,
  NETWORK_CONNECTION_KINDS,
  NETWORK_LAYOUT_PRESETS,
  networkVocabularyHas,
} from "@fdai/network-topology-contracts";

import { diagramDefinition } from "./definitions.js";
import { azureDiagramIconForResourceType } from "./azure-resource-icons.js";
import type { DiagramSpec } from "./types.js";

const schemaPath = fileURLToPath(
  new URL("../../schema/diagram.schema.json", import.meta.url),
);
const schema = JSON.parse(await readFile(schemaPath, "utf8")) as object;
const require = createRequire(import.meta.url);
const AjvConstructor = require("ajv") as typeof import("ajv").default;
const addFormats = require("ajv-formats") as typeof import("ajv-formats").default;
const ajv = new AjvConstructor({ allErrors: true, strict: true });
addFormats(ajv);
const validateSchema = ajv.compile<DiagramSpec>(schema);

function formatSchemaErrors(errors: ErrorObject[] | null | undefined): string {
  return (errors ?? [])
    .map((error) => `${error.instancePath || "/"} ${error.message ?? "is invalid"}`)
    .join("; ");
}

function endpointParts(endpoint: string): [string, string | undefined] {
  const [elementId, portId] = endpoint.split(":", 2);
  return [elementId ?? endpoint, portId];
}

function findDuplicate(values: string[]): string | undefined {
  const seen = new Set<string>();
  return values.find((value) => {
    if (seen.has(value)) return true;
    seen.add(value);
    return false;
  });
}

function validateGantt(spec: DiagramSpec): void {
  const nodeIds = new Set(spec.nodes.map((node) => node.id));
  const temporalTypes = new Set<string>();
  for (const node of spec.nodes) {
    if (node.start === undefined && !node.after) {
      throw new Error(`Gantt task '${node.id}' requires 'start' or 'after'`);
    }
    if (node.end === undefined && node.duration === undefined) {
      throw new Error(`Gantt task '${node.id}' requires 'end' or 'duration'`);
    }
    if (node.after && (!nodeIds.has(node.after) || node.after === node.id)) {
      throw new Error(`Gantt task '${node.id}' has invalid dependency '${node.after}'`);
    }
    for (const value of [node.start, node.end]) {
      if (value !== undefined) temporalTypes.add(typeof value);
    }
  }
  if (temporalTypes.size > 1) {
    throw new Error("Gantt tasks cannot mix numeric and date axes");
  }
}

function validateSpecializedDiagram(spec: DiagramSpec): void {
  if (spec.kind === "pie") {
    if (spec.nodes.length < 2 || spec.nodes.some((node) => !node.value)) {
      throw new Error("Pie diagrams require at least two positive node values");
    }
  }
  if (spec.kind === "radar") {
    if (spec.nodes.length < 3 || spec.nodes.some((node) => node.value === undefined)) {
      throw new Error("Radar diagrams require at least three node values");
    }
  }
  if (["quadrant", "xy-chart", "venn", "wardley"].includes(spec.kind)) {
    if (spec.nodes.some((node) => node.xValue === undefined || node.yValue === undefined)) {
      throw new Error(`Diagram kind '${spec.kind}' requires xValue and yValue on every node`);
    }
  }
  if (spec.kind === "sankey" && spec.edges.some((edge) => edge.weight === undefined)) {
    throw new Error("Sankey diagrams require weight on every edge");
  }
}

function validateNetworkDiagram(spec: DiagramSpec): void {
  const usesNetworkSemantics = spec.kind === "network"
    || spec.canvas.profile === "network-azure-reference"
    || spec.canvas.networkPreset !== undefined
    || spec.groups.some((group) => group.networkRole !== undefined)
    || spec.nodes.some((node) => node.networkRole !== undefined)
    || spec.edges.some((edge) => edge.connectionKind !== undefined);
  if (!usesNetworkSemantics) return;
  if (spec.posture !== "expected") {
    throw new Error("Authored network diagrams require posture 'expected'");
  }
  if (spec.canvas.networkPreset && spec.kind !== "network") {
    throw new Error("Network layout presets require diagram kind 'network'");
  }
  for (const group of spec.groups) {
    if (group.networkRole && !networkVocabularyHas(NETWORK_BOUNDARY_ROLES, group.networkRole)) {
      throw new Error(`Unknown network boundary role '${group.networkRole}' on '${group.id}'`);
    }
  }
  for (const edge of spec.edges) {
    if (edge.connectionKind && !networkVocabularyHas(NETWORK_CONNECTION_KINDS, edge.connectionKind)) {
      throw new Error(`Unknown network connection kind '${edge.connectionKind}' on '${edge.id}'`);
    }
    if (edge.sourceEvidence && edge.sourceEvidence !== "expected") {
      throw new Error(`Authored edge '${edge.id}' requires expected evidence posture`);
    }
  }
  if (
    spec.canvas.networkPreset
    && !networkVocabularyHas(NETWORK_LAYOUT_PRESETS, spec.canvas.networkPreset)
  ) {
    throw new Error(`Unknown network layout preset '${spec.canvas.networkPreset}'`);
  }
}

export function validateDiagram(value: unknown): DiagramSpec {
  if (!validateSchema(value)) {
    throw new Error(`Diagram schema validation failed: ${formatSchemaErrors(validateSchema.errors)}`);
  }

  const spec = value as DiagramSpec;
  if (spec.kind === "gantt") validateGantt(spec);
  validateSpecializedDiagram(spec);
  validateNetworkDiagram(spec);
  const definition = diagramDefinition(spec.kind);
  if (
    definition.requiredEdgeKind &&
    !spec.edges.some((edge) => edge.kind === definition.requiredEdgeKind)
  ) {
    throw new Error(
      `Diagram kind '${spec.kind}' requires an edge of kind '${definition.requiredEdgeKind}'`,
    );
  }
  if (
    definition.requiredGroupPresentation &&
    !spec.groups.some(
      (group) => group.presentation === definition.requiredGroupPresentation,
    )
  ) {
    throw new Error(
      `Diagram kind '${spec.kind}' requires a '${definition.requiredGroupPresentation}' group`,
    );
  }
  const elementIds = [...spec.groups.map((group) => group.id), ...spec.nodes.map((node) => node.id)];
  const duplicateElement = findDuplicate(elementIds);
  if (duplicateElement) {
    throw new Error(`Duplicate diagram element id: ${duplicateElement}`);
  }

  const duplicateEdge = findDuplicate(spec.edges.map((edge) => edge.id));
  if (duplicateEdge) {
    throw new Error(`Duplicate diagram edge id: ${duplicateEdge}`);
  }

  const groupIds = new Set(spec.groups.map((group) => group.id));
  const edgeIds = new Set(spec.edges.map((edge) => edge.id));
  for (const element of [...spec.groups, ...spec.nodes]) {
    if (element.parent && !groupIds.has(element.parent)) {
      throw new Error(`Unknown parent group '${element.parent}' on '${element.id}'`);
    }
  }
  for (const group of spec.groups) {
    if (group.alignWith && !groupIds.has(group.alignWith)) {
      throw new Error(`Unknown alignment group '${group.alignWith}' on '${group.id}'`);
    }
  }
  for (const annotation of spec.annotations ?? []) {
    if (annotation.anchor && !elementIds.includes(annotation.anchor) && !edgeIds.has(annotation.anchor)) {
      throw new Error(`Unknown annotation anchor '${annotation.anchor}' on '${annotation.id}'`);
    }
  }

  const nodeById = new Map(spec.nodes.map((node) => [node.id, node]));
  for (const node of spec.nodes) {
    if (
      node.presentation === "icon"
      && !node.icon
      && !azureDiagramIconForResourceType(node.resourceType)
      && node.kind !== "agent"
    ) {
      throw new Error(`Icon presentation requires an icon on '${node.id}'`);
    }
  }
  const validEndpointIds = new Set(elementIds);
  for (const edge of spec.edges) {
    for (const endpoint of [edge.from, edge.to]) {
      const [elementId, portId] = endpointParts(endpoint);
      if (!validEndpointIds.has(elementId)) {
        throw new Error(`Unknown edge endpoint '${endpoint}' on '${edge.id}'`);
      }
      if (portId) {
        const node = nodeById.get(elementId);
        if (!node?.ports?.some((port) => port.id === portId)) {
          throw new Error(`Unknown edge port '${endpoint}' on '${edge.id}'`);
        }
      }
    }
  }

  return spec;
}

export function parseDiagram(source: string): DiagramSpec {
  return validateDiagram(parse(source));
}
