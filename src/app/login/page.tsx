import { Suspense } from "react";
import { LoginPage } from "@/components/auth/auth-pages";
export const dynamic = "force-dynamic";
export default function Page() {
  return (
    <Suspense fallback={<div className="auth-state">Preparando acceso…</div>}>
      <LoginPage />
    </Suspense>
  );
}
