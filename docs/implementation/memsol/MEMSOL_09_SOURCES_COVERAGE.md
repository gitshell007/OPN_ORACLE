# MEMSOL-09 · Fuentes, cobertura y retención

## Naming honesto

| Etiqueta UI | Capacidad real Signal hoy | Nota |
|---|---|---|
| Menciones web | web_search / OSINT | **no** es prensa verificada con medio+fecha garantizados |
| Publicaciones oficiales | BORME, BOE/gazette, CNMV, EUR-Lex… | salud por conector |
| Licitaciones | PLACSP/TED multicountry | active vs historical |
| Propiedad industrial | patents EPO / OEPM | credenciales cifradas |

## coverage_manifest

Cada job de pregunta/informe debe rellenar `requested/consulted/failed/excluded/used`.
Una fuente fallida **no** se presenta como ausencia de información.

## Retención

- Signal usage logs: política 2026-07-31 (agregados permanentes, payloads 7d…)
- Memory sources: tombstone + hash al expirar
- Oracle evidence: políticas existentes + soft-delete documents

## Gate

Reconstruir manifest y coste de un job desde audit; health de conector visible en Actividad.
