# ClamAV para documentos

Oracle mantiene el pipeline documental en modo fail-closed: un documento solo es descargable y
citable si está `ready` y `scan_status=clean`, salvo la excepción temporal y auditada para PDFs
oficiales PLACSP descrita abajo.

## Estado temporal aprobado

`DOCUMENT_ALLOW_OFFICIAL_UNSCANNED=false` por defecto. Si el responsable lo activa, Oracle acepta
documentos `ready + not_configured` únicamente cuando:

- `DOCUMENT_SCANNER_MODE=noop`;
- la fuente original es `https://contrataciondelestado.es`;
- el documento queda marcado en `scan_result.official_unscanned_acceptance`;
- se emite el audit event `document.official_unscanned_accepted`.

No se aceptan jamás `infected` ni `error`. Cuando ClamAV esté desplegado, desactiva
`DOCUMENT_ALLOW_OFFICIAL_UNSCANNED` y configura `DOCUMENT_SCANNER_MODE=clamav`.

## Despliegue previsto de ClamAV

1. Añadir un servicio `clamav`/`clamd` en `compose.prod.yml`, en red privada de Compose y sin puertos
   publicados al host.
2. Configurar memoria suficiente para cargar firmas y healthcheck local del demonio.
3. Añadir en `/etc/opn-oracle/oracle.env`:

   ```bash
   DOCUMENT_SCANNER_MODE=clamav
   DOCUMENT_CLAMAV_HOST=clamav
   DOCUMENT_CLAMAV_PORT=3310
   DOCUMENT_CLAMAV_TIMEOUT_SECONDS=15
   DOCUMENT_ALLOW_OFFICIAL_UNSCANNED=false
   ```

4. Desplegar, ejecutar `oracle-control health` y procesar un documento limpio de prueba.
5. Verificar que un documento EICAR queda `quarantined`/`infected` en staging antes de habilitar
   documentos críticos.

## Retirada de la excepción

Tras ClamAV:

- eliminar `DOCUMENT_ALLOW_OFFICIAL_UNSCANNED=true` del entorno;
- revisar documentos con `scan_result.official_unscanned_acceptance.accepted=true`;
- reprocesarlos para obtener `scan_status=clean` o cuarentena real;
- mantener los audit events históricos como trazabilidad de la excepción aprobada.
