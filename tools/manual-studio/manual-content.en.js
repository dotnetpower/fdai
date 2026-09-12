import { buildSreIncidentResponseDeck } from "./sre-incident-response.en.js";
import { buildOntologyFoundationDeck } from "./ontology-foundation.en.js";
import { buildArtOfPossibleDeck } from "./art-of-possible.en.js";
import { buildReadinessMaturityDeck } from "./readiness-maturity.en.js";
import { buildValuePrioritizationDeck } from "./value-prioritization.en.js";
import { buildTargetArchitectureDeck } from "./target-architecture.en.js";

const docs = {
  constitution: "docs/roadmap/architecture/fdai-constitution.md",
  security: "docs/roadmap/architecture/security-and-identity.md",
  ontology: "docs/roadmap/architecture/operating-ontology.md",
  ontologyPlatform: "docs/roadmap/architecture/operating-ontology-platform.md",
  pantheon: "docs/roadmap/agents/agent-pantheon.md",
  operator: "docs/roadmap/operations/operator-initiated-sre-and-arb.md",
  deployment: "docs/roadmap/deployment/deployment.md",
  hardening: "docs/roadmap/deployment/production-deployment-hardening.md",
  execution: "docs/roadmap/decisioning/execution-model.md",
  metrics: "docs/roadmap/architecture/goals-and-metrics.md",
  dataGovernance: "docs/roadmap/architecture/data-governance.md",
  structuralModel: "docs/roadmap/architecture/ontology-structural-model.md",
  metamodel: "docs/roadmap/architecture/operating-ontology-metamodel.md",
  llmStrategy: "docs/roadmap/architecture/llm-strategy.md",
  semanticRetrieval: "docs/roadmap/rules-and-detection/rule-semantic-retrieval.md",
  documentIngestion: "docs/roadmap/interfaces/document-ingestion.md",
  ontologyDistillation: "docs/roadmap/rules-and-detection/document-ontology-distillation.md",
  operationalLearning: "docs/roadmap/rules-and-detection/operational-learning-ontology.md",
  behaviorKnowledge: "docs/roadmap/interfaces/behavior-knowledge.md",
  ontologyAgentLoop: "docs/roadmap/architecture/architecture-review/ontology-agent-loop.md",
  actionOntology: "docs/roadmap/decisioning/action-ontology.md",
  standingAuthority: "docs/roadmap/decisioning/escalation-and-standing-authority.md",
  runtimeAxes: "docs/roadmap/architecture/decisions/0002-independent-runtime-axes.md",
};

const deckAssets = {
  "ontology-foundation": "assets/ontology-foundation.jpeg",
  "responsible-ai-security": "assets/responsible-ai.jpeg",
  "pilot-production": "assets/pilot-production.jpeg",
  "ai-operating-model": "assets/operating-model.jpeg",
  "enterprise-scale-roadmap": "assets/scale-roadmap.jpeg",
};

const deckProfiles = {
  "responsible-ai-security": {
    label: "GUARDRAILS",
    sections: ["Identity and data", "Execution safety", "Operational controls"],
    segments: [[1, "Identity and data"], [10, "Execution safety"], [18, "Operational controls"]],
  },
  "pilot-production": {
    label: "ACTIVATE",
    sections: ["Baseline", "Shadow mode", "Promotion and operations"],
    segments: [[1, "Baseline and current boundaries"], [10, "Shadow-mode validation"], [27, "Promotion and operations"]],
  },
  "ai-operating-model": {
    label: "OPERATE",
    sections: ["Accountability", "Governance", "Measurement and improvement"],
    segments: [[1, "Accountability"], [10, "Governance and operations"], [27, "Measurement and improvement"]],
  },
  "enterprise-scale-roadmap": {
    label: "EVOLVE",
    sections: ["Scale dependencies", "Expansion waves", "Exit criteria"],
    segments: [[1, "Current position and dependencies"], [14, "Expansion waves"], [38, "Exit criteria and next decision"]],
  },
};

const statusLabels = {
  ASSESS: "ASSESS",
  BOUNDARY: "BOUNDARY",
  CRITERIA: "CRITERIA",
  CURRENT: "CURRENT IMPLEMENTATION",
  DECISION: "DECISION",
  DEPLOYMENT: "DEPLOYMENT",
  ENVISION: "ENVISION",
  FINOPS: "FINOPS",
  FOUNDATION: "FOUNDATION",
  FRAME: "FRAME",
  GAP: "CURRENT GAP",
  GATE: "GATE",
  GOVERN: "GOVERNANCE",
  HANDOVER: "HANDOVER",
  HOLD: "HOLD",
  INSPECT: "INSPECT",
  IMPLEMENTED: "IMPLEMENTED",
  IN_PROGRESS: "IN PROGRESS",
  ILLUSTRATIVE: "ILLUSTRATIVE",
  LLMOPS: "LLMOPS",
  METRIC: "MEASURE",
  NEXT: "NEXT",
  NOT_STARTED: "NOT STARTED",
  OPERATE: "OPERATE",
  PLAYBOOK: "PLAYBOOK",
  PRINCIPLE: "PRINCIPLE",
  PROPOSAL: "PROPOSAL",
  ROADMAP: "ROADMAP",
  SCORE: "ASSESSMENT",
  TARGET: "TARGET",
  TRACE: "TRACE",
  VALIDATED: "VALIDATED",
};

function sourceLabel(source) {
  const paths = Array.isArray(source) ? source : [source];
  return `<small class="evidence-source">Sources: ${paths.join(" / ")}</small>`;
}

function statusLabel(state) {
  const [group, sequence] = state.split(" ", 2);
  if (group === "GATE") return sequence ? `GATE ${sequence}` : statusLabels.GATE;
  if (group === "PHASE") return `PHASE ${sequence}`;
  if (group === "WAVE") return `WAVE ${sequence}`;
  return statusLabels[state] ?? state;
}

function splitPoint(point) {
  const separator = point.indexOf(":");
  if (separator < 0) return [point, "Record the evidence to verify and the completion criteria together."];
  return [point.slice(0, separator), point.slice(separator + 1)];
}

function cards(points, label) {
  return `
    <section class="agent-constellation" aria-label="${label}">
      ${points.map((point) => {
        const [name, detail] = splitPoint(point);
        return `<div><article><strong>${name}</strong><span>${detail}</span></article></div>`;
      }).join("")}
    </section>`;
}

function flow(points, label) {
  return `
    <figure aria-label="${label}">
      <div class="architecture-map">
        ${points.map((point, index) => {
          const [name, detail] = splitPoint(point);
          const connector = index < points.length - 1 ? "<i aria-hidden=\"true\"></i>" : "";
          return `<div class="arch-node"><span>${String(index + 1).padStart(2, "0")}</span><strong>${name}</strong><small>${detail}</small></div>${connector}`;
        }).join("")}
      </div>
    </figure>`;
}

function matrix(points, label) {
  return `
    <table class="manual-matrix" aria-label="${label}">
      <thead><tr><th scope="col">Review dimension</th><th scope="col">Decision evidence</th></tr></thead>
      <tbody>${points.map((point) => {
        const [name, detail] = splitPoint(point);
        return `<tr><th scope="row">${name}</th><td>${detail}</td></tr>`;
      }).join("")}</tbody>
    </table>`;
}

function decisionTree(points, label) {
  return `
    <nav class="manual-decision-tree" aria-label="${label}">
      <ol class="safety-list">${points.map((point) => {
        const [question, outcome] = splitPoint(point);
        return `<li><span><strong>${question}</strong><small>${outcome}</small></span></li>`;
      }).join("")}</ol>
    </nav>`;
}

function timeline(points, label) {
  return `
    <ol class="manual-timeline journey" aria-label="${label}">
      ${points.map((point, index) => {
        const [phase, gate] = splitPoint(point);
        const connector = index < points.length - 1 ? "<i aria-hidden=\"true\"></i>" : "";
        return `<li><span><strong>${phase}</strong><small>${gate}</small></span></li>${connector}`;
      }).join("")}
    </ol>`;
}

function responsibilityMap(points, label) {
  return `
    <section class="identity-flow" aria-label="${label}">
      ${points.map((point, index) => {
        const [owner, duty] = splitPoint(point);
        const connector = index < points.length - 1 ? "<i aria-hidden=\"true\"></i>" : "";
        return `<div><small>Accountable</small><strong>${owner}</strong><span>${duty}</span></div>${connector}`;
      }).join("")}
    </section>`;
}

function evidenceChain(points, label) {
  return `
    <figure class="manual-evidence-chain" aria-label="${label}">
      <figcaption>Conditions for evidence to support the next decision</figcaption>
      <div class="journey">${points.map((point, index) => {
        const [evidence, use] = splitPoint(point);
        const connector = index < points.length - 1 ? "<i aria-hidden=\"true\"></i>" : "";
        return `<span><strong>${evidence}</strong><small>${use}</small></span>${connector}`;
      }).join("")}</div>
    </figure>`;
}

function briefingNumbers(points, label) {
  return `
    <section class="briefing-number-grid" aria-label="${label}">
      ${points.map((point) => {
        const [value, detail] = splitPoint(point);
        return `<article><strong>${value}</strong><span>${detail}</span></article>`;
      }).join("")}
    </section>`;
}

function briefingComparison(points, label) {
  return `
    <section class="briefing-comparison" aria-label="${label}">
      ${points.map((point, index) => {
        const [name, detail] = splitPoint(point);
        return `<article><small>${String(index + 1).padStart(2, "0")}</small><strong>${name}</strong><span>${detail}</span></article>`;
      }).join("")}
    </section>`;
}

function briefingLayers(points, label) {
  return `
    <figure class="briefing-layers" aria-label="${label}">
      ${points.map((point, index) => {
        const [name, detail] = splitPoint(point);
        return `<div style="--layer:${index}"><strong>${name}</strong><span>${detail}</span></div>`;
      }).join("")}
    </figure>`;
}

const visualBuilders = {
  cards,
  flow,
  matrix,
  tree: decisionTree,
  timeline,
  responsibility: responsibilityMap,
  evidence: evidenceChain,
  numbers: briefingNumbers,
  comparison: briefingComparison,
  layers: briefingLayers,
};

function topic(state, title, lead, points, source, visual = "cards") {
  return { state, title, lead, points: points.split("|"), source, visual };
}

