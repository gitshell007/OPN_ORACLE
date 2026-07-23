import type { Metadata } from "next";
import "@/styles/concept-a.css";
import { AuthBoundary } from "@/components/auth/auth-boundary";
import { VectorShell } from "@/components/concept-a/vector-shell";

export const metadata: Metadata = {
  title: {
    absolute: "OPN Oracle",
  },
  description: "Inteligencia estratégica trazable",
};

export const dynamic = "force-dynamic";

export default function ProductLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthBoundary requireTenant>
      <VectorShell>{children}</VectorShell>
    </AuthBoundary>
  );
}
