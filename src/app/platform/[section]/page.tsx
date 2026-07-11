import { notFound } from "next/navigation";
import { PlatformOperationalOverview, PlatformSystem } from "@/components/platform/platform-pages";
import { PlatformBackups } from "@/components/platform/platform-backups";

const sections = {
  jobs: {
    title: "Trabajos y colas",
    description: "Salud global de trabajos, colas y reintentos sin payload sensible.",
    api: "Agregado global de jobs pendiente de contrato",
  },
  integrations: {
    title: "Integraciones",
    description: "Salud agregada de conexiones e incidencias de integración.",
    api: "Agregado global de integraciones pendiente de contrato",
  },
  system: {
    title: "Salud técnica",
    description: "Estado resumido de servicios y dependencias permitidas.",
    api: "GET /health y GET /meta",
  },
  backups: {
    title: "Copias de seguridad",
    description: "Creación, retención y recuperación de copias de plataforma.",
    api: "GET y POST /api/v1/platform/backups",
  },
} as const;

export default async function Page({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  const config = sections[section as keyof typeof sections];
  if (!config) notFound();
  if (section === "system") return <PlatformSystem />;
  if (section === "backups") return <PlatformBackups />;
  if (section === "jobs" || section === "integrations") {
    return <PlatformOperationalOverview kind={section} />;
  }
  notFound();
}
