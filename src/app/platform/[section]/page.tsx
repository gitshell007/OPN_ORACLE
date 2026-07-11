import { notFound } from "next/navigation";
import { PlatformOperationalOverview, PlatformSystem } from "@/components/platform/platform-pages";
import { PlatformBackups } from "@/components/platform/platform-backups";

const sections = {
  jobs: {
    title: "Trabajos y colas",
    description: "Salud global de trabajos, colas y reintentos sin información sensible.",
  },
  integrations: {
    title: "Integraciones",
    description: "Salud agregada de conexiones e incidencias de integración.",
  },
  system: {
    title: "Salud técnica",
    description: "Estado resumido de servicios y dependencias permitidas.",
  },
  backups: {
    title: "Copias de seguridad",
    description: "Creación, retención y recuperación de copias de plataforma.",
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
