# Mapa del repositorio

**Fecha de auditoría:** 2026-07-10  
**Estado:** actualizado tras las fases 02–03  
**Decisión de interfaz:** `CANONICAL_UI=vector`

## Resumen ejecutivo

El repositorio conserva el frontend en la raíz y añade el backend autoritativo en `apps/api`. Ya existen Flask, OpenAPI, migraciones, modelos de plataforma, PostgreSQL/Redis configurables, RLS y Compose de desarrollo. `main.py` sigue siendo únicamente el ejemplo de PyCharm. Celery funcional, CI/CD, Nginx y despliegue productivo permanecen pendientes.

Vector Command Center es la interfaz canónica por decisión explícita del usuario. Horizon Decision Canvas permanece en `concept-b` únicamente como prototipo comparativo no canónico y descartable. No debe recibir nuevas capacidades productivas ni condicionar los contratos del backend. Su retirada o archivo se hará en un cambio posterior y explícito, nunca como parte de la fundación Flask.

## Baseline técnico real

| Área | Estado detectado |
|---|---|
| Git | Rama `master`, commit base `2ab0e14`; abundantes cambios y archivos no versionados del usuario |
| Gestor frontend | npm 11.17.0 con `package-lock.json` |
| Runtime observado | Node 26.5.0; Python 3.11 para la API mediante `uv` |
| Framework web | Next.js 16.2.10, React/React DOM 19.2.7, App Router |
| Lenguaje | TypeScript 6.0.3, `strict: true`, alias `@/* -> src/*` |
| UI | Radix, TanStack Table, React Hook Form, Zod, Lucide y Sonner |
| Tests | Vitest y Playwright; smoke A/B y test unitario de fixtures |
| Backend | Flask modular en `apps/api`; `main.py` no es backend de producto |
| Persistencia | Fixtures y `localStorage` de navegador, solo para la demo |
| Infraestructura | Dockerfile, Compose de desarrollo e init PostgreSQL; producción pendiente |

Las versiones anteriores son las resueltas por el lockfile instalado. `package.json` declara dependencias como `latest`, lo que reduce la reproducibilidad si se regenera el lockfile y debe corregirse de forma controlada en una fase posterior.

## Módulos existentes

```text
src/
├── app/                         # Next.js App Router
│   ├── page.tsx                 # selector comparativo A/B
│   ├── layout.tsx               # OracleProvider y toasts
│   ├── concept-a/               # Vector, interfaz canónica
│   │   ├── portfolio/
│   │   ├── dossiers/[id]/
│   │   └── settings/
│   └── concept-b/               # Horizon, prototipo no canónico
├── components/
│   ├── concept-a/               # shell y patrones propios de Vector
│   ├── concept-b/               # shell y patrones propios de Horizon
│   └── shared/                  # provider, creación y command palette de la demo
├── lib/oracle/
│   ├── types.ts                 # dominio simplificado + OracleRepository
│   ├── mock-repository.ts       # implementación determinista de demo
│   ├── fixtures.ts              # datos sintéticos compartidos
│   ├── storage.ts               # persistencia local de demo
│   └── format.ts
└── styles/                      # tokens/estilos separados por concepto
```

### Rutas existentes

| Ruta | Función | Futuro |
|---|---|---|
| `/` | Comparador de prototipos | sustituir por entrada/login cuando se consolide Vector |
| `/concept-a/portfolio` | portfolio Vector | base de la interfaz canónica |
| `/concept-a/dossiers/[id]` | detalle Vector | base del expediente canónico |
| `/concept-a/settings` | preferencias Vector | evolucionar a cuenta/tenant/sesiones reales |
| `/concept-b/portfolio` | portfolio Horizon | prototipo no canónico |
| `/concept-b/dossiers/[id]` | detalle Horizon | prototipo no canónico |
| `/concept-b/settings` | ajustes Horizon | prototipo no canónico |

## Capa de datos del prototipo

`OracleRepository` define seis operaciones de demo: listar/obtener/crear expedientes, listar/actualizar señales y actualizar ajustes. `MockOracleRepository` usa fixtures y una latencia fija. `OracleProvider` todavía conoce directamente fixtures y almacenamiento, por lo que la abstracción es parcial: durante la integración deberá consumir un cliente HTTP tipado y dejar los fixtures detrás de un adapter de demo/test.

Las claves `opn-oracle-prototype:v1:*` de `localStorage` guardan preferencias, expedientes creados y acciones de señales. Son estado descartable de prototipo. No contienen autenticación, pero tampoco pueden convertirse en fuente autoritativa de datos de negocio.

El único supuesto FastAPI localizado estaba en `README_UI_PROTOTYPES.md`; ya se ha corregido a Flask. El código no importa ningún SDK ni llama una API.

## Estructura objetivo menos disruptiva

No se moverá el frontend antes de que la API Flask tenga una base estable. La evolución será incremental:

