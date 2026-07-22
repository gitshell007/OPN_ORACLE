"""Strict structured outputs shared by Oracle AI agents."""

from __future__ import annotations

from datetime import date as CalendarDate
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Fact(StrictModel):
    statement: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[UUID] = Field(min_length=1)


class Inference(StrictModel):
    statement: str = Field(min_length=1, max_length=4000)
    reasoning_summary: str = Field(min_length=1, max_length=4000)
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class Recommendation(StrictModel):
    action: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=4000)
    priority: Literal["low", "medium", "high", "critical"]


class SituationFact(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationInference(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    reasoning_summary: str = Field(min_length=1, max_length=4000)
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationChange(StrictModel):
    change: str = Field(min_length=1, max_length=4000)
    importance: Literal["low", "medium", "high", "critical"]
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationOpportunity(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=4000)
    urgency: Literal["low", "medium", "high", "critical"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationRisk(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=4000)
    severity: Literal["low", "medium", "high", "critical"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationActor(StrictModel):
    actor_id: UUID | None = None
    name: str = Field(min_length=1, max_length=500)
    relevance: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationMilestone(StrictModel):
    label: str = Field(min_length=1, max_length=500)
    date: CalendarDate | None = None
    status: str = Field(min_length=1, max_length=200)
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationDecision(StrictModel):
    decision: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=4000)
    urgency: Literal["low", "medium", "high", "critical"]
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationAction(StrictModel):
    action: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=4000)
    priority: Literal["low", "medium", "high", "critical"]


class EvidenceCoverage(StrictModel):
    cited_items: int = Field(ge=0)
    available_items: int = Field(ge=0)
    limitations: list[str] = Field(default_factory=list)


class EntityMention(StrictModel):
    name: str = Field(min_length=1, max_length=500)
    entity_type: Literal["person", "organization", "place", "technology", "other"]
    evidence_ids: list[UUID] = Field(default_factory=list)


class DuplicateHint(StrictModel):
    signal_id: UUID
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: int = Field(ge=0, le=100)


class ContradictionHint(StrictModel):
    statement: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[UUID] = Field(min_length=2)
    confidence: int = Field(ge=0, le=100)


class AgentOutput(StrictModel):
    facts: list[Fact]
    inferences: list[Inference]
    recommendations: list[Recommendation]
    confidence: int = Field(ge=0, le=100)
    open_questions: list[str]
    warnings: list[str]


class IntakeOutput(AgentOutput):
    proposed_title: str
    proposed_description: str
    dossier_type: Literal[
        "project",
        "strategic_account",
        "market",
        "technology",
        "tender_or_grant",
        "investment",
        "partnership",
        "product_launch",
        "regulatory_affair",
        "risk_watch",
        "competitive_intelligence",
        "custom",
    ]


class ScoreSet(StrictModel):
    relevance: int = Field(ge=0, le=100)
    novelty: int = Field(ge=0, le=100)
    strategic_impact: int = Field(ge=0, le=100)
    source_credibility: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)


class SignalTriageOutput(AgentOutput):
    category: Literal[
        "news",
        "official_publication",
        "social_signal",
        "company_signal",
        "market_signal",
        "regulatory_signal",
        "tender_or_grant",
        "relationship_signal",
        "internal_document",
        "risk_signal",
        "opportunity_signal",
        "other",
    ]
    recommended_status: Literal["reviewed", "dismissed", "candidate_for_promotion"]
    scores: ScoreSet
    why_it_matters: str
    recommended_next_action: str = "Revisión humana"
    entities: list[EntityMention] = Field(default_factory=list)
    duplicate_hints: list[DuplicateHint] = Field(default_factory=list)
    contradiction_hints: list[ContradictionHint] = Field(default_factory=list)


class EntityResolutionOutput(AgentOutput):
    decision: Literal["match", "no_match", "needs_review", "create_new"]
    matched_actor_id: UUID | None
    rationale: str


class OpportunityScores(StrictModel):
    strategic_fit: int = Field(ge=0, le=100)
    urgency: int = Field(ge=0, le=100)
    expected_value: int = Field(ge=0, le=100)
    actionability: int = Field(ge=0, le=100)
    relationship_leverage: int = Field(ge=0, le=100)
    timing: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)
    execution_effort: int = Field(ge=0, le=100)
    blocking_risk: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)


