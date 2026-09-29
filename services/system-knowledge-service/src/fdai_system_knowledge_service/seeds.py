"""Reviewed FDAI system-knowledge records compiled into the runtime catalog."""

from __future__ import annotations

from dataclasses import dataclass

from fdai_service_contracts.system_knowledge import (
    SystemKnowledgeAuthorityRole,
    SystemKnowledgeSourceKind,
    SystemKnowledgeStatus,
)


@dataclass(frozen=True, slots=True)
class SeedSource:
    """One tracked source coordinate resolved by the catalog compiler."""

    path: str
    symbol: str
    source_kind: SystemKnowledgeSourceKind
    authority_role: SystemKnowledgeAuthorityRole


@dataclass(frozen=True, slots=True)
class KnowledgeSeed:
    """Reviewed content for one answerable FDAI behavior."""

    knowledge_id: str
    subject_id: str
    title: str
    status: SystemKnowledgeStatus
    owner: str
    question_aliases: tuple[str, ...]
    designed_behavior: tuple[str, ...]
    implemented_behavior: tuple[str, ...]
    limitations: tuple[str, ...]
    sources: tuple[SeedSource, ...]


def _doc(path: str, symbol: str, role: SystemKnowledgeAuthorityRole) -> SeedSource:
    return SeedSource(path, symbol, SystemKnowledgeSourceKind.DOC, role)


def _code(path: str, symbol: str) -> SeedSource:
    return SeedSource(
        path,
        symbol,
        SystemKnowledgeSourceKind.CODE,
        SystemKnowledgeAuthorityRole.IMPLEMENTATION,
    )


