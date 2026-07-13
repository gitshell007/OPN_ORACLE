# Release

## Objetivo

Promover un commit validado a imágenes inmutables y activar producción con aprobación humana.

## Prerrequisitos y procedimiento rápido

- CI verde o checks locales equivalentes cuando el cambio todavía esté en UAT.
- Backup pre-release local y restore aislado válidos.
- Preparar `/opt/opn-oracle/releases/<release>` desde el commit validado, con
  `RELEASE_SHA256SUMS`, y ejecutar `sudo oracle-control update <release>`.
- Confirmar health, HTTPS, Celery, un único beat y smoke funcional.

El receipt off-host cifrado es opcional por defecto para iteración rápida. Vuelve a ser obligatorio
si el operador activa `ORACLE_REQUIRE_OFFSITE_RECEIPT=1`.

## Fallo, rollback y escalado

El activador restaura punteros si falla. No ejecutar downgrade automático de base de datos:
preservar logs y aplicar [ROLLBACK.md](./ROLLBACK.md) o forward-fix según la migración.
