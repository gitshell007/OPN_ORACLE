"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { ApiError, api } from "@oracle/api-client";
import { FilePlus2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { toast } from "sonner";
import { starterProfileFor } from "@/lib/dossier-starter-profiles";

export function CreateProductDossierDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange(open: boolean): void;
}) {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [type, setType] = useState("project");
  const [goal, setGoal] = useState("");
  const [description, setDescription] = useState("");
  const [createStarterProfile, setCreateStarterProfile] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const dossier = await api.dossiers.create({
        title: title.trim(),
        type,
        strategic_goal: goal.trim(),
        description: description.trim(),
        create_starter_profile: createStarterProfile,
      });
      onOpenChange(false);
      setTitle("");
      setGoal("");
      setDescription("");
      setCreateStarterProfile(true);
      toast.success("Expediente creado", {
        description: "Se ha creado como borrador en el workspace predeterminado.",
      });
      router.push(`/app/dossiers/${dossier.id}`);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo crear el expediente.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content create-product-dialog">
          <Dialog.Title>Nuevo expediente</Dialog.Title>
          <Dialog.Description>
            Define el contexto mínimo. Podrás completar objetivos, miembros y
            fuentes desde la configuración del expediente.
          </Dialog.Description>
          <Dialog.Close className="dialog-close" aria-label="Cerrar">
            <X size={18} />
          </Dialog.Close>
          <form onSubmit={submit}>
            <label className="field">
              <span id="dossier-title-label">Nombre</span>
              <input
                aria-labelledby="dossier-title-label"
                required
                minLength={2}
                maxLength={240}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                autoFocus
              />
            </label>
            <label className="field">
              <span id="dossier-type-label">Tipo</span>
              <select
                aria-labelledby="dossier-type-label"
                value={type}
                onChange={(event) => setType(event.target.value)}
              >
                <option value="project">Proyecto</option>
                <option value="market">Mercado</option>
                <option value="strategic_account">Cuenta estratégica</option>
                <option value="tender_or_grant">Licitación o convocatoria</option>
                <option value="partnership">Alianza</option>
                <option value="regulatory_affair">Asunto regulatorio</option>
                <option value="custom">Otro</option>
              </select>
              <small>{starterProfileFor(type).description}</small>
            </label>
            <label className="field">
              <span id="dossier-goal-label">Objetivo estratégico</span>
              <textarea
                aria-labelledby="dossier-goal-label"
                required
                maxLength={5000}
                value={goal}
                onChange={(event) => setGoal(event.target.value)}
              />
            </label>
            <label className="field">
              <span id="dossier-description-label">Descripción (opcional)</span>
              <textarea
                aria-labelledby="dossier-description-label"
                maxLength={10000}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            <label className="field full">
              <span>Base de trabajo</span>
              <span className="checkbox-row">
                <input
                  type="checkbox"
                  aria-label="Crear una base inicial editable"
                  checked={createStarterProfile}
                  onChange={(event) =>
                    setCreateStarterProfile(event.target.checked)
                  }
                />
                Crear una base inicial editable
              </span>
              <small>
                {createStarterProfile
                  ? `${starterProfileFor(type).focus} No activará fuentes ni monitores externos.`
                  : "El expediente se creará vacío; podrás añadir estos elementos desde su configuración."}
              </small>
            </label>
            {error && <p className="form-error" role="alert">{error}</p>}
            <div className="dialog-actions">
              <Dialog.Close className="vector-secondary" type="button">
                Cancelar
              </Dialog.Close>
              <button className="vector-primary" disabled={busy || !title.trim() || !goal.trim()}>
                <FilePlus2 size={16} />
                {busy ? "Creando…" : "Crear expediente"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
