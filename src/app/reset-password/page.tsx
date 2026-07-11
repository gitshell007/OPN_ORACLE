import { Suspense } from "react";
import { NewPasswordPage } from "@/components/auth/auth-pages";
export const dynamic = "force-dynamic";
export default function Page() {
  return (
    <Suspense fallback={<div className="auth-state">Validando enlace…</div>}>
      <NewPasswordPage mode="reset" />
    </Suspense>
  );
}
