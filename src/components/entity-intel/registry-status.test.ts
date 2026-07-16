import { describe, expect, it } from "vitest";
import type { EntityIntelRegistryAct } from "@oracle/api-client";
import {
  latestRegistryStatuses,
  registryActDedupeKey,
  registryStatusCounts,
  registryStatusKey,
} from "./registry-status";

const appointment2019: EntityIntelRegistryAct = {
  person: "BURGOS CANTO MIGUEL",
  role: "Administrador",
  action: "nombramiento",
  date: "2019-01-01",
  source_url: "https://boe.test/2019",
};

const termination2024: EntityIntelRegistryAct = {
  person: "BURGOS CANTO MIGUEL",
  role: "Administrador",
  action: "cese",
  date: "2024-01-01",
  source_url: "https://boe.test/2024",
};

const termination2020: EntityIntelRegistryAct = {
  person: "PEREZ LOPEZ ANA",
  role: "Consejera",
  action: "cese",
  date: "2020-01-01",
  source_url: "https://boe.test/2020",
};

const reappointment2025: EntityIntelRegistryAct = {
  person: "PEREZ LOPEZ ANA",
  role: "Consejera",
  action: "nombramiento",
  date: "2025-01-01",
  source_url: "https://boe.test/2025",
};

describe("registry-status", () => {
  it.each([
    [[termination2024, appointment2019], "Signal DESC"],
    [[appointment2019, termination2024], "ASC/invertido"],
  ])("marca como cesado cuando el cese es el acto más reciente (%s)", (items) => {
    const statuses = latestRegistryStatuses(items, "company");
    const key = registryStatusKey("company", appointment2019);

    expect(statuses.get(key)?.action).toBe("cese");
    expect(registryStatusCounts(items, "company")).toEqual({ active: 0, ended: 1 });
  });

  it.each([
    [[reappointment2025, termination2020], "Signal DESC"],
    [[termination2020, reappointment2025], "ASC/invertido"],
  ])("marca como activo cuando el renombramiento es el acto más reciente (%s)", (items) => {
    const statuses = latestRegistryStatuses(items, "company");
    const key = registryStatusKey("company", reappointment2025);

    expect(statuses.get(key)?.action).toBe("nombramiento");
    expect(registryStatusCounts(items, "company")).toEqual({ active: 1, ended: 0 });
  });

  it("usa un desempate estable cuando falta fecha", () => {
    const items: EntityIntelRegistryAct[] = [
      { person: "SIN FECHA", role: "Administrador", action: "cese", source_url: "https://boe.test/b" },
      { person: "SIN FECHA", role: "Administrador", action: "nombramiento", source_url: "https://boe.test/a" },
    ];
    const reversed = [...items].reverse();

    expect(latestRegistryStatuses(items, "company")).toEqual(
      latestRegistryStatuses(reversed, "company"),
    );
  });

  it("incluye contraparte en la clave de deduplicación de actos", () => {
    const first = {
      person: "PERSONA A",
      role: "Administrador",
      date: "2026-01-01",
      source_url: "https://boe.test/same",
    };
    const second = { ...first, person: "PERSONA B" };

    expect(registryActDedupeKey("company", first)).not.toBe(
      registryActDedupeKey("company", second),
    );
  });
});
