# Despliegue nativo de desarrollo — Oracle

**Host:** `oracle-dev.opnconsultoria.com` → `159.195.216.33`  
**Modelo:** sin Docker para Oracle; systemd + PostgreSQL/Redis/Nginx nativos.  
**Fecha de arranque:** 2026-07-28  

## Rama de despliegue

| Campo | Valor |
|---|---|
| Checkout local canónico | `/Users/gitshellmini/PycharmProjects/OPN_ORACLE` |
| Rama a desplegar en el host | `oracle-dev` |
| Remoto | `origin` → `gitshell007/OPN_ORACLE` |
| URL del entorno | `https://oracle-dev.opnconsultoria.com` |

Reglas:

- Los releases inmutables del host se construyen desde un **SHA de `oracle-dev`**, no desde `master` a ciegas.
- `master` puede avanzar con trabajo no listo para el entorno dev compartido; `oracle-dev` es la línea que el servidor debe ejecutar.
- Tras mergear a `oracle-dev`, construir release con el SHA exacto y CI aceptable, y activar con symlink `current`.
- No hacer `git pull` in-place sobre `/opt/opn-oracle/current`.

## Ventana de congelación

Cuando haya **grabación de vídeo o demo en curso**, **no se despliega** a oracle-dev.

| Quién | Qué hace |
|---|---|
| Quien graba o demuestra | Fija el SHA (y el `CURRENT_RELEASE`) que está usando; no asume que `current` sea estable |
| Quien despliega | Espera a que la ventana se cierre, o coordina un SHA explícito acordado con quien graba |
| Ambos | Si se necesita un hotfix durante la ventana, se acuerda y se documenta el cambio de SHA antes de activar el release |

Motivo: el agente de vídeo y las demos pierden trabajo si la UI o la API cambian debajo del sondeo (SHA distinto al que se estaba grabando). La congelación es operativa, no un candado en el script: la disciplina es humana y se anuncia en el canal de trabajo antes de empezar.

## Fingerprint SSH validado

| Tipo | SHA256 |
|---|---|
| ED25519 | `SHA256:J+djX/nOcNIYx0R/Y1yrpJcoqW83bbmYk6odQzVMKfQ` |
| RSA | `SHA256:M0+BxshIr6NDoegg2C/CU6MaSwOTgTqUn35OgnJ5ixM` |
| ECDSA | `SHA256:M1mkbDnRqWWlnOwlYOzDnbLngHpNsH/25krZM6RpnXc` |

Contraste: `ssh-keyscan` del host, entradas previas en `known_hosts` para
`oracle-dev.opnconsultoria.com` y huellas publicadas por el propio host tras login.
No se usó `StrictHostKeyChecking=accept-new` para confiar ciegamente.

## Inventario previo (Fase 0)

- Debian 13 (trixie), kernel 6.12.96, hostname `v2202607388167489673`
- 4 vCPU AMD EPYC-Genoa (KVM), 7,8 GiB RAM, 251 GiB disco, sin swap
- Listeners: solo SSH `:22`
- Sin Nginx, PostgreSQL, Redis, Docker, Node, Certbot previos
- DNS A: `oracle-dev` y `risk-dev` → `159.195.216.33`; sin AAAA real
- Clave GitHub en servidor: autenticación OK a `gitshell007` (no imprimir la privada)

## Componentes instalados

| Componente | Versión host |
|---|---|
| PostgreSQL | 17.10 |
| Redis | 8.0.2 (Debian trixie; no 7.x en repos) |
| Python | 3.13.5 (`requires-python >=3.11,<3.14`) |
| uv | 0.11.x |
| Node | 20.19.2 |
| Nginx | 1.26.3 |
| Certbot | 4.0.0 |

Usuarios sistema: `opn-oracle`, `opn-risk` (nologin).

Rutas:

```text
/opt/opn-oracle/releases/<id>/
/opt/opn-oracle/current -> releases/<id>
/etc/opn-oracle-dev/oracle.env
/etc/opn-oracle-dev/secrets/*
/var/lib/opn-oracle-dev/
/var/log/opn-oracle-dev/
/var/backups/opn-oracle-dev/
```

## PostgreSQL / Redis

- Escucha únicamente en loopback (`127.0.0.1` / `::1`).
- Bases: `opn_oracle_dev` (owner `oracle_migrator`), `opn_risk_advisor_dev` (shell).
- Roles Oracle exactos: `oracle_migrator` (BYPASSRLS), `oracle_app` (NOBYPASSRLS).
- Redis: `requirepass`, DBs lógicas 0–4 para Oracle (cache/session/ratelimit/broker/result).

## Snapshot de datos

- Origen producción: Docker `opn-oracle-prod-postgres-1`, DB `opn_oracle`.
- Dump custom `-Fc` (sin roles globales), transferido por SSH a
  `/var/backups/opn-oracle-dev/imports/`.
- SHA-256 y recuentos en manifiesto + evidencia de restore temporal y final.
- Alembic origen/destino: `20260726_0026`.
- Redis de producción **no** se migra (re-login obligatorio).
- `DOCUMENTS_ENABLED=false`; storage de documentos no migrado.
- Keyring de integración de dev es **nuevo** (credenciales cifradas de prod no legibles).
- Correo `capture`; AI/Signal deshabilitados.

## Servicios systemd

- `opn-oracle-api.service` → Gunicorn `127.0.0.1:8010`
- `opn-oracle-web.service` → Next standalone `127.0.0.1:3010`
- `opn-oracle-worker.service` → Celery concurrency 1
- `opn-oracle-beat.service` → un único beat, schedule en `/var/lib/opn-oracle-dev/`

## Nginx / TLS

- Server blocks por hostname: `oracle-dev`, `risk-dev` (placeholder 503).
- Certificados Let's Encrypt vía webroot `/var/www/certbot`.
- `/health/ready` solo loopback; `/internal/` y `/metrics` bloqueados.

## Scripts versionados

Ver `infra/native-dev/`.

### Activación de release y migración

`activate-release.sh <release-id>` hace el swap del symlink `current`, migra y reinicia servicios:

- La migración corre como `opn-oracle` con `set -a; source /etc/opn-oracle-dev/oracle.env`
  y `.venv/bin/flask --app opn_oracle.wsgi:app db upgrade` desde `current/apps/api`.
  No usar `uv run`: `uv` está en `/usr/local/bin`, fuera del PATH restringido de ese paso.
- No materializar secretos `*_FILE` en variables de entorno: `opn_oracle/config.py`
  los resuelve en runtime y lanza ConfigError si `X` y `X_FILE` están definidos a la vez.
- Tras migrar: `systemctl restart opn-oracle-api opn-oracle-web opn-oracle-worker opn-oracle-beat`.

## Rollback

1. **Código:** `ln -sfn /opt/opn-oracle/releases/<prev> /opt/opn-oracle/current` y
   `systemctl restart opn-oracle-api opn-oracle-web opn-oracle-worker opn-oracle-beat`.
2. **Config:** restaurar backups timestamped en `/var/backups/opn-oracle-dev/`.
3. **Datos:** restaurar dump `-Fc` a una base nueva; **sin downgrade Alembic automático**.
4. Si el esquema ya avanzó de forma incompatible, forward-fix o restore explícito.

## Nexus

No hay repositorio `Nexus` en la org `gitshell007` ni DNS `nexus-dev.opnconsultoria.com`.
Bloqueo documentado hasta identificación de producto.

## Risk

Repositorio local `opn_risk_advisor` / GitHub `gitshell007/opn_risk_advisor`.
Despliegue **después** de Oracle sano; base `opn_risk_advisor_dev` y roles `risk_*` propios.
