# TLS y renovación

El certificado previsto es exclusivamente para `oracle.opnconsultoria.com`. No se emitirá hasta
que el usuario confirme el email ACME, acepte los términos, apruebe la Etapa B y los puertos 80/443
sean accesibles. El A record ya coincide; no existe AAAA, por lo que no debe añadirse uno hasta
validar conectividad IPv6 completa.

## Emisión segura

1. Instalar Nginx, Certbot y su plugin mediante paquetes soportados por Ubuntu 26.04.
2. Instalar `oracle-http.conf`, crear `/var/www/certbot` y validar `nginx -t`.
3. Verificar desde fuera que el challenge HTTP y `/health/live` llegan al host correcto.
4. Usar ACME staging si se repite el ensayo; evitar consumir rate limits de producción.
5. Emitir mediante webroot `/var/www/certbot` con el email autorizado y el dominio exacto. No guardar el email ni credenciales
   privadas en scripts versionados.
6. Instalar `oracle-https.conf`, validar y recargar.

La plantilla HTTPS declara explícitamente protocolos/cifrados y no depende de snippets auxiliares
generados por el plugin Nginx de Certbot.

## Verificación obligatoria

```bash
curl --fail --head https://oracle.opnconsultoria.com/login
openssl s_client -connect oracle.opnconsultoria.com:443 \
  -servername oracle.opnconsultoria.com -verify_return_error </dev/null
sudo certbot certificates
sudo certbot renew --dry-run
systemctl list-timers --all | grep -E 'certbot|snap.certbot'
```

Comprueba SAN, issuer, chain, fechas, redirect HTTP→HTTPS y renovación. La plantilla empieza con
HSTS de un día, sin `includeSubDomains` ni `preload`. No aumentes el max-age hasta observar HTTPS y
renovación estables y probar rollback. `HSTS_ENABLED` de Flask permanece `false` mientras Nginx sea
la única autoridad de esa cabecera.

## Incidencias

- Si ACME falla, conserva HTTP solo para challenge/health; no permitas login o datos reales por HTTP.
- Si el certificado aún no existe, no instales el server block HTTPS: `nginx -t` fallaría.
- Si se rompe HTTPS, restaura el backup del site y recarga tras `nginx -t`; no borres certificados.
- Una copia local de `/etc/letsencrypt` no constituye backup off-host.
