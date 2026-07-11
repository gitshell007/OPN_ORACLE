"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { X } from "lucide-react";
import { useState } from "react";
export function PrototypeSwitcher() {
  const path = usePathname();
  const [visible, setVisible] = useState(true);
  if (!visible) return null;
  const suffix = path.includes("/settings")
    ? "/settings"
    : path.includes("/dossiers/")
      ? `/dossiers/${path.split("/dossiers/")[1]}`
      : "/portfolio";
  return (
    <nav className="prototype-switcher" aria-label="Cambiar concepto">
      <span>Prototipo</span>
      <Link
        href={`/concept-a${suffix}`}
        aria-current={path.startsWith("/concept-a") ? "page" : undefined}
      >
        A · Vector
      </Link>
      <Link
        href={`/concept-b${suffix}`}
        aria-current={path.startsWith("/concept-b") ? "page" : undefined}
      >
        B · Horizon
      </Link>
      <button
        className="close"
        onClick={() => setVisible(false)}
        aria-label="Ocultar selector para captura"
      >
        <X size={14} />
      </button>
    </nav>
  );
}
