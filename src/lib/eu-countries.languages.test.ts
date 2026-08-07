import { describe, expect, it } from "vitest";
import {
  filterSurveillanceLanguages,
  isIsoLanguageCode,
  languageName,
  languagesForCountries,
} from "./eu-countries";

describe("languageName / isIsoLanguageCode", () => {
  it("nombra el alemán en español y acepta ISO 639-1", () => {
    expect(languageName("de")).toBe("Alemán");
    expect(languageName("ES")).toBe("Español");
    expect(isIsoLanguageCode("de")).toBe(true);
    expect(isIsoLanguageCode("deu")).toBe(false);
  });
});

describe("filterSurveillanceLanguages", () => {
  it("encuentra alemán por alias intuitivos (ale, aleman, german)", () => {
    for (const needle of ["ale", "alemán", "aleman", "german", "de"]) {
      const hits = filterSurveillanceLanguages(needle);
      expect(hits.some((item) => item.code === "de")).toBe(true);
    }
  });

  it("encuentra inglés por ing / english", () => {
    expect(filterSurveillanceLanguages("ing").some((item) => item.code === "en")).toBe(
      true,
    );
    expect(
      filterSurveillanceLanguages("english").some((item) => item.code === "en"),
    ).toBe(true);
  });

  it("conserva códigos huérfanos seleccionados", () => {
    const hits = filterSurveillanceLanguages("", ["xx"]);
    expect(hits.some((item) => item.code === "xx")).toBe(true);
  });
});

describe("languagesForCountries", () => {
  it("sugiere es y de para ES y DE", () => {
    expect(languagesForCountries(["ES", "DE"])).toEqual(["es", "de"]);
  });
});
