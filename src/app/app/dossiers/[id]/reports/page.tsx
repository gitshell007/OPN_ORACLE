import { AuthBoundary } from "@/components/auth/auth-boundary";
import { DossierReportsRoute } from "@/components/reporting/report-library";

export default function DossierReportsPage() {
  return (
    <AuthBoundary permission="report.read">
      <DossierReportsRoute />
    </AuthBoundary>
  );
}
