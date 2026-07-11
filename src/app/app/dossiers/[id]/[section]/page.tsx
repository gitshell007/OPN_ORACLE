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
import { DossierDocumentsSection } from "@/components/dossiers/dossier-documents-section";
import { DossierSettingsSection } from "@/components/dossiers/dossier-settings-section";
import { DOSSIER_TABS } from "@/lib/app-routes";

const sectionCopy: Record<string, { description: string; api: string }> = {
  signals: { description: "Señales asociadas a este expediente.", api: "GET /api/v1/dossiers/{id}/signals" },
  opportunities: { description: "Oportunidades y puntuación del expediente.", api: "GET /api/v1/dossiers/{id}/opportunities" },
  risks: { description: "Riesgos, escenarios y mitigaciones del expediente.", api: "GET /api/v1/dossiers/{id}/risks" },
  actors: { description: "Actores y relaciones en contexto.", api: "GET /api/v1/dossiers/{id}/actors" },
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
      ) : (
        <DossierSettingsSection dossierId={id} />
      )}
    </AuthBoundary>
  );
}
