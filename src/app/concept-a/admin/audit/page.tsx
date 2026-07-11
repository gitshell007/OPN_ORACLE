import { TenantAudit } from "@/components/admin/tenant-admin";
import { AuthBoundary } from "@/components/auth/auth-boundary";
export default function Page() {
  return (
    <AuthBoundary permission="audit.read">
      <TenantAudit />
    </AuthBoundary>
  );
}
