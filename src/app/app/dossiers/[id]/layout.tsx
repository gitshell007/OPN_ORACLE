import { DossierCompletionWizard } from "@/components/dossiers/dossier-completion-wizard";
import { DossierNavigation } from "@/components/navigation/product-navigation";

export default async function DossierLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <>
      <div className="dossier-nav-row">
        <DossierNavigation dossierId={id} />
        <DossierCompletionWizard dossierId={id} />
      </div>
      {children}
    </>
  );
}
