/**
 * Presets de geografías para el intake de Mercado.
 *
 * Oracle es transversal/global: la API acepta ISO 3166-1 alpha-2 e ISO 3166-2.
 * Esta lista solo mejora el UX (búsqueda y chips); no es una restricción de dominio.
 * Se mantiene el nombre de módulo por compatibilidad con imports existentes.
 */

export interface EuCountry {
  /** Código ISO 3166-1 alpha-2 o ISO 3166-2, en mayúsculas. */
  code: string;
  name: string;
  /** Idiomas oficiales principales (ISO 639-1, minúsculas). */
  languages: readonly string[];
}

/** Estados miembros de la UE (preset de conveniencia). */
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

/** Mercados frecuentes fuera de la UE (mismo formato; no exhaustivo). */
export const EXTRA_COUNTRIES: readonly EuCountry[] = [
  { code: "GB", name: "Reino Unido", languages: ["en"] },
  { code: "CH", name: "Suiza", languages: ["de", "fr", "it"] },
  { code: "NO", name: "Noruega", languages: ["no"] },
  { code: "US", name: "Estados Unidos", languages: ["en"] },
  { code: "CA", name: "Canadá", languages: ["en", "fr"] },
  { code: "MX", name: "México", languages: ["es"] },
  { code: "BR", name: "Brasil", languages: ["pt"] },
  { code: "AR", name: "Argentina", languages: ["es"] },
  { code: "CL", name: "Chile", languages: ["es"] },
  { code: "CO", name: "Colombia", languages: ["es"] },
  { code: "PE", name: "Perú", languages: ["es"] },
  { code: "AE", name: "Emiratos Árabes Unidos", languages: ["ar", "en"] },
  { code: "SA", name: "Arabia Saudí", languages: ["ar"] },
  { code: "JP", name: "Japón", languages: ["ja"] },
  { code: "CN", name: "China", languages: ["zh"] },
  { code: "KR", name: "Corea del Sur", languages: ["ko"] },
  { code: "IN", name: "India", languages: ["en", "hi"] },
  { code: "AU", name: "Australia", languages: ["en"] },
  { code: "ZA", name: "Sudáfrica", languages: ["en"] },
  { code: "MA", name: "Marruecos", languages: ["ar", "fr"] },
  { code: "TR", name: "Turquía", languages: ["tr"] },
];

/**
 * Comunidades y ciudades autónomas de España (ISO 3166-2).
 * Útiles en contratación pública: el ámbito autonómico define a quién le interesa el contrato.
 */
export const ES_AUTONOMOUS_COMMUNITIES: readonly EuCountry[] = [
  { code: "ES-AN", name: "Andalucía", languages: ["es"] },
  { code: "ES-AR", name: "Aragón", languages: ["es"] },
  { code: "ES-AS", name: "Asturias", languages: ["es"] },
  { code: "ES-IB", name: "Illes Balears", languages: ["es", "ca"] },
  { code: "ES-CN", name: "Canarias", languages: ["es"] },
  { code: "ES-CB", name: "Cantabria", languages: ["es"] },
  { code: "ES-CL", name: "Castilla y León", languages: ["es"] },
  { code: "ES-CM", name: "Castilla-La Mancha", languages: ["es"] },
  { code: "ES-CT", name: "Cataluña", languages: ["es", "ca"] },
  { code: "ES-VC", name: "Comunidad Valenciana", languages: ["es", "ca"] },
  { code: "ES-EX", name: "Extremadura", languages: ["es"] },
  { code: "ES-GA", name: "Galicia", languages: ["es", "gl"] },
  { code: "ES-MD", name: "Madrid", languages: ["es"] },
  { code: "ES-MC", name: "Murcia", languages: ["es"] },
  { code: "ES-NC", name: "Navarra", languages: ["es", "eu"] },
  { code: "ES-PV", name: "País Vasco", languages: ["es", "eu"] },
  { code: "ES-RI", name: "La Rioja", languages: ["es"] },
  { code: "ES-CE", name: "Ceuta", languages: ["es"] },
  { code: "ES-ML", name: "Melilla", languages: ["es"] },
];

/** Catálogo de presets UI: UE + mercados extra (solo países). */
export const PRESET_COUNTRIES: readonly EuCountry[] = [...EU_COUNTRIES, ...EXTRA_COUNTRIES];

/**
 * Catálogo UI completo: países + CCAA españolas.
 * La API acepta cualquier ISO-2 / ISO 3166-2 bien formado, no solo este preset.
 */
export const PRESET_GEOGRAPHIES: readonly EuCountry[] = [
  ...PRESET_COUNTRIES,
  ...ES_AUTONOMOUS_COMMUNITIES,
];

/** Mercados prioritarios del producto: se muestran primero y preseleccionados. */
export const PRIORITY_COUNTRY_CODES: readonly string[] = ["ES", "DE"];

const byCode = new Map(PRESET_GEOGRAPHIES.map((country) => [country.code, country]));

export function euCountryName(code: string): string {
  return byCode.get(code.toUpperCase())?.name ?? code.toUpperCase();
}

/** Idiomas sugeridos (sin duplicados, en orden de selección) para los códigos dados. */
export function languagesForCountries(codes: readonly string[]): string[] {
  return [
    ...new Set(
      codes.flatMap((code) => {
        const upper = code.toUpperCase();
        const direct = byCode.get(upper)?.languages;
        if (direct) return direct;
        // ES-VC → idiomas de ES si no hay entrada de subdivisión (no debería pasar con CCAA).
        const country = upper.split("-")[0];
        return byCode.get(country)?.languages ?? [];
      }),
    ),
  ];
}

/** True si el valor es un código ISO 3166-1 alpha-2 bien formado. */
export function isIsoAlpha2(code: string): boolean {
  return /^[A-Za-z]{2}$/.test(code.trim());
}

/**
 * True si el valor es ISO 3166-1 alpha-2 o ISO 3166-2 (subdivisión).
 * Alineado con la validación de la API (`_ISO_GEOGRAPHY`).
 */
export function isIsoGeographyCode(code: string): boolean {
  return /^[A-Za-z]{2}(-[A-Za-z0-9]{1,3})?$/.test(code.trim());
}
