export const DOSSIER_STARTER_PROFILES = {
  project: {
    description: "Para avanzar una iniciativa con hitos, dependencias y decisiones.",
    focus: "Creará un objetivo de avance, dos hipótesis de trabajo y una vigilancia inicial sobre hitos, mercado, publicaciones y riesgos.",
  },
  market: {
    description: "Para entender un mercado, segmento, país o región objetivo.",
    focus: "Creará un objetivo de análisis, dos hipótesis y una vigilancia inicial de mercado, competencia y regulación.",
  },
  strategic_account: {
    description: "Para desarrollar una relación prioritaria con una organización.",
    focus: "Creará un objetivo de cuenta, dos hipótesis y una vigilancia inicial sobre la organización, actores y oportunidades.",
  },
  tender_or_grant: {
    description: "Para preparar una licitación, ayuda o convocatoria concreta.",
    focus: "Creará un objetivo de preparación, dos hipótesis y una vigilancia inicial de plazos, requisitos, publicaciones y riesgos.",
  },
  partnership: {
    description: "Para explorar o estructurar una colaboración estratégica.",
    focus: "Creará un objetivo de alianza, dos hipótesis y una vigilancia inicial sobre las partes, oportunidades y riesgos.",
  },
  regulatory_affair: {
    description: "Para anticipar una norma, consulta, autorización o cambio regulatorio.",
    focus: "Creará un objetivo regulatorio, dos hipótesis y una vigilancia inicial de publicaciones, regulador y posibles impactos.",
  },
  custom: {
    description: "Para cualquier prioridad estratégica que no encaje en las categorías anteriores.",
    focus: "Creará un objetivo de delimitación, dos hipótesis y una vigilancia inicial editable.",
  },
} as const;

export type DossierStarterType = keyof typeof DOSSIER_STARTER_PROFILES;

export function starterProfileFor(type: string) {
  return DOSSIER_STARTER_PROFILES[
    type as DossierStarterType
  ] ?? DOSSIER_STARTER_PROFILES.custom;
}
