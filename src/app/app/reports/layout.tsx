import { AuthBoundary } from "@/components/auth/auth-boundary";

export default function ReportsLayout({ children }: { children: React.ReactNode }) {
  return <AuthBoundary permission="report.read">{children}</AuthBoundary>;
}