function buildDeck(id, eyebrow, topics) {
  const profile = deckProfiles[id];
  return topics.map((item, index) => {
    const number = String(index + 1).padStart(2, "0");
    const chapter = profile.segments
      .filter(([start]) => index >= start)
      .at(-1)?.[1] ?? profile.sections[0];
    if (index === 0) {
      return {
        eyebrow: `FDAI / ${eyebrow}`,
        title: item.title,
        lead: item.lead,
        layout: `briefing-cover deck-${id}`,
        content: `
          <figure class="briefing-cover-art">
            <img src="${deckAssets[id]}" alt="">
            <figcaption>${profile.label}</figcaption>
          </figure>
          <ol class="briefing-cover-index" aria-label="Key sections of ${item.title}">
            ${profile.sections.map((section, sectionIndex) => `<li><small>0${sectionIndex + 1}</small><span>${section}</span></li>`).join("")}
          </ol>
          ${sourceLabel(item.source)}`,
      };
    }
    const builder = visualBuilders[item.visual] ?? cards;
    return {
      eyebrow: `${number} / ${statusLabel(item.state)}`,
      title: item.title,
      lead: item.lead,
      layout: `briefing-${item.visual} deck-${id}`,
      content: `
        <div class="briefing-status-row">
          <span class="manual-status" data-state="${item.state}" aria-label="Design status: ${statusLabel(item.state)}">${statusLabel(item.state)}</span>
          <span>${chapter} / ${number} / ${String(topics.length).padStart(2, "0")}</span>
        </div>
        ${builder(item.points, item.title)}
        ${sourceLabel(item.source)}`,
    };
  });
}

function ontologyPanels(points, label) {
  return `
    <section class="ontology-panel-grid" aria-label="${label}">
      ${points.map((point, index) => {
        const [name, detail] = splitPoint(point);
        return `<article><small>${String(index + 1).padStart(2, "0")}</small><strong>${name}</strong><span>${detail}</span></article>`;
      }).join("")}
    </section>`;
}

function ontologyNumbers(points, label) {
  return `
    <section class="ontology-number-grid" aria-label="${label}">
      ${points.map((point) => {
        const [value, detail] = splitPoint(point);
        return `<article><strong>${value}</strong><span>${detail}</span></article>`;
      }).join("")}
    </section>`;
}

function ontologyFlow(points, label) {
  return `
    <ol class="ontology-flow" aria-label="${label}">
      ${points.map((point, index) => {
        const [name, detail] = splitPoint(point);
        return `<li><small>${String(index + 1).padStart(2, "0")}</small><strong>${name}</strong><span>${detail}</span></li>`;
      }).join("")}
    </ol>`;
}

function ontologyStack(points, label) {
  return `
    <figure class="ontology-stack" aria-label="${label}">
      ${points.map((point, index) => {
        const [name, detail] = splitPoint(point);
        return `<div style="--stack-step:${index}"><strong>${name}</strong><span>${detail}</span></div>`;
      }).join("")}
    </figure>`;
}

function ontologyTable(points, label) {
  return `
    <table class="ontology-table" aria-label="${label}">
      <thead><tr><th scope="col">Category</th><th scope="col">Technical meaning and boundary</th></tr></thead>
      <tbody>${points.map((point) => {
        const [name, detail] = splitPoint(point);
        return `<tr><th scope="row">${name}</th><td>${detail}</td></tr>`;
      }).join("")}</tbody>
    </table>`;
}

function ontologyGraph(points, label) {
  const [center, ...satellites] = points;
  const [centerName, centerDetail] = splitPoint(center);
  return `
    <figure class="ontology-graph" aria-label="${label}">
      <div class="ontology-graph-center"><strong>${centerName}</strong><span>${centerDetail}</span></div>
      <div class="ontology-graph-orbit">
        ${satellites.map((point) => {
          const [name, detail] = splitPoint(point);
          return `<article><strong>${name}</strong><span>${detail}</span></article>`;
        }).join("")}
      </div>
    </figure>`;
}

const ontologyBuilders = {
  panels: ontologyPanels,
  numbers: ontologyNumbers,
  flow: ontologyFlow,
  stack: ontologyStack,
  table: ontologyTable,
  graph: ontologyGraph,
};

function ontologyTopic(state, chapter, title, lead, points, source, visual = "panels") {
  return { state, chapter, title, lead, points: points.split("|"), source, visual };
}

function buildOntologyDeck(topics) {
  return topics.map((item, index) => {
    const number = String(index + 1).padStart(2, "0");
    if (index === 0) {
      return {
        eyebrow: "FDAI / DATA & ONTOLOGY FOUNDATION",
        title: item.title,
        lead: item.lead,
        layout: "ontology-cover",
        content: `
          <figure class="ontology-cover-art" aria-label="How LLM, RAG, ontology, and FDAI connect">
            <img src="${deckAssets["ontology-foundation"]}" alt="">
            <figcaption><strong>LLM</strong><i></i><strong>RAG</strong><i></i><strong>Ontology</strong><i></i><strong>FDAI</strong></figcaption>
          </figure>
          ${sourceLabel(item.source)}`,
      };
    }
    const builder = ontologyBuilders[item.visual] ?? ontologyPanels;
    return {
      eyebrow: `${number} / ${item.chapter}`,
      title: item.title,
      lead: item.lead,
      layout: `ontology-${item.visual}`,
      content: `
        <div class="ontology-status-row">
          <span class="manual-status" data-state="${item.state}" aria-label="Design status: ${statusLabel(item.state)}">${statusLabel(item.state)}</span>
          <span>${item.chapter}</span>
        </div>
        ${builder(item.points, item.title)}
        ${sourceLabel(item.source)}`,
    };
  });
}

const readinessMaturity = buildReadinessMaturityDeck();

const artOfPossible = buildArtOfPossibleDeck({ sourceLabel, statusLabel });

const valuePrioritization = buildValuePrioritizationDeck();

const targetArchitecture = buildTargetArchitectureDeck();

