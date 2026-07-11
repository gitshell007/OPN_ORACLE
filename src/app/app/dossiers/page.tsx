import { AuthBoundary } from "@/components/auth/auth-boundary";
import { DossierInventory } from "@/components/dossiers/dossier-inventory";

export default function DossiersPage() {
  return (
    <AuthBoundary permission="dossier.read">
      <DossierInventory />
    </AuthBoundary>
  );
}
