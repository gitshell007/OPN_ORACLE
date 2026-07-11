# UAT results · v0.1.0-rc.1

## Evidencia ejecutada el 2026-07-11

| Área | Resultado | Evidencia |
|---|---|---|
| Login superadmin | PASS | Playwright autenticado contra producción |
| Portal de plataforma | PASS | navegación y permisos de `super_admin` |
| Crear tenant | PASS | `OPN Consultoría`, slug `opn-consultoria`, plan `enterprise` |
| Catálogo de tenants | PASS | 1 organización activa y toast de confirmación |
| Backups UI/host | PASS parcial | catálogo desplegado, timers activos, 2 backups locales |
| HTTPS | PASS | HTTP 308 a HTTPS y `/health/live` 200 |
| Celery | PASS | worker responde ping y un beat |
| Frontend unit/component | PASS | 22 archivos, 70 tests |
| Frontend lint/tipos/build | PASS | ESLint, TypeScript y build correctos |
| Backend unitario aislado | FAIL de gate | 99 pasan y 62 se omiten; cobertura 40,34 % < 85 % al excluir integración |
| Backend completo | NOT RUN en este cierre | requiere PostgreSQL/Redis de prueba; última evidencia previa 258/258 |
| Owner del primer tenant | PASS parcial | invitación real creada para el destinatario autorizado; usuario/membership `invited`, rol `owner`, token vigente y job Graph `succeeded` |
| UAT funcional Oracle | NOT RUN | requiere owner/membership y datos sintéticos controlados |
| Matriz completa de roles | PASS automatizado / NOT RUN manual | suites previas cubren RBAC/RLS; falta UAT manual separada |
| Restore desde descarga off-host | NOT RUN | existe restore local probado; falta automatización de descarga |
| CI remoto | NOT RUN | workflows aún no consolidados en GitHub |

## Defecto corregido durante UAT

El superadmin sin tenant era dirigido a `/app` y veía acceso restringido. El login ahora dirige a
`/platform/tenants`; una entrada manual en `/app` también redirige. La recreación de Redis invalidó
sesiones como estaba previsto y se comprobó el acceso posterior.

El formulario de owner enviaba un campo interno `role` que el allowlist de Flask rechazaba con 422,
aunque los dos campos visibles fueran válidos. Se retiró ese campo redundante, se añadió una prueba
de regresión del payload exacto y se desplegó el release
`20260711T165300Z-invite-owner-fix`. La invitación se repitió mediante Playwright: el formulario se
limpió, mostró `Propietario invitado` y PostgreSQL confirmó usuario/membership invitados, rol
`owner`, invitación vigente y entrega Graph completada en el primer intento.

La primera revisión del owner detectó identificadores internos en inglés y varios defectos de
espaciado. Se añadió traducción central para procesos/colas/estados/roles, se retiró microcopy
técnica de las rutas productivas y se corrigieron la altura de procesos, el vacío de informes,
los márgenes del resumen del expediente y la cabecera del modal de creación. La regresión queda
cubierta por pruebas de copias de producto y del modal de tareas.

## Pendiente para completar UAT

Aceptar la invitación enviada, recorrer creación de expediente y módulos Oracle,
ejecutar roles negativos/cross-tenant manuales, fallos controlados y responsive/axe sobre el release
candidato reproducible.
