# Runbooks operativos de OPN Oracle

Estos procedimientos son borradores ejecutables que deben validarse en staging durante las fases
14–15. No contienen IPs, credenciales ni comandos que borren datos. Ante cualquier sospecha
cross-tenant o compromiso de sesión prevalece preservar evidencia y cortar exposición sobre
recuperar disponibilidad.

| Incidente | Runbook |
|---|---|
| API caída / readiness | `DEPENDENCIES.md` |
| PostgreSQL / pool | `DEPENDENCIES.md` |
| Redis | `DEPENDENCIES.md` |
| Celery backlog/fallos | `ASYNC_AND_SIGNAL.md` |
| Signal degradado | `ASYNC_AND_SIGNAL.md` |
| Certificado | `HOST_AND_DATA.md` |
| Disco | `HOST_AND_DATA.md` |
| Backup | `HOST_AND_DATA.md` |
| Compromiso de sesión | `SECURITY_INCIDENTS.md` |
| Sospecha cross-tenant | `SECURITY_INCIDENTS.md` |

Reglas comunes: declarar incidente y hora UTC; asignar incident commander y escriba; usar IDs de
request/job, no payloads sensibles; no improvisar SQL de escritura; registrar cada cambio y su
rollback; y cerrar solo con causa, impacto, evidencia y acciones preventivas.

