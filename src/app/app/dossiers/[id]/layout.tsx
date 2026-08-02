import Link from "next/link";
import { Settings } from "lucide-react";
import { DossierCompletionWizard } from "@/components/dossiers/dossier-completion-wizard";
import {
  DossierNavigation,
  DossierSubnav,
} from "@/components/navigation/product-navigation";

export default async function DossierLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const base = `/app/dossiers/${encodeURIComponent(id)}`;
  return (
    <>
      <div className="dossier-nav-row">
        <DossierNavigation dossierId={id} />
        <div className="dossier-nav__utility">
          {/* Preguntar es transversal: se llega desde cualquier sección, no
              sólo desde su grupo. */}
          <Link
            className="vector-secondary"
            href={`${base}/ask`}
            data-testid="dossier-ask-shortcut"
          >
            Preguntar
          </Link>
          <Link
            className="icon-button bordered"
            href={`${base}/settings`}
            data-testid="dossier-settings-shortcut"
            aria-label="Configuración del expediente"
            title="Configuración del expediente"
          >
            <Settings size={16} aria-hidden="true" />
          </Link>
          <DossierCompletionWizard dossierId={id} />
        </div>
      </div>
      <DossierSubnav dossierId={id} />
      {children}
    </>
  );
}
