import { describe, expect, it } from "vitest";
import {
  productJobTypeLabel,
  productAuditActionLabel,
  productDossierTypeLabel,
  productPlanLabel,
  productQueueLabel,
  productRoleLabel,
  productSignalTypeLabel,
  productStatusLabel,
} from "./product-copy";

describe("copias de producto", () => {
  it("presenta los identificadores de procesos con lenguaje de negocio", () => {
    expect(productJobTypeLabel("notifications.evaluate_alerts")).toBe(
      "Evaluación de alertas",
    );
    expect(productJobTypeLabel("oracle.document.process")).toBe(
      "Procesamiento de documento",
    );
    expect(productJobTypeLabel("provider.unknown_operation")).toBe(
      "Proceso interno de Oracle",
    );
  });

  it("traduce estados, colas y roles visibles", () => {
    expect(productStatusLabel("invited")).toBe("Invitado");
    expect(productQueueLabel("maintenance")).toBe("Mantenimiento");
    expect(productRoleLabel("owner")).toBe("Propietario");
    expect(productPlanLabel("enterprise")).toBe("Empresarial");
    expect(productAuditActionLabel("tenant.member.invited")).toBe("Miembro invitado");
  });

  it("oculta los códigos internos de expedientes y fuentes", () => {
    expect(productDossierTypeLabel("strategic_account")).toBe("Cuenta estratégica");
    expect(productSignalTypeLabel("company_signal")).toBe("Actividad de una organización");
    expect(productSignalTypeLabel("unknown_source")).toBe("Fuente externa");
  });
});
