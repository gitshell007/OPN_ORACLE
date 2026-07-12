import { notFound } from "next/navigation";
import { AuthBoundary } from "@/components/auth/auth-boundary";
import { GlobalResourceInventory, type GlobalResourceSection } from "@/components/navigation/global-resource-inventory";
import { ProductChanges } from "@/components/navigation/product-changes";

const sections = {
  dossiers: {
    title: "Expedientes",
    description: "Todos los expedientes estratégicos que puedes consultar.",
    permission: "dossier.read",
    api: "GET /api/v1/dossiers",
  },
  changes: {
    title: "Qué ha cambiado",
    description: "Cambios recientes que pueden influir en tus expedientes.",
    permission: "dossier.read",
    api: "Agregación de señales, riesgos, oportunidades, decisiones y auditoría",
  },
  signals: {
    title: "Señales",
    description: "Noticias y avisos que pueden afectar a tus expedientes.",
    permission: "signal.read",
    api: "GET /api/v1/signals",
  },
  opportunities: {
    title: "Oportunidades",
    description: "Oportunidades que puedes valorar y convertir en acciones.",
    permission: "opportunity.read",
    api: "GET /api/v1/opportunities",
  },
  risks: {
    title: "Riesgos",
    description: "Situaciones que pueden frenar el avance y requieren seguimiento.",
    permission: "risk.read",
    api: "GET /api/v1/risks",
  },
  actors: {
    title: "Actores",
    description: "Personas, empresas y organismos relacionados con tus expedientes.",
    permission: "actor.read",
    api: "GET /api/v1/actors y relaciones",
  },
  meetings: {
    title: "Reuniones",
    description: "Reuniones, preparación y próximos pasos de tus expedientes.",
    permission: "meeting.read",
    api: "GET /api/v1/meetings",
  },
  tasks: {
    title: "Tareas",
    description: "Acciones pendientes, responsables y fechas de tus expedientes.",
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
