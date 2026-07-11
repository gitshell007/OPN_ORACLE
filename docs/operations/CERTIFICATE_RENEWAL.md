# Renovación de certificado

## Objetivo y procedimiento

Mantener TLS válido. Ejecutar `sudo certbot renew --dry-run`, comprobar timer y expiración, y
validar Nginx/HTTPS según [TLS.md](./TLS.md).

## Fallo

No desactivar HTTPS. Revisar DNS, puerto 80, challenge y logs; escalar antes de 14 días restantes.

