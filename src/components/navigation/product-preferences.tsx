"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { toast } from "sonner";
import { SettingsHeader } from "@/components/auth/account-security";
import { useAuth } from "@/components/auth/auth-provider";

type Density = "compact" | "balanced" | "comfortable";
type FontScale = "small" | "medium" | "large";

const FONT_LABELS: Record<FontScale, string> = {
  small: "Pequeña",
  medium: "Media",
  large: "Grande",
};

function applyFontScale(value: FontScale) {
  document.documentElement.dataset.fontScale = value;
}

export function ProductPreferences() {
  const pathname = usePathname();
  const userId = useAuth().identity!.user.id;
  const densityKey = `oracle:ui:density:${userId}`;
  const navigationKey = `oracle:nav:compact:${userId}`;
  const fontKey = `oracle:ui:font-scale:${userId}`;
  const [density, setDensity] = useState<Density>("balanced");
  const [compact, setCompact] = useState(false);
  const [fontScale, setFontScale] = useState<FontScale>("medium");
  const showAccountTabs = pathname.startsWith("/app/account");

  useEffect(() => {
    const kickoff = window.setTimeout(() => {
      const stored = window.localStorage.getItem(densityKey);
      if (stored === "compact" || stored === "comfortable" || stored === "balanced") {
        setDensity(stored);
      }
      setCompact(window.localStorage.getItem(navigationKey) === "true");
      const font = window.localStorage.getItem(fontKey);
      if (font === "small" || font === "medium" || font === "large") {
        setFontScale(font);
        applyFontScale(font);
      }
    }, 0);
    return () => window.clearTimeout(kickoff);
  }, [densityKey, fontKey, navigationKey]);

  const save = () => {
    window.localStorage.setItem(densityKey, density);
    window.localStorage.setItem(navigationKey, String(compact));
    window.localStorage.setItem(fontKey, fontScale);
    document.documentElement.dataset.density = density;
    applyFontScale(fontScale);
    window.dispatchEvent(new Event("oracle:navigation-preference"));
    toast.success("Preferencias visuales guardadas", {
      description: "Solo se conserva configuración de interfaz, nunca contenido sensible.",
    });
  };

  const reset = () => {
    window.localStorage.removeItem(densityKey);
    window.localStorage.removeItem(navigationKey);
    window.localStorage.removeItem(fontKey);
    delete document.documentElement.dataset.density;
    delete document.documentElement.dataset.fontScale;
    setDensity("balanced");
    setCompact(false);
    setFontScale("medium");
    window.dispatchEvent(new Event("oracle:navigation-preference"));
    toast.success("Preferencias visuales restablecidas");
  };

  return (
    <div className="settings-page">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Preferencias personales</div>
          <h1>Preferencias</h1>
          <p>
            Estas opciones se guardan únicamente en este dispositivo. El idioma,
            la zona horaria y la accesibilidad avanzada estarán disponibles en
            una próxima actualización.
          </p>
        </div>
      </section>
      {showAccountTabs && <SettingsHeader active="preferences" />}
      <section className="settings-section">
        <header>
          <h2>Tamaño de fuente</h2>
          <p>Ajusta la legibilidad de la interfaz productiva sin cambiar la densidad.</p>
        </header>
        <div className="segmented choice" aria-label="Tamaño de fuente">
          {(["small", "medium", "large"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={fontScale === value}
              onClick={() => {
                setFontScale(value);
                applyFontScale(value);
              }}
            >
              {FONT_LABELS[value]}
            </button>
          ))}
        </div>
      </section>
      <section className="settings-section">
        <header>
          <h2>Densidad</h2>
          <p>Ajusta el ritmo visual sin reducir la legibilidad.</p>
        </header>
        <div className="segmented choice" aria-label="Densidad de interfaz">
          {(["compact", "balanced", "comfortable"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={density === value}
              onClick={() => setDensity(value)}
            >
              {value === "compact"
                ? "Compacta"
                : value === "balanced"
                  ? "Equilibrada"
                  : "Cómoda"}
            </button>
          ))}
        </div>
      </section>
      <section className="settings-section">
        <header>
          <h2>Navegación</h2>
          <p>El estado se aísla por usuario y no contiene datos de negocio.</p>
        </header>
        <label className="setting-checkbox">
          <input
            type="checkbox"
            checked={compact}
            onChange={(event) => setCompact(event.target.checked)}
          />
          Abrir la navegación en modo compacto
        </label>
      </section>
      <div className="placeholder-actions">
        <button className="vector-primary" type="button" onClick={save}>Guardar</button>
        <button className="vector-secondary" type="button" onClick={reset}>Restablecer</button>
      </div>
    </div>
  );
}
