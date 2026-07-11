import { Suspense } from "react";
import { NewPasswordPage } from "@/components/auth/auth-pages";
export const dynamic = "force-dynamic";
export default function Page() {
  return (
    <Suspense
      fallback={<div className="auth-state">Validando invitación…</div>}
    >
      <NewPasswordPage mode="invite" />
    </Suspense>
  );
}
