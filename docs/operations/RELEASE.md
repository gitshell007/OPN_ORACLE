# Release

## Objetivo

Promover un commit validado a imágenes inmutables y activar producción con aprobación humana.

## Prerrequisitos y procedimiento rápido

- CI verde del workflow `CI` para el SHA exacto que se va a publicar; `release.yml` falla cerrado
  si no existe esa ejecución `success`. Los checks locales no sustituyen este gate.
- Backup pre-release local y restore aislado válidos.
- Preparar `/opt/opn-oracle/releases/<release>` desde el commit validado, con
  `RELEASE_SHA256SUMS`, y ejecutar `sudo oracle-control update <release>`.
- Confirmar health, HTTPS, Celery, un único beat y smoke funcional.

El receipt off-host cifrado es opcional por defecto para iteración rápida. Vuelve a ser obligatorio
si el operador activa `ORACLE_REQUIRE_OFFSITE_RECEIPT=1`.

## Fallo, rollback y escalado

El activador solo restaura punteros si el fallo ocurre antes de iniciar migración o arranque de la
aplicación. Desde `mutation_started` en adelante conserva el release seleccionado, no revierte
esquema y exige diagnóstico/forward-fix explícito. No ejecutar downgrade automático de base de
datos: preservar logs, ejecutar `oracle-control health` para revisar coherencia y aplicar
[ROLLBACK.md](./ROLLBACK.md) solo si el esquema actual es compatible.
