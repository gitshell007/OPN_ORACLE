import { Suspense } from "react";
import { ActorDuplicateMergePanel } from "@/components/actors/actor-duplicate-merge-panel";
import { AuthBoundary } from "@/components/auth/auth-boundary";

export default function Page() {
  return (
    <AuthBoundary permission="actor.read">
      <Suspense
        fallback={
          <div className="auth-state" role="status">
            Cargando candidatos a fusión…
          </div>
        }
      >
        <ActorDuplicateMergePanel />
      </Suspense>
    </AuthBoundary>
  );
}
