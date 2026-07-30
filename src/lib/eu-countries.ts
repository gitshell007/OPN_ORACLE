export interface EuCountry {
  /** Código ISO 3166-1 alpha-2, en mayúsculas. */
  code: string;
  name: string;
  /** Idiomas oficiales principales (ISO 639-1, minúsculas). */
  languages: readonly string[];
}

export const EU_COUNTRIES: readonly EuCountry[] = [
  { code: "DE", name: "Alemania", languages: ["de"] },
  { code: "AT", name: "Austria", languages: ["de"] },
  { code: "BE", name: "Bélgica", languages: ["nl", "fr"] },
  { code: "BG", name: "Bulgaria", languages: ["bg"] },
  { code: "CY", name: "Chipre", languages: ["el"] },
  { code: "HR", name: "Croacia", languages: ["hr"] },
  { code: "DK", name: "Dinamarca", languages: ["da"] },
  { code: "SK", name: "Eslovaquia", languages: ["sk"] },
  { code: "SI", name: "Eslovenia", languages: ["sl"] },
  { code: "ES", name: "España", languages: ["es"] },
  { code: "EE", name: "Estonia", languages: ["et"] },
  { code: "FI", name: "Finlandia", languages: ["fi"] },
  { code: "FR", name: "Francia", languages: ["fr"] },
  { code: "GR", name: "Grecia", languages: ["el"] },
  { code: "HU", name: "Hungría", languages: ["hu"] },
  { code: "IE", name: "Irlanda", languages: ["en"] },
  { code: "IT", name: "Italia", languages: ["it"] },
  { code: "LV", name: "Letonia", languages: ["lv"] },
  { code: "LT", name: "Lituania", languages: ["lt"] },
  { code: "LU", name: "Luxemburgo", languages: ["fr", "de"] },
  { code: "MT", name: "Malta", languages: ["mt", "en"] },
  { code: "NL", name: "Países Bajos", languages: ["nl"] },
  { code: "PL", name: "Polonia", languages: ["pl"] },
  { code: "PT", name: "Portugal", languages: ["pt"] },
  { code: "CZ", name: "Chequia", languages: ["cs"] },
  { code: "RO", name: "Rumanía", languages: ["ro"] },
  { code: "SE", name: "Suecia", languages: ["sv"] },
];

/** Mercados prioritarios del producto: se muestran primero y preseleccionados. */
export const PRIORITY_COUNTRY_CODES: readonly string[] = ["ES", "DE"];

const byCode = new Map(EU_COUNTRIES.map((country) => [country.code, country]));

export function euCountryName(code: string): string {
  return byCode.get(code.toUpperCase())?.name ?? code.toUpperCase();
}

/** Idiomas sugeridos (sin duplicados, en orden de selección) para los países dados. */
export function languagesForCountries(codes: readonly string[]): string[] {
  return [
    ...new Set(codes.flatMap((code) => byCode.get(code.toUpperCase())?.languages ?? [])),
  ];
}