const ontologyFoundation = buildOntologyDeck([
  ontologyTopic("FOUNDATION", "FOUNDATION", "Data & Ontology Foundation", "Connect the probabilistic exploration of LLMs and RAG to the formal meaning of ontology and deterministic FDAI validation.", "LLM:Generate language candidates|RAG:Retrieve evidence candidates|Ontology:Shared meaning and constraints|FDAI:Decisions with separated authority", [docs.constitution, docs.llmStrategy, docs.ontology]),
  ontologyTopic("PRINCIPLE", "PART 1 / LLM", "An LLM calculates probabilities for the next token", "It repeatedly selects a plausible next token from context, but cannot guarantee factuality, freshness, or authority by itself.", "Input tokens:Split a sentence into units the model handles|Context representation:Calculate relationships among preceding tokens|Probability distribution:Score every possible next token|Generation:Add the selected token back to the input", docs.llmStrategy, "flow"),
  ontologyTopic("PRINCIPLE", "PART 1 / LLM", "A Transformer calculates contextual relationships in parallel", "It updates each token's contextual representation through embeddings, position information, self-attention, and feed-forward neural networks.", "Embedding:Convert tokens to continuous vectors|Position:Add sequence information to vectors|Attention:Calculate relevance with queries, keys, and values|Logits:Score the next token across the vocabulary", docs.llmStrategy, "stack"),
  ontologyTopic("BOUNDARY", "PART 1 / LLM", "Model context is not the same as operational fact", "Distinguish learned patterns, the current conversation, and authoritative operational observations to explain an answer's source and validity period.", "Model parameters:Statistical patterns from training, not current facts|Context window:Temporarily holds the request and attached evidence|Operational observation:External fact with source, as-of time, and completeness", [docs.llmStrategy, docs.dataGovernance], "table"),
  ontologyTopic("BOUNDARY", "PART 1 / LLM", "Hallucination is unverified generation, not a tone of voice", "Because generation tries to complete a sentence even when evidence is absent or conflicting, fluency cannot stand in for trustworthiness.", "Evidence present:Do citations match the scope of the claim?|Evidence conflict:Is the difference exposed and the decision held?|Evidence absent:Is unknown or clarification returned instead of a guess?|Authority request:Is language prevented from being mistaken for execution authority?", [docs.constitution, docs.llmStrategy], "panels"),
  ontologyTopic("TARGET", "PART 1 / FDAI ROUTING", "FDAI uses deterministic methods first", "The design target ratios are hypotheses to validate for workload classification, not actual processing rates or guaranteed outcomes.", "70-80%:Target for T0 rules, policies, and state machines|15-20%:Target for T1 similarity and lightweight classification|5-10%:Target for T2 evidence-grounded reasoning", docs.llmStrategy, "numbers"),
  ontologyTopic("PRINCIPLE", "PART 1 / EMBEDDING", "Embeddings represent semantic similarity as coordinates", "Converting text or structured objects into fixed-length vectors makes it possible to find nearby candidates quickly.", "Vectorization:Compress input into numeric coordinates|Distance calculation:Find nearby candidates with cosine similarity or similar measures|Candidate retrieval:Pass the top k candidates to subsequent validation|Boundary:Proximity does not mean identity, factuality, or causality", [docs.llmStrategy, docs.behaviorKnowledge], "flow"),
  ontologyTopic("BOUNDARY", "PART 1 / EMBEDDING", "A similarity score is not a verdict", "Vector search only orders candidates; it does not decide policy compliance, authority, or operational effect.", "Similar:Signal that wording or context is close|Identical:Requires exact identifier and version validation|Related:Requires relationship type and direction validation|Actionable:Requires additional policy, risk, approval, and recovery validation", [docs.constitution, docs.semanticRetrieval], "table"),
  ontologyTopic("PRINCIPLE", "PART 1 / RAG", "RAG retrieves external evidence before generation", "It converts a question into a search representation, finds candidates in permitted sources, reranks them, and passes them into generation context.", "Question normalization:Separate intent from search terms|Candidate set:Select only accessible sources|Hybrid search:Combine lexical and semantic scores|Reranking:Reflect purpose and freshness|Generation and citation:Link claims to evidence locations", [docs.semanticRetrieval, docs.documentIngestion], "flow"),
  ontologyTopic("BOUNDARY", "PART 1 / SECURE RAG", "RAG blocks unauthorized access and prompt injection first", "Build the permitted candidate set first and treat retrieved documents as untrusted data to prevent both leakage and indirect prompt injection.", "1. Principal and purpose:Fix role, scope, and intended use|2. Permitted candidates:Include only accessible document IDs|3. Trust boundary:Treat document instructions as data, not commands|4. Ranking:Calculate lexical and semantic scores within permitted candidates|5. Generation context:Pass only citable excerpts", [docs.llmStrategy, docs.dataGovernance, docs.documentIngestion], "stack"),
  ontologyTopic("CURRENT", "PART 1 / FDAI RETRIEVAL", "Active rules and discovered documents use different generations", "Separating the validated execution catalog from exploratory sources prevents a discovery result from becoming decision evidence immediately.", "62:Active rule catalog|8,487:Discovered document projections|1-20:Search result limit per request|5 seconds:Catalog search function timeout", [docs.semanticRetrieval, "services/core-control-plane/src/fdai/core/ontology_platform/catalog_queries.py"], "numbers"),
  ontologyTopic("FOUNDATION", "PART 2 / ONTOLOGY", "Ontology adds shared meaning and constraints to data", "Versioned declarations define what objects, relationships, properties, and actions mean, rather than merely agreeing on storage formats.", "Data:Observed values and records|Schema:Structure of fields and data types|Ontology:Shared meaning, relationships, and constraints|Knowledge graph:Instances connected according to the ontology", [docs.ontology, docs.metamodel], "table"),
  ontologyTopic("GAP", "PART 2 / METAMODEL", "The five operating lenses differ from the five declaration types", "Questions are read through Object, Relationship, State, Context, and Action. Object, Link, Function, and Action are active; Interface still awaits catalog integration after contract support.", "Object:Declare identity and properties as an Object|Link:Constrain Relationship endpoints and direction|State:Calculate from observations rather than declare independently|Context:Runtime bundle of goals, constraints, and evidence|Action:Function and Action are active; Interface integration is in progress", [docs.ontology, docs.metamodel, docs.structuralModel], "panels"),
  ontologyTopic("CURRENT", "PART 2 / IDENTITY", "Object identity persists when display names change", "ObjectRef and an exact type_ref track the same target across name changes, provider representation changes, and release changes.", "ObjectRef:Stable object reference|type_ref:Declaration name and version|release_digest:Release used for interpretation|display_name:Mutable human-readable label", [docs.ontology, docs.ontologyPlatform], "table"),
  ontologyTopic("CURRENT", "PART 2 / LINKS", "LinkType separates direction from causality", "It validates stored edge direction, permitted traversal direction, and causal claims independently, without creating reverse links automatically.", "Stored direction:Meaning recorded from source to target|Traversal direction:Direction a query may follow|Reverse direction:Used only with a separate declaration and evidence|Causal meaning:A relationship alone does not prove cause and effect", [docs.structuralModel, docs.ontology], "flow"),
  ontologyTopic("BOUNDARY", "PART 2 / STATE", "State is calculated from observations, not created as a new object", "State is reproduced from versioned semantic rules and time-bound observations instead of adding unlimited state objects.", "Declaration:Property meaning and permitted range|Observation:Value, source, and event time|State:Result calculated at an as-of time|Context:Bundle of goals, constraints, purpose, and evidence", [docs.metamodel, docs.dataGovernance], "stack"),
  ontologyTopic("CURRENT", "PART 2 / TIME", "Operational facts require more than one time", "Separating when something occurred, was valid, and was recorded supports late-arriving evidence and historical replay.", "event_time:When the event occurred|effective_time:Interval when the fact was valid|recorded_time:When the system recorded it|fresh_until:Latest time the fact may be reused in a decision", [docs.dataGovernance, docs.ontology], "table"),
  ontologyTopic("CURRENT", "PART 2 / PROVENANCE", "Content digests fix interpretation and replay", "Plans, candidates, query results, and function inputs and outputs are linked by SHA-256 digests of canonical JSON.", "sha256:64-character hexadecimal content address|canonical JSON:Serialize the same meaning to identical bytes|lineage:Preserve source ID, revision, and as-of time|replay:Verify the same input and release combination", [docs.dataGovernance, docs.ontologyPlatform, "services/core-control-plane/src/fdai/core/ontology_platform/semantic_plans.py"], "panels"),
  ontologyTopic("CURRENT", "PART 2 / PROPERTY SEMANTICS", "Matching a property's data type is not enough", "Validate units, ranges, enum values, time zones, and numeric precision to normalize provider-specific representations into comparable values.", "64 KiB:Maximum single canonical JSON value|Decimal:Preserve the meaning of the authored decimal|RFC 3339:Time boundary with a time zone|Finite values:Reject NaN and infinity", [docs.structuralModel, docs.ontology], "numbers"),
  ontologyTopic("CURRENT", "PART 2 / RELEASE", "OntologyRelease is never changed in place", "Each new declaration set receives a new digest and compatibility decision so the meaning of existing records cannot change retroactively.", "compatible:Existing consumers can read it unchanged|migration_required:Use only after explicit transformation|incompatible:Never accept automatically|release envelope:Pin the exact release across services", [docs.ontologyPlatform, docs.structuralModel], "table"),
  ontologyTopic("CURRENT", "PART 2 / UNKNOWN", "Unmapped facts remain unknown", "Do not infer service relationships or neutral types; separate provider evidence, the reason for absence, and the review proposal.", "Service relationship:unknown_service - connection is not proven|Neutral type:unclassified-resource - mapping is not reviewed|Unavailable:unavailable - authoritative source could not be read|Change proposal:proposal - candidate pending review, not a fact", [docs.ontology, docs.dataGovernance], "panels"),
  ontologyTopic("CURRENT", "PART 2 / INTENT", "Goals and constraints are formal operational objects", "Connect SLO, recovery, cost, control, and architecture conditions with units, scope, owner, and validity interval.", "ServiceObjective:SLI, measurement window, and target value|RecoveryObjective:RTO, RPO, and applicable scope|CostObjective:Currency, period, and budget boundary|ControlObjective:Goal that policy and controls must achieve|ArchitectureConstraint:Reviewed condition and applicable target", [docs.ontology, docs.actionOntology], "table"),
  ontologyTopic("CURRENT", "PART 2 / EFFECTS", "An action and its effect are not one success state", "Separate selection, execution attempt, and independent observation so API success is not mistaken for an operational outcome.", "DecisionCase:Goal, constraints, and no-action baseline|ActionOption:Comparable response candidate|ActionRun:Execution attempt and evidence|ExpectedEffect:Predefined metric range|ObservedOutcome:Actual effect observed independently", [docs.operationalLearning, docs.constitution, "services/core-control-plane/src/fdai/core/decision_case/models.py"], "flow"),
  ontologyTopic("CURRENT", "PART 3 / FDAI PLATFORM", "FDAI separates the semantic layer from the decision layer", "It projects provider facts, queries them with release-pinned meaning, and decides actions through separate policy, risk, and approval paths.", "Provider evidence:Authoritative external observation|Projection:Neutral objects and relationships|Ontology release:Versioned declarations|Secured query:Evidence of role, purpose, and completeness|Decision path:Rules, risk, approval, and execution", [docs.ontologyPlatform, docs.constitution], "stack"),
  ontologyTopic("CURRENT", "PART 3 / CATALOG SCALE", "Raw provider types do not become the ontology unchanged", "Instead of copying every Azure type, promote only neutral classifications and reviewed mappings needed for operational questions into the formal catalog.", "3,405:Discovered raw Azure resource types|11:Canonical top-level classes|80:Reviewed class memberships|80:Neutral ResourceTypes", [docs.structuralModel, docs.ontology], "numbers"),
  ontologyTopic("CURRENT", "PART 3 / RULE SEMANTICS", "Compare properties read by rules with semantic declarations", "Match Property references in active rules to the catalog, and do not mark properties complete before semantic review.", "62 / 62:Active rule Property references connected|45:Reviewed property meanings|Rule:Meaning and input contract|PolicyArtifact:Authored Rego and AST digest", [docs.structuralModel, docs.semanticRetrieval], "numbers"),
  ontologyTopic("CURRENT", "PART 3 / KNOWLEDGE PROJECTIONS", "External knowledge is a read-only projection without execution authority", "Frameworks and diagnostic sources support exploration and validation but do not create approval, policy verdicts, or execution authority.", "456:WARA and APRL FrameworkControls|61:Diagnostic mechanisms|427:Independent validation evidence items|Reference only:No approval, risk verdict, or execution authority", [docs.ontology, docs.semanticRetrieval], "numbers"),
  ontologyTopic("CURRENT", "PART 3 / OBJECTSET", "ObjectSet is not a free-form graph query", "The request specifies types, predicates, named relationships, and result, candidate, and traversal limits to bound both cost and semantic scope.", "32:Maximum predicates per query|1,000:Limit for IN values, candidates, and root IDs|64:LinkType traversal limit|1-5:Relationship traversal depth|100-1,000:Result limit", [docs.ontologyPlatform, "services/core-control-plane/src/fdai/core/ontology_platform/models.py"], "numbers"),
  ontologyTopic("CURRENT", "PART 3 / COMPLETENESS", "Interpret query limits and empty results together", "No result is evidence of absence only when evidence proves that the entire scope was checked.", "RESULT_LIMIT:Stopped at the requested result count|CANDIDATE_LIMIT:Checked only some candidates before filtering|TRAVERSAL_LIMIT:Did not inspect the full relationship traversal scope|complete empty:Only a proven-complete empty result supports absence", [docs.ontologyPlatform, "services/core-control-plane/src/fdai/core/ontology_platform/object_sets.py"], "table"),
  ontologyTopic("CURRENT", "PART 3 / QUERY EXECUTION", "Query plans progress in batches of executable nodes", "Fix node dependencies as a DAG and run only nodes ready at the same time in parallel to control time, concurrency, and failure propagation.", "8:Concurrent node limit|30 seconds:Per-node timeout|32:Plan DAG node limit|17:Supported QueryNodeKinds|Batch execution:Failed dependencies propagate as explicit states", [docs.ontologyPlatform, "packages/service-contracts/src/fdai_service_contracts/ontology_query.py"], "numbers"),
  ontologyTopic("CURRENT", "PART 3 / SECURED QUERY", "Secured query evidence exposes authority and loss", "Return role scope, purpose of use, de-identification, observation as-of time, and projection digest with the results.", "Time mode:Only current_state_only is supported today|0-5 seconds:Permitted as-of-time error|De-identification:Counts of removed objects, links, and identities|No authority:execution_authority is false", [docs.ontologyPlatform, "services/core-control-plane/src/fdai/core/ontology_platform/query_gateway.py"], "panels"),
  ontologyTopic("CURRENT", "PART 3 / SEMANTIC PLAN", "Semantic interpretation starts with three candidate sources", "Lexical matches, embeddings, and models all create non-authoritative candidates; unresolved terms remain when exact catalog evidence is absent.", "LEXICAL:Exact term and alias match|EMBEDDING:Candidate based on vector similarity|MODEL:Structured candidate proposed by an LLM|SHA-256:candidate_digest fixes input, release, and scores", [docs.ontologyAgentLoop, "services/core-control-plane/src/fdai/core/ontology_platform/semantic_plans.py"], "panels"),
  ontologyTopic("CURRENT", "PART 3 / VERIFICATION", "Verification raises confidence but does not replace the decision path", "A candidate becomes a plan only after receiving explicit verification evidence, and still follows the standard decision, policy, and approval path.", "EXACT_CATALOG:Exact declaration in the active release|PROMOTED_SURFACE:Semantic surface promoted after review|OPERATOR_CONFIRMATION:Confirmation by an authenticated person|VerifiedSemanticPlan:Input with fixed meaning, not an execution command", [docs.ontologyAgentLoop, docs.constitution], "table"),
  ontologyTopic("CURRENT", "PART 3 / FUNCTIONS", "Ontology functions are pinned to call context and release", "The function registry binds the exact release, calling agent, role ceiling, purpose, and evidence references into evidence.", "16:Unique-purpose limit per call|64:Evidence-reference limit|7:Server-assigned EvidenceAuthority types|0:Catalog search functions permitted to use credentials or network", [docs.ontologyPlatform, "services/core-control-plane/src/fdai/core/ontology_platform/functions.py"], "numbers"),
  ontologyTopic("GAP", "PART 3 / BEHAVIOR KNOWLEDGE", "Behavior knowledge retrieval still requires restoration of the primary path", "The in-memory index for 384-dimensional hybrid search is implemented, but 13 baseline seeds, the server response path, persistent storage, and operational evidence are still absent.", "384 dimensions:Implemented in-memory semantic search|13:Baseline seeds not restored|In progress:Structured contracts and source-freshness checks|Not started:Server responses, persistent storage, and operational evidence", docs.behaviorKnowledge, "numbers"),
  ontologyTopic("CURRENT", "PART 3 / DOCUMENT DISTILLATION", "Meaning extracted from documents ends as a change proposal", "Model output is an OntologyChangeProposal and does not directly modify an active release or instance graph.", "Ingest:Preserve source, revision, and access scope|Extract:Candidate object, relationship, and property meanings|Propose:Create OntologyChangeProposal|Review:Check conflicts, duplicates, evidence, and compatibility|Promote:Use a separate release procedure", [docs.documentIngestion, docs.ontologyDistillation], "flow"),
  ontologyTopic("CURRENT", "PART 4 / RECONCILIATION", "Change effects close through asynchronous reconciliation records", "Compare expected effects with authoritative follow-up observations. Terminal states are MATCHED, MISMATCHED, TIMED_OUT, and UNSCORABLE.", "8:Reconciliation-attempt limit per effect|64:State-store CAS attempt limit|16 MiB:Aggregate record limit|30 seconds:Outbox delivery lease", [docs.ontologyPlatform, "services/core-control-plane/src/fdai/core/ontology_platform/reconciliation_state_store.py"], "numbers"),
  ontologyTopic("GAP", "PART 4 / CURRENT GAPS", "Separate current implementation gaps from target architecture", "A declaration in documentation or partial code is not complete without end-to-end projection and operational evidence.", "Historical query:SecuredObjectSetQueryGateway is current_state_only|ControlObjective:Some declarations exist, but runtime projection and equivalence execution remain|Causal analysis:Relationships and correlation alone do not establish cause|Action execution:Policy, approval, and isolated execution paths outside the ontology platform remain responsible", [docs.ontologyPlatform, docs.structuralModel], "table"),
  ontologyTopic("TARGET", "PART 4 / OPERATING MODEL", "The quality target is trustworthy answers, not a type count", "The platform team must operate release accuracy, projection freshness, query completeness, access control, and reproducible migration together.", "Semantic management:Declarations, compatibility, and release digests|Data management:Source, freshness, completeness, and de-identification|Retrieval management:Generations, evaluation sets, recall, and false positives|Operations management:Latency, truncation, conflicts, and reconciliation failure|Governance:Promotion, retirement, owners, and evidence", [docs.dataGovernance, docs.ontologyPlatform], "panels"),
  ontologyTopic("NEXT", "PART 4 / DELIVERY SEQUENCE", "Expand from read quality to action validation in sequence", "Secure authoritative projections and measurable retrieval quality before adding models or types, then expand to bounded action proposals.", "1. Observation baseline:Identity, time, source, and completeness|2. Semantic release:Reviewed types, relationships, and properties|3. Secure retrieval:Permitted candidates, hybrid ranking, and evaluation set|4. Semantic plan:Candidates, verification evidence, and unresolved terms|5. Action proposal:Policy, risk, approval, recovery, and independent effect verification", [docs.constitution, docs.ontologyPlatform, docs.actionOntology], "flow"),
]);

