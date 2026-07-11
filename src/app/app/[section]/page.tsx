import { notFound } from "next/navigation";
import { AuthBoundary } from "@/components/auth/auth-boundary";
import { GlobalResourceInventory, type GlobalResourceSection } from "@/components/navigation/global-resource-inventory";
import { ProductChanges } from "@/components/navigation/product-changes";

const sections = {
  dossiers: {
    title: "Expedientes",
    description: "Inventario global de expedientes estratégicos autorizados.",
    permission: "dossier.read",
    api: "GET /api/v1/dossiers",
  },
  changes: {
    title: "Qué ha cambiado",
    description: "Cambios priorizados, trazables y acotados por fecha.",
    permission: "dossier.read",
    api: "Agregación de señales, riesgos, oportunidades, decisiones y auditoría",
  },
  signals: {
    title: "Señales",
    description: "Bandeja global para revisar señales y abrir su contexto.",
    permission: "signal.read",
    api: "GET /api/v1/signals",
  },
  opportunities: {
    title: "Oportunidades",
    description: "Cartera agregada de oportunidades y siguientes acciones.",
    permission: "opportunity.read",
    api: "GET /api/v1/opportunities",
  },
  risks: {
    title: "Riesgos",
    description: "Registro agregado de riesgos que protegen el avance estratégico.",
    permission: "risk.read",
    api: "GET /api/v1/risks",
  },
  actors: {
    title: "Actores",
    description: "Directorio tabular y relaciones entre actores compartidos.",
    permission: "actor.read",
    api: "GET /api/v1/actors y relaciones",
  },
  meetings: {
    title: "Reuniones",
    description: "Agenda, documentos preparatorios y seguimientos vinculados a expedientes.",
    permission: "meeting.read",
    api: "GET /api/v1/meetings",
  },
  tasks: {
    title: "Tareas",
    description: "Trabajo personal y de equipo con origen y decisión visibles.",
    permission: "task.read",
    api: "GET /api/v1/tasks",
  },
} as const;

export default async function GlobalSectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  const config = sections[section as keyof typeof sections];
  if (!config) notFound();
  if (section === "changes") {
    return <AuthBoundary permission="dossier.read"><ProductChanges /></AuthBoundary>;
  }
  if (["signals", "opportunities", "risks", "actors", "meetings", "tasks"].includes(section)) {
    return (
      <AuthBoundary permission={config.permission}>
        <GlobalResourceInventory section={section as GlobalResourceSection} />
      </AuthBoundary>
    );
  }
  notFound();
}
