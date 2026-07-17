# Protección de rama `master`

Estado: cambio manual pendiente en GitHub. No está configurado desde el repositorio.

Durante UAT la decisión vigente es:

- ejecutar `CI` automáticamente en cada `pull_request` hacia `master`;
- conservar `workflow_dispatch` para validaciones puntuales;
- no ejecutar CI en cada `push`;
- bloquear `release.yml` si el SHA exacto no tiene un run `CI` con conclusión `success`.

Cuando se cierre UAT, configurar la protección de `master` en GitHub:

1. Ir a `Settings` → `Branches` → `Branch protection rules`.
2. Crear o editar la regla para `master`.
3. Activar `Require a pull request before merging`.
4. Activar `Require status checks to pass before merging`.
5. Activar `Require branches to be up to date before merging`.
6. Marcar como requeridos estos checks del workflow `CI`:
   - `Frontend and contract`
   - `Backend, migrations and integration`
   - `Security, images and SBOM`

Procedimiento de excepción: si GitHub Actions tiene una incidencia y el responsable de producto
autoriza publicar sin CI verde, debe registrarse manualmente en el runbook operativo con SHA,
motivo, verificación alternativa, aprobador y ventana de rollback. El workflow `release.yml` no
implementa bypass: falla cerrado.
