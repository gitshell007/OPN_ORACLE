# P2 · Readiness operativa (backup off-host, documentos, patentes)

Estado observado en el host de `oracle.opnconsultoria.com` (2026-07-26).

## 1. Backup local (ya operativo)

| Pieza | Estado |
|---|---|
| `opn-oracle-backup-schedule.timer` | activo · diario ~00:17 UTC |
| `opn-oracle-backup-agent.timer` | activo · cada minuto |
| Destino | `/var/backups/opn-oracle` · `root` 0700 |
| Restore aislado | sí (gate de `oracle-control update`) |
| Retención | 30 días (`ORACLE_RETENTION_DAYS`) |
| Disco | ~53 GiB libres de 75 GiB |

No hace falta rehacer la copia local.

## 2. Copia cifrada off-host (nuevo pipeline)

### Qué se entregó en el repo

- `scripts/backup-offsite.sh` — empaqueta el backup, cifra AES-256-CBC (pbkdf2), publica por
  `local` o `rsync`, escribe receipt en `ORACLE_OFFSITE_RECEIPT_ROOT`.
- Integración en `backup-maintenance.sh` tras restore aislado (no-op si
  `ORACLE_OFFSITE_ENABLED=0`).
- `infra/production/backup.conf.example` ampliado.
- `install-backup-systemd.sh` valida el script nuevo.

### Activación en el host (operador)

```bash
# 1) Clave (una vez)
sudo openssl rand -out /etc/opn-oracle/secrets/oracle_backup_offsite_key 32
sudo chown root:root /etc/opn-oracle/secrets/oracle_backup_offsite_key
sudo chmod 0400 /etc/opn-oracle/secrets/oracle_backup_offsite_key

# 2) Destino
# Opción A — volumen montado / segundo disco (method=local):
sudo install -d -m 0700 /var/backups/opn-oracle-offsite
# Opción B — rsync a otro host (method=rsync):
#   ORACLE_OFFSITE_DEST=oracle-offsite@backup.example:/data/oracle

# 3) /etc/opn-oracle/backup.conf (no secretos)
ORACLE_OFFSITE_ENABLED=1
ORACLE_OFFSITE_METHOD=local   # o rsync
ORACLE_OFFSITE_DEST=/var/backups/opn-oracle-offsite
ORACLE_OFFSITE_KEY_FILE=/etc/opn-oracle/secrets/oracle_backup_offsite_key
ORACLE_OFFSITE_RECEIPT_ROOT=/var/backups/opn-oracle/offsite-receipts

# 4) Probar con el backup más reciente
sudo ORACLE_OFFSITE_ENABLED=1 \
  ORACLE_OFFSITE_METHOD=local \
  ORACLE_OFFSITE_DEST=/var/backups/opn-oracle-offsite \
  ORACLE_OFFSITE_KEY_FILE=/etc/opn-oracle/secrets/oracle_backup_offsite_key \
  /opt/opn-oracle/current/scripts/backup-offsite.sh --push-latest

sudo /opt/opn-oracle/current/scripts/backup-offsite.sh \
  --verify-receipt /var/backups/opn-oracle/offsite-receipts/*.OFFSITE_RECEIPT.txt
```

Para **releases estrictos** con gate off-host:

```bash
sudo ORACLE_REQUIRE_OFFSITE_RECEIPT=1 \
  ORACLE_BACKUP_OFFSITE_RECEIPT=/var/backups/opn-oracle/offsite-receipts/ID.OFFSITE_RECEIPT.txt \
  …
```

### Limitaciones honestas

- `method=local` en el mismo disco **no** es DR real: sirve para validar el pipeline y para
  volúmenes USB/NFS montados fuera de `BACKUP_ROOT`. El destino de producción debe ser **otra
  máquina o object storage** con retención/inmutabilidad.
- No se implementa restore completo desde off-host en este P2: el receipt + checksum demuestran
  integridad del artefacto cifrado; el restore de dump sigue siendo
  `restore-test-production.sh` / `restore-production.sh` sobre un tarball descifrado a mano.
- La clave offsite no se respalda en el propio backup (evitar dependencias circulares): guárdala
  en el gestor de secretos de OPN.

## 3. Documentos (`DOCUMENTS_ENABLED=false`)

En prod (2026-07-26):

```text
DOCUMENTS_ENABLED=false
DOCUMENT_STORAGE_BACKEND=local
DOCUMENT_SCANNER_MODE=noop
DOCUMENT_ALLOW_OFFICIAL_UNSCANNED=true
DOCUMENT_LOCAL_ROOT=/var/lib/oracle-storage
```

La API responde `503 documents_disabled` a propósito (fail-closed).

### Gate para activar (no hacerlo sin decisión)

1. Destino de objetos (local endurecido o S3-compatible) con cifrado en reposo y backup.
2. Antivirus: `DOCUMENT_SCANNER_MODE=clamav` (o equivalente) en worker sin red de salida innecesaria.
3. Runbook de restore de objetos + claves (ampliar `BACKUP_RESTORE.md`).
4. Tests de integración de documentos en CI del SHA.
5. Variables en `oracle.env` + secret files; deploy con backup previo.

Hasta entonces: **no** activar en producción; la UI no debe vender subida documental.

## 4. Patentes EPO

La ficha de entidad puede devolver `epo_search_404` en la sección de patentes. No bloquea
registry/grafo/noticias. Para demo: no insistir en la pestaña patentes. Corrección = contrato
EPO/Signal o ocultar la sección si la fuente no responde.

## 5. Seguridad de acceso (manual)

- Rotar la contraseña de cualquier cuenta usada en UAT por chat (p. ej. owner de demo).
- No reutilizar la misma clave en otros sistemas.
- Preferir invitación de un solo uso o reset controlado.

## 6. Checklist de cierre P2 ops

| Ítem | Criterio |
|---|---|
| Backup local diario | timers activos + MANIFEST reciente |
| Restore aislado | evidencia en `/var/backups/.../restore-evidence` |
| Offsite pipeline en repo | `backup-offsite.sh` + hook maintenance |
| Offsite activado en host | `ORACLE_OFFSITE_ENABLED=1` + 1 receipt verificado |
| Documentos | siguen disabled o gate 1–5 completado |
| Patentes | conocido / no bloqueante |
| Credenciales demo | rotadas tras UAT |
