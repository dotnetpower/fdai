"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

const FRONTEND = "typescript-compiler";
const MODEL_VERSION = "1.1.0";
const ENTRYPOINTS = new Set(["get", "post", "put", "patch", "delete", "use"]);

function stableId(prefix, ...parts) {
  const raw = parts.map(String).join("\0");
  return `${prefix}:${crypto.createHash("sha256").update(raw).digest("hex").slice(0, 24)}`;
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
}

function digest(value) {
  const raw = JSON.stringify(canonical(value));
  return `sha256:${crypto.createHash("sha256").update(raw).digest("hex")}`;
}

function readRequest() {
  const input = fs.readFileSync(0);
  if (input.length > 2_000_000) throw new Error("request exceeds 2000000 bytes");
  const request = JSON.parse(input.toString("utf8"));
  if (!request || typeof request !== "object" || Array.isArray(request)) {
    throw new Error("request must be an object");
  }
  return request;
}

function relativeFile(root, fileName) {
  const relative = path.relative(root, fileName).split(path.sep).join("/");
  if (!relative || relative.startsWith("../") || path.isAbsolute(relative)) return null;
  return relative;
}

function location(root, sourceFile, node) {
  const relative = relativeFile(root, sourceFile.fileName);
  if (!relative) throw new Error("node is outside the analysis root");
  const start = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
  const end = sourceFile.getLineAndCharacterOfPosition(node.getEnd());
  return {
    path: relative,
    start_line: start.line + 1,
    start_column: start.character + 1,
    end_line: end.line + 1,
    end_column: end.character + 1,
  };
}

function terminal(expression) {
  if (ts.isIdentifier(expression)) return expression.text;
  if (ts.isPropertyAccessExpression(expression)) return expression.name.text;
  return null;
}

