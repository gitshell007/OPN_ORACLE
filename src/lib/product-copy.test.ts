import { describe, expect, it } from "vitest";
import {
  productActorTypeLabel,
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

  it("traduce tipos de actor de descubrimiento sin exponer el enum", () => {
    expect(productActorTypeLabel("company")).toBe("Empresa");
    expect(productActorTypeLabel("person")).toBe("Persona");
    expect(productActorTypeLabel("institution")).toBe("Institución");
    expect(productActorTypeLabel("research_group")).toBe("Grupo de investigación");
    expect(productActorTypeLabel("potential_customer")).toBe("Cliente potencial");
  });
});