const responsibleAiSecurity = buildDeck("responsible-ai-security", "RESPONSIBLE AI & SECURITY", [
  topic("INSPECT", "Autonomy starts with identity and evidence", "Review separation of authority and fail-closed conditions before model features.", "Identity:Who can act?|Authority:What can be executed?|Evidence:Why was it executed, and what was the result?", docs.security),
  topic("CURRENT", "Human approval and execution identity are different", "People do not hold the executor identity, and no principal both approves and executes an action.", "Human:Authenticated approver|Executor:Non-interactive workload identity|Principle:No self-approval", docs.security, "responsibility"),
  topic("VALIDATED", "Azure executors use the Managed Identity boundary", "The shared implementation separates short-lived, audience-bound OIDC tokens from user-assigned Managed Identity references. Each deployment supplies action allowlists and resource roles.", "Shared contract:Request only short-lived OIDC tokens|Identity:User-assigned Managed Identity reference|Deployment responsibility:Action allowlist and roles|Prohibited:Human credentials and long-lived secrets", docs.security, "flow"),
  topic("CURRENT", "Execution identities are separated by domain", "Identity references for Change Safety, Resilience, and FinOps cannot substitute for authority in another domain.", "identity/change:Change deployment|identity/resilience:Recovery scope|identity/finops:Cost operations", docs.security, "matrix"),
  topic("CURRENT", "Unknown identity references are denied", "There is no automatic fallback to a shared executor identity, so a bad binding cannot expand authority.", "Verified:Exact identity and domain binding|Unknown:Explicit denial|Missing:Action held|Cross-domain:No authority substitution", docs.security, "tree"),
  topic("DEPLOYMENT", "Deployments bind action authority to the minimum scope", "The shared repository provides identity boundaries; each deployment operates resource-scoped roles and action allowlists.", "Shared implementation:Identity separation and unknown-reference denial|Deployment responsibility:Resource scope and allowlists|Operations:Observe effective access and recertify|Next:Measurement-based custom roles", docs.security, "matrix"),
  topic("IN_PROGRESS", "Insufficient access is handled as an independent request", "Approval of the original action does not grant executor access. The AccessGrantRequest lifecycle is implemented but remains inactive until deployment policy, identity mapping, and effective-access probes are connected.", "Original action:Held under current authority|Access request:Limited to the exact plan and revision|Deployment binding:Policy, identity, mapping, and probes|Recheck:Current effective access immediately before execution", docs.security, "evidence"),
  topic("CURRENT", "Secrets are injected at runtime", "Applications read environment variables or mounted paths; Core does not call a cloud secrets SDK.", "Source:Key Vault reference|Runtime:Environment-variable binding|Failure:Block during startup", docs.security, "flow"),
  topic("IN_PROGRESS", "Treat every model input as data that requires validation", "External documents and tool output are not execution instructions. Do not transmit when redaction is insufficient. Check data residency and retention terms before deployment.", "Data minimization:Send required fields and pointers, not source records|Prompt injection:Never treat external instructions as execution commands|Provider boundary:Check region, retention, and training-use terms|Failure:Do not transmit; route to human review", [docs.dataGovernance, docs.security], "comparison"),
  topic("CURRENT", "Limit network ingress and egress", "The executor and Core have no public ingress; egress is limited to required control planes and model endpoints.", "Ingress:Event bus only|Management:Private network|Egress:Deny by default with an allowlist", docs.security, "matrix"),
  topic("IMPLEMENTED", "The supply chain is pinned by image digest and attestations", "Run only verified images and never use mutable latest tags.", "Dependencies:Pinned lockfiles|Artifacts:SBOM, signed image, and supply-chain attestations|Runtime:Pinned image digest|Plan:Apply only permitted changes", docs.security, "evidence"),
  topic("IN_PROGRESS", "Seven safeguards determine eligibility for autonomous state changes", "PR-based actions, direct APIs, and tool calls use a common pre-effect evidence contract. Equivalent end-to-end evidence for Workflow and isolated executor paths is in progress.", "Stop condition:Machine-evaluable termination criteria|Tested recovery:Rollback or state-forward recovery|Blast radius:Maximum target count|Dry run:Bound to the current plan revision|Target lock:Block concurrent effects|Duplicate suppression:Treat redelivery as no change|Two-phase audit:Record intent and outcome separately", docs.security, "comparison"),
  topic("CURRENT", "Stop conditions must be machine-evaluable", "Termination criteria are conditions that can be checked during and after execution, not facts held in human memory.", "Declaration:ActionType stop_conditions|Observation:Check continuously during execution|Violation:Stop effects and transition to recovery|Outcome:Record reason and time in the audit", docs.security, "evidence"),
  topic("CURRENT", "Recovery is defined by contract before execution", "Each action declares rollback, state restoration, or safe state-forward recovery. Irreversible actions require multi-person approval and the best available recovery plan.", "pr_revert and scripted:Code- or script-based rollback|snapshot_restore and pitr:State restoration|state_forward_only:Advance to a safe next state instead of the prior state|irreversible:Separate irreversible marker and human quorum", docs.security, "matrix"),
  topic("CURRENT", "Blast radius can be calculated from the graph", "Traverse contains and reverse depends_on relationships to bounded depth to identify the actual affected targets.", "Target:Exact resource and revision|Traversal:Graph with depth and result limits|State:Current load and conflicts|Gate:Maximum affected resource count", docs.security, "flow"),
  topic("CURRENT", "Dry-run evidence is bound to the current plan revision", "Do not reuse predictions produced for another plan or stale state.", "Input:Plan digest and target revision|Prediction:Expected changes and protected-objective impact|Failure:Hold incomplete or stale evidence|Pass:Successful preflight validation evidence", docs.security, "evidence"),
  topic("CURRENT", "Duplicate suppression and target locking prevent double execution", "Redelivery and concurrent runs must not apply the same effect twice to one resource.", "Key:Stable idempotency identifier|Lock:Logical target and owner fence|Restart:Conservatively retain execution-unknown state|Replay:Duplicate produces no change", docs.security, "flow"),
  topic("CURRENT", "Audit spans intent through outcome", "Store append-only audit intent before side effects, then close it with execution evidence, independent effect, recovery, or the final outcome.", "Before execution:Audit intent and plan|During execution:Attempt and provider evidence|Observation:Independent effect state|Closure:Success, failure, recovery, or hold", docs.security, "timeline"),
  topic("CURRENT", "The risk gate never raises authority", "Select the lowest result among the first-match risk table and the ActionType tier, blast-radius, role, and environment ceilings.", "Autonomous execution:enforce_auto|Human approval:enforce_hil|Shadow mode:shadow_only|Block:deny", docs.execution, "matrix"),
  topic("IMPLEMENTED", "The emergency stop works without executor identity", "When activated, it lowers every change execution to the shadow-mode ceiling. Approval requests remain visible, but no change executes until the stop is cleared, and a failed state read is treated as active.", "Activation:Authenticated operator and revision check|Authority:Change without executor identity|Effect:Limit all changes to shadow_only|Failure:Keep blocking when state cannot be read", docs.security, "tree"),
  topic("CURRENT", "New capabilities begin in shadow mode", "Only actions validated with sufficient samples, contract compliance, and every safety metric on the same scenarios and revision receive a separate promotion review.", "Observe:No state change|Measure:Success and safety metrics|Block:Zero wrong targets, unauthorized executions, policy leaks, or unverified success claims|Promote:Independent review and explicit registry change", [docs.metrics, docs.security], "timeline"),
  topic("IN_PROGRESS", "A3-E cannot yet grant live execution authority", "The evaluator and store are implemented in shadow mode but are not connected to decision and execution paths. Live use requires a full pre-effect authority guarantee and operational observation evidence.", "Implemented:Evaluator, store, snapshots, and blocker|Not connected:Risk gate and executor|Open design:Full pre-effect lock or lease|Open evidence:Live operational observation cohort and promotion review", [docs.standingAuthority, docs.security], "comparison"),
  topic("IN_PROGRESS", "Production privacy exit criteria are in progress", "Shared data minimization, de-identification, and retention contracts are implemented. Deployment-specific data ownership, retention schedules, model-provider terms, privacy impact assessment, and operational evidence remain.", "Implemented:Pre-model minimization evidence and primary de-identification|Deployment responsibility:Data and privacy owners and retention values|Approval required:Provider terms, region, and impact assessment|Operational evidence:Deletion, legal hold, access review, and audit anchor", docs.dataGovernance, "evidence"),
  topic("TARGET", "Responsible AI review covers the full decision chain, not only the model", "Formalized intent, evidence checks, verifier, risk, approval, and effect verification must all close together.", "Input:Scope limitation and de-identification|Decision:Deterministic execution eligibility|Outcome:Independent observation", docs.constitution, "flow"),
  topic("NEXT", "Assign owners for open exit criteria at the next security review", "Keep A3-E, privacy, common execution end-to-end validation, and live operational drills as independent approval items.", "Security:A3-E and identity drills|Privacy:Production exit criteria|Runtime:End-to-end safeguards validation", docs.security, "responsibility"),
]);

