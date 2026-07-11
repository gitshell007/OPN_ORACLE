# Auditoría read-only del servidor · 2026-07-11

**Etapa:** F14-A, solo lectura  
**Hora de observación:** 08:52 UTC  
**Host esperado:** servidor facilitado para `oracle.opnconsultoria.com`  
**Resultado:** identidad y DNS coinciden; no autoriza cambios ni producción

No se usó, imprimió ni almacenó la contraseña compartida en conversación. El acceso read-only se
realizó con una clave SSH que ya estaba autorizada localmente y `BatchMode=yes`. No se leyeron
`.env`, claves privadas, secretos de Docker ni contenido de certificados.

## Identidad

| Dato | Observado |
|---|---|
| Hostname / FQDN local | `oracle` / `oracle` |
| IPv4 | `167.233.73.138` |
| IPv6 del host | `2a01:4f8:c015:4031::1` |
| Usuario de auditoría | `root`, UID 0; `sudo -n` disponible |
| SSH | puerto 22, escucha IPv4 e IPv6 |
| ED25519 | `SHA256:q7Jgl/nG635KPlyUl21Efko7T6nzvNgWk4X3My/9uC4` |
| RSA | `SHA256:wCmPwuI1LhyOn5N9KCLtVuTFLy30XuMvuo43GCtRIf8` |

Los fingerprints obtenidos desde fuera coinciden con los publicados por el propio host tras el
login por clave. El reverse DNS es `static.138.73.233.167.clients.your-server.de`.

## Sistema y recursos

- Ubuntu 26.04 LTS (`resolute`), kernel `7.0.0-27-generic`, arquitectura amd64/KVM.
- 2 vCPU AMD EPYC Genoa, 3,7 GiB RAM; 3,3 GiB disponibles durante la auditoría.
- Sin swap.
- Disco raíz ext4: 75 GiB, 1,9 GiB usados (3 %); inodos 2 %.
- Timezone UTC; reloj sincronizado, Chrony/NTP activo.
- Uptime 1 día; carga 0,17/0,08/0,08. El contador transitorio de sesiones correspondía a los SSH
  paralelos de la propia auditoría; `who` quedó vacío al finalizar.
- Sin unidades systemd fallidas; journal 16 MiB. `unattended-upgrades` está activo.
- El kernel reporta `TSA: Vulnerable: No microcode`; al ser KVM debe revisarse con el proveedor y
  no se afirma que un paquete dentro del guest pueda corregirlo.

## Red, DNS y firewall

- `oracle.opnconsultoria.com` tiene A `167.233.73.138`, coincidente con el host.
- No existe AAAA. Esto evita una ruta IPv6 incorrecta; si se publica en el futuro debe usar la IPv6
  observada y probar HTTP/ACME por IPv6 antes.
- No hay CAA; los NS del dominio son de DomainControl. Existe MX de Microsoft 365 para el dominio,
  pero no se ha confirmado el email autorizado para Let's Encrypt.
- Listeners: únicamente SSH 22 en todas las interfaces, además de DNS/Chrony loopback y DHCP.
- Sondeo externo acotado: 22 abierto; 80, 443, 3000, 8000, 5432 y 6379 cerrados o filtrados.
- UFW está instalado pero **inactivo**; no se observaron reglas nftables. Hoy la exposición queda
  limitada porque no hay otros listeners, pero es un gate obligatorio antes de Docker/web.

## SSH

`sshd -T` informa:

- `Port 22`;
- `PermitRootLogin yes`;
- `PasswordAuthentication yes`;
- `PubkeyAuthentication yes`;
- `MaxAuthTries 6`.

**Finding F14-A-01 · critical release blocker:** una credencial root fue compartida en un canal no
secreto y el host permite root/password. Debe tratarse como comprometida. No se debe iniciar
provisioning hasta rotarla mediante sesión interactiva/console sin historial y confirmar acceso por
clave en una segunda sesión. Deshabilitar password/root directo exige aprobación separada,
`sshd -t`, sesión de respaldo y reload; no se realizó.

## Software y servicios

No están instalados Docker/Compose, Podman, Nginx, Apache, Caddy, Certbot, PostgreSQL ni Redis. No
hay contenedores, volúmenes ni redes Docker. Solo se ejecutan servicios base de Ubuntu: SSH,
systemd-networkd/resolved, Chrony, cron/at, journald/rsyslog, polkit, multipath y agente QEMU.

Los índices APT existentes ofrecen, sin haber ejecutado update ni instalado nada:

- Docker.io 29.1.3 y Compose v2 2.40.3;
- Nginx 1.28.3;
- Certbot 4.0.0 y plugin Nginx;
- PostgreSQL host 18 y Redis host 8.0.5, aunque la arquitectura propuesta los ejecuta en Compose y
  no requiere esos paquetes host.

## Directorios, despliegue y backups

- `/opt` y `/srv` no contienen despliegues, repositorios ni Compose detectables.
- `/etc/nginx` no existe.
- No existe `/var/lib/docker`, PostgreSQL o Redis.
- No hay usuario/grupo Docker ni usuario de deploy; solo `root` entre las cuentas interactivas
  listadas.
- `/var/backups` existe, root:root 0755, sin un backup de Oracle detectado.
- Solo existe el timer estándar `dpkg-db-backup`; no hay timer de aplicación, DB, certificado o
  backup externo.

## Conflictos y capacidad

No hay conflicto actual en 80/443/3000/8000/5432/6379. El host es limpio, pero 2 vCPU/3,7 GiB es
un perfil ajustado para Next, API, PostgreSQL, Redis, Celery y parsing. El primer despliegue debe:

- mantener IA, Signal HTTP, PDF y documentos productivos deshabilitados hasta configurar sus gates;
- usar un worker Celery consolidado de concurrencia 1 y un beat único;
- fijar límites de memoria/CPU y alertar antes de OOM;
- medir staging y valorar subir a 8 GiB antes de IA, parsing concurrente o carga real.

No se recomienda compensar sin más con swap no cifrada, porque puede contener sesiones o datos
sensibles. La decisión de ampliar recursos o swap cifrada requiere revisión separada.

## Findings y bloqueos

| ID | Severidad | Estado | Gate |
|---|---|---|---|
| F14-A-01 root/password expuesto y permitido | Critical release blocker | Abierto | Rotar antes de cualquier cambio; hardening SSH con aprobación separada |
| F14-A-02 UFW/nft sin política activa | High antes de exponer servicios | Abierto | Permitir SSH actual, 80/443; denegar puertos internos antes de arrancar Compose |
| F14-A-03 sin backups/restore externo | High release blocker | Abierto | Destino, cifrado, retención y restore real en F15 |
| F14-A-04 recursos ajustados, sin swap | Medium | Abierto | Límites, carga y decisión 4→8 GiB |
| F14-A-05 TSA sin microcode reportado | Medium | Abierto | Confirmación/mitigación del proveedor |
| F14-A-06 no existe stack de producción | Esperado | Abierto | Aplicar únicamente tras aprobación de Etapa B |

## Evidencia no ejecutada

- No se emitió certificado ni se abrió 80/443.
- No se actualizó APT ni se instaló paquete alguno.
- No se creó usuario, directorio, firewall, repo, secret file, container, volumen o backup.
- No se verificó email ACME, destino backup, SMTP, S3/ClamAV, observabilidad o superadmin porque
  faltan decisiones/secretos seguros.

