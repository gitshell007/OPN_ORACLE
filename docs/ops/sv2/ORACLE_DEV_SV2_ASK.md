# ORACLE_DEV_SV2_ASK · SV2-ASK (PROMPT_000031)

**Host:** `oracle-dev.opnconsultoria.com` / `v2202607388167489673` / `159.195.216.33`  
**Release:** `20260802T040823Z-native-4b454e1`  
**Fecha:** 2026-08-02  
**Prompt:** `SV2-ASK`  
**Alcance:** política AI tenant demo `max_classification public→internal`; revalidar Ask + informe.  
**Prohibido:** producción, signal-dev mutaciones, código/config host no autorizada.

---

## 1. Cambio de política AI (autorizado)

| Campo | Valor |
| --- | --- |
| Tenant | `sv2-demo` / `a6edb3c8-0611-4d7a-a6e1-e882c7460539` |
| Policy id | `307016dd-b2a2-4d2b-89c3-561049ab4be7` |
| Mecanismo | **UPDATE directo en BD** (no hay PUT admin de `max_classification`; solo GET `/api/v1/tenant-admin/ai-policy` + test) |
| RLS | `set_config('app.tenant_id', '<tenant>', true)` en la misma transacción |
| Antes | `max_classification=public` (resto: enabled=true, provider=signal, kill_switch=false) |
| Después | `max_classification=internal` (`updated_at=2026-08-02T12:23:45.824973+02:00`) |

### SQL exacto

```sql
BEGIN;
SELECT set_config('app.tenant_id', 'a6edb3c8-0611-4d7a-a6e1-e882c7460539', true);
UPDATE ai_tenant_policies
SET max_classification = 'internal',
    updated_at = now()
WHERE tenant_id = 'a6edb3c8-0611-4d7a-a6e1-e882c7460539'
  AND max_classification = 'public'
RETURNING id, tenant_id, max_classification, updated_at;
COMMIT;
```

### Audit

| Campo | Valor |
| --- | --- |
| audit_events.id | `9249048a-aa0d-493e-b279-428ff8d2c1b2` |
| action | `tenant.ai_policy.max_classification.updated` |
| actor_type | `service` |
| result | `success` |
| metadata | `from=public`, `to=internal`, `mechanism=direct_sql_dev`, `prompt=SV2-ASK` |

### Verificación API (owner)

`GET /api/v1/tenant-admin/ai-policy` → `max_classification=internal`, `provider=signal`.

---

## 2. Validación Ask + informe (owner real)

Login: `owner.sv2.demo@oracle.invalid` sobre dossier `ab7bba16-3e55-4f35-ad73-0c84e2850688`.  
Creds host: `/root/sv2_demo_owner_credentials.txt` (chmod 600).  
Evidencia host: `/var/backups/opn-oracle-dev/sv2-ask-20260802/`.

### 2.1 Ask

| Campo | Valor |
| --- | --- |
| Pregunta | ¿Quién es el administrador único y qué licitación tiene en curso Nexus Ibérica? |
| conversation_id | `504c78b5-5345-4bf4-bd9b-c40719a8b3c8` |
| message_id | `a7662ed8-875a-4465-94a7-759c55c2a8e8` |
| job_id | `2e1de7d7-f55a-4192-b4c9-7de24737d8d8` |
| job_type | `oracle.dossier_question.answer` |
| HTTP enqueue | **202** |
| Job status | **failed** `permanent_failure` (~0.31 s) |
| Respuesta/citas | **No generadas** (sin mensaje assistant) |

### 2.2 Informe `custom_brief`

| Campo | Valor |
| --- | --- |
| report_id | `d65d25f3-69d3-42e4-8a56-bbb5b4390f7e` |
| plan job | `5823c646-abf7-4562-8e62-cff2c5851cac` (`oracle.report.custom_brief.plan`) |
| HTTP create | **202** |
| lifecycle | quedó en `brief_draft` / `plan_status=draft` |
| Job status | **failed** `permanent_failure` (~0.18 s) |
| Artefacto | no (sin plan propuesto ni download) |

Jobs failed previos del turno 030 **no borrados** (histórico intacto).

---

## 3. Clasificación superada; nuevo bloqueo

### 3.1 Prueba de que el fix de política funcionó

| Antes (030) | Después (031) |
| --- | --- |
| `AIPolicyDenied: La clasificación del contexto excede la política` (`max_classification=public` vs docs `internal`) | Contexto `data_classification=internal` **aceptado** por política |
| No llegaba a Signal `/ai/run` | Worker: `POST https://signal-dev.opnconsultoria.com/api/v1/ai/run` |

