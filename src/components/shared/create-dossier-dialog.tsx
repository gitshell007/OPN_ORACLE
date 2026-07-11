"use client";
import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { X } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { useOracle } from "./oracle-provider";
import { typeLabels } from "@/lib/oracle/format";
import type { CreateDossierInput } from "@/lib/oracle/types";

const schema = z.object({
  title: z.string().min(4, "Escribe un título de al menos 4 caracteres"),
  type: z.string().min(1),
  objective: z.string().min(12, "Describe el objetivo con algo más de detalle"),
  geography: z.string().min(2, "Indica al menos una geografía"),
  sectors: z.string().min(2, "Añade al menos una etiqueta"),
  owner: z.string().min(2),
  monitorEnabled: z.boolean(),
});
type FormValues = z.infer<typeof schema>;
export function CreateDossierDialog({
  open,
  onOpenChange,
  accent,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  accent?: "a" | "b";
}) {
  const { createDossier } = useOracle();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      type: "project",
      owner: "Lucía Herrera",
      monitorEnabled: true,
    },
  });
  const submit = async (v: FormValues) => {
    await createDossier(v as CreateDossierInput);
    toast.success("Expediente creado", {
      description: "Ya aparece en ambos portfolios.",
    });
    reset();
    onOpenChange(false);
  };
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content" data-accent={accent}>
          <Dialog.Title className="dialog-title">
            Crear expediente estratégico
          </Dialog.Title>
          <Dialog.Description className="dialog-description">
            Define el objetivo inicial. Podrás ajustar el radar y sus fuentes
            después.
          </Dialog.Description>
          <Dialog.Close className="dialog-close" aria-label="Cerrar">
            <X size={18} />
          </Dialog.Close>
          <form onSubmit={handleSubmit(submit)}>
            <div className="form-grid">
              <div className="field full">
                <label htmlFor="dossier-title">Título</label>
                <input
                  id="dossier-title"
                  autoFocus
                  placeholder="Ej. Entrada mercado Mediterráneo"
                  aria-invalid={!!errors.title}
                  aria-describedby={
                    errors.title ? "dossier-title-error" : undefined
                  }
                  {...register("title")}
                />
                {errors.title && (
                  <span className="error" id="dossier-title-error">
                    {errors.title.message}
                  </span>
                )}
              </div>
              <div className="field">
                <label htmlFor="dossier-type">Tipo</label>
                <select id="dossier-type" {...register("type")}>
                  {Object.entries(typeLabels).map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="dossier-owner">Responsable</label>
                <select id="dossier-owner" {...register("owner")}>
                  <option>Lucía Herrera</option>
                  <option>Sergio Navas</option>
                  <option>Marta Cid</option>
                </select>
              </div>
              <div className="field full">
                <label htmlFor="dossier-objective">Objetivo estratégico</label>
                <textarea
                  id="dossier-objective"
                  placeholder="Qué decisión o avance debe facilitar este expediente"
                  aria-invalid={!!errors.objective}
                  aria-describedby={
                    errors.objective ? "dossier-objective-error" : undefined
                  }
                  {...register("objective")}
                />
                {errors.objective && (
                  <span className="error" id="dossier-objective-error">
                    {errors.objective.message}
                  </span>
                )}
              </div>
              <div className="field">
                <label htmlFor="dossier-geo">Geografía</label>
                <input
                  id="dossier-geo"
                  placeholder="España, Portugal"
                  aria-invalid={!!errors.geography}
                  aria-describedby={
                    errors.geography ? "dossier-geo-error" : undefined
                  }
                  {...register("geography")}
                />
                {errors.geography && (
                  <span className="error" id="dossier-geo-error">
                    {errors.geography.message}
                  </span>
                )}
              </div>
              <div className="field">
                <label htmlFor="dossier-tags">Sectores o etiquetas</label>
                <input
                  id="dossier-tags"
                  placeholder="Innovación, regulación"
                  aria-invalid={!!errors.sectors}
                  aria-describedby={
                    errors.sectors ? "dossier-tags-error" : undefined
                  }
                  {...register("sectors")}
                />
                {errors.sectors && (
                  <span className="error" id="dossier-tags-error">
                    {errors.sectors.message}
                  </span>
                )}
              </div>
              <label className="check-row full">
                <input type="checkbox" {...register("monitorEnabled")} />
                <span>
                  <strong>Activar monitor de Signal Avanza</strong>
                  <br />
                  Preparará una primera sincronización con fuentes sintéticas.
                </span>
              </label>
            </div>
            <div className="form-actions">
              <Dialog.Close className="button-base" type="button">
                Cancelar
              </Dialog.Close>
              <button
                className={`button-base button-primary ${accent ?? ""}`}
                disabled={isSubmitting}
              >
                {isSubmitting ? "Creando…" : "Crear expediente"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