const pilotProduction = buildDeck("pilot-production", "PILOT TO PRODUCTION", [
  topic("PLAYBOOK", "Move one decision type from shadow mode to enforce mode", "Deployment owners manage measurable exit criteria and reversible scope, not feature count.", "Start:Clearly scoped execution charter|Learn:Shadow-mode evidence|Advance:Independent promotion review", docs.security),
  topic("PHASE 0", "Fix the pilot execution charter on one page", "Agree on targets, goals, baseline, owners, authority ceiling, and effect sources before starting.", "Target:Exact resource set|Value:Baseline metric|Safety:ActionType contract", docs.operator, "cards"),
  topic("PHASE 0", "Measure the current human-led operation as the baseline", "Compare current operations with FDAI results using the same scenarios, period, samples, and revision. Use at least 30 samples and a confidence interval in each cohort.", "Cost:Cost per incident, change, or optimization|Autonomy:Automated resolution rate|Speed:Median and p90 MTTR and change lead time|Load:Human touchpoints per 100 events|Safety:Four violations that must be exactly 0", docs.metrics, "comparison"),
  topic("PHASE 0", "Register authoritative evidence sources", "Synthetic data can test behavior but cannot prove live operational readiness.", "Inventory:Target IDs|Telemetry:Effect metrics|Audit:Decision lineage", docs.constitution, "evidence"),
  topic("PHASE 0", "Connect service relationships and operating objectives", "Selecting only a Resource cannot establish business impact or higher-level constraints.", "Resource:runs_on target|Service:Owner and criticality|Objective:SLO, recovery, and cost", docs.ontology, "flow"),
  topic("PHASE 0", "Review the ActionType safety contract", "Review stop conditions, tested recovery, blast radius, dry run, target lock, duplicate suppression, and two-phase audit before execution code.", "Preconditions:Stop, recovery, scope, and dry run|Execution:Target lock and duplicate suppression|Audit:Record intent first and close the outcome", docs.security, "tree"),
  topic("PHASE 0", "Separate executors from approvers", "Do not combine human identity and workload identity, even in the pilot environment.", "Approver:Authenticated person|Executor:Non-interactive identity|Auditor:Independent evidence", docs.security, "responsibility"),
  topic("GATE 0", "Keep current operations when readiness is insufficient", "Start shadow mode only after evidence, owners, a measurement baseline, and a recovery path are ready. IaC or GitOps is recommended for reproducible changes.", "Proceed:Required evidence and accountability are complete|Hold:Bounded remediation is defined|Stop:Unsafe or not measurable|Recommended:IaC or GitOps baseline", [docs.constitution, docs.deployment], "tree"),
  topic("PHASE 1", "Shadow mode decides without making live changes", "A new action only decides and records, then compares its result with the actual human outcome.", "Input:Live event|Decision:Formal verdict|State change:None", docs.security, "flow"),
  topic("PHASE 1", "Freeze six scenarios that cover success and failure", "Success cases alone are insufficient. Pin the input set and expected results to a revision and replay them under the same conditions.", "Successful completion:Path closes through expected effect|Hold or block:unknown or deny|Goal conflict:Cross-domain tradeoff|Partial failure and recovery:Compensation and recovery_incomplete|A3-E applicability:Scenario or explicit non-applicability|Deterministic replay:Same inputs and results", docs.constitution, "comparison"),
  topic("PHASE 1", "Increase T0 coverage first", "Resolve repeatable decisions with policy and rules, and limit T2 to a small set of ambiguous cases.", "T0:Deterministic rules|T1:Verified case reuse|T2:Evidence-grounded residual ambiguity", docs.constitution, "flow"),
  topic("PHASE 1", "Separate hold reasons from learning data", "Do not combine missing evidence, stale information, conflicts, and lack of authority into one model failure.", "Evidence:Missing or stale|Policy:Denied or requires approval|System:Dependency unavailable", docs.constitution, "matrix"),
  topic("PHASE 1", "Measure the quality of the human-review queue", "Separate required approvals from unnecessary escalations to reduce excessive approval notifications.", "Required:Risk policy|Residual:Ambiguity|Avoidable:Evidence-recovery gap", docs.pantheon, "matrix"),
  topic("PHASE 1", "Preserve shadow-mode audits as complete traces", "Events, tiers, verdicts, action versions, and evidence as-of times must be replayable.", "Event:Correlation ID|Verdict:Selected authority ceiling|Evidence:Evidence by source", docs.execution, "evidence"),
  topic("GATE 1", "Four safety metrics must be exactly 0", "Promotion is blocked by even one wrong target, unauthorized execution, policy-violation leak, or success claim without independent verification, regardless of average contract compliance.", "0:Wrong target or stale-revision execution|0:Execution with unregistered authority, identity, or blast radius|0:Policy violation leaking into enforce mode|0:Success claim without independent effect confirmation", [docs.constitution, docs.metrics], "numbers"),
  topic("PHASE 2", "Validate a dry run bound to the current plan", "Practice outside production is useful, but a production change still requires a dry run bound to the current target and plan digest immediately before execution.", "Plan:Immutable digest and target revision|Non-production practice:Validate the mechanical path|Before execution:Validate again with current evidence|Outcome:Prediction evidence without side effects", docs.security, "evidence"),
  topic("PHASE 2", "Exercise the declared recovery outcome separately", "Happy-path success and recoverability are different evidence. Recovery may restore prior state, advance to a safe next state, or provide best-effort recovery for an irreversible action.", "Trigger:Controlled failure|Contract:Rollback, restoration, or state-forward recovery|Irreversible:Human quorum and best available recovery|Verify:Declared terminal state and effect", docs.security, "timeline"),
  topic("PHASE 2", "Validate blast-radius calculation against the live graph", "Do not rely on a fixed classification; compare bounded dependencies with the maximum affected resource count.", "Start:Exact target|Graph:contains and depends_on|Limit:Declared ceiling", docs.security, "flow"),
  topic("PHASE 2", "Deliberately replay duplicate delivery", "At-least-once events and retries must not produce a second change.", "First attempt:Reserve key|Retry:Detect duplicate|Outcome:One effect", docs.constitution, "timeline"),
  topic("PHASE 2", "Exercise emergency-stop and degraded paths", "Verify that a dependency failure or operator stop lowers authority to shadow.", "Normal:Standard ceiling|Degraded:Shadow only|Emergency stop:Immediate isolation", docs.execution, "tree"),
  topic("GATE 2", "Prove both safety drills and operational controls", "Do not begin enforce-mode review if any of the seven safeguards, independent effect observation, identity recertification, emergency stop, break-glass access, or audit anchors is missing.", "Execution contract:Seven safeguards and independent effect closure|Identity:Least privilege and recertification|Emergency control:Emergency-stop and break-glass drills|Audit:Exact revision and anchor evidence", docs.security, "matrix"),
  topic("PHASE 3", "Request promotion per capability", "An environment or enabled value does not automatically change ActionType authority.", "Capability:Exact action version|Mode:Shadow to enforce|Registry:Reviewed state", docs.constitution, "evidence"),
  topic("PHASE 3", "Recheck the RiskGate result immediately before delivery", "Even after promotion, current impact, role, environment, and system state can lower autonomy.", "Fixed condition:ActionType ceiling|Dynamic condition:Current checks and state|Final:Lowest authority", docs.execution, "flow"),
  topic("PHASE 3", "Limit the first enforce run to a small batch", "Permit state changes only within a small blast radius and clear stop conditions.", "Scope:One limited target group|Rate:Explicit ceiling|Stop:Machine-evaluable", docs.security, "cards"),
  topic("PHASE 3", "Validate the human-approval path in practice", "Approval is bound to the exact action, target, plan revision, and idempotency key. Timeout or insufficient quorum becomes a no-execution terminal state.", "Request:Specific action and blast radius|Approval:Authenticated principal separate from executor|Quorum:Count required by risk policy|Timeout:No change and closed audit", docs.security, "timeline"),
  topic("PHASE 3", "Wait through the effect-observation window after execution responds", "Completion requires an authoritative independent observer to confirm the expected range after the provider response.", "Delivery:Command accepted|Observation:Independent source|Closure:ObservedOutcome", docs.constitution, "evidence"),
  topic("GATE 3", "Apply strict exit criteria to the first enforce run", "Proceed to the next batch only after safe execution, confirmed expected effect, and a closed audit chain.", "Execution:Safeguards passed|Effect:Metric is within range|Audit:Terminal closure", docs.ontology, "tree"),
  topic("PHASE 4", "Review performance and safety together in every operating cycle", "Compare cost, automated resolution, MTTR, change lead time, and human touchpoints in the same cohort, together with the four zero criteria and recovery and effect metrics.", "Performance:Five success metrics and confidence intervals|Safety:Four exact-zero criteria|Operations:Recovery, effect verification, and human review|Evidence:Frozen scenarios and exact revision", docs.metrics, "matrix"),
  topic("PHASE 4", "Quality degradation triggers automatic demotion", "Return to shadow mode and analyze the cause instead of patching while retaining authority.", "Detect:Exit criteria degrade|Demote:Immediate shadow mode|Recover:Promote again after new evidence", docs.security, "timeline"),
  topic("PHASE 4", "New rules begin as inactive candidates", "Pilot learning does not immediately change the catalog or authority.", "Norns (learning-candidate proposer) agent:Propose candidate|Mimir (rule reviewer) agent:Review rule|Registry:Separate promotion", docs.pantheon, "responsibility"),
  topic("PHASE 4", "Operational handover requires owners and procedures", "Approvals, recovery, alerts, and evidence sources must remain operable after the deployment team leaves.", "Service owner:Operational outcome|Platform owner:Runtime|Security owner:Authority", docs.pantheon, "responsibility"),
  topic("IMPLEMENTED", "Operator Workflow initiation is proposal-only", "POST /workflows/run accepts only idempotent, revision-bound shadow-mode requests and rejects mode=enforce.", "Requester:Shadow-mode proposal|Operator:Durable outbox|Event bus:Independent service delivery|Core:Standard authority path", docs.operator, "flow"),
  topic("IN_PROGRESS", "Operational evidence for the Workflow enforce path remains open", "The Core step executor has a controlled path, but preserved runtime evidence has not proven local and deployed paths through owner approval and every safeguard.", "Current:Core step-executor code|Open:Owner approval and end-to-end safeguards|Open:Local and deployed parity evidence|Boundary:Operator API is proposal-only", docs.operator, "evidence"),
  topic("IMPLEMENTED", "Protected deployments use exact artifacts", "Signed images, SBOMs, attestations, and sealed plans constrain changes to identity, commands, and other services' state.", "Artifact:Signed and pinned image digest|Plan:Only permitted differences|Apply:Health checks after migration|Recovery:Retain the prior healthy revision", docs.deployment, "timeline"),
  topic("NOT_STARTED", "Automated progressive delivery remains a target", "Automated dev, staging, and prod promotion, traffic-split canaries, SLO-based rollback, and Console blue-green deployment are not implemented.", "Current:Protected plan and apply flow|Target:Promote the same artifact across environments|Target:Canary and SLO-based rollback|Target:Console blue-green deployment", docs.deployment, "matrix"),
  topic("IN_PROGRESS", "Production readiness combines implemented gates with operational evidence", "Plan gates for private networking, durability, signed images, monitoring, and cost inputs are implemented. Production apply and recovery evidence for the exact revision remains.", "Implemented:Production plan blockers|In progress:Protected plan and apply evidence|Security:Identity and safeguards on every execution path|Operations:On-call, DR, and recovery drills", docs.hardening, "responsibility"),
  topic("PROPOSAL", "Review the cost ceiling before scaling", "Monitoring and a monthly budget are required inputs to a production plan.", "Capacity:Resource characteristics|Monitoring:Alert targets|Cost:Budget and owner", docs.hardening, "matrix"),
  topic("DECISION", "Production transition has one of four outcomes", "Choose promotion, continued shadow mode, reduced scope, or stop, with evidence.", "Promote:All gates and operational evidence complete|Continue shadow:More evidence required|Reduce scope:Redesign for smaller targets and authority|Stop:Unsafe or no value", docs.security, "tree"),
  topic("HANDOVER", "Operations receives evidence for the exact revision", "Handover includes deployment, identity, safeguards, effects, recovery, and DR evidence, not only code links.", "Build:Artifact provenance and supply-chain attestations|Operations:Authority, alerts, audit, and budget|Recovery:RPO, RTO, prior revision, and failover and failback drills|Effect:Independent observation and unresolved conflicts", docs.deployment, "evidence"),
  topic("NEXT", "The next use case reuses validated boundaries", "Choose an adjacent decision within the existing ontology, observers, and approval path instead of expanding authority.", "Reuse:Types and mappings|Reuse:Evidence sources|Reuse:Safe operating procedures", docs.ontologyPlatform, "flow"),
]);

