import { notFound } from "next/navigation";
import { AuthBoundary } from "@/components/auth/auth-boundary";
import {
  DossierIntelligenceSection,
  type IntelligenceSectionKind,
} from "@/components/dossiers/dossier-intelligence-section";
import {
  DossierWorkSection,
  type DossierWorkKind,
} from "@/components/dossiers/dossier-work-section";
import { DossierActivitySection } from "@/components/dossiers/dossier-activity-section";
import { DossierAskSection } from "@/components/dossiers/dossier-ask-section";
import { DossierCustomBriefSection } from "@/components/dossiers/dossier-custom-brief-section";
import { DossierDocumentsSection } from "@/components/dossiers/dossier-documents-section";
import { DossierIntakeSection } from "@/components/dossiers/dossier-intake-section";
import { DossierOpportunityAnalysisSection } from "@/components/dossiers/dossier-opportunity-analysis-section";
import { DossierRiskAnalysisSection } from "@/components/dossiers/dossier-risk-analysis-section";
import { DossierActorPartnershipSection } from "@/components/dossiers/dossier-actor-partnership-section";
import { DossierEntityResolutionSection } from "@/components/dossiers/dossier-entity-resolution-section";
import { DossierInvestigationsSection } from "@/components/dossiers/dossier-investigations-section";
import { DossierProcurementSection } from "@/components/dossiers/dossier-procurement-section";
import { DossierSettingsSection } from "@/components/dossiers/dossier-settings-section";
import { DOSSIER_TABS } from "@/lib/app-routes";

const sectionCopy: Record<string, { description: string; api: string }> = {
  activity: { description: "Vigilancias, monitores y jobs del expediente.", api: "GET /api/v1/dossiers/{id}/activity" },
  ask: { description: "Preguntas durables a Oracle con citas.", api: "POST /api/v1/dossiers/{id}/conversations/.../messages" },
  intake: {
    description: "Propuesta de expediente a partir de pliego o documentos (confirmación humana).",
    api: "POST /api/v1/ai/dossiers/{id}/intake/runs",
  },
  "opportunity-analysis": {
    description: "Propuesta de oportunidad con citas a evidencia (confirmación humana).",
    api: "POST /api/v1/ai/dossiers/{id}/opportunity/runs",
  },
  "risk-analysis": {
    description: "Propuesta de riesgo con citas a evidencia (confirmación humana).",
    api: "POST /api/v1/ai/dossiers/{id}/risk/runs",
  },
  "actor-priority": {
    description: "Priorización de actores con scores citados (confirmación humana).",
    api: "POST /api/v1/ai/dossiers/{id}/actor-partnership/runs",
  },
  "entity-resolution": {
    description: "Resolución de entidades con NIF preferente (sin fusión automática).",
    api: "POST /api/v1/ai/dossiers/{id}/entity-resolution/runs",
  },
  "custom-brief": { description: "Brief libre y plan de informe personalizado.", api: "POST /api/v1/dossiers/{id}/reports/custom" },
  signals: { description: "Señales asociadas a este expediente.", api: "GET /api/v1/dossiers/{id}/signals" },
  opportunities: { description: "Oportunidades y puntuación del expediente.", api: "GET /api/v1/dossiers/{id}/opportunities" },
  procurement: { description: "Licitaciones y adjudicaciones PLACSP fijadas como evidencia.", api: "GET /api/v1/dossiers/{id}/procurement" },
  risks: { description: "Riesgos, escenarios y mitigaciones del expediente.", api: "GET /api/v1/dossiers/{id}/risks" },
  actors: { description: "Actores y relaciones en contexto.", api: "GET /api/v1/dossiers/{id}/actors" },
  investigations: { description: "Investigaciones empresariales trazables con revisión humana.", api: "GET /api/v1/dossiers/{id}/investigations" },
  meetings: { description: "Reuniones, documentos preparatorios y seguimiento.", api: "GET /api/v1/dossiers/{id}/meetings" },
  tasks: { description: "Tareas y trabajo pendiente del expediente.", api: "GET /api/v1/dossiers/{id}/tasks" },
  documents: { description: "Documentos, búsqueda y evidencias citables.", api: "GET /api/v1/dossiers/{id}/documents" },
  decisions: { description: "Decisiones humanas y su trazabilidad.", api: "GET /api/v1/dossiers/{id}/decisions" },
  settings: { description: "Configuración y monitores del expediente.", api: "GET/PATCH /api/v1/dossiers/{id}" },
};

export default async function DossierSectionPage({
  params,
}: {
  params: Promise<{ id: string; section: string }>;
}) {
  const { id, section } = await params;
  const tab = DOSSIER_TABS.find((item) => item.segment === section);
  const copy = sectionCopy[section];
  if (!tab || !copy || section === "reports") notFound();
  return (
    <AuthBoundary permission={tab.permission}>
      {(["signals", "opportunities", "risks"] as const).includes(
        section as IntelligenceSectionKind,
      ) ? (
        <DossierIntelligenceSection
          dossierId={id}
          kind={section as IntelligenceSectionKind}
        />
      ) : (["actors", "meetings", "tasks", "decisions"] as const).includes(
          section as DossierWorkKind,
        ) ? (
        <DossierWorkSection dossierId={id} kind={section as DossierWorkKind} />
      ) : section === "documents" ? (
        <DossierDocumentsSection dossierId={id} />
      ) : section === "procurement" ? (
        <DossierProcurementSection dossierId={id} />
      ) : section === "investigations" ? (
        <DossierInvestigationsSection dossierId={id} />
      ) : section === "activity" ? (
        <DossierActivitySection dossierId={id} />
      ) : section === "ask" ? (
        <DossierAskSection dossierId={id} />
      ) : section === "intake" ? (
        <DossierIntakeSection dossierId={id} />
      ) : section === "opportunity-analysis" ? (
        <DossierOpportunityAnalysisSection dossierId={id} />
      ) : section === "risk-analysis" ? (
        <DossierRiskAnalysisSection dossierId={id} />
      ) : section === "actor-priority" ? (
        <DossierActorPartnershipSection dossierId={id} />
      ) : section === "entity-resolution" ? (
        <DossierEntityResolutionSection dossierId={id} />
      ) : section === "custom-brief" ? (
        <DossierCustomBriefSection dossierId={id} />
      ) : (
        <DossierSettingsSection dossierId={id} />
      )}
    </AuthBoundary>
  );
}