Filas `ai_audit_logs` (tenant demo):

| agent | status | provider (Oracle) | model (Oracle log) | error_code | cost | classification |
| --- | --- | --- | --- | --- | --- | --- |
| `dossier_question_answer` | failed | signal | mock-oracle-v1 | `AIUnavailable` | **0** micros | **internal** |
| `report_custom_brief_plan` | failed | signal | mock-oracle-v1 | `AIUnavailable` | **0** micros | **internal** |

### 3.2 Causa raíz nueva (signal-dev runtime)

Repro autenticado con la API key del host (`SIGNAL_AI_API_KEY_FILE`):

```text
POST https://signal-dev.opnconsultoria.com/api/v1/ai/run
→ HTTP 404
body.ok=false
body.consumer_id=61
body.provider=ollama
body.model=qwen3.5:9b
body.result.error="model 'qwen3.5:9b' not found"
usage.estimated_cost_usd=null  (coste 0; no OpenRouter)
```

Aplica a **ambas** tasks:

- `dossier_question_answer`
- `report_custom_brief_plan`

Notas:

1. El **404 no es “ruta inexistente”**: sin API key la misma URL responde `401 missing_api_key`. Con key, Signal ejecuta la task del consumer **61** y Ollama responde “model not found”, reenviado como HTTP 404.
2. Ruta **no es producción**: `SIGNAL_AI_BASE_URL` host = `signal-dev.opnconsultoria.com`; `SIGNAL_AI_ALLOWED_HOSTS` = solo signal-dev. IC prod Signal en Oracle permanece disabled (no tocado).
3. Coste efectivo **0** (Ollama fallido antes de tokens; `actual_cost_micros=0`).
4. **signal-dev no se muta** en este turno (alcance). El fix mínimo sería en Signal consumer 61 / registry de task → modelo Ollama instalado (p. ej. pull `qwen3.5:9b` o reasignar a un tag presente), **fuera** del alcance 031.

### 3.3 Por qué no se encadenó otro fix

| Candidato | ¿Autorizado 031? | Decisión |
| --- | --- | --- |
| Otra fila tenant demo (`ai_tenant_policies` provider/model) | Excepción reversible tenant | `provider` ya es `signal`; el modelo efectivo lo elige **Signal** por task/consumer, no Oracle |
| Host env / Ollama pull / Signal consumer CMS | **No** (signal-dev + config host no listada) | Documentar y detener |
| Código Oracle | **No** | — |

---

## 4. Latencia / proveedor (por job)

| Job | Duración | Oracle→Signal | Provider real | Model real | Coste |
| --- | --- | --- | --- | --- | --- |
| `oracle.dossier_question.answer` `2e1de7d7…` | ~0.31 s | signal-dev `/api/v1/ai/run` | ollama | `qwen3.5:9b` (missing) | 0 |
| `oracle.report.custom_brief.plan` `5823c646…` | ~0.18 s | idem | ollama | `qwen3.5:9b` (missing) | 0 |

---

## 5. Estado final

| Superficie | Estado |
| --- | --- |
| oracle-dev services | api/web/worker/beat/nginx **active** |
| Política AI demo | **`internal`** (fix aplicado) |
| Ask / informe | **bloqueados** por modelo Ollama ausente en signal-dev consumer 61 |
| Expediente demo | intacto; conversación + report draft creados; jobs failed nuevos como histórico |
| signal-dev | **no mutado** |
| Producción | **no tocada** |

### Fix mínimo propuesto (siguiente turno, fuera 031)

1. En **signal-dev** (CMS consumer del API key Oracle, id **61**): alinear task keys `dossier_question_answer` y `report_custom_brief_plan` a un modelo Ollama **instalado**, o `ollama pull qwen3.5:9b`.  
2. Re-ejecutar Ask + `custom_brief` plan → accept lifecycle (sin re-tocar política).  
3. Continuar plan 032 IC / 033 bridge solo cuando Ask base con memoria Oracle funcione.

---

## 6. Evidencia

| Artefacto | Ubicación |
| --- | --- |
| Host evidence | `/var/backups/opn-oracle-dev/sv2-ask-20260802/` |
| Policy before/after JSON | `policy_before.json` / `policy_after.json` |
| SQL | `policy_update.sql` |
| Signal model errors | `42_signal_model_errors.json` |
| DB snapshot | `43_final_db_state.txt` |
| Branch | `sv2/ask-unblock` |
| Trailer | `Prompt: SV2-ASK` |
