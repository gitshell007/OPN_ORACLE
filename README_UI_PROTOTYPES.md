# OPN Oracle — escaparate A/B

> Documento de referencia del escaparate disponible solo en desarrollo. La aplicación productiva canónica, sus rutas Flask y los comandos actuales se documentan en `README.md`.

Frontend de OPN Oracle con Vector como interfaz canónica autenticada y Horizon conservado como referencia comparativa sobre datos sintéticos:

- **Vector Command Center:** navegación lateral, alta densidad, tabla operativa e inspección rápida.
- **Horizon Decision Canvas:** prototipo comparativo no canónico, conservado temporalmente como referencia.

## Arranque

```bash
npm ci
npm run dev
```

Abre `http://localhost:3000`. La raíz contiene el guion neutral de comparación.

Para conectar Vector con Flask durante desarrollo, arranca la API y usa el proxy same-origin:

```bash
ORACLE_API_ORIGIN=http://127.0.0.1:8000 npm run dev
```

En producción Nginx enruta `/api` a Flask. La web usa cookie opaca `HttpOnly`,
`credentials: include` y CSRF conservado únicamente en memoria.

## Rutas

| Ruta                                                    | Contenido                         |
| ------------------------------------------------------- | --------------------------------- |
| `/`                                                     | Selector y guía de evaluación     |
| `/concept-a/portfolio`                                  | Portfolio Vector                  |
| `/concept-a/dossiers/dach-2027`                         | Expediente Vector                 |
| `/concept-a/settings`                                   | Ajustes Vector                    |
| `/login`, `/forgot-password`, `/reset-password`         | Identidad y recuperación          |
| `/concept-a/settings/profile`, `/security`, `/sessions` | Cuenta y sesiones reales          |
| `/concept-a/admin/members`, `/audit`                    | Administración tenant por permiso |
| `/platform/tenants`, `/users`, `/audit`                 | Portal diferenciado de plataforma |
| `/concept-b/portfolio`                                  | Canvas Horizon                    |
| `/concept-b/dossiers/dach-2027`                         | Expediente Horizon                |
| `/concept-b/settings`                                   | Ajustes Horizon                   |

## Interacciones

- Búsqueda, filtros, ordenación, selección y densidad de tablas.
- Creación validada de un expediente y persistencia en ambos conceptos.
- Inspección de señales y acciones de revisión, descarte y promoción.
- Menú de usuario, notificaciones y búsqueda global con `⌘K` / `Ctrl+K`.
- Preferencias persistentes con efecto visible en densidad y navegación.
- Selector flotante A/B ocultable para capturas limpias.

## Estado local y restablecimiento

La demo utiliza claves versionadas de `localStorage`:

```text
opn-oracle-prototype:v1:settings
opn-oracle-prototype:v1:dossiers:tenant:<tenant-id>
opn-oracle-prototype:v1:signal-actions:tenant:<tenant-id>
```

Usa **Restablecer estado de la demo** en `/` o **Restablecer preferencias** en Ajustes. No se guardan credenciales ni información sensible.

## Arquitectura y conexión a Flask

Los tipos, fixtures y persistencia de `src/lib/oracle` pertenecen exclusivamente a `/concept-*`. Las rutas `/app` consumen el cliente tipado de Flask y no montan `OracleProvider` ni `MockOracleRepository`. En producción, `/` y `/concept-*` redirigen a `/app`, y la build rechaza la activación explícita de prototipos.

Autenticación, dominio estratégico, documentos, informes, notificaciones, administración tenant y plataforma consumen Flask mediante el cliente de `packages/api-client`:

1. `npm run api:client:generate` regenera tipos desde `docs/api/openapi.json`.
2. `npm run api:client:check` detecta drift del artefacto generado.
3. Signal Avanza permanece tras su adaptador en Flask y fuera del navegador.

Los shells, layouts, tablas, inspectores y ajustes visuales están separados bajo `components/concept-a` y `components/concept-b`.

## Verificación

```bash
npm run lint
npm run typecheck
npm run test
npm run build
npm run test:e2e
```

## ZIP limpio para revisión con ChatGPT

```bash
./scripts/create-chatgpt-exam-zip.sh
```

Genera `dist/opn-oracle-chatgpt-exam.zip` mediante una lista blanca. Incluye únicamente código, configuración, documentación y tests; excluye dependencias, cachés, capturas, Git, archivos del IDE y el Python de ejemplo.

## Limitaciones deliberadas

- `/concept-a` y `/concept-b` conservan fixtures tenant-namespaced para comparación; `/app` usa Flask.
- Las referencias a Nexus y Sentinel dentro de los conceptos son demostrativas; Signal Avanza productivo vive tras el adaptador Flask.
- Las acciones del escaparate pueden ser simuladas; informes, documentos, exportaciones y sincronización de `/app` usan flujos reales y jobs durables.
- El grafo y la matriz de actores son representaciones de prototipo, no motores de análisis relacional.
