# OPN Oracle

OPN Oracle es una aplicación de inteligencia estratégica centrada en el expediente (`StrategicDossier`). La interfaz productiva canónica es **Vector Command Center** y consume Flask como autoridad de datos, permisos y concurrencia.

## Arranque local

```bash
npm ci
cd apps/api && uv sync --frozen && cd ../..
ORACLE_API_ORIGIN=http://127.0.0.1:8000 npm run dev
```

Arranca Flask en otra terminal siguiendo [apps/api/README.md](apps/api/README.md). La web usa cookie de sesión `HttpOnly`, `credentials: include` y CSRF en memoria.

## Superficies

- `/app`: inicio productivo con read model agregado.
- `/app/dossiers`: inventario server-side; `/app/dossiers/:id/*`: contexto completo.
- `/app/changes`: transiciones estratégicas durables.
- `/app/signals`, `/opportunities`, `/risks`, `/actors`, `/meetings`, `/tasks`: vistas globales autorizadas.
- `/app/reports`, `/notifications`, `/exports`: entrega y seguimiento.
- `/app/admin/*`: administración tenant; `/platform/*`: portal separado para superadministración.
- `/login` y flujos asociados: autenticación, recuperación e invitaciones.

En desarrollo, `/`, `/concept-a/*` y `/concept-b/*` conservan el escaparate comparativo con datos sintéticos. En producción redirigen a `/app`. Una build con `ORACLE_ENABLE_UI_PROTOTYPES=1` falla deliberadamente para impedir que el repositorio mock se habilite como producto.

## Contrato API

```bash
npm run api:openapi
npm run api:client:generate
npm run api:client:check
```

El contrato exportado vive en `docs/api/openapi.json` y el cliente generado en `packages/api-client`. Las pantallas productivas no importan fixtures ni `MockOracleRepository`.

## Verificación

```bash
npm run lint
npm run typecheck
npm run test
npm run build
npm run test:e2e
npm run quality:scan

scripts/api-test.sh
```

`scripts/api-test.sh` resuelve `uv` desde `~/.local/bin/uv` antes de consultar el `PATH`, por lo
que funciona también en shells no interactivos que no cargan `.zshrc`. Si no se han definido
`ORACLE_RUN_INTEGRATION=1`, `TEST_DATABASE_URL`, `TEST_RUNTIME_DATABASE_URL` y `TEST_REDIS_URL`,
intenta levantar PostgreSQL y Redis desechables con Docker; sin Docker falla cerrado para no saltar
integraciones ni cobertura.

En un entorno sin Docker, antes de entregar trabajo, usa la comprobación rápida:

```bash
scripts/api-test.sh --unit
```

Ejecuta lint, formato, tipos y los tests unitarios sin umbral de cobertura, y avisa de que es
parcial. **No sustituye al gate de release** —los tests de integración no se ejecutan y el release
sigue exigiendo CI verde del SHA exacto— pero detecta la mayoría de las regresiones en segundos.
Entregar código sin haber ejecutado al menos esto no es aceptable.

Las pruebas de integración backend requieren PostgreSQL/Redis desechables y las variables descritas en [apps/api/README.md](apps/api/README.md).

## Preferencias y restablecimiento

Las preferencias visuales productivas son locales al navegador y pueden restablecerse desde `/app/account/preferences`. Los prototipos guardan su propio estado versionado y solo están disponibles en desarrollo. Ninguna credencial se persiste en `localStorage`.

## Documentación

- [Estado de implementación](docs/implementation/STATUS.md)
- [Arquitectura de información](docs/product/INFORMATION_ARCHITECTURE.md)
- [Navegación](docs/product/NAVIGATION_SPEC.md)
- [Matriz ruta/permiso](docs/product/ROUTE_PERMISSION_MATRIX.md)
- [Arquitectura técnica](docs/architecture/REPOSITORY_MAP.md)
- [Estrategia y matriz de pruebas](docs/quality/TEST_STRATEGY.md)
- [Readiness de seguridad](docs/security/READINESS_REPORT.md)

## Paquete de revisión

```bash
./scripts/create-chatgpt-exam-zip.sh
```

Genera `dist/opn-oracle-chatgpt-exam.zip` mediante lista blanca, sin dependencias, cachés, secretos ni artefactos locales.
