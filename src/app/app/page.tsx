import { AuthBoundary } from "@/components/auth/auth-boundary";
import { ProductHome } from "@/components/navigation/product-home";

export default function HomePage() {
  return (
    <AuthBoundary permission="dossier.read">
      <ProductHome />
    </AuthBoundary>
  );
}