const sreIncidentResponse = buildSreIncidentResponseDeck({ sourceLabel, statusLabel });
const ontologyFoundationSlides = buildOntologyFoundationDeck();

const aiOperatingModel = buildDeck("ai-operating-model", "AI OPERATING MODEL", [
  topic("OPERATE", "Connect accountability with operating cadence", "Leaders operate 15 fixed roles, platform accountability, governance, FinOps, and LLMOps decisions as one system.", "Accountability:One accountable owner|Governance:Separated authority|Operating cadence:Measured evidence|Outcome:Independent observation and audit", docs.pantheon),
  topic("CURRENT", "The 15 agent roles are fixed", "Distributions and downstream implementations supply only bindings; they do not add or rename agents.", "5:Governance, memory, and learning roles|7:Collection, observation, decision, and execution roles|3:Cost, capacity, and resilience specialists|15:Fixed total agents", docs.pantheon, "numbers"),
  topic("CURRENT", "Only the single owning agent publishes an authoritative object", "Many subscribers may read the same projection, but it has one authoritative publisher, and every state change crosses a schema-validated event bus.", "Owner:One publishing agent per object|Consumers:Multiple independent subscribers|Transport:Events with schema and lineage|Recovery:At-least-once delivery and duplicate-safe replay", docs.pantheon, "matrix"),
  topic("CURRENT", "Odin arbitrates only eligible goal tradeoffs", "Options that violate safety or policy are excluded before portfolio scoring.", "Forseti:Publish arbitration request|Odin:Rank eligible options|Saga:Audit decision", docs.pantheon, "responsibility"),
  topic("CURRENT", "Maintain the boundary between Forseti and Thor", "The decision-maker does not execute, and the executor does not create a new verdict.", "Forseti:Evidence-grounded decision|Thor:Deliver eligible action|Vidar:Recover from failure", docs.pantheon, "responsibility"),
  topic("CURRENT", "Var turns human approval decisions into verified records", "Var handles approval requests, denials, quorum, and expiry but never executes an action.", "Human:Authenticated decision for the current request|Var:Approval record with validated scope and expiry|Thor:Recheck authority before effect|Saga:Audit approval lineage", docs.pantheon, "flow"),
  topic("CURRENT", "Saga owns the append-only audit ledger", "Saga preserves every terminal path and shadow-mode outcome with a correlation ID.", "Intent:Record before effect|Decision:Exit criteria and authority|Execution:Attempt and provider evidence|Outcome:Effect, recovery, and terminal closure", docs.pantheon, "evidence"),
  topic("CURRENT", "Rule learning and execution promotion follow separate paths", "Norns creates inactive rule candidates, Mimir reviews them independently, and catalog PRs govern them. ActionType and Workflow execution promotion uses separate shadow evidence and registries.", "Norns:Inactive candidate with evidence|Mimir:Review rule quality and provenance|Catalog:Merge reviewed PR|Execution promotion:Separate evidence and authority registry", docs.pantheon, "responsibility"),
  topic("CURRENT", "Bragi owns the conversation lifecycle and formalized intent", "Bragi manages conversations, turns, user preferences, handovers, and retrospective reviews, and converts natural language into formalized tool requests. It does not decide, approve, or execute.", "Operator:Goal, scope, and constraints|Bragi:Formalize conversation and intent|Read port:Evidence-grounded explanation|Authority port:Forward through the standard agent path", docs.pantheon, "flow"),
  topic("CURRENT", "Njord, Freyr, and Loki create domain candidates", "Cost, capacity, and resilience expertise enters the same control boundary, not a separate superior agent.", "Njord:Cost proposal|Freyr:Capacity forecast|Loki:Chaos and resilience", docs.pantheon, "cards"),
  topic("PROPOSAL", "A goal-governance council manages priorities and exceptions", "This is a recommended operating model. The council cannot change constitutional priorities; it decides tradeoffs among eligible goals, budgets, and exception expiry.", "Input:SLO, risk, cost, and unresolved conflicts|Decision:Priority among eligible options|Authority:Never above policy and safety boundaries|Record:Decision, owner, expiry, and review", docs.constitution, "timeline"),
  topic("GOVERN", "Architecture review operates as a continuous process", "Assess structural conformance, operational readiness, and execution progress separately rather than combining them into one state.", "Structure:Specification and contract validity|Readiness:Evidence completeness and owner|Execution:Process stage and blocker|Change:Re-enter through an ActionType path", docs.operator, "matrix"),
  topic("PROPOSAL", "Promotion review separates feature use from execution authority", "The organization's review body should assess availability, enablement, environment, execution mode, and deployment evidence independently. Each deployment defines its body name and quorum.", "Available:Prerequisites complete|Enabled:Operator choice|Execution mode:Shadow or enforce|Evidence:Frozen scenarios and exact revision", [docs.constitution, docs.runtimeAxes], "tree"),
  topic("PROPOSAL", "Set the security review cadence to deployment risk", "Action allowlists, role assignments, access recertification, and break-glass access require recurring review, but monthly or quarterly frequency is deployment policy, not a fixed product fact.", "Recurring:Review effective access and allowlists|On change:Recertify identity and roles|On use:Review break-glass access afterward|Evidence:Owner and next review date", docs.security, "timeline"),
  topic("GOVERN", "Data governance owns evidence quality", "Treat source identity, purpose, freshness, observation scope, and de-identification as production exit criteria.", "Source:Authenticated|Quality:Fresh and complete|Privacy:Minimized and de-identified", docs.dataGovernance, "matrix"),
  topic("FINOPS", "FinOps covers model and infrastructure costs together", "Connect deterministic coverage and T2 call cost to verified operational outcomes.", "Runtime:Platform spend|Inference:T2 rate and unit price|Outcome:Verified savings", docs.execution, "matrix"),
  topic("FINOPS", "Cost-increasing actions pass separate criteria", "Do not execute horizontal scaling automatically without a monthly cost estimate or when it exceeds the threshold.", "Estimate:Monthly cost impact|Gate:Risk table|Verdict:Approve or hold", docs.execution, "tree"),
  topic("FINOPS", "Budget is an input to the production deployment plan", "Production hardening does not pass without a monthly budget and alert recipients.", "Budget:Amount and owner|Alert:Recipient|Review:Variance and follow-up action", docs.hardening, "evidence"),
  topic("LLMOPS", "LLMOps limits T2 to residual ambiguity", "Manage not only model performance, but also the rate T0 and T1 cannot decide, multi-model disagreement, verifier outcomes, cost, and latency.", "Demand:Not resolved by T0 and T1|Generation:Two different models|Verification:Check evidence, contract, and policy|Boundary:T2 does not create execution authority", docs.constitution, "flow"),
  topic("LLMOPS", "Record prompt and model versions for replay", "Decision context pins the evidence as-of time and exact algorithm or model version.", "Input:De-identified context|Model:Exact version|Output:Verified proposal", docs.constitution, "evidence"),
  topic("LLMOPS", "Route model disagreement to human review", "One model's confidence cannot replace confirmation by another model and the verifier.", "Generation:Two different models|Comparison:Check agreement|Escalation:Unresolved conflict", docs.constitution, "tree"),
  topic("LLMOPS", "Models do not grant execution eligibility", "A deterministic verifier, policy, and dry run decide whether an action may execute.", "LLM:Proposal|Verifier:Validate contract|RiskGate:Authority ceiling", docs.execution, "flow"),
  topic("PROPOSAL", "The daily operating cycle reviews exceptions and system state", "In the recommended operating calendar, people focus on holds, evidence conflicts, degradation, and recovery state rather than every event.", "Exceptions:Holds and expired approvals|Dependencies:Audit, recovery, and observation state|Owner:Next action and due date|Evidence:Trace and exact revision", docs.pantheon, "cards"),
  topic("PROPOSAL", "The weekly operating cycle reviews outcomes and human-review load", "Compare contract compliance, human approvals, recovery, and independent effects against the same scenarios.", "Quality:Contract-compliant terminal outcomes|Load:Human touchpoints per 100 events|Recovery:Failures and completion time|Outcome:Success verified by independent observation", docs.metrics, "matrix"),
  topic("PROPOSAL", "The monthly operating cycle reviews promotion and cost", "Review observation duration, safety metrics, inference spend, and platform budget as independent criteria.", "Promotion:Samples, duration, and confidence interval|LLMOps:Models, verifier, and T2 rate|FinOps:Cost per work unit and budget variance|Decision:Retain, demote, or review", [docs.metrics, docs.security], "timeline"),
  topic("PROPOSAL", "The quarterly operating cycle revalidates authority and resilience", "The recommended cycle records role recertification, recovery, emergency-stop, and DR drills against the exact revision. Deployment risk policy sets the actual frequency.", "Identity:Least privilege and effective access|Recovery:Exercise the declared contract|Control:Emergency stop and break-glass access|DR:RPO, RTO, failover, and failback", docs.security, "timeline"),
  topic("METRIC", "Prioritize control outcomes over per-agent KPIs", "Measure SLO restoration, recurrence prevention, change safety, and realized savings rather than individual activity volume.", "SRE:Recovery and recurrence prevention|Change:Verified safe outcome|FinOps:Realized savings", docs.metrics, "cards"),
  topic("METRIC", "Evaluate operating performance with five metrics and safety criteria", "Do not claim improvement until baseline and treatment cohorts are measured with the same scenarios and revision. Metric aggregation is implemented, but live operational comparison evidence is not yet complete.", "5:Cost per work unit, automated resolution, MTTR, change lead time, and human touchpoints|4:Core safety violations that must be exactly 0|30+:Minimum samples in each cohort|1:Frozen scenario set and exact revision", docs.metrics, "numbers"),
  topic("METRIC", "Do not reduce the human-approval rate indiscriminately", "Distinguish policy-required approval from unnecessary escalation.", "Required:Risk and authority|Residual:Ambiguity|Avoidable:Evidence gap", docs.pantheon, "tree"),
  topic("METRIC", "Eliminate success without effect", "Close outcome KPIs with independent observation, not delivery success.", "Attempt:Executor receipt|Observation:Authoritative source|Assessment:Compare expected with actual", docs.ontology, "evidence"),
  topic("CURRENT", "Local and deployed environments use the same contracts", "Only providers and credentials differ; catalogs, gates, and Process events do not change arbitrarily.", "Same:Rules and promotion|Same:Risk and approval|Different:Adapters and identity", docs.operator, "matrix"),
  topic("IN_PROGRESS", "Workflow enforce parity remains an operational item", "The proposal-only Operator boundary and durable outbox are implemented, but local and deployed runtime evidence must prove owner approval and every safeguard.", "Current:Durable proposal connection|Open:End-to-end evidence for enforce path|Open:Environment parity|Owners:Platform and governance", docs.operator, "responsibility"),
  topic("GAP", "Do not mark production privacy evidence complete", "Shared de-identification implementation and deployment privacy approval are different states.", "Implemented:Minimization path|In progress:Production gate|Open:Preserved evidence", docs.security, "matrix"),
  topic("NOT_STARTED", "Progressive delivery is a roadmap item", "Automated artifact promotion and canary-based rollback are targets, not current operating features.", "Current:Protected Workflow|Target:Automated promotion|Target:SLO-based rollback", docs.deployment, "timeline"),
  topic("PROPOSAL", "RACI connects the fixed Pantheon with accountable people", "Assign accountable owners for policy, service, security, and platform without changing agent roles.", "Service owner:Business outcome|Platform owner:Runtime SLO|Security owner:Authority policy", docs.pantheon, "responsibility"),
  topic("PROPOSAL", "Operating reviews begin with evidence links", "Review exact traces, releases, and evidence rather than slide colors or verbal reports.", "Trace:Correlation ID|Release:Digest|Evidence:Source and as-of time", docs.ontologyPlatform, "evidence"),
  topic("PROPOSAL", "Every exception has an expiry and review", "Policy exceptions and break-glass access are time-bounded and never become permanent authority automatically.", "Scope:Limited targets|Time:Explicit expiry|Closure:Post-use review audit", docs.security, "timeline"),
  topic("PROPOSAL", "Work handover transfers operational evidence, not authority", "A new owner receives procedures, decision lineage, and recovery evidence; authority follows a separate grant process.", "Knowledge:Procedures and cases|Evidence:Traces and outcomes|Authority:Separate recertification", docs.pantheon, "responsibility"),
  topic("DECISION", "Operating-model approval includes open items", "Specify owners, deadlines, and exit criteria between CURRENT and TARGET.", "Accept:Implemented boundaries|Track:Evidence in progress|Reject:Unsupported claims", docs.constitution, "tree"),
  topic("NEXT", "Adopt the four operating-calendar cycles as deployment policy", "Use daily operations, weekly outcomes, monthly promotion and cost, and quarterly authority and recovery drills as a starting point for assigning owners and actual frequency.", "Daily:Exceptions and dependencies|Weekly:Outcomes and human touchpoints|Monthly:Promotion and FinOps|Quarterly:Identity, recovery, and DR", docs.security, "timeline"),
]);

