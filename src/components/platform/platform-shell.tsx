"use client";

import { LogOut, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/auth-provider";
import { toast } from "sonner";
import { breadcrumbsForPath, PLATFORM_ROUTES } from "@/lib/app-routes";

export function PlatformShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const auth = useAuth();
  const links = PLATFORM_ROUTES.filter((route) => route.nav);
  const crumbs = breadcrumbsForPath(pathname);
  return (
    <div className="platform-app">
      <a className="skip-link" href="#platform-content">
        Saltar al contenido principal
      </a>
      <header className="platform-header">
        <Link href="/platform" className="platform-brand">
          <span>O</span>
          <strong>OPN Oracle</strong>
          <b>
            <ShieldCheck size={14} />
            Datos de plataforma
          </b>
        </Link>
        <nav aria-label="Plataforma">
          {links.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              className={
                pathname === href ||
                (href !== "/platform" && pathname.startsWith(`${href}/`))
                  ? "active"
                  : ""
              }
              href={href}
              aria-label={label}
              aria-current={
                pathname === href ||
                (href !== "/platform" && pathname.startsWith(`${href}/`))
                  ? "page"
                  : undefined
              }
            >
              <Icon size={16} />
              {label}
            </Link>
          ))}
        </nav>
        <div className="platform-user">
          <span>{auth.identity!.user.display_name}</span>
          <button
            onClick={() =>
              void auth
                .logout()
                .then(() => router.replace("/login"))
                .catch(() => toast.error("No se pudo cerrar la sesión"))
            }
            aria-label="Cerrar sesión"
          >
            <LogOut size={16} />
          </button>
        </div>
      </header>
      <div className="platform-notice">
        <ShieldCheck size={16} />
        <span>
          Contexto de plataforma. Las acciones afectan a organizaciones y quedan
          auditadas.
        </span>
        <Link href="/app">Volver a Oracle</Link>
      </div>
      <nav className="platform-breadcrumbs" aria-label="Migas de pan">
        <Link href="/platform">Plataforma</Link>
        {crumbs
          .filter((crumb) => crumb.label !== "Plataforma")
          .map((crumb) => (
            <span key={`${crumb.href ?? "current"}-${crumb.label}`}>
              <i>/</i>
              {crumb.href ? (
                <Link href={crumb.href}>{crumb.label}</Link>
              ) : (
                <strong aria-current="page">{crumb.label}</strong>
              )}
            </span>
          ))}
      </nav>
      <main className="platform-content" id="platform-content" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
