"use client";

import { ApiError, api, type CustomBriefAccepted } from "@oracle/api-client";
import { FilePlus2 } from "lucide-react";
import { FormEvent, useState } from "react";
import { toast } from "sonner";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { idempotencyKey } from "@/components/reporting/reporting-utils";

export function DossierCustomBriefSection({ dossierId }: { dossierId: string }) {
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<CustomBriefAccepted | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const text = brief.trim();
    if (text.length < 1) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.customBriefs.create(
        dossierId,
        { brief_request: text },
        idempotencyKey(`brief-${dossierId}-${Date.now()}`),
      );
      setAccepted(result);
      toast.success("Brief registrado", {
        description: "Plan en cola (202). No se ha invocado report_writer.",
      });
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo crear el informe personalizado.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dossier-section-page">
      <header className="vector-panel">
        <div>
          <span className="section-kicker">Asistente de informes</span>
          <h1>Informe libre</h1>
          <p>
            Guarda el encargo como brief versionado y encola la planificación. El plan
            propuesto requiere revisión humana antes de redactar.
          </p>
        </div>
      </header>

      <section className="vector-panel">
        <form onSubmit={(event) => void onSubmit(event)} className="stack-form">
          <label className="field full">
            <span>Encargo del informe</span>
            <textarea
              required
              minLength={1}
              maxLength={20000}
              rows={6}
              value={brief}
              onChange={(event) => setBrief(event.target.value)}
              placeholder="Describe audiencia, alcance, periodo, fuentes deseadas y formato…"
            />
          </label>
          <AsyncActionButton
            type="submit"
            className="vector-primary"
            busy={busy}
            disabled={busy || !brief.trim()}
          >
            <FilePlus2 size={15} /> Crear brief y planificar
          </AsyncActionButton>
        </form>
        {error ? (
          <p role="alert" className="form-error">
            {error}
          </p>
        ) : null}
      </section>

      {accepted ? (
        <section className="vector-panel" aria-live="polite">
          <h2>Solicitud aceptada</h2>
          <dl className="placeholder-contract">
            <div>
              <dt>Informe</dt>
              <dd>{accepted.report_id}</dd>
            </div>
            <div>
              <dt>Job</dt>
              <dd>{accepted.job_id}</dd>
            </div>
            <div>
              <dt>Plan</dt>
              <dd>{accepted.plan_status}</dd>
            </div>
          </dl>
          <p>
            Estado inicial <strong>Pendiente</strong>. Cuando el worker proponga el plan,
            revisa el informe en la biblioteca sin tratar un borrador parcial como listo.
          </p>
        </section>
      ) : null}
    </div>
  );
}