class CandidateActor(StrictModel):
    actor_id: UUID | None = None
    name: str = Field(min_length=1, max_length=500)
    role: str = Field(min_length=1, max_length=500)
    evidence_ids: list[UUID] = Field(default_factory=list)


class NextBestAction(StrictModel):
    action: str = Field(min_length=1, max_length=2000)
    owner_role: str = Field(min_length=1, max_length=500)
    due_date: CalendarDate | None = None
    rationale: str = Field(min_length=1, max_length=4000)


class OpportunityAnalysisOutput(AgentOutput):
    title: str
    opportunity_type: Literal[
        "grant",
        "tender",
        "partner",
        "client",
        "market",
        "investment",
        "media",
        "regulatory",
        "other",
    ] = "other"
    summary: str = ""
    recommendation: Literal["go", "investigate", "hold", "no_go"]
    scores: OpportunityScores
    deadline: CalendarDate | None = None
    confirmed_requirements: list[str] = Field(default_factory=list)
    unknown_requirements: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    candidate_actors: list[CandidateActor] = Field(default_factory=list)
    next_best_action: NextBestAction | None = None


class RiskScores(StrictModel):
    impact: int = Field(ge=0, le=100)
    likelihood: int = Field(ge=0, le=100)
    velocity: int = Field(ge=0, le=100)
    exposure: int = Field(ge=0, le=100)
    uncertainty: int = Field(ge=0, le=100)
    controllability: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)


class RiskScenario(StrictModel):
    name: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=4000)
    probability: int = Field(ge=0, le=100)
    impact: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class RiskMitigation(StrictModel):
    action: str = Field(min_length=1, max_length=2000)
    owner_role: str = Field(min_length=1, max_length=500)
    effectiveness: int = Field(ge=0, le=100)
    trigger: str = Field(min_length=1, max_length=1000)


class RiskAnalysisOutput(AgentOutput):
    title: str
    category: Literal[
        "regulatory",
        "commercial",
        "reputational",
        "operational",
        "territorial",
        "financial",
        "technical",
        "relationship",
        "security",
        "other",
    ] = "other"
    description: str = ""
    recommended_status: Literal["watch", "mitigate", "accept_candidate", "dismiss_candidate"]
    scores: RiskScores
    leading_indicators: list[str] = Field(default_factory=list)
    suggested_owner_role: str = ""
    suggested_review_date: CalendarDate | None = None
    scenarios: list[RiskScenario] = Field(default_factory=list)
    mitigations: list[RiskMitigation] = Field(default_factory=list)


class ActorScores(StrictModel):
    influence: int = Field(ge=0, le=100)
    relevance: int = Field(ge=0, le=100)
    relationship_strength: int = Field(ge=0, le=100)
    accessibility: int = Field(ge=0, le=100)
    strategic_alignment: int = Field(ge=0, le=100)
    recent_activity: int = Field(ge=0, le=100)
    overall_priority: int = Field(ge=0, le=100)


