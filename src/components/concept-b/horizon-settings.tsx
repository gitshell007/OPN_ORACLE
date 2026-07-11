"use client";

import * as Switch from "@radix-ui/react-switch";
import { Bell, Gauge, RotateCcw, Save, UserRound } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useOracle } from "@/components/shared/oracle-provider";
import { resetDemoState } from "@/lib/oracle/storage";
import type { UserSettings } from "@/lib/oracle/types";

export function HorizonSettings() {
  const { settings, saveSettings } = useOracle();
  return (
    <HorizonSettingsForm
      key={JSON.stringify(settings)}
      settings={settings}
      saveSettings={saveSettings}
    />
  );
}
function HorizonSettingsForm({
  settings,
  saveSettings,
}: {
  settings: UserSettings;
  saveSettings: (value: UserSettings) => Promise<void>;
}) {
  const [draft, setDraft] = useState(settings);
  const [saving, setSaving] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const field = <K extends keyof UserSettings>(
    key: K,
    value: UserSettings[K],
  ) => setDraft((v) => ({ ...v, [key]: value }));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    await saveSettings(draft);
    setSaving(false);
    toast.success("Preferencias guardadas", {
      description: "Se aplican en ambos conceptos.",
    });
  };
  const reset = () => {
    resetDemoState();
    setConfirmReset(false);
    toast.success("Demostración restablecida");
  };
  return (
    <>
      <header className="b-settings-head">
        <p className="b-eyebrow">Configuración del espacio</p>
        <h1>Ajusta tu canvas</h1>
        <p>
          Define el nivel de detalle, el umbral de señales y el ritmo de avisos.
          Los cambios se guardan en este navegador.
        </p>
      </header>
      <form className="b-settings-layout" onSubmit={submit}>
        <nav aria-label="Secciones de preferencias">
          <a href="#profile">
            <UserRound /> Identidad
          </a>
          <a href="#experience">
            <Gauge /> Canvas
          </a>
          <a href="#notifications">
            <Bell /> Avisos
          </a>
        </nav>
        <div className="b-settings-content">
          <section id="profile">
            <div className="b-setting-title">
              <div>
                <span>01</span>
                <h2>Identidad de trabajo</h2>
                <p>Visible en asignaciones y listas de foco.</p>
              </div>
              <span className="b-avatar">LH</span>
            </div>
            <div className="b-settings-grid">
              <label>
                <span>Nombre</span>
                <input
                  value={draft.name}
                  onChange={(e) => field("name", e.target.value)}
                  required
                />
              </label>
              <label>
                <span>Rol</span>
                <input
                  value={draft.role}
                  onChange={(e) => field("role", e.target.value)}
                  required
                />
              </label>
              <label className="wide">
                <span>Correo electrónico</span>
                <input
                  type="email"
                  value={draft.email}
                  onChange={(e) => field("email", e.target.value)}
                  required
                />
              </label>
            </div>
          </section>
          <section id="experience">
            <div className="b-setting-title">
              <div>
                <span>02</span>
                <h2>Comportamiento del canvas</h2>
                <p>Formato de lectura y umbral del radar.</p>
              </div>
            </div>
            <div className="b-settings-grid">
              <label>
                <span>Idioma</span>
                <select
                  value={draft.language}
                  onChange={(e) => field("language", e.target.value)}
                >
                  <option>Español</option>
                  <option>English</option>
                </select>
              </label>
              <label>
                <span>Zona horaria</span>
                <select
                  value={draft.timezone}
                  onChange={(e) => field("timezone", e.target.value)}
                >
                  <option>Europe/Madrid</option>
                  <option>Europe/Lisbon</option>
                  <option>UTC</option>
                </select>
              </label>
              <label>
                <span>Vista inicial</span>
                <select
                  value={draft.landing}
                  onChange={(e) =>
                    field("landing", e.target.value as UserSettings["landing"])
                  }
                >
                  <option value="portfolio">Portfolio</option>
                  <option value="signals">Señales</option>
                </select>
              </label>
              <label>
                <span>Densidad</span>
                <select
                  value={draft.density}
                  onChange={(e) =>
                    field("density", e.target.value as UserSettings["density"])
                  }
                >
                  <option value="comfortable">Cómoda</option>
                  <option value="balanced">Equilibrada</option>
                  <option value="compact">Compacta</option>
                </select>
              </label>
              <label className="wide b-range">
                <span>
                  Relevancia mínima <strong>{draft.relevanceThreshold}%</strong>
                </span>
                <input
                  aria-label="Relevancia mínima"
                  type="range"
                  min="40"
                  max="95"
                  value={draft.relevanceThreshold}
                  onChange={(e) =>
                    field("relevanceThreshold", Number(e.target.value))
                  }
                />
                <small>
                  Las señales bajo este umbral quedan en segundo plano.
                </small>
              </label>
            </div>
            <Toggle
              label="Reducir movimiento"
              detail="Minimiza animaciones no esenciales."
              checked={draft.reducedMotion}
              onChange={(v) => field("reducedMotion", v)}
            />
            <Toggle
              label="Explicar puntuaciones"
              detail="Añade contexto junto a los scores."
              checked={draft.showScoreExplanations}
              onChange={(v) => field("showScoreExplanations", v)}
            />
          </section>
          <section id="notifications">
            <div className="b-setting-title">
              <div>
                <span>03</span>
                <h2>Avisos y digest</h2>
                <p>Elige cuándo recibir cambios relevantes.</p>
              </div>
            </div>
            <Toggle
              label="Notificaciones activas"
              detail="Avisos de hitos y señales que superan tu umbral."
              checked={draft.notifications}
              onChange={(v) => field("notifications", v)}
            />
            <fieldset className="b-radio-group" disabled={!draft.notifications}>
              <legend>Frecuencia</legend>
              {(
                [
                  ["daily", "Diario", "Cada mañana."],
                  ["weekly", "Semanal", "Lectura consolidada los lunes."],
                  ["off", "Sin digest", "Solo avisos dentro de Oracle."],
                ] as const
              ).map(([value, label, detail]) => (
                <label key={value}>
                  <input
                    type="radio"
                    name="digest"
                    checked={draft.digest === value}
                    onChange={() => field("digest", value)}
                  />
                  <span>
                    <strong>{label}</strong>
                    <small>{detail}</small>
                  </span>
                </label>
              ))}
            </fieldset>
          </section>
          <section className="b-danger-zone">
            <h2>Datos de demostración</h2>
            <p>
              Elimina expedientes creados, decisiones y preferencias guardadas.
            </p>
            {!confirmReset ? (
              <button type="button" onClick={() => setConfirmReset(true)}>
                <RotateCcw size={16} /> Restablecer demostración
              </button>
            ) : (
              <div className="b-confirm-reset">
                <strong>¿Restablecer ahora?</strong>
                <button type="button" onClick={reset}>
                  Sí, eliminar cambios
                </button>
                <button type="button" onClick={() => setConfirmReset(false)}>
                  Cancelar
                </button>
              </div>
            )}
          </section>
          <div className="b-save-bar">
            <p>
              {JSON.stringify(draft) === JSON.stringify(settings)
                ? "Todo está guardado"
                : "Hay cambios sin guardar"}
            </p>
            <button
              disabled={
                saving || JSON.stringify(draft) === JSON.stringify(settings)
              }
            >
              <Save size={17} />
              {saving ? "Guardando…" : "Guardar preferencias"}
            </button>
          </div>
        </div>
      </form>
    </>
  );
}
function Toggle({
  label,
  detail,
  checked,
  onChange,
}: {
  label: string;
  detail: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="b-toggle-row">
      <div>
        <strong>{label}</strong>
        <p>{detail}</p>
      </div>
      <Switch.Root
        className="b-switch"
        checked={checked}
        onCheckedChange={onChange}
        aria-label={label}
      >
        <Switch.Thumb />
      </Switch.Root>
    </div>
  );
}
