# Go / No-Go · v0.1.0-rc.1

## Decisión

`NO-GO`

## Razones

- La aplicación base está desplegada y el primer tenant puede crearse, pero no se ha completado el
  UAT funcional con owner y roles separados.
- El árbol local contiene el producto y fixes aún no consolidados en un commit/tag reproducible.
- CI/CD está implementado en el workspace, pero todavía no ha producido una ejecución verde ni
  imágenes GHCR promovibles.
- Falta automatizar la copia off-host diaria y probar restore desde una descarga remota.
- Los gates de documentos, Signal real e IA real permanecen cerrados.

## Condiciones para reconsiderar

Commit/revisión del árbol, CI verde, imágenes por digest, owner y UAT completo, copia off-host
automática con receipt y restore descargado, scans sin critical/high y aprobación explícita de GO.

