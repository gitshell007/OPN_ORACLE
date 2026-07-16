import { notFound } from "next/navigation";
import { AuthBoundary } from "@/components/auth/auth-boundary";
import { EntityDossier } from "@/components/entity-intel/entity-dossier";

const supportedTypes = new Set(["company", "person"]);

export default async function EntityGraphPage({
  params,
}: {
  params: Promise<{ type: string; norm: string }>;
}) {
  const { type, norm } = await params;
  if (!supportedTypes.has(type)) notFound();
  const name = decodeURIComponent(norm).trim();
  if (name.length < 2) notFound();
  return (
    <AuthBoundary permission="actor.read">
      <EntityDossier name={name} type={type as "company" | "person"} />
    </AuthBoundary>
  );
}
