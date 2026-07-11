"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  Bell,
  ChevronDown,
  LayoutDashboard,
  Menu,
  Plus,
  Settings2,
  SlidersHorizontal,
  UserRound,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { CommandPalette } from "@/components/shared/command-palette";
import { CreateDossierDialog } from "@/components/shared/create-dossier-dialog";
import { useOracle } from "@/components/shared/oracle-provider";
import { PrototypeSwitcher } from "@/components/shared/prototype-switcher";

export function HorizonShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { signals, settings } = useOracle();
  const [createOpen, setCreateOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const unread = signals.filter((signal) => signal.status === "new").length;

  return (
    <div className="horizon">
      <a className="b-skip" href="#horizon-content">
        Saltar al contenido
      </a>
      <header className="b-header">
        <div className="b-header-inner">
          <Link
            className="b-brand"
            href="/concept-b/portfolio"
            aria-label="Oracle Horizon, inicio"
          >
            <span className="b-brand-mark" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            <span>
              <strong>OPN Oracle</strong>
              <small>Horizon Decision Canvas</small>
            </span>
          </Link>
          <nav
            className={`b-nav ${mobileOpen ? "open" : ""}`}
            aria-label="Navegación principal"
          >
            <Link
              href="/concept-b/portfolio"
              onClick={() => setMobileOpen(false)}
              aria-current={
                path.includes("portfolio") || path.includes("dossiers")
                  ? "page"
                  : undefined
              }
            >
              <LayoutDashboard size={16} /> Canvas
            </Link>
            <Link
              href="/concept-b/portfolio#signals"
              onClick={() => setMobileOpen(false)}
            >
              <SlidersHorizontal size={16} /> Señales
            </Link>
            <Link
              href="/concept-b/settings"
              onClick={() => setMobileOpen(false)}
              aria-current={path.includes("settings") ? "page" : undefined}
            >
              <Settings2 size={16} /> Ajustes
            </Link>
          </nav>
          <div className="b-header-tools">
            <CommandPalette concept="b" onCreate={() => setCreateOpen(true)} />
            <button
              className="b-icon-button b-notify"
              aria-label={`${unread} notificaciones nuevas`}
              onClick={() =>
                toast.info("Cola de decisiones", {
                  description: `${unread} señales esperan revisión.`,
                })
              }
            >
              <Bell size={18} />
              {unread > 0 && <span>{unread}</span>}
            </button>
            <DropdownMenu.Root>
              <DropdownMenu.Trigger
                className="b-user-trigger"
                aria-label="Abrir menú de usuario"
              >
                <span className="b-avatar">LH</span>
                <span className="b-user-copy">
                  <strong>{settings.name}</strong>
                  <small>{settings.role}</small>
                </span>
                <ChevronDown size={14} />
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content
                  className="b-menu"
                  align="end"
                  sideOffset={8}
                >
                  <DropdownMenu.Label className="b-menu-label">
                    Espacio de demostración
                  </DropdownMenu.Label>
                  <DropdownMenu.Item asChild>
                    <Link href="/concept-b/settings">
                      <UserRound size={16} /> Perfil y preferencias
                    </Link>
                  </DropdownMenu.Item>
                  <DropdownMenu.Separator />
                  <DropdownMenu.Item asChild>
                    <Link href="/concept-a/portfolio">
                      <Settings2 size={16} /> Comparar con Vector
                    </Link>
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
            <button
              className="b-create-top"
              onClick={() => setCreateOpen(true)}
            >
              <Plus size={17} /> Nuevo expediente
            </button>
            <button
              className="b-mobile-menu"
              onClick={() => setMobileOpen((v) => !v)}
              aria-expanded={mobileOpen}
              aria-label="Abrir navegación"
            >
              {mobileOpen ? <X /> : <Menu />}
            </button>
          </div>
        </div>
      </header>
      <main id="horizon-content" className="b-main">
        {children}
      </main>
      <footer className="b-footer">
        <span>OPN Oracle · Horizon Decision Canvas</span>
        <span>Datos sintéticos · 10 jul 2026</span>
      </footer>
      <CreateDossierDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        accent="b"
      />
      <PrototypeSwitcher />
    </div>
  );
}
