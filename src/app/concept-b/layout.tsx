import "@/styles/concept-b.css";
import { redirect } from "next/navigation";
import { HorizonShell } from "@/components/concept-b/horizon-shell";
import { OracleProvider } from "@/components/shared/oracle-provider";

export default function ConceptBLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  if (process.env.NODE_ENV === "production") {
    redirect("/app");
  }

  return (
    <OracleProvider>
      <HorizonShell>{children}</HorizonShell>
    </OracleProvider>
  );
}
