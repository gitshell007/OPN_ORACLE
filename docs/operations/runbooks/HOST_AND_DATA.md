# Host, TLS, disco y backups

## Certificado próximo a caducar o TLS inválido

**Síntomas:** alerta a 30/14/7 días, fallo de renovación, cadena/SAN inválido o handshake fallido.  
**Confirmación:** inspeccionar certificado desde fuera y local, SAN, issuer, cadena, reloj, DNS
A/AAAA, challenge y logs de Certbot/Nginx. No activar HSTS hasta confirmar HTTPS estable.  
**Mitigación:** corregir DNS/challenge/firewall, renovar en dry-run y recargar Nginx solo tras
validar configuración. Mantener certificado vigente anterior durante el cambio.  
**Rollback:** restaurar config/cert symlink anterior y recargar; nunca servir HTTP sensible como
fallback.  
**Escalado:** SRE a 14 días, incidente crítico a 48 h o si expiró; avisar producto si hay ventana.

## Espacio de disco bajo

**Síntomas:** > 80/90 % ocupado, inodos bajos, WAL/logs/storage crecen, escrituras fallan.  
**Confirmación:** medir por filesystem e inodos; atribuir a PostgreSQL/WAL, Docker, logs, objetos,
temporales o backups. Preservar evidencia y legal holds.  
**Mitigación:** detener productores de uploads/reportes; aplicar rotación/retención documentada;
ampliar volumen si procede. No borrar WAL, tablas, volúmenes Docker ni objetos manualmente.  
**Rollback:** si una limpieza automatizada retiró material indebido, detenerla y restaurar desde
la copia verificada; revertir configuración de logging/retención causante.  
**Escalado:** SRE a 80 %, incidente a 90 % o cualquier error de escritura; owner documental si
afecta objetos/retención.

## Backup fallido o no verificable

**Síntomas:** job fallido/ausente, tamaño anómalo, checksum inválido, copia demasiado antigua o
restore drill fallido.  
**Confirmación:** comprobar PostgreSQL y objetos, manifiesto/checksum/cifrado/retención y destino
off-host. No considerar Redis parte de la verdad de negocio.  
**Mitigación:** conservar última copia válida, corregir sin sobrescribirla, ejecutar nueva copia y
restore en entorno aislado con claves custodiadas; verificar migraciones, integridad, RLS y muestra
de documentos.  
**Rollback:** volver al script/credencial/configuración anterior; nunca reducir retención para
silenciar falta de espacio.  
**Escalado:** SRE/DBA inmediato si se incumple RPO; security si el destino o claves pudieron quedar
expuestos; dirección si no existe copia restaurable. Producción queda bloqueada sin restore medido.

