import { AuthBoundary } from "@/components/auth/auth-boundary";

export default function ExportsLayout({ children }: { children: React.ReactNode }) {
  return <AuthBoundary permission="export.create">{children}</AuthBoundary>;
}
