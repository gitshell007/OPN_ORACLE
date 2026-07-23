"use client";

import * as Popover from "@radix-ui/react-popover";
import { Check, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";

export type ProcurementFeedbackReason =
  "wrong_sector" | "amount" | "region" | "buyer" | "other";

export type ProcurementFeedbackVerdict = "relevant" | "not_relevant";

export interface ProcurementFeedbackValue {
  id: string;
  reason: ProcurementFeedbackReason;
  verdict: ProcurementFeedbackVerdict;
}

const REASON_LABELS: Record<ProcurementFeedbackReason, string> = {
  wrong_sector: "Sector incorrecto",
  amount: "Importe",
  region: "Región",
  buyer: "Comprador",
  other: "Otro motivo",
};

interface ProcurementFeedbackControlProps {
  busy?: boolean;
  feedback?: ProcurementFeedbackValue | null;
  label: string;
  onRelevant: () => void;
  onNotRelevant: (reason: ProcurementFeedbackReason) => void;
  onUndo: () => void;
}

export function ProcurementFeedbackControl({
  busy = false,
  feedback,
  label,
  onRelevant,
  onNotRelevant,
  onUndo,
}: ProcurementFeedbackControlProps) {
  if (feedback) {
    return (
      <div className="procurement-feedback-recorded" role="status">
        <div>
          <Check size={14} />
          <span>
            {feedback.verdict === "relevant"
              ? "Marcada como relevante"
              : `No relevante · ${REASON_LABELS[feedback.reason]}`}
          </span>
        </div>
        <small>Lo tendremos en cuenta cuando pidas revisar el plan.</small>
        <button
          className="vector-secondary compact"
          type="button"
          disabled={busy}
          onClick={onUndo}
        >
          <RotateCcw size={13} />
          {busy ? "Deshaciendo…" : "Deshacer"}
        </button>
      </div>
    );
  }

  return (
    <div
      className="procurement-feedback-actions"
      role="group"
      aria-label={`Valoración para ${label}`}
    >
      <button
        className="vector-secondary compact"
        type="button"
        disabled={busy}
        onClick={onRelevant}
      >
        <ThumbsUp size={13} />
        {busy ? "Registrando…" : "Relevante"}
      </button>
      <Popover.Root>
        <Popover.Trigger asChild>
          <button
            className="vector-secondary compact"
            type="button"
            disabled={busy}
          >
            <ThumbsDown size={13} />
            No relevante
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            className="procurement-feedback-reasons"
            align="start"
            sideOffset={6}
          >
            <strong>¿Por qué no encaja?</strong>
            <div role="group" aria-label={`Motivo para ${label}`}>
              {(
                Object.entries(REASON_LABELS) as [
                  ProcurementFeedbackReason,
                  string,
                ][]
              ).map(([reason, reasonLabel]) => (
                <button
                  key={reason}
                  type="button"
                  onClick={() => onNotRelevant(reason)}
                >
                  {reasonLabel}
                </button>
              ))}
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}
