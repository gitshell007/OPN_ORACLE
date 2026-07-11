import { AuthBoundary } from "@/components/auth/auth-boundary";
import { PlatformShell } from "@/components/platform/platform-shell";

export const dynamic = "force-dynamic";
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <AuthBoundary platform>
      <PlatformShell>{children}</PlatformShell>
    </AuthBoundary>
  );
}
