# Oracle release candidate: MEMSOL local-only (Signal task keys)

| Campo | Valor |
|--------|--------|
| Branch | `release/memsol-local-only` |
| Base | `origin/master` @ `abff6e7` |
| Extra | `082a3c9` wiring + Titan schema coerce |
| **No deploy** | este doc no autoriza producción |

## Contenido

- Migraciones **`20260731_0027`** → **`20260731_0028`** (ya en master; head de cadena desde `20260726_0026`).
- Workers Celery `oracle.dossier_question.answer` / `oracle.report.custom_brief.plan` (master).
- UI Actividad/Preguntar/brief (master).
- **Cableado** `execute_agent` → Signal task_keys (cherry-pick).
- Coerción Titan en schemas (cherry-pick).

## Dev vs Prod

| Entorno | Acción propuesta (futura) |
|---------|---------------------------|
| Oracle Dev | Deploy release dir desde esta branch; alembic ya puede estar en 0028 en dev |
| Oracle Prod | Solo tras GO + auth; backup; upgrade 0026→0027→0028; recreate workers |

## Rollback

1. `CURRENT_RELEASE` → `PREVIOUS_RELEASE` (symlink files).
2. Si 0027/0028 ya aplicadas y hay que deshacer datos: restore desde `/var/backups/opn-oracle/<id>/` (`docs/operations/BACKUP_RESTORE.md`).
3. Downgrade alembic solo con plan de datos: `20260731_0028` → `20260726_0026` **no** es trivial si hay filas nuevas.

## Dependencia Signal

Requiere Signal release `release/memsol-local-only` (task keys + attempts) **antes** o en el mismo cut de canario.
