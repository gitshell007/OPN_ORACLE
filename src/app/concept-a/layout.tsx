import "@/styles/concept-a.css";
import { redirect } from "next/navigation";
import { VectorShell } from "@/components/concept-a/vector-shell";
import { AuthBoundary } from "@/components/auth/auth-boundary";
import { OracleProvider } from "@/components/shared/oracle-provider";

export default function ConceptALayout({
  children,
}: {
  children: React.ReactNode;
}) {
  if (process.env.NODE_ENV === "production") {
    redirect("/app");
  }

  return (
    <OracleProvider>
      <AuthBoundary requireTenant>
        <VectorShell>{children}</VectorShell>
      </AuthBoundary>
    </OracleProvider>
  );
}
