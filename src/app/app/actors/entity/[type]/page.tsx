import { notFound } from "next/navigation";
import { AuthBoundary } from "@/components/auth/auth-boundary";
import { EntityDossier } from "@/components/entity-intel/entity-dossier";
import { EntitySearchPanel } from "@/components/entity-intel/entity-intel";

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

  // /app/actors/entity/company without ?name=… is a valid entry point (e.g. after
  // login or a truncated bookmark). Show search instead of a hard 404.
  if (name.length < 2) {
    return (
      <AuthBoundary permission="actor.read">
        <div className="entity-intel-page">
          <header className="page-heading">
            <div>
              <div className="eyebrow">Inteligencia de entidad</div>
              <h1>{type === "person" ? "Buscar persona" : "Buscar empresa"}</h1>
              <p>
                Indica la denominación registral o el nombre exacto. La ficha se abre con
                la forma canónica{" "}
                <code>?name=…</code> para evitar errores de enrutado con espacios.
              </p>
            </div>
          </header>
          <EntitySearchPanel initialKind={type as "company" | "person"} />
        </div>
      </AuthBoundary>
    );
  }

  return (
    <AuthBoundary permission="actor.read">
      <EntityDossier name={name} type={type as "company" | "person"} />
    </AuthBoundary>
  );
}
