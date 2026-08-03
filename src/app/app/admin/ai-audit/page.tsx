import { Suspense } from "react";
import { AiAuditPanel } from "@/components/admin/ai-audit-panel";
import { AuthBoundary } from "@/components/auth/auth-boundary";

export default function Page() {
  return (
    <AuthBoundary permission="audit.read">
      <Suspense
        fallback={
          <div className="auth-state" role="status">
            Cargando auditoría de IA…
          </div>
        }
      >
        <AiAuditPanel />
      </Suspense>
    </AuthBoundary>
  );
}
