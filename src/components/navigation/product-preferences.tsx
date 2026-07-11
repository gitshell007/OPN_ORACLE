"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useAuth } from "@/components/auth/auth-provider";

type Density = "compact" | "balanced" | "comfortable";

export function ProductPreferences() {
  const userId = useAuth().identity!.user.id;
  const densityKey = `oracle:ui:density:${userId}`;
  const navigationKey = `oracle:nav:compact:${userId}`;
  const [density, setDensity] = useState<Density>("balanced");
  const [compact, setCompact] = useState(false);

  useEffect(() => {
    const kickoff = window.setTimeout(() => {
      const stored = window.localStorage.getItem(densityKey);
      if (stored === "compact" || stored === "comfortable" || stored === "balanced") {
        setDensity(stored);
      }
      setCompact(window.localStorage.getItem(navigationKey) === "true");
    }, 0);
    return () => window.clearTimeout(kickoff);
  }, [densityKey, navigationKey]);

  const save = () => {
    window.localStorage.setItem(densityKey, density);
    window.localStorage.setItem(navigationKey, String(compact));
    document.documentElement.dataset.density = density;
    window.dispatchEvent(new Event("oracle:navigation-preference"));
    toast.success("Preferencias visuales guardadas", {
      description: "Solo se conserva configuración de interfaz, nunca contenido sensible.",
    });
  };

  const reset = () => {
    window.localStorage.removeItem(densityKey);
    window.localStorage.removeItem(navigationKey);
    delete document.documentElement.dataset.density;
    setDensity("balanced");
    setCompact(false);
    window.dispatchEvent(new Event("oracle:navigation-preference"));
    toast.success("Preferencias visuales restablecidas");
  };

  return (
    <div className="settings-page">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Preferencias personales</div>
          <h1>Apariencia y navegación</h1>
          <p>
            Estas opciones son locales al dispositivo. Idioma, zona horaria y
            accesibilidad durable se habilitarán cuando exista su endpoint.
          </p>
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
        <button className="vector-primary" onClick={save}>Guardar</button>
        <button className="vector-secondary" onClick={reset}>Restablecer</button>
      </div>
    </div>
  );
}
