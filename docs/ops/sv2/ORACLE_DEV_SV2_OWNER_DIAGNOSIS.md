# ORACLE_DEV_SV2_OWNER_DIAGNOSIS · SV2-OWNER (PROMPT_000030)

**Host:** `oracle-dev.opnconsultoria.com` / `v2202607388167489673` / `159.195.216.33`  
**Release:** `20260802T040823Z-native-4b454e1` (`4b454e1…`)  
**Signal-dev receptor:** `064c32d` (no mutado este turno)  
**Fecha:** 2026-08-02  
**Prompt:** `SV2-OWNER`  
**Alcance:** crear owner real de demo + diagnóstico golden path **sin fixes de código**.

---

## 1. Owner y tenant (cierra MDEV11-OWNER-CREDS-ABSENT / A14)

### Mecanismo

| Opción | Resultado |
| --- | --- |
| `flask create-dev-tenant` | **Bloqueado** — `APP_ENV=production` en oracle-dev |
| `flask admin bootstrap-superadmin` | Exige confirmación de producción; no usado |
| **One-off seed** vía `create_app()` + `PasswordHasher` (Argon2id) | **Usado** (mismo path de hash que la app) |

Script host: `/tmp/sv2_seed_owner.py` (no commit).  
Credenciales (chmod 600): **`/root/sv2_demo_owner_credentials.txt`** en oracle-dev.  
**No** se publica la contraseña en este documento ni en el Gate Packet.

### Identidades creadas

| Campo | Valor |
| --- | --- |
| email / username | `owner.sv2.demo@oracle.invalid` |
| display_name | `SV2 Demo Owner` |
| user_id | `8abca82d-e18f-4c23-b863-186276a92e3f` |
| tenant_slug | `sv2-demo` |
| tenant_id | `a6edb3c8-0611-4d7a-a6e1-e882c7460539` |
| membership_id | `2db7000d-af53-401c-8578-8b22b5722059` |
| role | `owner` (rol sistema máximo de producto) |
| hash | Argon2id via `opn_oracle.auth.passwords.PasswordHasher` |

Tenant real preexistente `opn-consultoria` (`efb2bca1-…`) con owners reales **no** se reutilizó: sin credenciales designadas y con IC Signal **disabled** + AI `kill_switch=true`. Se creó tenant demo sintético autorizado.

### Login verificado

```text
GET  /api/v1/auth/csrf          → 200 + csrf_token
POST /api/v1/auth/login         → 200 (email + tenant_id + X-CSRF-Token + Origin)
GET  /api/v1/auth/me            → 200 sesión utilizable
```

Cookies de sesión capturadas solo en host (`/var/backups/opn-oracle-dev/sv2-owner-20260802/cookies.txt`).

---

## 2. Matriz golden path (10 pasos)

Evidencia host: `/var/backups/opn-oracle-dev/sv2-owner-20260802/`.

