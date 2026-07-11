"use client";
import * as Switch from "@radix-ui/react-switch";
import {
  Bell,
  ChevronRight,
  PlugZap,
  RotateCcw,
  SlidersHorizontal,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useOracle } from "@/components/shared/oracle-provider";
import { defaultSettings } from "@/lib/oracle/fixtures";
import type { UserSettings } from "@/lib/oracle/types";
const sections = [
  { id: "appearance", label: "Apariencia", icon: SlidersHorizontal },
  { id: "notifications", label: "Notificaciones", icon: Bell },
  { id: "integrations", label: "Integraciones", icon: PlugZap },
];
/* eslint-disable react-hooks/set-state-in-effect */
export function VectorSettings() {
  const { settings, saveSettings } = useOracle();
  const [draft, setDraft] = useState(settings);
  const [active, setActive] = useState("appearance");
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState(false);
  useEffect(() => setDraft(settings), [settings]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(settings);
  const field = <K extends keyof UserSettings>(
    key: K,
    value: UserSettings[K],
  ) => setDraft((v) => ({ ...v, [key]: value }));
  const save = async () => {
    setSaving(true);
    await saveSettings(draft);
    setSaving(false);
    toast.success("Preferencias guardadas", {
      description: "La densidad y navegación ya se aplican al portfolio.",
    });
  };
  const reset = async () => {
    await saveSettings(defaultSettings);
    setDraft(defaultSettings);
    setConfirm(false);
    toast.success("Preferencias restablecidas");
  };
  return (
    <div className="settings-page">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Cuenta y workspace</div>
          <h1>Ajustes</h1>
          <p>
            Configura cómo Oracle prioriza señales y presenta tu espacio de
            trabajo.
          </p>
        </div>
        {dirty && <span className="unsaved">● Cambios sin guardar</span>}
      </section>
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Secciones de ajustes">
          {sections.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={active === id ? "active" : ""}
              onClick={() => {
                setActive(id);
                document
                  .getElementById(id)
                  ?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
            >
              <Icon size={17} />
              <span>{label}</span>
              <ChevronRight size={15} />
            </button>
          ))}
        </nav>
        <main>
          <section className="settings-section" id="appearance">
            <header>
              <h2>Apariencia y navegación</h2>
              <p>Ajusta la densidad sin perder información.</p>
            </header>
            <SettingRow
              title="Densidad"
              detail="Modifica altura de filas, controles y espaciado."
            >
              <div className="segmented choice">
                <button
                  aria-pressed={draft.density === "compact"}
                  onClick={() => field("density", "compact")}
                >
                  Compacta
                </button>
                <button
                  aria-pressed={draft.density === "balanced"}
                  onClick={() => field("density", "balanced")}
                >
                  Equilibrada
                </button>
                <button
                  aria-pressed={draft.density === "comfortable"}
                  onClick={() => field("density", "comfortable")}
                >
                  Cómoda
                </button>
              </div>
            </SettingRow>
            <SettingRow
              title="Página inicial"
              detail="Pantalla que se abre al entrar en Vector."
            >
              <select
                value={draft.landing}
                onChange={(e) =>
                  field("landing", e.target.value as UserSettings["landing"])
                }
              >
                <option value="portfolio">Command Center</option>
                <option value="signals">Radar de señales</option>
              </select>
            </SettingRow>
            <SettingRow
              title="Navegación compacta"
              detail="Reduce la barra lateral a iconos."
            >
              <Toggle
                label="Navegación compacta"
                checked={draft.navigationCompact}
                onChange={(v) => field("navigationCompact", v)}
              />
            </SettingRow>
            <SettingRow
              title="Reducir movimiento"
              detail="Desactiva transiciones no esenciales."
            >
              <Toggle
                label="Reducir movimiento"
                checked={draft.reducedMotion}
                onChange={(v) => field("reducedMotion", v)}
              />
            </SettingRow>
            <SettingRow
              title="Explicaciones de score"
              detail="Muestra razonamiento, confianza y evidencias."
            >
              <Toggle
                label="Explicaciones de score"
                checked={draft.showScoreExplanations}
                onChange={(v) => field("showScoreExplanations", v)}
              />
            </SettingRow>
          </section>
          <section className="settings-section" id="notifications">
            <header>
              <h2>Señales y notificaciones</h2>
              <p>Controla qué cambios requieren tu atención.</p>
            </header>
            <SettingRow
              title="Umbral mínimo de relevancia"
              detail="Solo se destacarán señales por encima de este valor."
            >
              <div className="range-control">
                <input
                  type="range"
                  min="40"
                  max="95"
                  step="5"
                  value={draft.relevanceThreshold}
                  onChange={(e) =>
                    field("relevanceThreshold", Number(e.target.value))
                  }
                />
                <b>{draft.relevanceThreshold}</b>
              </div>
            </SettingRow>
            <SettingRow
              title="Notificaciones en la aplicación"
              detail="Avisos de oportunidades, riesgos e hitos."
            >
              <Toggle
                label="Notificaciones en la aplicación"
                checked={draft.notifications}
                onChange={(v) => field("notifications", v)}
              />
            </SettingRow>
            <SettingRow
              title="Resumen periódico"
              detail="Frecuencia del digest estratégico."
            >
              <div className="segmented choice">
                <button
                  aria-pressed={draft.digest === "daily"}
                  onClick={() => field("digest", "daily")}
                >
                  Diario
                </button>
                <button
                  aria-pressed={draft.digest === "weekly"}
                  onClick={() => field("digest", "weekly")}
                >
                  Semanal
                </button>
                <button
                  aria-pressed={draft.digest === "off"}
                  onClick={() => field("digest", "off")}
                >
                  Desactivado
                </button>
              </div>
            </SettingRow>
          </section>
          <section className="settings-section" id="integrations">
            <header>
              <h2>Integraciones</h2>
              <p>Estado simulado de las capacidades conectadas.</p>
            </header>
            <div className="integration-list">
              <Integration
                name="Signal Avanza"
                detail="Ingesta y normalización de señales"
                status="Conectado"
              />
              <Integration
                name="Nexus"
                detail="Actores, relaciones y reuniones"
                status="Disponible"
              />
              <Integration
                name="Sentinel"
                detail="Riesgos, escenarios y auditoría"
                status="Disponible"
              />
            </div>
          </section>
          <section className="settings-danger">
            <div>
              <strong>Restablecer preferencias</strong>
              <p>
                Vuelve a los ajustes iniciales. Los expedientes creados no se
                eliminan.
              </p>
            </div>
            {confirm ? (
              <div className="confirm-actions">
                <span>¿Confirmas el restablecimiento?</span>
                <button className="vector-danger" onClick={reset}>
                  Sí, restablecer
                </button>
                <button
                  className="vector-secondary"
                  onClick={() => setConfirm(false)}
                >
                  Cancelar
                </button>
              </div>
            ) : (
              <button
                className="vector-secondary danger-outline"
                onClick={() => setConfirm(true)}
              >
                <RotateCcw size={15} />
                Restablecer
              </button>
            )}
          </section>
          <div className="settings-savebar">
            <span>
              {dirty
                ? "Tienes cambios pendientes"
                : "Preferencias actualizadas"}
            </span>
            <button
              className="vector-primary"
              disabled={!dirty || saving}
              onClick={save}
            >
              {saving ? "Guardando…" : "Guardar cambios"}
            </button>
          </div>
        </main>
      </div>
    </div>
  );
}
function SettingRow({
  title,
  detail,
  children,
}: {
  title: string;
  detail: string;
  children: React.ReactNode;
}) {
  return (
    <div className="setting-row">
      <div>
        <strong>{title}</strong>
        <p>{detail}</p>
      </div>
      {children}
    </div>
  );
}
function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <Switch.Root
      aria-label={label}
      className="vector-switch"
      checked={checked}
      onCheckedChange={onChange}
    >
      <Switch.Thumb />
    </Switch.Root>
  );
}
function Integration({
  name,
  detail,
  status,
}: {
  name: string;
  detail: string;
  status: string;
}) {
  return (
    <div>
      <span className="integration-icon">
        <PlugZap size={18} />
      </span>
      <span>
        <strong>{name}</strong>
        <small>{detail}</small>
      </span>
      <b>
        <i /> {status}
      </b>
      <button
        className="vector-secondary"
        onClick={() =>
          toast.info(`${name}: ${status}`, {
            description: "La conexión es simulada en este prototipo.",
          })
        }
      >
        Configurar
      </button>
    </div>
  );
}
