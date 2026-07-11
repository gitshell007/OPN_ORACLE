# Security signoff · v0.1.0-rc.1

## Resultado

No se firma el release definitivo. No hay critical/high de código conocidos sin corregir, pero
persisten gates de release no satisfechos.

## Controles verificados

- HTTPS y redirect; PostgreSQL/Redis sin puertos públicos; health y servicios sanos.
- Sesión opaca, CSRF, RBAC/RLS e IDOR cubiertos por las suites de fases anteriores.
- Workflows con `contents: read`, checkout sin credenciales persistentes y acciones fijadas por SHA.
- Backups locales diarios, retención 30 días, restore aislado y restauración productiva con TTY.

## Bloqueos

1. Árbol de trabajo no consolidado y candidato no reproducible desde un commit remoto.
2. Workflows nuevos aún no ejecutados; no existe evidencia actual de Trivy/SBOM sobre este commit.
   La ejecución aislada backend pasa 99 tests pero falla el gate de cobertura al excluir integración.
3. Copia off-host diaria y restore periódico desde descarga no automatizados.
4. Documentos productivos siguen deshabilitados hasta S3/ClamAV/sandbox aprobados.
5. Signal HTTP e IA real siguen deshabilitados por falta de gates de proveedor/contrato.

Estos gates no se aceptan implícitamente ni reciben owner/fecha inventados.