| # | Paso | Veredicto | Evidencia / causa raíz | Arreglo mínimo propuesto | Tamaño |
|---|---|---|---|---|---|
| 1 | Crear expediente | **PASS** | `POST /api/v1/dossiers` → 201; dossier `ab7bba16-3e55-4f35-ad73-0c84e2850688` title «SV2 Demo · Nexus Ibérica Sistemas»; type efectivo `custom` (payload competitive-intelligence normalizado) | — | — |
| 2 | Aceptar intención | **PASS** | `accept_creation_intent=true` → revision `eda923db-26f7-496e-be32-04bc58c7a361` status `accepted` v1; audit `intent.accepted_at_creation` | — | — |
| 3 | Subir documento demo | **PASS** | Fixture Signal `demo_document_es.txt`; `POST …/documents` → 202; doc `bb2adaf5-…` status **ready**; job `oracle.document.process` **succeeded** (17 chunks) | — | — |
| 4 | Doc → memoria Signal | **FAIL** | Outbox API: `bilateral_outbox_enabled=false`, `items=[]`. `stage_memory_event` **solo definido** en `integrations/memory_outbox.py:126` — **ningún caller**. `MEMORY_CONTEXT_MODE` host **disabled**. Sin IC `signal-avanza` en tenant `sv2-demo`. Deuda **DISPATCH-MDEV05-002** | Ver §3 fix #1–#3 | M |
| 5 | Añadir actor | **PASS** | `POST …/dossiers/{id}/actors` `canonical_name=Nexus Ibérica…` → 201; actor `750e3cfa-…`, link `a2c4ce8f-…` | — | — |
| 6 | Activar vigilancia | **PARTIAL** | `POST …/surveillance-actions/confirm` news_mentions → 201 local `active`; `degraded=true`, reason `DUR-MDEV05-001`; `signal_monitor_id=null`; monitors `[]`. Flags: `SIGNAL_AVANZA_ENABLED=false`; adapter `MEMORY_SURVEILLANCE_SIGNAL_ENABLED` default OFF + `MEMORY_DURABLE_STORE_READY` OFF (`surveillance_signal_adapter.py`) | Ver §3 fix #4 | S |
| 7 | Estado memoria Oracle | **PARTIAL** | DMP GET default disabled → PUT **shadow** 200 (perfil `bc29d7c1-…`); **effective** sigue host `disabled` / sin connection_id / sin snapshot Signal | Ver §3 fix #2–#3 | S |
| 8 | Ask con citas | **FAIL** | Conv + message 202; job `oracle.dossier_question.answer` **failed** `permanent_failure`. Repro in-process: `AIPolicyDenied: La clasificación del contexto excede la política.` — policy tenant `max_classification=public` vs contexto `internal` (`ai/service.py:658`, `policy_defaults.py` default public). Worker activo; no es fallo de cola | Ver §3 fix #5 | S |
| 9 | Generar informe | **PARTIAL** | Report `5933ef6e-…` creado 202 lifecycle `brief_draft`; job plan **failed** misma causa `AIPolicyDenied` clasificación. Sin artefacto/citas | Mismo #5 + lifecycle accept en demo | S |
| 10 | MCC Signal consumer UI | **PARTIAL** | signal-dev: `/`→303 `/admin/login`, `/healthz` 200, `/admin` 307. UI consumer autenticada c:64 **no** ejercida (SV2-MCC). signal-dev **no** mutado | SV2-MCC | S |

### Flags / deudas observadas (no encendidos este turno)

| Flag / deuda | Valor en oracle-dev | Efecto |
| --- | --- | --- |
| `MEMORY_BILATERAL_OUTBOX_ENABLED` | unset / false | No staging outbox bilateral |
| `MEMORY_CONTEXT_MODE` | disabled (default) | Retrieve Signal desactivado a nivel host |
| `SIGNAL_AVANZA_ENABLED` | false | Vigilancia/mock global |
| `MEMORY_SURVEILLANCE_SIGNAL_ENABLED` | default 0 | Adapter fail-closed |
| `MEMORY_DURABLE_STORE_READY` | default 0 | No pretender E2E vigilancia→Signal |
| DISPATCH-MDEV05-002 | abierta | Sin puente document.ready→Signal ingest |
| AI `max_classification` (sv2-demo) | **public** (default seed) | Bloquea Ask/informe con docs `internal` |

Camino fail-closed reutilizable (031):  
- `memory_outbox.stage_memory_event` ya devuelve `bilateral_outbox_disabled` si flag OFF.  
- `surveillance_signal_adapter.publish_surveillance_scope` degrade/fail-closed si flags OFF o store no durable.

---

## 3. Arreglos mínimos priorizados para 031+ (≤1 turno c/u)

1. **P0 · AI policy demo (Ask + informe)** — S  
   - Acción: `UPDATE ai_tenant_policies SET max_classification='internal' WHERE tenant_id=sv2-demo` (o admin UI).  
   - Ficheros: BD / `ai/policy_defaults.py` (opcional default dev).  
   - Desbloquea steps 8–9 sin código si Signal AI path ya opera.

