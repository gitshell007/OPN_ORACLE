# Taxonomía CPV española

`cpv_2008_es.json` contiene las 9.454 etiquetas españolas del Common Procurement
Vocabulary, versión 2008.

- Fuente oficial: Publications Office of the European Union.
- Dataset: `http://publications.europa.eu/resource/dataset/cpv`.
- Esquema de conceptos: `http://data.europa.eu/cpv/cpv`.
- Endpoint reproducible: `https://publications.europa.eu/webapi/rdf/sparql`.
- Fecha de descarga: 2026-07-23.
- SHA-256 del fichero versionado:
  `19868de65c3d4660382d83d2c79a9a53e292bde19741cf491d5faf0cd7893852`.
- Consulta y comprobación del recuento: `scripts/update_cpv_taxonomy.py`.

La aplicación carga este fichero sin red. Para actualizarlo, ejecuta el script y
revisa tanto el recuento como el diff antes de commitear.
