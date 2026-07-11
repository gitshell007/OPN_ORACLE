import { AnyPermissionBoundary } from "@/components/auth/auth-boundary";
import { AdminNavigation } from "@/components/navigation/product-navigation";

const adminPermissions = [
  "tenant.users.manage",
  "tenant.settings.manage",
  "tenant.integrations.manage",
  "audit.read",
] as const;

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AnyPermissionBoundary permissions={adminPermissions}>
      <section className="page-heading admin-heading">
        <div>
          <div className="eyebrow">Organización activa</div>
          <h1>Administración</h1>
          <p>Configuración de la organización separada de las preferencias personales.</p>
        </div>
      </section>
      <AdminNavigation />
      {children}
    </AnyPermissionBoundary>
  );
}
