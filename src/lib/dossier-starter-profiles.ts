export const DOSSIER_STARTER_PROFILES = {
  project: {
    description: "Para avanzar una iniciativa con hitos, dependencias y decisiones.",
    bestFor: "Úsalo cuando ya hay una iniciativa concreta que necesita seguimiento operativo y memoria de decisiones.",
    focus: "Creará un objetivo de avance, dos hipótesis de trabajo y una vigilancia inicial sobre hitos, mercado, publicaciones y riesgos.",
  },
  market: {
    description: "Para entender un mercado, segmento, país o región objetivo.",
    bestFor: "Úsalo cuando la prioridad es explorar un territorio, sector o segmento antes de decidir dónde actuar.",
    focus: "Creará un objetivo de análisis, dos hipótesis y una vigilancia inicial de mercado, competencia y regulación.",
  },
  strategic_account: {
    description: "Para desarrollar una relación prioritaria con una organización.",
    bestFor: "Úsalo para cuentas clave, clientes potenciales o instituciones donde importan actores, señales y próximos movimientos.",
    focus: "Creará un objetivo de cuenta, dos hipótesis y una vigilancia inicial sobre la organización, actores y oportunidades.",
  },
  tender_or_grant: {
    description: "Para preparar una licitación, ayuda o convocatoria concreta.",
    bestFor: "Úsalo cuando hay una oportunidad formal con plazos, requisitos, documentación y competidores que vigilar.",
    focus: "Creará un objetivo de preparación, dos hipótesis y una vigilancia inicial de plazos, requisitos, publicaciones y riesgos.",
  },
  partnership: {
    description: "Para explorar o estructurar una colaboración estratégica.",
    bestFor: "Úsalo cuando la pregunta principal es con quién colaborar y bajo qué condiciones.",
    focus: "Creará un objetivo de alianza, dos hipótesis y una vigilancia inicial sobre las partes, oportunidades y riesgos.",
  },
  regulatory_affair: {
    description: "Para anticipar una norma, consulta, autorización o cambio regulatorio.",
    bestFor: "Úsalo cuando un cambio normativo o administrativo puede abrir una oportunidad o alterar el plan.",
    focus: "Creará un objetivo regulatorio, dos hipótesis y una vigilancia inicial de publicaciones, regulador y posibles impactos.",
  },
  custom: {
    description: "Para cualquier prioridad estratégica que no encaje en las categorías anteriores.",
    bestFor: "Úsalo cuando necesitas empezar con una estructura mínima y adaptar después el expediente a mano.",
    focus: "Creará un objetivo de delimitación, dos hipótesis y una vigilancia inicial editable.",
  },
} as const;

export type DossierStarterType = keyof typeof DOSSIER_STARTER_PROFILES;

export function starterProfileFor(type: string) {
  return DOSSIER_STARTER_PROFILES[
    type as DossierStarterType
  ] ?? DOSSIER_STARTER_PROFILES.custom;
}
