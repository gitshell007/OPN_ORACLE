# Despliegue nativo de Oracle en desarrollo

Host objetivo: `oracle-dev.opnconsultoria.com` (`159.195.216.33`).

Modelo:

- Sin Docker para Oracle.
- Releases inmutables en `/opt/opn-oracle/releases/<id>` y symlink `current`.
- Config no secreta en `/etc/opn-oracle-dev/oracle.env`.
- Secretos en `/etc/opn-oracle-dev/secrets/*` (root + grupo de servicio, `0400`/`0440`).
- PostgreSQL y Redis nativos en loopback.
- Gunicorn `127.0.0.1:8010`, Next `127.0.0.1:3010`, Nginx TLS.

Scripts:

| Script | Uso |
|---|---|
| `bootstrap-host.sh` | Fase 1–2: paquetes, usuarios, dirs, PG, Redis |
| `import-prod-snapshot.sh` | Fase 3: restore de dump `-Fc` a `opn_oracle_dev` |
| `build-release.sh` | Fase 4: release inmutable desde SHA |
| `install-systemd.sh` | Unidades API/web/worker/beat |
| `install-nginx.sh` | Server blocks HTTP/HTTPS + ACME |

No copiar secretos de producción. Correo en `capture`, AI/Signal deshabilitados,
`DOCUMENTS_ENABLED=false` hasta migrar storage.
