import { describe, expect, it } from "vitest";
import { DEMO_NOW, dossierFixtures, signalFixtures } from "./fixtures";

describe("fixtures compartidos de Oracle",()=>{
  it("mantiene la fecha y volumen de demo deterministas",()=>{
    expect(DEMO_NOW.toISOString()).toBe("2026-07-10T07:30:00.000Z");
    expect(dossierFixtures).toHaveLength(8);
    expect(signalFixtures).toHaveLength(20);
  });
  it("vincula todas las señales a expedientes y evidencias",()=>{
    const ids=new Set(dossierFixtures.map(d=>d.id));
    expect(signalFixtures.every(s=>ids.has(s.dossierId)&&s.evidence.length===2)).toBe(true);
  });
  it("evita referencias verticales o compañías reales en el núcleo de datos",()=>{
    const text=JSON.stringify({dossierFixtures,signalFixtures}).toLowerCase();
    expect(text).not.toMatch(/iberdrola|otan|grafeno|defensa/);
  });
});
