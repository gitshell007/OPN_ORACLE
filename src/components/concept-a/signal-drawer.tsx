"use client";
import * as Dialog from "@radix-ui/react-dialog";
import {
  Check,
  CheckCircle2,
  ClipboardPlus,
  ExternalLink,
  FileWarning,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useOracle } from "@/components/shared/oracle-provider";
import { formatDate, signalTypeLabel } from "@/lib/oracle/format";
import type { Signal } from "@/lib/oracle/types";
export function SignalDrawer({
  signal,
  open,
  onOpenChange,
}: {
  signal: Signal | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { actOnSignal } = useOracle();
  const [busy, setBusy] = useState(false);
  if (!signal) return null;
  const act = async (
    status: "reviewed" | "dismissed" | "promoted",
    promotedAs?: "opportunity" | "risk",
  ) => {
    setBusy(true);
    await actOnSignal({ signalId: signal.id, status, promotedAs });
    setBusy(false);
    toast.success(
      promotedAs === "opportunity"
        ? "Señal promovida a oportunidad"
        : promotedAs === "risk"
          ? "Riesgo registrado"
          : status === "dismissed"
            ? "Señal descartada"
            : "Señal revisada",
      { description: "El estado se conserva en ambos conceptos." },
    );
    onOpenChange(false);
  };
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="drawer-overlay" />
        <Dialog.Content className="signal-drawer">
          <Dialog.Close className="drawer-close" aria-label="Cerrar detalle">
            <X size={19} />
          </Dialog.Close>
          <div className="drawer-heading">
            <span className="signal-type">
              <FileWarning size={14} />
              {signalTypeLabel[signal.sourceType]}
            </span>
            <Dialog.Title>{signal.title}</Dialog.Title>
            <Dialog.Description>{signal.summary}</Dialog.Description>
          </div>
          <div className="score-grid">
            <Score label="Relevancia" value={signal.relevance} />
            <Score label="Novedad" value={signal.novelty} />
            <Score label="Confianza" value={signal.confidence} />
            <Score label="Credibilidad" value={signal.credibility} />
          </div>
          <section className="fact-block">
            <span>Hecho verificado</span>
            <p>{signal.summary}</p>
            <small>
              {signal.sourceName} · {formatDate(signal.publishedAt, true)}{" "}
              <ExternalLink size={12} />
            </small>
          </section>
          <section>
            <h3>Por qué importa</h3>
            <p>{signal.whyItMatters}</p>
          </section>
          <section>
            <h3>Actores relacionados</h3>
            <div className="actor-chips">
              {signal.actors.map((a) => (
                <span key={a}>{a}</span>
              ))}
            </div>
          </section>
          <section>
            <h3>Evidencias</h3>
            <div className="evidence-list">
              {signal.evidence.map((e) => (
                <article key={e.id}>
                  <CheckCircle2 size={16} />
                  <span>
                    <strong>{e.label}</strong>
                    <small>{e.source}</small>
                    <p>{e.excerpt}</p>
                  </span>
                </article>
              ))}
            </div>
          </section>
          <div className="drawer-recommendation">
            <span>Recomendación Oracle</span>
            <p>
              Revisar el encaje y convertirla en acción antes del próximo hito.
            </p>
            <small>
              Confianza {signal.confidence}% · inferencia basada en 2 evidencias
            </small>
          </div>
          <footer>
            <button
              disabled={busy}
              className="vector-secondary"
              onClick={() => act("reviewed")}
            >
              <Check size={16} />
              Marcar revisada
            </button>
            <button
              disabled={busy}
              className="vector-secondary"
              onClick={() =>
                toast.success("Tarea creada", {
                  description: `Revisar: ${signal.title}`,
                })
              }
            >
              <ClipboardPlus size={16} />
              Crear tarea
            </button>
            <button
              disabled={busy}
              className="vector-primary"
              onClick={() => act("promoted", "opportunity")}
            >
              <Sparkles size={16} />
              Promover a oportunidad
            </button>
            <button
              disabled={busy}
              className="vector-danger"
              onClick={() => act("promoted", "risk")}
            >
              <ShieldAlert size={16} />
              Registrar riesgo
            </button>
            <button
              disabled={busy}
              className="text-button danger-text"
              onClick={() => act("dismissed")}
            >
              Descartar señal
            </button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
function Score({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
      <i>
        <b style={{ width: `${value}%` }} />
      </i>
    </div>
  );
}
