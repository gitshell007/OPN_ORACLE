# 26 — Redespliegue: activar el fix del panel «Objetivos e hipótesis» (P24)

> Prompt de operación para Codex **con acceso al host de producción**. No es un cambio de código:
> el fix ya está en `master`. El objetivo es **cortar un release y activarlo** siguiendo el runbook,
> con backup y smoke, para que el panel «Objetivos e hipótesis» deje de fallar en producción.

## Contexto

- Auditoría en vivo del 2026-07-13: tras desplegar la remediación de UX (commit `2e6f390`), el panel
  **«Objetivos e hipótesis»** del Resumen del expediente cargaba con error rojo **«Paginación u
  ordenación no válida»**. Causa: el panel pide las listas con `sort=position`, pero `_model_page`
  (`apps/api/src/opn_oracle/oracle/routes.py`) no incluía `"position"` en su lista blanca de
  ordenación.
- **Fix ya mergeado en `master`:** commit **`5ceae64`** («fix: allow sorting dossier objectives and
  hypotheses by position»). Verificado en local: Ruff, mypy y `108 passed`.
- **No hay migración** en este cambio → es un **upgrade solo de aplicación** (menor riesgo, rollback
  de app seguro sin tocar esquema). El release anterior activo contiene `2e6f390`.

## Fuentes de verdad (léelas antes de operar)

`docs/operations/RELEASE.md`, `docs/operations/DEPLOYMENT.md`, `docs/operations/CONTROL_CENTER.md`,
`docs/operations/BACKUP_RESTORE.md` y `docs/operations/ROLLBACK.md`. Respeta `AGENTS.md §14`
(auditoría read-only previa, no tocar SSH/UFW/Nginx, backup antes de actuar) y los gates de la
fase 14/15. No ejecutes `git pull`, `docker compose down/-v`, `DROP DATABASE`, `pg_restore` sobre
producción ni Alembic downgrade.

## Procedimiento

1. **Prerrequisito CI:** confirma que el pipeline de GitHub Actions está **verde** en `5ceae64`
   (frontend, backend con PostgreSQL/Redis/Celery, migraciones, scans, imágenes, SBOM).
2. **Backup pre-release verificado:** crea backup local y prueba restore aislado; conserva el
   manifiesto y la evidencia. En el host:
   ```bash
   sudo /opt/opn-oracle/current/scripts/oracle-control.sh backup
   sudo /opt/opn-oracle/current/scripts/oracle-control.sh restore-test
   ```
3. **Preparar el release** desde el commit `5ceae64` como artefacto inmutable en
   `/opt/opn-oracle/releases/<release-id>` con su `RELEASE_SHA256SUMS`, siguiendo el modelo de
   `RELEASE.md`/`DEPLOYMENT.md` (sin `.git`, `.env`, credenciales ni resultados de tests; secretos y
   `oracle.env` permanecen en `/etc/opn-oracle`). El `<release-id>` debe ser inmutable
   (commit + timestamp).
4. **Preflight** en el nuevo release:
   ```bash
   cd /opt/opn-oracle/releases/<release-id>
   ORACLE_SECRETS_DIR=/etc/opn-oracle/secrets \
     docker compose --env-file /etc/opn-oracle/oracle.env -f compose.prod.yml config --quiet
   ```
5. **Activar** el release (el activador restaura punteros si falla):
   ```bash
   sudo /opt/opn-oracle/current/scripts/oracle-control.sh update <release-id>
   ```
   Como no hay migración nueva, Alembic no debe aplicar cambios de esquema; verifica que el head
   sigue siendo `20260712_0015` y que no se ejecuta ningún downgrade.
6. **Smoke y salud:**
   ```bash
   ./scripts/smoke-production.sh https://oracle.opnconsultoria.com
   sudo /opt/opn-oracle/current/scripts/oracle-control.sh health
   ```
   Confirma HTTPS 200, un único beat, Celery `pong`, API/web solo en loopback y PostgreSQL/Redis sin
   puertos publicados.
7. **Rollback si algo falla:** `sudo /opt/opn-oracle/current/scripts/oracle-control.sh rollback`
   (solo aplicación; nunca esquema). Sigue `ROLLBACK.md`.

> Nota operativa 2026-07-13: durante UAT el receipt off-host cifrado no bloquea este despliegue.
> Para volver al gate estricto, ejecutar con `ORACLE_REQUIRE_OFFSITE_RECEIPT=1` y aportar
> `ORACLE_BACKUP_OFFSITE_RECEIPT`.

## Verificación específica del fix (obligatoria)

Autenticado en Vector, entra en un expediente con base inicial (por ejemplo el de prueba
«Gigafactoría de baterías CATL-Stellantis», `292d85e5-3dc1-4c2f-81a5-8a73a29e1fb4`) y en el
**Resumen** confirma que:

- [ ] El panel **«Objetivos e hipótesis»** carga **sin** el error «Paginación u ordenación no
      válida» y muestra el objetivo y las dos hipótesis de la base inicial, ordenados por `position`.
- [ ] No hay errores de consola en esa vista.

## Criterios de aceptación del despliegue

- [ ] Release inmutable activo desde `5ceae64` con manifest/checksums; head `20260712_0015` sin
      migración nueva.
- [ ] Smoke público, health, worker y beat correctos.
- [ ] Panel «Objetivos e hipótesis» funcional en producción.
- [ ] Backup pre-release local + restore aislado registrados; receipt off-host solo si se activa el
      modo estricto.
- [ ] `docs/implementation/STATUS.md` actualizado con release-id, comandos ejecutados y resultado.

## No hacer

- No apliques cambios de código en este prompt: el fix ya está en `master`.
- No modifiques Nginx/UFW/SSH/TLS ni ejecutes migraciones/downgrades.
- No publiques en salidas compartidas la config, secretos, tokens ni URLs completas.
