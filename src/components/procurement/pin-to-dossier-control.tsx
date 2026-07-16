"use client";

import {
  api,
  type BackendDossier,
  type DossierProcurementKind,
} from "@oracle/api-client";
import { Pin, RefreshCw } from "lucide-react";
import { type FormEvent, useEffect, useId, useState } from "react";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { problemMessage } from "./procurement-helpers";

export function PinToDossierControl({
  kind,
  folderId,
  compact = false,
}: {
  kind: DossierProcurementKind;
  folderId: string;
  compact?: boolean;
}) {
  const selectId = useId();
  const [dossiers, setDossiers] = useState<BackendDossier[]>([]);
  const [dossierId, setDossierId] = useState("");
  const [loading, setLoading] = useState(false);
  const [pinning, setPinning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const result = await api.dossiers.list({
          page: 1,
          size: 100,
          sort: "-updated_at",
        });
        if (cancelled) return;
        setDossiers(result.data);
        setDossierId((current) => current || result.data[0]?.id || "");
      } catch (reason) {
        if (!cancelled)
          setError(problemMessage(reason, "No se pudieron cargar tus expedientes."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => {
      cancelled = true;
      window.clearTimeout(kickoff);
    };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!dossierId || !folderId) return;
    setPinning(true);
    setError(null);
    setMessage(null);
    try {
      await api.dossierProcurement.pin(dossierId, {
        kind,
        folder_id: folderId,
      });
      setMessage("Referencia fijada al expediente.");
    } catch (reason) {
      setError(
        problemMessage(reason, "No se pudo fijar la referencia al expediente."),
      );
    } finally {
      setPinning(false);
    }
  }

  return (
    <PermissionGate permission="opportunity.write">
      <form
        className={compact ? "procurement-pin compact" : "procurement-pin"}
        onSubmit={submit}
      >
        <label htmlFor={selectId}>
          <span>Fijar a expediente</span>
          <select
            id={selectId}
            value={dossierId}
            onChange={(event) => setDossierId(event.target.value)}
            disabled={loading || pinning || dossiers.length === 0}
          >
            {dossiers.length === 0 ? (
              <option value="">
                {loading ? "Cargando expedientes…" : "Sin expedientes activos"}
              </option>
            ) : (
              dossiers.map((dossier) => (
                <option key={dossier.id} value={dossier.id}>
                  {dossier.title || "Expediente sin título"}
                </option>
              ))
            )}
          </select>
        </label>
        <button
          className="vector-secondary"
          type="submit"
          disabled={loading || pinning || !dossierId}
        >
          {pinning ? <RefreshCw size={14} /> : <Pin size={14} />}
          {compact ? "Fijar" : "Fijar"}
        </button>
        {message && <small className="procurement-pin-ok">{message}</small>}
        {error && (
          <small className="procurement-pin-error" role="alert">
            {error}
          </small>
        )}
      </form>
    </PermissionGate>
  );
}
