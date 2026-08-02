# SV2-BRIDGE · Documento → memoria Signal (outbox real) + RT-08

## Resumen

Cableado Oracle Dev del puente `document.ready` → outbox bilateral MDEV-05 → publish HTTP
a signal-dev (IC keyring) + dual-write durable `/memory/v1/ingest` para materializar
sources/chunks/extract. RT-08 prompt contract bump a **1.0.1** (arrays obligatorios con `[]`).
Parches host de SV2-IC formalizados en commit.

## Código

| Área | Cambio |
| --- | --- |
| `documents/service.py` | Pre-commit `stage_document_ready_memory`; post-commit `dispatch_memory_outbox_event` |
| `integrations/memory_outbox.py` | Stage helpers, items from chunks, publisher dual-write |
| `integrations/tasks.py` | `dispatch_outbox` branch `memory.bilateral.*` |
| `integrations/memory_http_client.py` | allowlist `signal-dev.opnconsultoria.com` + `post_json` |
| `integrations/memory_context.py` | fallback `external_tenant_id` desde metadata IC |
| RT-08 | Oracle prompt + contractual catalogs `prompt_version=1.0.1` |
| Tests | `tests/test_memory_sv2_bridge_outbox.py` (+ mdev05 suite) |

## Flags (solo oracle-dev env)

```text
MEMORY_BILATERAL_OUTBOX_ENABLED=1
MEMORY_CONTEXT_MODE=http
MEMORY_CONTEXT_BASE_URL=https://signal-dev.opnconsultoria.com
```

Default OFF sin env. Publisher reutiliza IC `signal-dev-sv2-demo` (c1986b88…).

## Deploy

- Mecanismo nativo: `infra/native-dev/build-release.sh` + `activate-release.sh`
- Rama: `sv2/bridge-dev`
- Rollback: `PREVIOUS_RELEASE` (`native-4b454e1`) + env sin `MEMORY_BILATERAL_OUTBOX_ENABLED`

## E2E (evidencia en Gate Packet)

1. Owner sube documento demo → ready
2. Outbox staged → delivered; durable ingest 200; (bilateral soft si flags OFF en Signal)
3. Signal BD: sources/chunks + extract jobs bajo `c:64|t:<tenant>`
4. DMP shadow refresh → items > 0
5. Ask shadow → items_observed > 0
6. Informe plan RT-08 v1.0.1 → plan_proposed

## Deuda conocida

- Signal `/ingest/bilateral` sigue siendo pipeline provisional in-process (flags OFF por defecto);
  dual-write a `/ingest` es el path durable real para retrieve/extract.
- RT-08 en runtime Signal requiere parche de host del prompt+manifest (hash contractual) además
  del catálogo Oracle — ver Gate Packet.