function analyze(request) {
  const root = fs.realpathSync(request.root);
  const maxDepth = Math.min(Math.max(request.limits?.max_call_depth || 12, 1), 64);
  const maxPaths = Math.min(Math.max(request.limits?.max_paths || 5000, 1), 20000);
  const maxNodes = Math.min(Math.max(request.limits?.max_graph_nodes || 100000, 1), 200000);
  const maxEdges = Math.min(Math.max(request.limits?.max_graph_edges || 200000, 1), 400000);
  const maxStateEntries = Math.min(Math.max(request.limits?.max_state_entries || 10000, 1), 100000);
  const maxFileBytes = Math.min(
    Math.max(request.limits?.max_file_bytes || 1000000, 1000),
    10000000,
  );
  if (!Array.isArray(request.files) || request.files.length < 1 || request.files.length > 5000) {
    throw new Error("files must contain between 1 and 5000 paths");
  }
  const inside = (base, candidate) => candidate === base || candidate.startsWith(`${base}${path.sep}`);
  const files = request.files.map((item) => {
    if (typeof item !== "string" || path.isAbsolute(item)) throw new Error("file path is invalid");
    const candidate = fs.realpathSync(path.resolve(root, item));
    if (!inside(root, candidate) || !/\.[cm]?tsx?$/.test(candidate)) {
      throw new Error("file path escapes the analysis root or has an unsupported extension");
    }
    return candidate;
  });
  const options = {
    allowJs: false,
    noEmit: true,
    noResolve: false,
    skipLibCheck: true,
    strict: false,
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.NodeNext,
    moduleResolution: ts.ModuleResolutionKind.NodeNext,
  };
  const defaultHost = ts.createCompilerHost(options, true);
  const libraryRoot = fs.realpathSync(path.dirname(ts.getDefaultLibFilePath(options)));
  const allowed = (fileName) => {
    const resolved = path.resolve(fileName);
    let candidate = resolved;
    try { candidate = fs.realpathSync(resolved); } catch { /* Missing candidates stay resolved. */ }
    if (inside(libraryRoot, candidate)) return true;
    if (!inside(root, candidate)) return false;
    try {
      return fs.statSync(candidate).size <= maxFileBytes;
    } catch {
      return true;
    }
  };
  const host = {
    ...defaultHost,
    fileExists: (fileName) => allowed(fileName) && defaultHost.fileExists(fileName),
    readFile: (fileName) => allowed(fileName) ? defaultHost.readFile(fileName) : undefined,
    getSourceFile: (fileName, languageVersion, onError, shouldCreateNewSourceFile) => (
      allowed(fileName)
        ? defaultHost.getSourceFile(fileName, languageVersion, onError, shouldCreateNewSourceFile)
        : undefined
    ),
    realpath: (fileName) => {
      if (!allowed(fileName)) return fileName;
      return defaultHost.realpath ? defaultHost.realpath(fileName) : fileName;
    },
  };
  const program = ts.createProgram(files, options, host);
  const checker = program.getTypeChecker();
  const sourceFiles = program.getSourceFiles().filter((file) => relativeFile(root, file.fileName));
  const nodes = new Map();
  const edges = new Map();
  const functions = new Map();
  const symbolFunctions = new Map();
  const namedFunctions = new Map();
  const entrypoints = new Set();
  const coverage = new Set();
  const candidates = [];
  const provenance = (confidence) => ({
    frontend: FRONTEND,
    frontend_version: ts.version,
    model_version: MODEL_VERSION,
    confidence,
    unresolved_alternatives: [],
  });
  const addNode = (node) => {
    if (!nodes.has(node.node_id) && nodes.size >= maxNodes) {
      throw new Error("graph node limit exceeded");
    }
    nodes.set(node.node_id, node);
  };
  const addEdge = (kind, sourceId, targetId, parameterIndex = null, flow = null) => {
    const edgeId = stableId("edge", kind, sourceId, targetId, parameterIndex, JSON.stringify(flow));
    const edge = {
      edge_id: edgeId,
      kind,
      source_id: sourceId,
      target_id: targetId,
      provenance: provenance(kind === "calls" ? "inferred" : "exact"),
    };
    if (parameterIndex !== null) edge.parameter_index = parameterIndex;
    if (flow !== null) {
      edge.source_role = flow.source.role;
      edge.target_role = flow.target.role;
      edge.source_context = flow.source.call_context;
      edge.target_context = flow.target.call_context;
    }
    if (!edges.has(edgeId) && edges.size >= maxEdges) throw new Error("graph edge limit exceeded");
    edges.set(edgeId, edge);
  };
  const resolveSymbol = (node) => {
    let symbol = checker.getSymbolAtLocation(node);
    if (symbol && symbol.flags & ts.SymbolFlags.Alias) symbol = checker.getAliasedSymbol(symbol);
    return symbol;
  };
  const functionForCall = (call) => {
    const symbol = resolveSymbol(call.expression);
    if (symbol) {
      const declaration = symbol.valueDeclaration || symbol.declarations?.[0];
      const resolved = declaration && symbolFunctions.get(declaration);
      if (resolved) return resolved;
    }
    return namedFunctions.get(terminal(call.expression)) || null;
  };

  for (const sourceFile of sourceFiles) {
    const relative = relativeFile(root, sourceFile.fileName);
    const fileId = stableId("file", relative);
    addNode({
      node_id: fileId,
      kind: "file",
      name: relative,
      span: location(root, sourceFile, sourceFile),
      type_status: "unknown",
    });
    const visit = (node) => {
      if (ts.isFunctionDeclaration(node) && node.name) {
        const functionId = stableId("function", relative, node.name.text, node.pos);
        const record = { id: functionId, node, sourceFile, relative, parameters: node.parameters };
        functions.set(functionId, record);
        symbolFunctions.set(node, record);
        const existing = namedFunctions.get(node.name.text);
        namedFunctions.set(node.name.text, existing === undefined ? record : null);
        addNode({
          node_id: functionId,
          kind: "function",
          name: `${relative}:${node.name.text}`,
          span: location(root, sourceFile, node),
          type_status: "resolved",
          type_name: checker.typeToString(checker.getTypeAtLocation(node.name)),
        });
        addEdge("declares", fileId, functionId);
        const blockId = stableId("block", functionId);
        addNode({
          node_id: blockId,
          kind: "basic_block",
          name: `${relative}:${node.name.text}:entry`,
          span: location(root, sourceFile, node),
          type_status: "unknown",
        });
        addEdge("controls", functionId, blockId);
        node.parameters.forEach((parameter) => {
          const name = parameter.name.getText(sourceFile);
          const symbolId = stableId("symbol", functionId, name);
          addNode({
            node_id: symbolId,
            kind: "symbol",
            name,
            span: location(root, sourceFile, parameter),
            type_status: "partial",
            type_name: checker.typeToString(checker.getTypeAtLocation(parameter)),
          });
          addEdge("declares", functionId, symbolId);
        });
      }
      ts.forEachChild(node, visit);
    };
    visit(sourceFile);
  }

  for (const record of functions.values()) {
    const visit = (node) => {
      if (ts.isCallExpression(node)) {
        const loc = location(root, record.sourceFile, node);
        const callId = stableId("call", record.relative, loc.start_line, loc.start_column);
        addNode({
          node_id: callId,
          kind: "call_site",
          name: node.expression.getText(record.sourceFile).slice(0, 512),
          span: loc,
          type_status: "unknown",
        });
        addEdge("controls", stableId("block", record.id), callId);
        const target = functionForCall(node);
        if (target) addEdge("calls", callId, target.id);
        if (ENTRYPOINTS.has(terminal(node.expression)) && node.arguments.length >= 2) {
          const handler = resolveSymbol(node.arguments[1]);
          const declaration = handler && (handler.valueDeclaration || handler.declarations?.[0]);
          const targetHandler = declaration && symbolFunctions.get(declaration);
          if (targetHandler) entrypoints.add(targetHandler.id);
        }
      }
      ts.forEachChild(node, visit);
    };
    if (record.node.body) visit(record.node.body);
  }

  for (const sourceFile of sourceFiles) {
    const visit = (node) => {
      if (ts.isCallExpression(node)
        && ENTRYPOINTS.has(terminal(node.expression))
        && node.arguments.length >= 2) {
        const handler = resolveSymbol(node.arguments[1]);
        const declaration = handler && (handler.valueDeclaration || handler.declarations?.[0]);
        const targetHandler = (declaration && symbolFunctions.get(declaration))
          || (ts.isIdentifier(node.arguments[1]) && namedFunctions.get(node.arguments[1].text));
        if (targetHandler) entrypoints.add(targetHandler.id);
      }
      ts.forEachChild(node, visit);
    };
    visit(sourceFile);
  }

  const selectors = request.rule.selectors;
  const matches = (name, role) => selectors.some((selector) => {
    if (selector.role !== role) return false;
    return name === selector.symbol || name.endsWith(`.${selector.symbol}`)
      || (!selector.symbol.includes(".") && name.split(".").at(-1) === selector.symbol);
  });
  const active = new Set();
  const evaluateFunction = (record, incoming, context, depth) => {
    if (depth > maxDepth) {
      coverage.add(stableId("typescript.call-depth", record.id));
      return null;
    }
    const signature = `${record.id}:${record.parameters.map((p) => incoming.has(p.name.getText())).join("")}`;
    if (active.has(signature)) {
      coverage.add(stableId("typescript.recursion", record.id));
      return null;
    }
    active.add(signature);
    let state = new Map(incoming);
    let aliases = new Map();
    if (entrypoints.has(record.id)) {
      for (const parameter of record.parameters) {
        const name = parameter.name.getText(record.sourceFile);
        if (state.has(name)) continue;
        const loc = location(root, record.sourceFile, parameter);
        const sourceId = stableId("source-param", record.id, name);
        addNode({
          node_id: sourceId,
          kind: "source",
          name: `entrypoint parameter ${name}`,
          span: loc,
          type_status: "unknown",
        });
        state.set(name, [{ node_id: sourceId, role: "source", span: loc, call_context: context }]);
      }
    }
    let returned = null;
    const accessPath = (node) => {
      if (!node) return null;
      if (ts.isIdentifier(node)) return aliases.get(node.text) || node.text;
      if (ts.isPropertyAccessExpression(node)) {
        const base = accessPath(node.expression);
        return base ? `${base}.${node.name.text}` : null;
      }
      if (ts.isElementAccessExpression(node)
        && (ts.isStringLiteralLike(node.argumentExpression)
          || ts.isNumericLiteral(node.argumentExpression))) {
        const base = accessPath(node.expression);
        return base ? `${base}[${JSON.stringify(node.argumentExpression.text)}]` : null;
      }
      return null;
    };
    const assign = (node, value) => {
      const key = accessPath(node);
      if (!key) return;
      if (!value) {
        state.delete(key);
        return;
      }
      if (!state.has(key) && state.size >= maxStateEntries) {
        state.clear();
        state.set("*", value);
        coverage.add(stableId("typescript.state-widening", record.id));
      } else state.set(key, value);
    };
    const expr = (node) => {
      if (!node) return null;
      if (ts.isIdentifier(node)) return state.get(accessPath(node)) || state.get("*") || null;
      if (ts.isStringLiteralLike(node) || ts.isNumericLiteral(node)) return null;
      if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) {
        return state.get(accessPath(node)) || expr(node.expression) || state.get("*") || null;
      }
      if (ts.isBinaryExpression(node)) return expr(node.left) || expr(node.right);
      if (ts.isTemplateExpression(node)) {
        for (const span of node.templateSpans) {
          const value = expr(span.expression);
          if (value) return value;
        }
        return null;
      }
      if (ts.isCallExpression(node)) {
        const name = node.expression.getText(record.sourceFile);
        const values = node.arguments.map(expr);
        const receiver = ts.isPropertyAccessExpression(node.expression)
          ? expr(node.expression.expression)
          : null;
        if (matches(name, "sink")) {
          const selector = selectors.find((item) => item.role === "sink"
            && (name === item.symbol || name.endsWith(`.${item.symbol}`)
              || (!item.symbol.includes(".") && name.split(".").at(-1) === item.symbol)));
          const value = values[selector?.argument_index || 0];
          if (value && candidates.length < maxPaths) {
            const loc = location(root, record.sourceFile, node);
            const sinkId = stableId("sink", record.relative, loc.start_line, loc.start_column, name);
            addNode({
              node_id: sinkId,
              kind: "sink",
              name: name.slice(0, 512),
              span: loc,
              type_status: "unknown",
            });
            candidates.push([...value, { node_id: sinkId, role: "sink", span: loc, call_context: context }]);
          }
          return null;
        }
        if (matches(name, "sanitizer")) return null;
        const target = functionForCall(node);
        if (target) {
          const loc = location(root, record.sourceFile, node);
          const callId = stableId("call", record.relative, loc.start_line, loc.start_column);
          const nested = [...context, target.id];
          const passed = new Map();
          target.parameters.forEach((parameter, index) => {
            if (values[index]) {
              passed.set(parameter.name.getText(target.sourceFile), [...values[index], {
                node_id: callId,
                role: "call",
                span: loc,
                call_context: nested,
              }]);
            }
          });
          const value = evaluateFunction(target, passed, nested, depth + 1);
          return value ? [...value, { node_id: callId, role: "return", span: loc, call_context: nested }] : null;
        }
        const value = receiver || values.find(Boolean) || null;
        if (value && !matches(name, "propagator")) {
          coverage.add(stableId("typescript.unresolved-call", record.relative, node.pos, name));
        }
        return value;
      }
      let found = null;
      ts.forEachChild(node, (child) => { if (!found) found = expr(child); });
      return found;
    };
    const statement = (node) => {
      if (ts.isVariableStatement(node)) {
        for (const declaration of node.declarationList.declarations) {
          if (ts.isIdentifier(declaration.name)) {
            const value = expr(declaration.initializer);
            const alias = accessPath(declaration.initializer);
            if (alias && !value) aliases.set(declaration.name.text, alias);
            else aliases.delete(declaration.name.text);
            assign(declaration.name, value);
          }
        }
      } else if (ts.isExpressionStatement(node)) {
        if (ts.isBinaryExpression(node.expression)
          && node.expression.operatorToken.kind === ts.SyntaxKind.EqualsToken
          && (ts.isIdentifier(node.expression.left)
            || ts.isPropertyAccessExpression(node.expression.left)
            || ts.isElementAccessExpression(node.expression.left))) {
          const value = expr(node.expression.right);
          if (ts.isIdentifier(node.expression.left)) {
            const alias = accessPath(node.expression.right);
            if (alias && !value) aliases.set(node.expression.left.text, alias);
            else aliases.delete(node.expression.left.text);
          }
          assign(node.expression.left, value);
        } else expr(node.expression);
      } else if (ts.isReturnStatement(node)) {
        returned = expr(node.expression);
        return true;
      } else if (ts.isThrowStatement(node)) return true;
      else if (ts.isBlock(node)) {
        for (const child of node.statements) if (statement(child)) return true;
      }
      else if (ts.isIfStatement(node)) {
        if (node.expression.kind === ts.SyntaxKind.TrueKeyword) return statement(node.thenStatement);
        if (node.expression.kind === ts.SyntaxKind.FalseKeyword) {
          return node.elseStatement ? statement(node.elseStatement) : false;
        }
        const originalState = state;
        const originalAliases = aliases;
        state = new Map(originalState);
        aliases = new Map(originalAliases);
        const leftTerminated = statement(node.thenStatement) || false;
        const leftState = state;
        const leftAliases = aliases;
        state = new Map(originalState);
        aliases = new Map(originalAliases);
        const rightTerminated = node.elseStatement ? statement(node.elseStatement) || false : false;
        const rightState = state;
        const rightAliases = aliases;
        state = originalState;
        aliases = originalAliases;
        state.clear();
        aliases.clear();
        if (!leftTerminated) {
          for (const [key, value] of leftState) state.set(key, value);
          for (const [key, value] of leftAliases) aliases.set(key, value);
        }
        if (!rightTerminated) {
          for (const [key, value] of rightState) state.set(key, value);
          for (const [key, value] of rightAliases) aliases.set(key, value);
        }
        return leftTerminated && rightTerminated;
      } else ts.forEachChild(node, statement);
      return false;
    };
    if (record.node.body) statement(record.node.body);
    active.delete(signature);
    return returned;
  };
  [...entrypoints].sort().forEach((id) => evaluateFunction(functions.get(id), new Map(), [id], 0));
  for (const candidate of candidates) {
    for (let index = 0; index + 1 < candidate.length; index += 1) {
      addEdge("flows_to", candidate[index].node_id, candidate[index + 1].node_id, null, {
        source: candidate[index],
        target: candidate[index + 1],
      });
    }
  }
  for (const diagnostic of program.getSyntacticDiagnostics()) {
    coverage.add(stableId("typescript.parse", diagnostic.file?.fileName || "unknown", diagnostic.start));
  }
  const graph = {
    schema_version: "1.1.0",
    revision: request.revision,
    build_context_digest: request.build_context_digest,
    framework_model_digest: request.framework_model_digest,
    frontend_versions: { [FRONTEND]: ts.version, "fdai.typescript.model": MODEL_VERSION },
    nodes: [...nodes.values()].sort((left, right) => left.node_id.localeCompare(right.node_id)),
    edges: [...edges.values()].sort((left, right) => left.edge_id.localeCompare(right.edge_id)),
    coverage_limits: [...coverage].sort(),
  };
  const graphDigest = digest(graph);
  const sanitizerContexts = selectors.filter((item) => item.role === "sanitizer")
    .map((item) => item.security_context).filter(Boolean).sort();
  const paths = candidates.map((steps) => {
    const semanticSteps = steps.map((step) => {
      const node = nodes.get(step.node_id);
      return {
        kind: node.kind,
        name: node.name,
        path: step.span.path,
        role: step.role,
        context: step.call_context,
      };
    });
    return {
      schema_version: "1.1.0",
      path_id: `path:${crypto.createHash("sha256").update(JSON.stringify(canonical([
        request.rule.rule_id,
        request.rule.version,
        semanticSteps,
      ]))).digest("hex")}`,
      revision: request.revision,
      graph_digest: graphDigest,
      rule_id: request.rule.rule_id,
      rule_version: request.rule.version,
      steps,
      sanitizers_considered: sanitizerContexts,
      coverage_limits: graph.coverage_limits,
    };
  });
  return { graph, paths };
}

module.exports = { analyze };

if (require.main === module) {
  try {
    process.stdout.write(`${JSON.stringify(analyze(readRequest()))}\n`);
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : "frontend failed"}\n`);
    process.exitCode = 1;
  }
}