2. **P0 · IC Signal-dev para tenant sv2-demo** — S/M  
   - Crear `integration_connections` provider signal-avanza, `adapter_mode=http`, base `https://signal-dev.opnconsultoria.com`, credential AES-GCM (reutilizar patrón consumer `opn-oracle-dev` id 64 / fp canario).  
   - Ficheros: admin integrations / `integrations/service.py` paths existentes.

3. **P0 · Host memory context + DMP shadow** — S  
   - `MEMORY_CONTEXT_MODE=http`, `MEMORY_CONTEXT_BASE_URL=https://signal-dev.opnconsultoria.com` (solo oracle-dev env).  
   - Mantener DMP del dossier demo en `shadow` (ya puesto). No augment (SV2-AUG).

4. **P0 · Puente document→Signal (DISPATCH-MDEV05-002)** — M  
   - En `documents/service.py` `process_document` al estado ready: llamar `stage_memory_event("document.version.ready")` si DMP∈{shadow,augment} e IC activa.  
   - En intent accept: opcional `intent.revision.accepted`.  
   - Activar `MEMORY_BILATERAL_OUTBOX_ENABLED=1` solo oracle-dev tras IC.  
   - Ficheros: `integrations/memory_outbox.py`, `documents/service.py`, worker outbox publisher.

5. **P1 · Vigilancia → Signal** — S  
   - Tras IC durable: evaluar `MEMORY_SURVEILLANCE_SIGNAL_ENABLED` + `MEMORY_DURABLE_STORE_READY` (fail-closed si no).  
   - Ficheros: `integrations/surveillance_signal_adapter.py`, env oracle-dev.

6. **P1 · Observabilidad AI jobs** — S  
   - Incluir `oracle.dossier_question.answer` y `oracle.report.custom_brief.*` en `AI_RETRY_CAUSE_JOB_TYPES` para no tragar la causa (`jobs/tasks.py`).

7. **P2 · SV2-MCC** — UI consumer Signal autenticada (c:64).

---

## 4. Estado final oracle-dev

| Check | Estado |
| --- | --- |
| hostname / IP | `v2202607388167489673` / `159.195.216.33` |
| services api/web/worker/beat/nginx | **active** |
| release | `native-4b454e1` (sin redeploy) |
| owner creds file | `/root/sv2_demo_owner_credentials.txt` mode 600 |
| dossier demo conservado | `ab7bba16-3e55-4f35-ad73-0c84e2850688` |
| documento ready | `bb2adaf5-5ad8-4287-be6b-f2aadcb3abf0` |
| jobs colgados creados por el turno | no (failed terminal Ask/plan; doc succeeded) |
| signal-dev | **no tocado** |
| producción | **no tocada** |

### Riesgos

- `APP_ENV=production` en Dev desactiva CLI seed; one-offs manuales necesarios.  
- Encender bilateral/surveillance sin IC + CMS canary puede generar outbox failed ruidoso.  
- Default `max_classification=public` es trampa silenciosa para docs `internal`.  
- WIP ajeno en checkout local `oracle-dev` **no** tocado (worktree aislado).

---

## 5. IDs de referencia rápida

```text
tenant_id   = a6edb3c8-0611-4d7a-a6e1-e882c7460539
user_id     = 8abca82d-e18f-4c23-b863-186276a92e3f
dossier_id  = ab7bba16-3e55-4f35-ad73-0c84e2850688
intent_rev  = eda923db-26f7-496e-be32-04bc58c7a361
document_id = bb2adaf5-5ad8-4287-be6b-f2aadcb3abf0
actor_id    = 750e3cfa-b392-4235-b375-dd1c1b765bbd
surv_action = 374ba61f-f9db-4c46-ae1e-8378c722cf6f
dmp_id      = bc29d7c1-6f36-4f45-bca8-236a233eccd4 (mode=shadow)
report_id   = 5933ef6e-ca25-499e-8707-747843c2bc77
creds_path  = /root/sv2_demo_owner_credentials.txt
evidence    = /var/backups/opn-oracle-dev/sv2-owner-20260802/
```

Prompt: SV2-OWNER
