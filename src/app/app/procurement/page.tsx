import { AuthBoundary } from "@/components/auth/auth-boundary";
import { ProcurementWorkspace } from "@/components/procurement/procurement-workspace";

export default function ProcurementPage() {
  return (
    <AuthBoundary permission="opportunity.read">
      <ProcurementWorkspace />
    </AuthBoundary>
  );
}
