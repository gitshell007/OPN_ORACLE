"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "./auth-provider";

export function AuthBoundary({
  children,
  permission,
  platform = false,
  requireTenant = false,
}: {
  children: React.ReactNode;
  permission?: string;
  platform?: boolean;
  requireTenant?: boolean;
}) {
  const auth = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const allowed = !permission || auth.can(permission);
  const platformAllowed =
    !platform || auth.identity?.user.platform_role === "super_admin";
  const tenantAllowed =
    !requireTenant || Boolean(auth.identity?.active_tenant_id);
  const redirectSuperAdminToPlatform =
    auth.status === "authenticated" &&
    requireTenant &&
    !tenantAllowed &&
    auth.identity?.user.platform_role === "super_admin";
  useEffect(() => {
    if (auth.status === "anonymous")
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (redirectSuperAdminToPlatform)
      router.replace("/platform/tenants");
  }, [auth.status, pathname, redirectSuperAdminToPlatform, router]);

  if (auth.status === "initializing")
    return (
      <div className="auth-state" role="status">
        <span className="auth-spinner" />
        Verificando sesión…
      </div>
    );
  if (auth.status === "anonymous")
    return (
      <div className="auth-state" role="status">
        Redirigiendo al acceso seguro…
      </div>
    );
  if (redirectSuperAdminToPlatform)
    return (
      <div className="auth-state" role="status">
        Redirigiendo a la administración de plataforma…
      </div>
    );
  if (auth.status === "session_expired")
    return (
      <div className="auth-state">
        <h1>Tu sesión ha caducado</h1>
        <p>
          Vuelve a identificarte para continuar. No guardamos credenciales en
          este dispositivo.
        </p>
        <Link href={`/login?next=${encodeURIComponent(pathname)}`}>
          Volver a iniciar sesión
        </Link>
      </div>
    );
  if (auth.status === "tenant_suspended")
    return (
      <div className="auth-state">
        <h1>Organización suspendida</h1>
        <p>
          El acceso está pausado. Contacta con un administrador de plataforma.
        </p>
      </div>
    );
  if (
    auth.status === "forbidden" ||
    !allowed ||
    !platformAllowed ||
    !tenantAllowed
  )
    return (
      <div className="auth-state">
        <h1>Acceso restringido</h1>
        <p>Tu cuenta no dispone del permiso necesario para esta sección.</p>
        <Link href="/app">Volver a Inicio</Link>
      </div>
    );
  if (auth.status === "error")
    return (
      <div className="auth-state">
        <h1>No podemos verificar la sesión</h1>
        <p>Comprueba la conexión y vuelve a intentarlo.</p>
        <button onClick={() => void auth.refresh()}>Reintentar</button>
      </div>
    );
  return children;
}

export function PermissionGate({
  permission,
  children,
  fallback = null,
}: {
  permission: string;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  return useAuth().can(permission) ? children : fallback;
}

export function AnyPermissionBoundary({
  permissions,
  children,
}: {
  permissions: readonly string[];
  children: React.ReactNode;
}) {
  const auth = useAuth();
  if (permissions.some((permission) => auth.can(permission))) return children;
  return (
    <div className="auth-state">
      <h1>Acceso restringido</h1>
      <p>Tu cuenta no dispone de permisos administrativos en esta organización.</p>
      <Link href="/app">Volver a Inicio</Link>
    </div>
  );
}
