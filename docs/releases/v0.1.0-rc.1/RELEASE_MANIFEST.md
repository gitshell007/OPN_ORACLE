# Release manifest · v0.1.0-rc.1

## Identidad

| Campo | Valor |
|---|---|
| Estado | candidato, no publicado como release Git |
| Commit base | `2ab0e14` en `master` |
| Árbol | con cambios no consolidados; no reproducible todavía desde GitHub |
| Producción activa | `20260711T163100Z-superadmin-entry` |
| Release anterior | `20260711T141509Z-backup-control` |
| Migración | `20260711_0011` |
| UI | Vector |

## Runtime observado en producción

- API/web: imágenes locales con tag inmutable `20260711T163100Z-superadmin-entry`.
- PostgreSQL 17.10, Redis 7.4.9, Celery 5.6.3, Nginx 1.28.3.
- Seis servicios activos; API, web, PostgreSQL, Redis y worker sanos; un único beat.
- Certificado Let's Encrypt para `oracle.opnconsultoria.com`, válido hasta 2026-10-09.
- GitHub Actions y publicación candidata GHCR quedan definidos en `.github/workflows`, pero no
  existen en el commit remoto hasta revisión/commit/push.

## Trazabilidad operativa

`CURRENT_RELEASE`, `ORACLE_RELEASE` y el enlace `current` fueron reconciliados a
`20260711T163100Z-superadmin-entry`. El control local incorpora actualización atómica del marcador
para activación, rollback y restauración tras fallo.

