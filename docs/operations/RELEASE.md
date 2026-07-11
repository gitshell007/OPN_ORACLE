# Release

## Objetivo

Promover un commit validado a imágenes inmutables y activar producción con aprobación humana.

## Prerrequisitos y procedimiento

- CI verde, diff revisado y entorno GitHub `production` con reviewers.
- Backup pre-release, restore aislado y receipt off-host válidos.
- Ejecutar `Release candidate`: se esperan dos digests GHCR y un manifiesto, nunca `latest`.
- Preparar `/opt/opn-oracle/releases/<release>` con `RELEASE_SHA256SUMS` y ejecutar
  `sudo /opt/opn-oracle/current/scripts/oracle-control.sh update <release>`.
- Confirmar health, HTTPS, Celery, un único beat y smoke funcional.

## Fallo, rollback y escalado

El activador restaura punteros si falla. No ejecutar downgrade automático de base de datos:
preservar logs y aplicar [ROLLBACK.md](./ROLLBACK.md) o forward-fix según la migración.