REFERENCE_SEEDS = (
    KnowledgeSeed(
        knowledge_id="action-safety",
        subject_id="action-safety",
        title="Action safety and authority",
        status=SystemKnowledgeStatus.IMPLEMENTED,
        owner="Forseti, Var, Thor, Saga, and Vidar",
        question_aliases=(
            "How does FDAI keep actions safe?",
            "FDAI는 작업을 어떻게 안전하게 실행하나요?",
        ),
        designed_behavior=(
            "Every action is a typed ActionType with risk, approval, rollback, impact, and audit boundaries.",
            "Natural language can propose work but never grants execution authority.",
        ),
        implemented_behavior=(
            "The action ontology and separated judge, approver, executor, auditor, and recovery roles are present.",
        ),
        limitations=(
            "A capability is not production-authorized merely because its ActionType and code exist.",
        ),
        sources=(
            _doc(
                "docs/roadmap/decisioning/action-ontology.md",
                "One ontology, two triggers",
                SystemKnowledgeAuthorityRole.DESIGN,
            ),
            _doc(
                "docs/roadmap/architecture/fdai-constitution.md",
                "Article 3: Agent-driven authority",
                SystemKnowledgeAuthorityRole.DESIGN,
            ),
        ),
    ),
    KnowledgeSeed(
        knowledge_id="behavior-knowledge",
        subject_id="behavior-knowledge",
        title="Structured behavior knowledge",
        status=SystemKnowledgeStatus.IN_PROGRESS,
        owner="Muninn and Bragi",
        question_aliases=(
            "How does FDAI explain its own behavior?",
            "FDAI는 자신의 동작을 어떻게 설명하나요?",
        ),
        designed_behavior=(
            "BehaviorSpec separates answerable behavior from source metadata used for freshness and authority checks.",
            "Implemented evidence outranks designed-only evidence, while stale or conflicting records are held.",
        ),
        implemented_behavior=(
            "The provider contracts and in-memory retrieval with tracked-source freshness validation are present.",
        ),
        limitations=(
            "Reference seeds, an Operator answer path, persistence, and current runtime evidence are not restored.",
        ),
        sources=(
            _doc(
                "docs/roadmap/interfaces/behavior-knowledge.md",
                "Two-layer contract",
                SystemKnowledgeAuthorityRole.DESIGN,
            ),
            _code(
                "services/core-control-plane/src/fdai/core/knowledge/behavior_index.py",
                "InMemoryBehaviorKnowledgeIndex",
            ),
        ),
    ),
    KnowledgeSeed(
        knowledge_id="bragi-conversation-boundary",
        subject_id="bragi",
        title="Bragi conversation boundary",
        status=SystemKnowledgeStatus.IMPLEMENTED,
        owner="Bragi",
        question_aliases=(
            "What is Bragi responsible for?",
            "Bragi는 무엇을 담당하나요?",
        ),
        designed_behavior=(
            "Bragi routes questions and presents typed results but never judges, approves, or executes.",
        ),
        implemented_behavior=(
            "The Pantheon specification binds Bragi to Conversation, Turn, preferences, and review projections.",
        ),
        limitations=(
            "Bragi ownership does not make every conversational capability production-validated.",
        ),
        sources=(
            _doc(
                "docs/roadmap/agents/agent-pantheon.md",
                "Two-port model",
                SystemKnowledgeAuthorityRole.DESIGN,
            ),
            _code(
                "services/core-control-plane/src/fdai/agents/_framework/pantheon.py",
                "_BRAGI",
            ),
        ),
    ),
    KnowledgeSeed(
        knowledge_id="document-ingestion",
        subject_id="document-ingestion",
        title="Governed document ingestion",
        status=SystemKnowledgeStatus.IMPLEMENTED,
        owner="Document Ingestion API and Document Processing Worker",
        question_aliases=(
            "How does FDAI ingest documents?",
            "FDAI는 문서를 어떻게 수집하나요?",
        ),
        designed_behavior=(
            "Uploads enter quarantine, safety and protection checks, extraction, chunking, indexing, and access-filtered retrieval.",
            "Derived content inherits source access, classification, version, and retention policy.",
        ),
        implemented_behavior=(
            "The repository ships independent ingestion and processing distributions with local and Azure provider seams.",
        ),
        limitations=(
            "Production provider binding and measured scale evidence remain deployment-owned.",
        ),
        sources=(
            _doc(
                "docs/roadmap/interfaces/document-ingestion.md",
                "Authorization and shared visibility",
                SystemKnowledgeAuthorityRole.DESIGN,
            ),
            _doc(
                "docs/roadmap/interfaces/document-ingestion.md",
                "Implementation boundaries and rollout",
                SystemKnowledgeAuthorityRole.VERIFICATION,
            ),
        ),
    ),
    KnowledgeSeed(
        knowledge_id="durable-conversation-delivery",
        subject_id="conversation-delivery",
        title="Durable conversation delivery",
        status=SystemKnowledgeStatus.IMPLEMENTED,
        owner="Operator Service",
        question_aliases=(
            "How does FDAI prevent duplicate chat replies?",
            "FDAI는 중복 채팅 응답을 어떻게 방지하나요?",
        ),
        designed_behavior=(
            "Conversation requests persist before publication and replies persist before provider I/O.",
            "Ambiguous acknowledgement is terminal duplicate risk and is not retried automatically.",
        ),
        implemented_behavior=(
            "Stable delivery identity, claims, acknowledgements, breakers, and restart recovery are implemented.",
        ),
        limitations=(
            "Each provider still requires an exact deployed canary before it is considered validated.",
        ),
        sources=(
            _doc(
                "docs/roadmap/interfaces/durable-conversation-delivery.md",
                "Semantic request ordering and isolation",
                SystemKnowledgeAuthorityRole.DESIGN,
            ),
            _doc(
                "docs/roadmap/interfaces/durable-conversation-delivery.md",
                "Implementation status",
                SystemKnowledgeAuthorityRole.VERIFICATION,
            ),
        ),
    ),
    KnowledgeSeed(
        knowledge_id="fdai-accuracy-contract",
        subject_id="fdai-constitution",
        title="FDAI accuracy contract",
        status=SystemKnowledgeStatus.IN_PROGRESS,
        owner="FDAI maintainers",
        question_aliases=(
            "What accuracy does FDAI guarantee?",
            "FDAI는 어떤 정확성을 보장하나요?",
        ),
        designed_behavior=(
            "FDAI guarantees contract-conformant behavior, not a correct diagnosis for every novel case.",
            "Insufficient evidence produces an explicit unknown, no-op, denial, rollback, or human review outcome.",
        ),
        implemented_behavior=(
            "Traceability records link constitutional requirements to implementation and evidence.",
        ),
        limitations=(
            "Partial or planned traceability entries block a claim of complete runtime conformance.",
        ),
        sources=(
            _doc(
                "docs/roadmap/architecture/fdai-constitution.md",
                "Article 2: Contract-conformant accuracy",
                SystemKnowledgeAuthorityRole.DESIGN,
            ),
        ),
    ),
    KnowledgeSeed(
        knowledge_id="human-identity",
        subject_id="human-identity",
        title="Human identity and RBAC",
        status=SystemKnowledgeStatus.IMPLEMENTED,
        owner="Operator Service",
        question_aliases=(
            "How does FDAI authenticate and authorize people?",
            "FDAI는 사용자를 어떻게 인증하고 권한을 확인하나요?",
        ),
        designed_behavior=(
            "Entra identity, FDAI roles, agent ownership, approval identity, and executor identity remain separate axes.",
        ),
        implemented_behavior=(
            "Conversation relationship context, approval callback identity, local session resilience, and IAM projections are implemented.",
        ),
        limitations=(
            "A role, stewardship assignment, or bot service token never grants executor authority.",
        ),
        sources=(
            _doc(
                "docs/roadmap/interfaces/user-rbac-and-identity.md",
                "Implementation status",
                SystemKnowledgeAuthorityRole.VERIFICATION,
            ),
        ),
    ),
    KnowledgeSeed(
        knowledge_id="operating-ontology",
        subject_id="operating-ontology",
        title="Operating ontology",
        status=SystemKnowledgeStatus.IMPLEMENTED,
        owner="Ontology Platform",
        question_aliases=(
            "What does the FDAI ontology do?",
            "FDAI 온톨로지는 어떤 역할을 하나요?",
        ),
        designed_behavior=(
            "The ontology validates shared object, relationship, evidence, action, and time meaning.",
            "It constrains interpretation but does not observe, judge, approve, execute, or grant permission.",
        ),
        implemented_behavior=(
            "Exact releases, typed declarations, bounded object sets, and evidence lanes are implemented.",
        ),
        limitations=(
            "An ontology projection is not authoritative proof of current external state.",
        ),
        sources=(
            _doc(
                "docs/roadmap/architecture/operating-ontology.md",
                "Catalog semantic projection",
                SystemKnowledgeAuthorityRole.DESIGN,
            ),
        ),
    ),
    KnowledgeSeed(
        knowledge_id="pantheon",
        subject_id="agent-pantheon",
        title="Fixed 15-agent Pantheon",
        status=SystemKnowledgeStatus.IMPLEMENTED,
        owner="Odin",
        question_aliases=(
            "How are FDAI agents organized?",
            "FDAI agent 조직은 어떻게 구성되나요?",
        ),
        designed_behavior=(
            "Fifteen fixed agents divide observation, judgment, approval, execution, recovery, audit, and learning.",
            "Authority-bearing collaboration uses schema-validated events and single-writer ownership.",
        ),
        implemented_behavior=(
            "The fixed roster, charters, topics, and role bindings are represented in PANTHEON_SPECS.",
        ),
        limitations=(
            "Agent presence does not imply that every enforcement capability is promoted.",
        ),
        sources=(
            _doc(
                "docs/roadmap/agents/agent-pantheon.md",
                "Design principles",
                SystemKnowledgeAuthorityRole.DESIGN,
            ),
            _code(
                "services/core-control-plane/src/fdai/agents/_framework/pantheon.py",
                "PANTHEON_SPECS",
            ),
        ),
    ),
    KnowledgeSeed(
        knowledge_id="root-cause-analysis",
        subject_id="root-cause-analysis",
        title="Root-cause analysis",
        status=SystemKnowledgeStatus.IN_PROGRESS,
        owner="Forseti",
        question_aliases=(
            "How does FDAI perform root cause analysis?",
            "FDAI는 근본 원인 분석을 어떻게 수행하나요?",
        ),
        designed_behavior=(
            "RCA is a cited, bounded hypothesis that never grants approval or execution authority.",
            "Conflicting, missing, stale, or scope-mismatched evidence produces a held result.",
        ),
        implemented_behavior=(
            "T0, T1, T2 hypothesis contracts, governed knowledge evidence, and read-only projection are implemented.",
        ),
        limitations=(
            "A retained live cohort has not yet proven governed operational cause accuracy across tiers.",
        ),
        sources=(
            _doc(
                "docs/roadmap-implementation/rules-and-detection/root-cause-analysis.md",
                "Implementation status",
                SystemKnowledgeAuthorityRole.VERIFICATION,
            ),
        ),
    ),
    KnowledgeSeed(
        knowledge_id="semantic-routing",
        subject_id="semantic-routing",
        title="Natural-language semantic routing",
        status=SystemKnowledgeStatus.IMPLEMENTED,
        owner="Bragi and the Semantic Planning runtime",
        question_aliases=(
            "How does FDAI route natural-language questions?",
            "FDAI는 자연어 질문을 어떻게 라우팅하나요?",
        ),
        designed_behavior=(
            "A schema-validated model proposes typed meaning and deterministic code validates and dispatches it.",
            "Runtime keyword lists and regular expressions do not select conversational capabilities.",
        ),
        implemented_behavior=(
            "Semantic judgment, exact-release manifests, verified plans, and typed holds are implemented.",
        ),
        limitations=(
            "Model unavailability or insufficient confidence returns clarification or an unavailable result.",
        ),
        sources=(
            _doc(
                ".github/instructions/architecture.instructions.md",
                "Natural-language intent routing (MUST)",
                SystemKnowledgeAuthorityRole.DESIGN,
            ),
        ),
    ),
    KnowledgeSeed(
        knowledge_id="service-boundaries",
        subject_id="service-boundaries",
        title="Independent service boundaries",
        status=SystemKnowledgeStatus.IN_PROGRESS,
        owner="FDAI maintainers",
        question_aliases=(
            "How are FDAI services separated?",
            "FDAI 서비스는 어떻게 분리되어 있나요?",
        ),
        designed_behavior=(
            "Each service owns its package, identity, data, migration, health, and rollback boundary.",
            "A new split needs a forcing trigger and complete transport, durability, observability, cost, and rollback evidence.",
        ),
        implemented_behavior=(
            "Five service distributions have validated independent release evidence.",
            "The System Knowledge Service is implemented as a sixth candidate without changing the validated five-service baseline.",
        ),
        limitations=(
            "The sixth service cannot claim production graduation until its scorecard and runtime receipts are complete.",
        ),
        sources=(
            _doc(
                "docs/roadmap/architecture/service-graduation-and-ownership.md",
                "Graduation scorecard",
                SystemKnowledgeAuthorityRole.DESIGN,
            ),
            _doc(
                "docs/roadmap/interfaces/system-knowledge-service.md",
                "Revised design",
                SystemKnowledgeAuthorityRole.DESIGN,
            ),
        ),
    ),
    KnowledgeSeed(
        knowledge_id="system-knowledge-service",
        subject_id="system-knowledge-service",
        title="System Knowledge Service",
        status=SystemKnowledgeStatus.IN_PROGRESS,
        owner="Muninn and Bragi",
        question_aliases=(
            "How does the FDAI system knowledge bot work?",
            "FDAI 시스템 지식 봇은 어떻게 동작하나요?",
        ),
        designed_behavior=(
            "A dedicated Teams bot verifies direct mentions and searches a release-bound catalog in a separate process.",
            "The service exposes no operational provider, approval, or execution capability.",
        ),
        implemented_behavior=(
            "The independent package, catalog compiler, deterministic search, Teams boundary, and focused tests are part of the current change.",
        ),
        limitations=(
            "Production Teams registration, persistent-volume binding, scale evidence, and timed rollback remain open.",
        ),
        sources=(
            _doc(
                "docs/roadmap/interfaces/system-knowledge-service.md",
                "Revised design",
                SystemKnowledgeAuthorityRole.DESIGN,
            ),
        ),
    ),
    KnowledgeSeed(
        knowledge_id="teams-a3-conversation",
        subject_id="teams-a3-conversation",
        title="Teams operational conversation edge",
        status=SystemKnowledgeStatus.IMPLEMENTED,
        owner="Operator Service",
        question_aliases=(
            "How does the existing FDAI Teams conversation path work?",
            "기존 FDAI Teams 대화 경로는 어떻게 동작하나요?",
        ),
        designed_behavior=(
            "The A3 edge authenticates Teams activities, maps vendor identity to an FDAI principal, and submits typed semantic turns.",
            "Durable delivery persists the terminal answer before provider I/O.",
        ),
        implemented_behavior=(
            "Teams ingress, publisher, renderer, queue, composition, and delivery worker are implemented.",
        ),
        limitations=(
            "The Teams provider path has not retained the deployed validation receipt recorded for Slack.",
            "The System Knowledge Service uses a separate bot and does not modify this operational path.",
        ),
        sources=(
            _doc(
                "docs/roadmap/interfaces/production-a3-channel-runtime.md",
                "Implementation status",
                SystemKnowledgeAuthorityRole.VERIFICATION,
            ),
            _code(
                "services/operator-service/src/fdai_operator_service/families/conversation/channel_edge/teams_ingress.py",
                "TeamsIngressVerifier",
            ),
        ),
    ),
)


__all__ = ["KnowledgeSeed", "REFERENCE_SEEDS", "SeedSource"]
