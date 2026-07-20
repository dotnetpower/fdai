import type { ErrorObject } from "ajv";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

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

export function validateDiagram(value: unknown): DiagramSpec {
  if (!validateSchema(value)) {
    throw new Error(`Diagram schema validation failed: ${formatSchemaErrors(validateSchema.errors)}`);
  }

  const spec = value as DiagramSpec;
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
  for (const element of [...spec.groups, ...spec.nodes]) {
    if (element.parent && !groupIds.has(element.parent)) {
      throw new Error(`Unknown parent group '${element.parent}' on '${element.id}'`);
    }
  }

  const nodeById = new Map(spec.nodes.map((node) => [node.id, node]));
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
