import type { ReactNode } from "react";

/**
 * Renderiza énfasis markdown básico (`**texto**` → <strong>) en textos de panel.
 * SV2-RIESGO-DECL micro-fix: evita asteriscos crudos en statement/semillas.
 * Solo negrita; no interpreta enlaces, listas ni HTML.
 */
export function renderInlineEmphasis(text: string | null | undefined): ReactNode {
  if (text == null || text === "") return text ?? "";
  const parts = String(text).split(/(\*\*[^*]+\*\*)/g);
  if (parts.length === 1) return text;
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return <span key={index}>{part}</span>;
  });
}

/** Strip de asteriscos de negrita (útil en asserts de texto plano). */
export function stripInlineEmphasis(text: string | null | undefined): string {
  if (text == null) return "";
  return String(text).replace(/\*\*([^*]+)\*\*/g, "$1");
}