```text
opn-oracle/
├── src/                          # frontend actual, permanece inicialmente
├── tests/                        # E2E frontend actual
├── apps/
│   └── api/
│       ├── pyproject.toml
│       ├── uv.lock               # o lock equivalente elegido en fase 02
│       ├── src/opn_oracle/
│       │   ├── app.py
│       │   ├── config.py
│       │   ├── extensions.py
│       │   ├── wsgi.py
│       │   ├── celery_app.py
│       │   ├── common/
│       │   ├── auth/
│       │   ├── platform/
│       │   ├── tenants/
│       │   ├── oracle/
│       │   ├── integrations/
│       │   ├── ai/
│       │   ├── notifications/
│       │   └── cli/
│       ├── migrations/
│       └── tests/
├── packages/
│   └── api-client/               # TypeScript generado desde OpenAPI Flask
├── infra/
│   ├── compose/
│   ├── nginx/
│   ├── scripts/
│   └── backups/
├── docs/
└── scripts/
```

Cuando la integración esté probada, el frontend podrá moverse a `apps/web` en un cambio mecánico aislado. Hacerlo durante la fundación Flask mezclaría riesgos sin aportar funcionalidad.

## Flujo objetivo y fronteras

```text
Navegador
  -> Next.js (presentación/SSR, puerto interno 3000)
  -> /api/v1 (cookie de sesión + CSRF)
  -> Nginx
  -> Gunicorn / Flask (autenticación, tenant, permisos y dominio)
       -> PostgreSQL (fuente de verdad)
       -> Redis (sesiones, límites, caché y broker)
       -> Celery (trabajo asíncrono durable mediante BackgroundJob)
       -> SignalAvanzaAdapter (mock o HTTP)
```

### Responsabilidades que no pueden cruzar Python/Node

Node/Next.js no puede:

- validar credenciales ni mantener la sesión autoritativa;
- decidir autorización, rol o aislamiento entre tenants;
- consultar PostgreSQL o Redis directamente;
- ejecutar reglas críticas de scoring o persistencia;
- gestionar Celery, jobs, webhooks, IA o secretos de integraciones;
- llamar Signal Avanza o proveedores IA desde el navegador;
- usar Route Handlers o Server Actions como backend paralelo de negocio.

Flask es responsable de identidad, tenant context, autorización, validación, persistencia, auditoría, OpenAPI, integraciones y coordinación de jobs. El frontend es responsable de navegación, presentación, validación de conveniencia, accesibilidad y caché de server state.

## OpenAPI y cliente TypeScript

Flask publicará el contrato versionado bajo `/api/v1` y generará un documento OpenAPI reproducible. El cliente de `packages/api-client` se regenerará desde ese documento; no se editará a mano. Una implementación HTTP adaptará inicialmente ese cliente a `OracleRepository`, permitiendo sustituir el mock sin reescribir Vector. A medio plazo, los DTO generados y los modelos de presentación deben separarse expresamente del dominio simplificado del prototipo.

## Configuración, pruebas y despliegue

| Área | Ubicación actual | Ubicación objetivo |
|---|---|---|
| Frontend config | raíz: `package.json`, `next.config.ts`, `tsconfig.json`, configs Vitest/Playwright/ESLint | raíz inicialmente; `apps/web` tras migración aislada |
| Frontend tests | `src/**/*.test.ts`, `tests/e2e` | igual inicialmente |
| API config | `apps/api/pyproject.toml`, `uv.lock` y configuración tipada | mantener y ampliar por fase |
| API tests | unitarios e integración PostgreSQL/Redis en `apps/api/tests` | ampliar con cada módulo |
| Migraciones | revisiones `0001` y `0002` | continuar con Alembic y migrador separado |
| OpenAPI | generado en `docs/api/openapi.json` | generar cliente en `packages/api-client` |
| Compose | `compose.dev.yml` e init PostgreSQL | topología productiva pendiente |
| Proxy/TLS | inexistente | `infra/nginx`; TLS/Certbot en host |
| Operaciones | scripts de captura/ZIP | `infra/scripts`, `infra/backups`, `docs/operations` |

## Plan incremental

1. ~~Crear `apps/api` con application factory, health checks y herramientas de calidad.~~
2. ~~Añadir PostgreSQL/Redis, modelos de plataforma, contexto tenant y RLS.~~
3. Implementar autenticación, sesiones opacas, CSRF y RBAC público en Flask.
4. Completar OpenAPI de auth y generar el cliente TypeScript.
5. Crear el adapter HTTP del frontend y migrar Vector flujo a flujo desde fixtures.
6. Retirar el selector A/B y archivar o borrar Horizon solo con autorización explícita.
7. Evaluar el movimiento mecánico de `src` a `apps/web` una vez estabilizados build y E2E.

## Riesgos inmediatos

- El árbol de trabajo está muy sucio y gran parte del frontend no está versionado; cualquier movimiento debe esperar a una salvaguarda/commit revisado por el usuario.
- `latest` en `package.json` compromete la reconstrucción si se pierde o regenera el lockfile.
- `OracleProvider` elude parcialmente `OracleRepository`, lo que aumenta el trabajo de sustitución por API.
- Los identificadores y DTO de demo no incluyen tenant ni versionado; no deben reutilizarse como modelos persistentes sin rediseño.
- `localStorage` es correcto solo para preferencias y estado sintético de demo; las sesiones y datos productivos deberán residir en Flask/PostgreSQL/Redis.
- Las credenciales de servidor compartidas en conversación deben considerarse expuestas y rotarse antes de cualquier despliegue. No se han usado ni copiado al repositorio.
