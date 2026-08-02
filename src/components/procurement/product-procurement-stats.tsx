"use client";

import { api } from "@oracle/api-client";
import { useCallback } from "react";
import {
  ProcurementStatsView,
  type ProcurementAnalyticsParams,
} from "@/components/procurement/procurement-stats-view";

export function ProductProcurementStats() {
  const loadAnalytics = useCallback(
    (params: ProcurementAnalyticsParams) => api.procurement.analytics(params),
    [],
  );

  return (
    <ProcurementStatsView
      loadAnalytics={loadAnalytics}
      eyebrow="Inteligencia · Mercado PLACSP"
      title="Estadísticas mercado"
      description="Rankings de mercado de licitaciones abiertas (CPV, organismos, regiones, tramos de importe). La muestra es compartida del registro PLACSP vía Signal; no son datos privados de tu organización."
    />
  );
}
