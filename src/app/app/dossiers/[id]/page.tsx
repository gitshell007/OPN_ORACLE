import { AuthBoundary } from "@/components/auth/auth-boundary";
import { ProductDossier } from "@/components/navigation/product-dossier";

export default function DossierPage() {
  return (
    <AuthBoundary permission="dossier.read">
      <ProductDossier />
    </AuthBoundary>
  );
}
