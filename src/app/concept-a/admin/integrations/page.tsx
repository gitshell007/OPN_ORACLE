import { SignalAdmin } from "@/components/admin/signal-admin";
import { AuthBoundary } from "@/components/auth/auth-boundary";

export default function Page() {
  return (
    <AuthBoundary permission="tenant.integrations.manage">
      <SignalAdmin />
    </AuthBoundary>
  );
}
