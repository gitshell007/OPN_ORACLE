export type DossierStatus = "draft" | "active" | "paused" | "archived";
export type DossierType = "project" | "strategic_account" | "market" | "technology" | "tender_or_grant" | "investment" | "partnership" | "regulatory_affair" | "custom";
export type RiskLevel = "low" | "medium" | "high" | "critical";
export type Density = "compact" | "balanced" | "comfortable";
export type SignalStatus = "new" | "reviewed" | "dismissed" | "promoted";
export type SignalType = "tender_or_grant" | "regulatory_signal" | "company_signal" | "market_signal" | "social_signal" | "news" | "internal_document" | "risk_signal" | "opportunity_signal";

export interface Evidence { id: string; label: string; source: string; excerpt: string; }
export interface Opportunity { id: string; title: string; score: number; deadline?: string; action: string; status: "candidate" | "qualified" | "active"; }
export interface RiskItem { id: string; title: string; score: number; level: RiskLevel; mitigation: string; status: "watch" | "mitigating" | "accepted"; }
export interface Actor { id: string; name: string; kind: "organisation" | "institution" | "person"; role: string; influence: number; alignment: number; }
export interface TimelineItem { id: string; date: string; type: "decision" | "meeting" | "task" | "signal"; title: string; detail: string; }
export interface StrategicDossier {
  id: string; title: string; type: DossierType; typeLabel: string; status: DossierStatus; owner: string;
  healthScore: number; opportunityScore: number; riskScore: number; riskLevel: RiskLevel; newSignals: number;
  nextMilestone: string; nextMilestoneDate: string; updatedAt: string; geography: string[]; sectors: string[];
  objective: string; livingSummary: string; opportunities: Opportunity[]; risks: RiskItem[]; actors: Actor[]; timeline: TimelineItem[];
}
export interface Signal {
  id: string; dossierId: string; title: string; summary: string; sourceType: SignalType; sourceName: string;
  publishedAt: string; relevance: number; novelty: number; confidence: number; credibility: number; status: SignalStatus;
  whyItMatters: string; evidence: Evidence[]; actors: string[];
}
export interface UserSettings {
  name: string; role: string; email: string; language: string; timezone: string; dateFormat: string;
  landing: "portfolio" | "signals"; density: Density; reducedMotion: boolean; showScoreExplanations: boolean;
  relevanceThreshold: number; digest: "daily" | "weekly" | "off"; notifications: boolean; navigationCompact: boolean;
}
export interface DossierFilters { query?: string; status?: DossierStatus | "all"; type?: DossierType | "all"; risk?: RiskLevel | "all"; }
export interface CreateDossierInput { title: string; type: DossierType; objective: string; geography: string; sectors: string; owner: string; monitorEnabled: boolean; }
export interface SignalAction { signalId: string; status: SignalStatus; promotedAs?: "opportunity" | "risk"; }

export interface OracleRepository {
  listDossiers(filters?: DossierFilters): Promise<StrategicDossier[]>;
  getDossier(id: string): Promise<StrategicDossier | null>;
  listSignals(dossierId?: string): Promise<Signal[]>;
  createDossier(input: CreateDossierInput): Promise<StrategicDossier>;
  updateSignal(action: SignalAction): Promise<Signal>;
  updateUserSettings(input: UserSettings): Promise<UserSettings>;
}
