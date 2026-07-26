import { AuthBoundary } from "@/components/auth/auth-boundary";
import { ProductProcurementStats } from "@/components/procurement/product-procurement-stats";

export default function ProcurementStatsPage() {
  return (
    <AuthBoundary permission="opportunity.read">
      <ProductProcurementStats />
    </AuthBoundary>
  );
}
