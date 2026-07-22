import { TenantAIAdmin } from "@/components/admin/tenant-admin";
import { AuthBoundary } from "@/components/auth/auth-boundary";

export default function Page() {
  return <AuthBoundary permission="tenant.settings.manage"><TenantAIAdmin /></AuthBoundary>;
}
