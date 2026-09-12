import { slide, entry, table, sources as s, references as r } from "./ontology-slide-kit.en.js";

/** Slides 2-14: why shared meaning matters and how the idea developed. */
export function foundationSlides() {
  return [
    slide({
      state: "PROBLEM", chapter: "01 / WHY NOW", layout: "tension",
      title: "A fluent answer is not an actionable decision",
      lead: "An LLM generates plausible answers. The current target, state, and authority require separate verification.",
      body: `<div class="oe-split">
        <blockquote class="oe-statement"><small>OPERATOR QUESTION</small><strong>Can I restart<br>this service?</strong><p>A persuasive answer alone cannot show<br>whether execution is safe now.</p></blockquote>
        <div class="oe-stack">${entry("WHAT THE LLM PROPOSES", "A plausible procedure and rationale", "Finds relevant patterns in context to create explanations and options.")}${entry("WHAT OPERATIONS VERIFIES", "Is it valid for this target now?", "Verifies the exact target, current observations, policy, recovery, and required approvals.")}</div>
      </div>`,
      takeaway: "Model confidence is not execution authority. Anything unverifiable remains unknown.",
      evidence: [s.llm, s.constitution],
    }),
    slide({
      state: "ILLUSTRATIVE", chapter: "02 / ONE WORD, MANY MEANINGS", layout: "fracture",
      title: "The same word service can identify three different targets",
      lead: "Example: Explain the cause of the payment service outage. First resolve which target service means.",
        body: `<div class="oe-meaning-map" role="group" aria-label="One expression, service, branches into three interpretations. The links show possible selections, not relationships between objects.">
          <div class="oe-meaning-source" data-meaning-node="term"><small>ONE EXPRESSION</small><strong>service</strong><p>Do not select a target<br>before clarification.</p></div>
          <div class="oe-meaning-links" aria-hidden="true"><i class="oe-meaning-trunk"></i><i class="oe-meaning-branch" data-branch-to="business"></i><i class="oe-meaning-branch" data-branch-to="runtime"></i><i class="oe-meaning-branch" data-branch-to="provider"></i></div>
          <div class="oe-meaning-targets"><article data-meaning-node="business"><small>01 / BUSINESS</small><strong>BusinessService</strong><p>A business unit connected to<br>service accountability and an SLO</p></article><article data-meaning-node="runtime"><small>02 / RUNTIME</small><strong>Kubernetes Service</strong><p>A network object that routes<br>traffic to Pods</p></article><article data-meaning-node="provider"><small>03 / PROVIDER TERM</small><strong>Cloud service</strong><p>A general name for a cloud<br>product family or management capability</p></article></div>
        </div>`,
      takeaway: "A shared name does not imply a shared type. Preserve unresolved terms and present verifiable candidates.",
      evidence: [s.ontology, s.metamodel],
    }),
    slide({
      state: "PROBLEM", chapter: "03 / FAILURE MODES", layout: "failure-matrix",
      title: "Meaning gaps lead to six failure modes",
      lead: "Without an ontology, LLM-only reasoning can combine target, relationship, time, evidence, and authority errors in one decision.",
      body: `<div class="oe-six">${entry("01", "Semantic ambiguity", "Fails to determine what type of target service denotes.")}${entry("02", "Identity conflation", "Combines different resources with similar names into one identity.")}${entry("03", "Relationship inference", "Assumes a dependency because two objects appear close.")}${entry("04", "Temporal loss", "Uses a state from an old document as a current fact.")}${entry("05", "Evidence overstatement", "Treats a partial query as verification of the full scope.")}${entry("06", "Authority confusion", "Interprets a work request as approval to execute.")}</div>`,
      takeaway: "More search results do not close these gaps. Each boundary requires distinct verification.",
      evidence: [s.constitution, s.ontology, s.governance],
    }),
    slide({
      state: "BOUNDARY", chapter: "04 / DISTINCT RESPONSIBILITIES", layout: "role-bands",
      title: "Generation, retrieval, meaning, and authority have distinct roles",
      lead: "LLMs, RAG, ontologies, and policies are complementary layers that answer different questions.",
      body: table(["Layer", "Question answered", "Responsibility excluded"], [
        ["LLM", "What interpretations and explanations are plausible?", "Guaranteeing current facts or approval to execute"],
        ["RAG", "Which material is relevant to this question?", "Guaranteeing that a document remains valid now"],
        ["Ontology", "What do targets and relationships mean?", "Observation, decision, approval, or execution"],
        ["Policy and evidence verification", "Is this decision eligible now?", "Turning model speculation into fact"],
      ]),
      takeaway: "Success in one layer does not imply success in the next. Verify generation, retrieval, meaning, and authority separately.",
      evidence: [s.llm, s.ontology, s.constitution],
    }),
    slide({
      state: "FOUNDATION", chapter: "05 / FROM DATA TO DECISION", layout: "meaning-ladder",
      title: "Storing data is not enough",
      lead: "Values, structure, meaning, current evidence, and decisions each have a distinct responsibility.",
      body: `<div class="oe-split oe-wide-left"><ol class="oe-ladder">
        <li><b>01</b><strong>Data</strong><span>What was observed?</span></li><li><b>02</b><strong>Schema</strong><span>What are the fields and data types?</span></li><li class="oe-emphasis"><b>03</b><strong>Ontology</strong><span>What do the values and relationships mean?</span></li><li><b>04</b><strong>Knowledge graph</strong><span>What evidence supports the connections?</span></li><li><b>05</b><strong>Decision</strong><span>What should happen within policy and authority?</span></li>
        </ol><aside class="oe-margin"><strong>Valid structure does not<br>guarantee shared meaning.</strong><p>A schema alone cannot show whether the same string field is a display name or a stable identifier.</p></aside></div>`,
      takeaway: "An ontology does not create facts without data, and policy does not turn ontology meaning into execution authority.",
      evidence: [s.ontology, s.platform],
    }),
    slide({
      state: "HISTORY", chapter: "06 / ARISTOTLE", layout: "aristotle",
      title: "It begins with an ancient question: What exists?",
      lead: "In the 4th century BCE, Aristotle explored being and categories. He did not use the term ontology.",
      body: `<div class="oe-split"><blockquote class="oe-quote"><small>ARISTOTLE / METAPHYSICS</small><strong>Being<br>as being</strong><p>What exists, in what categories it can be described,<br>and what relationships it has.</p></blockquote>
        <div class="oe-category-study"><small>THE TEN TRADITIONALLY TRANSLATED CATEGORIES</small><div class="oe-category-grid">${["Substance", "Quantity", "Quality", "Relation", "Place", "Time", "Position", "State", "Action", "Being affected"].map(word => `<span>${word}</span>`).join("")}</div><p>The effort to define categories and relationships<br>still matters in modern model design.</p></div></div>`,
      takeaway: "This is a similarity in questions, not a direct technical lineage. Ancient category theory is not a modern computational model.",
      evidence: [s.ontology, r.aristotle, r.logic],
    }),
    slide({
      state: "HISTORY", chapter: "07 / A NAME EMERGES", layout: "history-timeline",
      title: "The study of being gains the name ontologia",
      lead: "In the modern era, the ancient inquiry became a named discipline concerned with being in general.",
      body: `<ol class="oe-timeline"><li><time>4th century BCE</time><strong>Aristotle</strong><p>Systematic questions about<br>being, substance, and categories</p></li><li><time>Middle Ages</time><strong>Scholastic philosophy</strong><p>Studies of essence and existence,<br>universals and particulars</p></li><li><time>1606</time><strong>Jacob Lorhard</strong><p>An early use of<br>ontologia as a heading</p></li><li><time>1730</time><strong>Christian Wolff</strong><p>A systematic general ontology<br>concerned with being in general</p></li></ol>`,
      takeaway: "This overview shows the main sequence, not a time-scaled axis. Claims of the term's first use depend on bibliographic criteria.",
      evidence: [s.ontology, r.logic],
    }),
    slide({
      state: "HISTORY", chapter: "08 / MAKING ASSUMPTIONS VISIBLE", layout: "logic-bridge",
      title: "Formal language makes assumptions visible",
      lead: "Formalizing natural language allows separate review of target scope, relationship direction, and counterexamples.",
      body: `<div class="oe-logic-pair"><div class="oe-natural"><small>NATURAL-LANGUAGE EXAMPLE</small><strong>Every service<br>has an owner.</strong></div><div class="oe-formal"><small>ILLUSTRATIVE LOGIC</small><code>∀x (Service(x) → ∃y owns(y,x))</code><p>The scope of Service and the direction of owns<br>must be interpreted explicitly.</p></div></div>
        <div class="oe-three oe-questions">${entry("SCOPE", "Which Service?", "Distinguish BusinessService from runtime objects")}${entry("RELATIONSHIP", "Who owns what?", "Compare the Owner -> Service direction with the declaration")}${entry("COUNTEREXAMPLE", "What if no owner exists?", "Report the gap rather than forcing a fact")}</div>`,
      takeaway: "Formality improves clarity but does not create facts. Real targets and ownership relationships require authoritative evidence.",
      evidence: [s.metamodel, r.logic],
    }),
    slide({
      state: "HISTORY", chapter: "09 / KNOWLEDGE REPRESENTATION", layout: "kr-evolution",
      title: "AI has expanded how knowledge is represented",
      lead: "Logic, frames, semantic networks, description logics, and knowledge graphs offer different ways to reuse concepts and relationships.",
      body: `<ol class="oe-timeline oe-five"><li><time>1950s-60s</time><strong>Symbolic AI</strong><p>Represents problems with logic and search</p></li><li><time>1970s</time><strong>Frames and semantic networks</strong><p>Structures objects, slots, and relationships</p></li><li><time>1980s</time><strong>Expert systems</strong><p>Apply domain rules and knowledge bases</p></li><li><time>1990s</time><strong>Description logics</strong><p>Formalize classification and consistency</p></li><li><time>2000s+</time><strong>Knowledge graphs</strong><p>Connect data through shared meaning</p></li></ol>`,
      takeaway: "This timeline simplifies major developments. These approaches coexist, and not all were called ontology at the time.",
      evidence: [s.ontology, r.logic],
    }),
    slide({
      state: "HISTORY", chapter: "10 / GRUBER, 1993", layout: "gruber",
      title: "Design shared concepts explicitly",
      lead: "Gruber described an ontology as a design artifact for sharing knowledge.",
      body: `<div class="oe-split oe-wide-left"><blockquote class="oe-quote oe-definition-quote"><small>THOMAS R. GRUBER / 1993</small><strong>explicit specification<br>of a conceptualization</strong><p>Specify which concepts and relationships are shared,<br>for what purpose, in a machine-processable form.</p></blockquote><div class="oe-stack">${entry("01 / CLARITY", "Keep meaning stable", "Interpret the same term consistently across contexts")}${entry("02 / COHERENCE", "Avoid contradictions", "Review declarations and inferences together")}${entry("03 / EXTENSIBILITY", "Preserve existing meaning", "Design for the addition of new concepts")}</div></div>`,
      takeaway: "An ontology is not a replica of the entire world. It is an agreed model of meaning shared for a specific purpose.",
      evidence: [s.ontology, r.gruber],
    }),
    slide({
      state: "HISTORY", chapter: "11 / SEMANTIC WEB", layout: "semantic-web",
      title: "RDF expresses connections; OWL expresses formal meaning",
      lead: "Shared web identifiers and logical constraints established a foundation for machines to interpret data together.",
      body: `<div class="oe-relation-example" role="img" aria-label="Example RDF triple: Workload A depends on Database B"><div class="oe-relation-node"><small>SUBJECT</small><strong>Workload A</strong></div><div class="oe-labeled-edge"><span>depends_on</span><i class="oe-edge" aria-hidden="true"></i></div><div class="oe-relation-node"><small>OBJECT</small><strong>Database B</strong></div></div>
        <div class="oe-two">${entry("RDF", "Subject, predicate, object", "Connects identifiers and relationships as a graph through triples.")}${entry("OWL", "Classes, properties, axioms", "Defines logical meaning and the constraints needed for inference.")}</div>`,
      takeaway: "FDAI uses its own typed contracts. Graph meaning does not replace current external facts, approval, or execution authority.",
      evidence: [s.structural, r.rdf, r.owl],
    }),
    slide({
      state: "HISTORY", chapter: "12 / THE LLM ERA", layout: "return-loop",
      title: "Add semantic rigor to linguistic flexibility",
      lead: "In the LLM era, ontologies complement generation by providing shared criteria for validating candidates.",
      body: `<div class="oe-duet"><article><small>SYMBOLIC KNOWLEDGE</small><strong>Consistent meaning</strong><p>Explicit types and relationships<br>Reproducible constraint validation</p><span>Agreement and authoring require effort.</span></article><b aria-hidden="true">+</b><article><small>LLM</small><strong>Broad expression</strong><p>Varied natural-language understanding<br>Explanations and interpretation candidates</p><span>Does not guarantee current facts or authority.</span></article></div>`,
      takeaway: "Resolve repeatable decisions with rules first. Residual ambiguity still passes through meaning, evidence, policy, and required approvals.",
      evidence: [s.llm, s.constitution, s.platform],
    }),
    slide({
      state: "FOUNDATION", chapter: "13 / OPERATING ONTOLOGY", layout: "definition-cube",
      title: "An operating ontology is a versioned meaning contract",
      lead: "It defines the objects, relationships, constraints, and semantic versions needed for cloud operations questions.",
      body: `<div class="oe-definition-grid">${entry("WHAT", "Object", "What exists?<br>Types of services, workloads, and resources")}${entry("HOW", "Relationship", "How are they connected?<br>Direction of dependency, deployment, and ownership")}${entry("MEANING", "Constraint", "What structure is valid?<br>Constraints on types, units, and endpoints")}${entry("VERSION", "Release", "Which meaning was applied?<br>Exact declaration version and digest")}</div>`,
      takeaway: "A release fixes meaning; observations provide current evidence. Separate policy and approval boundaries determine action eligibility.",
      evidence: [s.ontology, s.metamodel],
    }),
  ];
}