const enterpriseScaleRoadmap = buildDeck("enterprise-scale-roadmap", "ENTERPRISE SCALE ROADMAP", [
  topic("ROADMAP", "Scale through evidence, not feature count", "Leaders scale one proven decision type through dependencies and exit criteria.", "Sequence:Build the foundation first|Gate:Evidence before authority|Scale:Reuse before expanding scope", docs.constitution),
  topic("PRINCIPLE", "Scale does not raise autonomy automatically", "Execution venue, deployment environment, evidence, execution mode, identity, and distribution are independent axes. A change on one axis does not raise authority on another.", "Execution venue:Local or deployed|Deployment environment:Development, staging, or production|Evidence:Authoritative or test data|Execution mode:Shadow or enforce|Identity and authority:Separate human and executor|Distribution:Upstream or downstream", docs.runtimeAxes, "layers"),
  topic("PRINCIPLE", "Separate current Azure implementation from provider targets", "The current scale plan uses Azure evidence; non-Azure providers remain a contract extension possibility only.", "Current:Azure adapters|Target:Provider-neutral contracts|Not implemented:Non-Azure providers", docs.deployment, "tree"),
  topic("PRINCIPLE", "One control plane supports multiple domains", "Under the SRE operating model, expand Resilience, Change Safety, and Cost Governance within the same safety boundary.", "SRE:Overall operating model|Domains:Initial three areas|ARB:Cross-domain governance", docs.constitution, "cards"),
  topic("WAVE 0", "Approve enterprise goal priorities", "First fix a common order that never places cost ahead of safety and reliability.", "1:Security and data integrity|2:SLO and change safety|3:Efficiency and cost", docs.constitution, "timeline"),
  topic("WAVE 0", "Create the decision-type inventory", "Instead of team tool inventories, collect who makes which decision from what evidence.", "Decision:Repeatable choice|Evidence:Authoritative source|Owner:Accountable person", docs.ontology, "cards"),
  topic("WAVE 0", "Do not collapse independent state axes into one enum", "Verdict, action lifecycle, execution state, recovery state, and effect observation are separate axes. Present plain English in the UI while preserving contract values in audit records.", "Verdict:Autonomous execution, human approval, hold, or deny|Lifecycle:Shadow or enforce mode|Execution:Pending, running, complete, failed, or execution unknown|Recovery:Not required, running, complete, or incomplete|Effect:Unobserved, confirmed, mismatched, or conflicting", [docs.execution, docs.runtimeAxes], "comparison"),
  topic("GATE 0", "Do not begin without sponsors and accountable owners", "Document accountability for value and risk, data, and platform outcomes.", "Sponsor:Priority and budget|Service owner:Operational outcome|Platform owner:Runtime", docs.pantheon, "responsibility"),
  topic("WAVE 1", "Deploy the operating-ontology release foundation", "Use immutable ontology releases and exact digests to prevent teams from interpreting the same concept differently.", "Catalog:Immutable release|Runtime:Exact reference|Compatibility:Migration verdict", docs.ontologyPlatform, "evidence"),
  topic("WAVE 1", "Populate the BusinessService-to-Workload spine", "Start with exact mappings for priority services instead of classifying every resource at once.", "Service:Criticality and owner|Workload:Deployable unit|Resource:Observed placement", docs.ontology, "flow"),
  topic("WAVE 1", "Make the unclassified-resource backlog visible", "Manage unknown_service and unclassified-resource as mapping work instead of hiding them.", "Unknown:Keep visible|Owner:Classification steward|Closure:Reviewed mapping", docs.ontology, "timeline"),
  topic("WAVE 1", "Standardize the evidence-source registry", "Make source identity, purpose, scope, freshness, completeness, and provenance shared evidence.", "Identity:Authenticated source|Time:Event time and recorded time|Scope:Completeness check", docs.constitution, "matrix"),
  topic("WAVE 1", "Apply the data-minimization boundary", "Preserve pointers and digests instead of source records, and retain de-identification details.", "Collect:Minimum fields|Store:Pointers and digests|Display:Role-based de-identification", docs.security, "flow"),
  topic("GATE 1", "Confirm five capabilities for formalized operational facts", "The system must answer each level from exact identity through evidence health before advancing to the next wave.", "C1 Identity:Exact ID and access control|C2 Relationship:Typed, directed links|C3 Dependencies:Traverse upstream and downstream impact|C4 Blast radius:Calculation with depth and result limits|C5 Evidence health:Freshness, completeness, conflict, and provenance", docs.ontologyPlatform, "comparison"),
  topic("WAVE 2", "Activate the fixed 15-agent composition", "Expand scope through configuration and provider bindings instead of creating new agents for each team.", "Fixed:Roles and object owners|Configuration:Scope and policy|Adapter:Provider implementation", docs.pantheon, "cards"),
  topic("WAVE 2", "Deploy topic ownership and schema gates", "Single writers, multiple readers, and duplicate-safe replay under at-least-once delivery prevent authority conflicts at scale.", "Publisher:One accountable owner|Transport:Validate schema and lineage|Consumer:Independent retries and backpressure|Replay:Safe under duplicates and reordering", docs.pantheon, "flow"),
  topic("WAVE 2", "Separate identity by service and domain", "Console, Core, collection, executor, and domain deployment principals do not share identities.", "Service:Distinct workload identities|Domain:Change, Resilience, and FinOps|Human:Separate approval", docs.security, "matrix"),
  topic("WAVE 2", "Connect the global emergency stop to operations", "Before enterprise expansion, practice stopping without executor identity and continuing through audit, callout, and expiry.", "Activation:Owner or break-glass access|Effect:Shadow-mode ceiling|Evidence:Drill evidence", docs.security, "timeline"),
  topic("GATE 2", "Validate required-dependency failures by role", "Loss of Saga or Vidar blocks every state change. Loss of an observer or Var blocks a change only when that action requires the dependency.", "Audit unavailable:No state changes|Recovery unavailable:No state changes|Observer unavailable:No success claim or subsequent change for that effect|Approval path unavailable:No execution only for actions requiring human approval", [docs.constitution, docs.pantheon], "tree"),
  topic("WAVE 3", "Harden the production foundation before the first enforce run", "Make private networking, durable PostgreSQL, monitoring, budget, and trusted images deployment exit criteria.", "Network:Private data services|Durability:HA, backup, RPO, and RTO|Supply chain:SBOM, signature, and pinned digest|Operations:Alerts, recipients, and budget", docs.hardening, "cards"),
  topic("WAVE 3", "Maintain per-service state ownership", "Per-service backend keys and isolation evidence limit the blast radius of large deployments.", "State:Backend key per service|Plan:Block changes to other services' state|Evidence:Digest and lineage|Recovery:Prior healthy revision per service", docs.deployment, "evidence"),
  topic("WAVE 3", "Run migrations and initial configuration in sequence", "After the Operator schema migration, write immutable Rule and ontology reference projections, then check service readiness.", "First:Schema migration|Next:Catalog initialization|Last:Readiness and health checks", docs.deployment, "timeline"),
  topic("WAVE 3", "Protect the recovery baseline", "Capture the healthy active revision and retain one inactive revision for recovery.", "Capture:Healthy active revision|Retain:One inactive revision|Recover:Protected Workflow|Verify:Failover and failback outcomes", docs.deployment, "evidence"),
  topic("GATE 3", "Preserve protected-apply evidence", "Do not claim production validation from code and plan blockers alone. Preserve plan, apply, health, and recovery boundaries for the exact revision.", "Plan:Exact revision and 0 unrelated deletions|Apply:Signed artifacts and migration|Observation:Service health and independent effect|Recovery:Prior revision, RPO, and RTO", docs.hardening, "tree"),
  topic("WAVE 4", "Begin the first domain with one decision type", "Choose the scope best prepared for value, repeatability, evidence, and tested recovery.", "Scope:One target type|Mode:Shadow|Measurement:Baseline and effect|Authority:No change until separate promotion", docs.security, "cards"),
  topic("WAVE 4", "Freeze a six-dimensional scenario set", "Use the same event set across success, hold, goal conflict, partial failure, A3-E applicability, and replay, not only success cases.", "Success:Full path closed through expected effect|Negative:Unknown or deny|Conflict:Cross-domain goal tradeoff|Recovery:Partial failure and compensation|A3-E:Scenario or explicit non-applicability|Replay:Deterministic result from the same input", docs.constitution, "comparison"),
  topic("WAVE 3", "Collect the observation period and review outcomes", "Close decision quality and policy-leak assessment with actual reviewer outcomes.", "Observation:No state change|Review:Separate human|Evidence:Stable observation ID", docs.pantheon, "timeline"),
  topic("WAVE 4", "Complete drills for all seven safeguards", "Validate stop, tested recovery, blast radius, dry run, target lock, duplicate suppression, and two-phase audit against the exact revision.", "7:Required safeguards|1:Exact ActionType and revision|0:Duplicate effects and authority escapes|Separate:Independent effect observation and review", docs.security, "numbers"),
  topic("GATE 4", "The first promotion receives independent review", "The pilot team cannot grant enforce authority from its own results alone.", "Deployment:Frozen scenarios and exact revision|Security:Review authority and safety metrics|Governance:Change promotion registry|Operations:Automatic demotion and emergency stop ready", docs.security, "responsibility"),
  topic("WAVE 5", "Reuse the validated foundation for adjacent decision types", "Scale through the same service mappings, evidence sources, approval paths, and observers.", "Reuse:Ontology spine|Reuse:Source evidence|Reuse:Safe operating procedures|Revalidate:New targets and blast radius", docs.ontology, "flow"),
  topic("WAVE 5", "Close the SRE operating path end to end", "Create scenario evidence from detection through tested recovery and recurrence closure.", "Detection:SLO or Incident|Recovery:Controlled action|Effect:Independent observation|Closure:Recurrence and protected-objective check", docs.constitution, "evidence"),
  topic("WAVE 5", "Close the full Change Safety path", "Graph differences and constraint review must lead to approval conditions and post-change verification.", "Change:Exact revision|Assessment:Impact and constraints|Approval:Conditions and quorum|Verification:Post-change outcome", docs.constitution, "flow"),
  topic("WAVE 5", "Close the full FinOps path", "When a cost anomaly Finding or Forecast leads to actual savings, reliability objectives must still hold.", "Opportunity:Cost evidence|Action:Constitutionally eligible option|Outcome:Realized savings|Protection:Maintain SLO and recovery objectives", docs.constitution, "evidence"),
  topic("WAVE 5", "Separate resilience scopes", "DR and chaos testing are different capabilities; each requires its own recovery and safe-experiment evidence.", "DR:RTO, RPO, failover, and failback evidence|Chaos:Human-approved fault injection|Shared:Blast radius and tested recovery", docs.constitution, "matrix"),
  topic("GATE 5", "Confirm the full path for each domain", "One success case is insufficient; all six scenario dimensions and every safety metric are required.", "Success:Expected effect|Boundary:Hold and deny|Conflict:Cross-domain goals|Resilience:Partial failure, recovery, and replay", docs.constitution, "tree"),
  topic("WAVE 6", "Separate organizational scope through policy and configuration", "Supply deployment-owned mappings and objectives without modifying shared Core.", "Shared repository:Stable concepts and contracts|Deployment:Instances and operating objectives|Downstream distribution:Injected implementations", docs.ontology, "matrix"),
  topic("PROPOSAL", "Operate an organization-wide promotion review body", "Each deployment defines the body's name and quorum, but a field team can never raise authority from its own results alone.", "Field team:Submit shadow-mode evidence|Independent review:Quality, safety, authority, and operational readiness|Decision:Promote, hold, reduce scope, or stop|Registry:Exact capability and revision state", docs.security, "responsibility"),
  topic("PROPOSAL", "Include access recertification cadence in deployment policy", "Regularly identify, revoke, and audit unused or excessive authority. Set the actual frequency according to risk and regulatory requirements.", "Inventory:Role assignments and effective access|Review:Owner and usage evidence|Action:Revoke, reduce, or expire exception|Evidence:Next review date and audit record", docs.security, "timeline"),
  topic("WAVE 6", "Review FinOps and LLMOps in one portfolio", "Connect model calls and platform costs to verified operational outcomes.", "Inference:T2 rate and spend|Platform:Service costs|Outcome:Realized value", docs.execution, "matrix"),
  topic("GATE 6", "Prove the economics of each scale unit by workload", "Compare costs and verified benefits separately per incident, change, and optimization instead of counting only teams or events.", "Cost per incident:Detection through independent effect closure|Cost per change:Includes review, execution, and recovery|Cost per optimization:Includes analysis and realization check|Constraint:Maintain safety and reliability objectives", [docs.metrics, docs.constitution], "tree"),
  topic("WAVE 7", "Arbitrate conflicts among multiple objectives", "Odin ranks only constitutionally eligible candidates, and Saga audits the conflict decision.", "Forseti:Compose arbitration request|Odin:Select, hold, or HIL|Saga:Preserve decision lineage", docs.pantheon, "responsibility"),
  topic("WAVE 7", "Align cross-domain evidence as-of times", "Cost, capacity, and resilience candidates must share the same target and as-of time.", "Target:Exact resource|Time:Common as-of time|Lineage:Candidate attested by its owner", docs.pantheon, "evidence"),
  topic("WAVE 7", "Seal a balanced learning cohort", "Operational records marked synthetic and duplicate revisions are not live promotion evidence.", "Cohort:Balanced success and failure cases|Revision:Pin FDAI and scenarios|Evidence:Non-synthetic, fresh, complete, and conflict-free|Review:Evaluation separate from creator", docs.pantheon, "matrix"),
  topic("GATE 7", "Verify that learning does not raise authority", "Pattern, RuleCandidate, and semantic plans must remain inactive until reviewed.", "Candidate:No execution authority|Review:Independent|Promotion:Catalog and registry", docs.ontologyPlatform, "tree"),
  topic("NOT_STARTED", "Connect environments by promoting the same artifact", "The target is for one signed image to move through dev, staging, and prod with traffic canaries and SLO-based rollback.", "dev:Build, supply-chain attestations, and integration|staging:Representative observation and canary|prod:Approved identical artifact|Rollback:Prior revision on SLO violation", docs.deployment, "timeline"),
  topic("NOT_STARTED", "Automated progressive delivery is not yet implemented", "Do not present traffic-split canaries, SLO-based rollback, or Console blue-green deployment as current features.", "Current:Protected plan and apply|Target:Automated environment promotion|Target:Traffic canary and SLO rollback|Target:Console blue-green deployment", docs.deployment, "matrix"),
  topic("IN_PROGRESS", "Do not make A3-E a prerequisite for enterprise scale", "Core A3-E components are implemented but not connected to the execution path. It cannot be used before live evidence and a way to retain authority throughout execution exist.", "Implemented:Evaluator, store, snapshots, and blocker|Not connected:Decision and execution paths|Open design:Full pre-effect lock or lease|Boundary:No executable A3-E authority", docs.standingAuthority, "cards"),
  topic("PROPOSAL", "The roadmap status board counts only exit criteria", "Show dependencies closed with exact evidence instead of activity-completion percentages.", "Complete:Preserved evidence|In progress:Implemented but evidence incomplete|Not started:Not implemented", docs.hardening, "matrix"),
  topic("PROPOSAL", "ARB re-reviews dependency changes between waves", "If a new service, identity, or state owner changes a safety assumption from an earlier gate, stop the next wave and update impact evidence.", "Change:Exact architecture revision|Review:Constraints and impact|Resume:Updated exit evidence", docs.operator, "evidence"),
  topic("PROPOSAL", "Prioritize Waves 0 through 2 in the next planning horizon", "After duration, owners, staffing, and budget are approved, close goals, the decision inventory, ontology spine, evidence registry, and identity separation in sequence.", "Plan start:Owners, duration, priorities, and available capacity|Midpoint:Formalized operational facts and evidence health|Exit:Composition that blocks safely on dependency failure|Next decision:Approve shadow mode for the first domain", docs.constitution, "timeline"),
]);

export const additionalManualSlides = {
  "readiness-maturity": readinessMaturity,
  "art-of-possible": artOfPossible,
  "value-prioritization": valuePrioritization,
  "target-architecture": targetArchitecture,
  "ontology-foundation": ontologyFoundationSlides,
  "responsible-ai-security": responsibleAiSecurity,
  "pilot-production": pilotProduction,
  "sre-incident-response": sreIncidentResponse,
  "ai-operating-model": aiOperatingModel,
  "enterprise-scale-roadmap": enterpriseScaleRoadmap,
};
