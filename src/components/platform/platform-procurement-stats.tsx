"use client";

import { api } from "@oracle/api-client";
import { useCallback } from "react";
import {
  ProcurementStatsView,
  type ProcurementAnalyticsParams,
} from "@/components/procurement/procurement-stats-view";

export function PlatformProcurementStats() {
  const loadAnalytics = useCallback(
    (params: ProcurementAnalyticsParams) => api.platform.procurementAnalytics(params),
    [],
  );

  return (
    <ProcurementStatsView
      loadAnalytics={loadAnalytics}
      eyebrow="Plataforma · Superadmin"
      title="Estadísticas licitaciones"
      description="Vista de mercado PLACSP para operadores de plataforma: inventario del registro Signal y rankings sobre una muestra acotada de licitaciones abiertas."
    />
  );
}
