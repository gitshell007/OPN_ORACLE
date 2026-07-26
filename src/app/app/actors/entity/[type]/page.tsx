import { notFound } from "next/navigation";
import { AuthBoundary } from "@/components/auth/auth-boundary";
import { EntityDossier } from "@/components/entity-intel/entity-dossier";

const supportedTypes = new Set(["company", "person"]);

export default async function EntityDossierByQueryPage({
  params,
  searchParams,
}: {
  params: Promise<{ type: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { type } = await params;
  if (!supportedTypes.has(type)) notFound();

  const query = await searchParams;
  const rawName = query.name;
  const name = (Array.isArray(rawName) ? rawName[0] : rawName)?.trim() ?? "";
  if (name.length < 2) notFound();

  return (
    <AuthBoundary permission="actor.read">
      <EntityDossier name={name} type={type as "company" | "person"} />
    </AuthBoundary>
  );
}