class ActorRole(StrictModel):
    role: str = Field(min_length=1, max_length=500)
    basis: Literal["fact", "inference"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class ActorRelationship(StrictModel):
    counterpart_actor_id: UUID | None = None
    counterpart_name: str = Field(min_length=1, max_length=500)
    relationship_type: str = Field(min_length=1, max_length=500)
    basis: Literal["fact", "inference"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class EngagementAction(StrictModel):
    action: str = Field(min_length=1, max_length=2000)
    channel: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=1000)
    priority: Literal["low", "medium", "high", "critical"]


class ActorAnalysisOutput(AgentOutput):
    actor_id: UUID | None
    roles: list[ActorRole] = Field(default_factory=list)
    scores: ActorScores
    confirmed_relationships: list[str] = Field(default_factory=list)
    inferred_relationships: list[str] = Field(default_factory=list)
    observable_interests: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    relationships: list[ActorRelationship] = Field(default_factory=list)
    engagement_actions: list[EngagementAction] = Field(default_factory=list)


class BriefingQuestion(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    purpose: str = Field(min_length=1, max_length=1000)
    priority: Literal["low", "medium", "high", "critical"]
    basis: Literal["fact", "hypothesis", "inference"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class ExpectedObjection(StrictModel):
    objection: str = Field(min_length=1, max_length=2000)
    response: str = Field(min_length=1, max_length=2000)
    basis: Literal["fact", "hypothesis", "inference"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class MeetingBriefingOutput(AgentOutput):
    meeting_objective: str
    minimum_outcome: str
    ideal_outcome: str
    hypotheses_to_validate: list[str] = Field(default_factory=list)
    participant_context: list[str] = Field(default_factory=list)
    key_messages: list[str] = Field(default_factory=list)
    questions: list[BriefingQuestion] = Field(default_factory=list)
    expected_objections: list[ExpectedObjection] = Field(default_factory=list)
    do_not_disclose: list[str] = Field(default_factory=list)
    desired_close: str = ""
    follow_up_tasks: list[str] = Field(default_factory=list)


class ReportParagraph(StrictModel):
    text: str = Field(min_length=1, max_length=8000)
    kind: Literal["fact", "inference", "recommendation", "decision"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class ReportSection(StrictModel):
    heading: str = Field(min_length=1, max_length=500)
    paragraphs: list[ReportParagraph]


class SourceIndexEntry(StrictModel):
    evidence_id: UUID
    label: str = Field(min_length=1, max_length=1000)
    locator: str = Field(min_length=1, max_length=2000)


class ReportOutput(AgentOutput):
    title: str
    executive_summary: str
    sections: list[ReportSection] = Field(default_factory=list)
    top_opportunities: list[str] = Field(default_factory=list)
    top_risks: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    decisions_required: list[str] = Field(default_factory=list)
    source_index: list[SourceIndexEntry] = Field(default_factory=list)


class MemoryChange(StrictModel):
    change: str = Field(min_length=1, max_length=4000)
    importance: Literal["low", "medium", "high", "critical"]
    evidence_ids: list[UUID] = Field(default_factory=list)


class MemoryItem(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    status: str = Field(min_length=1, max_length=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class MemoryCuratorOutput(AgentOutput):
    living_summary: str
    what_changed: list[MemoryChange]
    current_objectives: list[MemoryItem] = Field(default_factory=list)
    active_hypotheses: list[MemoryItem] = Field(default_factory=list)
    supported_hypotheses: list[MemoryItem] = Field(default_factory=list)
    contradicted_hypotheses: list[MemoryItem] = Field(default_factory=list)
    human_decisions: list[MemoryItem] = Field(default_factory=list)
    next_milestones: list[MemoryItem] = Field(default_factory=list)


class ClaimIssue(StrictModel):
    path: str
    claim: str
    reason: str


class EvidenceReviewerOutput(AgentOutput):
    verdict: Literal["pass", "pass_with_warnings", "fail"]
    unsupported_claims: list[ClaimIssue]
    misused_evidence: list[ClaimIssue] = Field(default_factory=list)
    missing_evidence: list[ClaimIssue] = Field(default_factory=list)
    classification_errors: list[str] = Field(default_factory=list)
    privacy_or_security_issues: list[str] = Field(default_factory=list)
    prompt_injection_indicators: list[str] = Field(default_factory=list)
    confidence_issues: list[str] = Field(default_factory=list)
    required_corrections: list[str]


class WeeklyChange(StrictModel):
    area: str = Field(min_length=1, max_length=500)
    change: str = Field(min_length=1, max_length=4000)
    significance: Literal["low", "medium", "high", "critical"]
    previous_state: str = Field(min_length=1, max_length=2000)
    current_state: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[UUID] = Field(default_factory=list)


class WeeklyChangeOutput(AgentOutput):
    period_start: datetime
    period_end: datetime
    coverage_summary: str
    changes: list[WeeklyChange] = Field(default_factory=list)
    no_change_areas: list[str] = Field(default_factory=list)


class DossierSituationSummaryOutput(StrictModel):
    headline: str = Field(min_length=1, max_length=500)
    executive_summary: str = Field(min_length=1, max_length=8000)
    situation_status: Literal["stable", "advancing", "blocked", "deteriorating", "uncertain"]
    facts: list[SituationFact] = Field(default_factory=list)
    inferences: list[SituationInference] = Field(default_factory=list)
    material_changes: list[SituationChange] = Field(default_factory=list)
    opportunities: list[SituationOpportunity] = Field(default_factory=list)
    risks: list[SituationRisk] = Field(default_factory=list)
    relevant_actors: list[SituationActor] = Field(default_factory=list)
    deadlines_and_milestones: list[SituationMilestone] = Field(default_factory=list)
    decisions_required: list[SituationDecision] = Field(default_factory=list)
    recommended_actions: list[SituationAction] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    confidence: int = Field(ge=0, le=100)
    evidence_coverage: EvidenceCoverage
    warnings: list[str] = Field(default_factory=list)


class DossierWizardSectionDiagnostic(StrictModel):
    section: Literal[
        "goal",
        "signals",
        "procurement",
        "opportunities",
        "risks",
        "actors",
        "hypotheses",
        "other",
    ]
    status: Literal["ok", "incomplete", "empty"]
    explanation: str = Field(min_length=1, max_length=2000)


class DossierWizardQuestion(StrictModel):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.:-]+$")
    question: str = Field(min_length=1, max_length=1000)
    why_it_matters: str = Field(min_length=1, max_length=2000)
    expected_input: str = Field(min_length=1, max_length=1000)


class DossierWizardPrefill(StrictModel):
    # create_signal_monitor
    name: str | None = Field(default=None, max_length=200)
    query: str | None = Field(default=None, max_length=1000)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    source_types: list[str] = Field(default_factory=list, max_length=20)
    languages: list[str] = Field(default_factory=list, max_length=20)
    geographies: list[str] = Field(default_factory=list, max_length=50)
    cadence: str | None = Field(default=None, max_length=50)
    # pin_procurement
    procurement_query: str | None = Field(default=None, max_length=1000)
    procurement_kind: Literal["tender", "award"] | None = None
    # create_opportunity/create_risk/create_actor
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    next_action: str | None = Field(default=None, max_length=2000)
    mitigation: str | None = Field(default=None, max_length=2000)
    actor_type: Literal["person", "organization", "institution", "program", "other"] | None = None
    tags: list[str] = Field(default_factory=list, max_length=30)
    roles: list[str] = Field(default_factory=list, max_length=30)
    # generic guidance
    note: str | None = Field(default=None, max_length=2000)


class DossierWizardRecommendedAction(StrictModel):
    kind: Literal[
        "create_signal_monitor",
        "pin_procurement",
        "create_opportunity",
        "create_risk",
        "create_actor",
        "refine_goal",
        "other",
    ]
    title: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=2000)
    prefill: DossierWizardPrefill = Field(default_factory=DossierWizardPrefill)


class DossierCompletionWizardOutput(StrictModel):
    summary: str = Field(min_length=1, max_length=4000)
    confidence: int = Field(ge=0, le=100)
    warnings: list[str] = Field(default_factory=list)
    section_diagnostics: list[DossierWizardSectionDiagnostic] = Field(default_factory=list)
    questions: list[DossierWizardQuestion] = Field(default_factory=list)
    recommended_actions: list[DossierWizardRecommendedAction] = Field(default_factory=list)


AGENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "intake": IntakeOutput,
    "signal_triage": SignalTriageOutput,
    "entity_resolution": EntityResolutionOutput,
    "opportunity": OpportunityAnalysisOutput,
    "risk": RiskAnalysisOutput,
    "actor_partnership": ActorAnalysisOutput,
    "meeting_briefing": MeetingBriefingOutput,
    "report_writer": ReportOutput,
    "competitive_procurement_intelligence": ReportOutput,
    "entity_dossier_intelligence": ReportOutput,
    "memory_curator": MemoryCuratorOutput,
    "evidence_reviewer": EvidenceReviewerOutput,
    "weekly_change": WeeklyChangeOutput,
    "dossier_situation_summary": DossierSituationSummaryOutput,
    "dossier_completion_wizard": DossierCompletionWizardOutput,
}
