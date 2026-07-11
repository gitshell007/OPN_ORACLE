# Webhooks Signal Avanza → OPN Oracle · contrato 2026-07-01

**Estado:** confirmado bilateralmente contra el productor Signal
**Última revisión:** 2026-07-11

## 1. Endpoint y activación

Endpoint receptor orientativo:

```text
POST /api/v1/integrations/signal-avanza/webhooks/v1/{subscription_key}
```

La ubicación de la suscripción puede cambiar tras acordar el contrato. `subscription_key` es un identificador opaco, de alta entropía y no secreto que permite resolver la conexión; Oracle nunca confía en un `tenant_id` del body. El adaptador HTTP real y las suscripciones reales permanecen desactivados hasta cerrar el contrato bilateral y superar E2E.

El endpoint no usa sesión ni CSRF. En producción solo acepta HTTPS y `Content-Type: application/json`. El límite de body y la ventana temporal son configurables; sus valores definitivos están abiertos.

## 2. Envelope propuesto

```json
{
  "event_id": "evt_example",
  "event_type": "signal.created",
  "api_version": "2026-07-01",
  "occurred_at": "2026-07-10T08:00:00Z",
  "delivery_attempt": 1,
  "monitor_id": "mon_ext_example",
  "data": {
    "signal": {
      "id": "sig_ext_example",
      "monitor_id": "mon_ext_example",
      "type": "official_publication",
      "title": "Convocatoria de ejemplo",
      "summary": "Resumen sintético.",
      "source": {
        "name": "Fuente de ejemplo",
        "url": "https://example.invalid/source/1",
        "published_at": "2026-07-10T07:55:00Z"
      },
      "language": "es",
      "entities": [],
      "tags": [],
      "categories": [],
      "content_hash": "sha256:0123456789abcdef",
      "observed_at": "2026-07-10T08:00:00Z",
      "created_at": "2026-07-10T08:00:01Z",
      "provenance": {"connector": "official-feed", "monitor_config_version": 3}
    }
  }
}
```

Eventos candidatos: `signal.created`, `signal.updated`, `monitor.health_changed`. Solo `signal.created` es necesario para el flujo mínimo y **la lista definitiva queda abierta**. `event_id` permanece estable entre retries; un `delivery_id` puede variar por entrega. No se presupone orden global.

## 3. Firma propuesta

Cabeceras orientativas:

```text
X-Opn-Signal-Timestamp: 1783670400
X-Opn-Signal-Signature-V2: <hex-hmac-sha256>
```

Contenido firmado, usando exactamente los bytes recibidos:

```text
<timestamp>.<raw_body>
```

Algoritmo propuesto: HMAC-SHA256 y comparación constant-time. Quedan abiertos el encoding hex/base64, nombres exactos de cabecera, posibilidad de múltiples firmas durante rotación y si `event_id` forma parte del contenido firmado.

Oracle comprueba, antes de encolar:

1. método, content type y tamaño;
2. suscripción/conexión activa;
3. timestamp parseable dentro de la tolerancia;
4. firma contra secreto actual y, durante un solape limitado, el anterior;
5. coincidencia entre event ID de cabecera y body si ambos están presentes;
6. unicidad de event ID dentro de la conexión.

El secreto se genera con entropía suficiente, se almacena cifrado y nunca se registra ni se devuelve tras su alta/rotación. La duración del solape de rotación queda abierta.

## 4. Persistencia, idempotencia y procesamiento

Oracle persiste primero un inbox durable con conexión/tenant resueltos, `event_id`, hashes, headers permitidos y raw body protegido. Después responde rápido y delega la validación de schema/normalización a Celery.

```text
received -> validated -> queued -> processed
   |            |           |
   +------------+-----------+-> rejected
                            +-> failed -> retry
```

Un event ID ya persistido para la misma conexión obtiene una respuesta 2xx idempotente y no duplica efectos. Una señal recibida también por polling se deduplica por proveedor + ID externo y hash de contenido. Oracle no ejecuta IA, triage largo ni creación automática de oportunidad/riesgo dentro del request webhook.

## 5. Respuestas y retry esperados

| Respuesta Oracle | Interpretación propuesta para Signal |
|---|---|
| `202` | Nueva entrega persistida y aceptada para procesamiento |
| `200`/`202` | Duplicado ya aceptado; éxito idempotente |
| `400`/`415`/`422` | Petición/schema no válido; no retry salvo corrección |
| `401`/`403` | Firma o suscripción no válida; no retry automático indefinido |
| `404` | Suscripción no reconocida; no revela tenant |
| `409` | Conflicto semántico excepcional; política abierta |
| `413` | Payload excede límite; no retry sin reducirlo |
| `429` | Retry respetando `Retry-After` |
| `5xx` | Retry con backoff exponencial y jitter |

Signal debe usar timeout corto, máximo de intentos, dead-letter y replay manual auditado. El éxito exacto (`cualquier 2xx` frente a `200/202`) y los calendarios de retry quedan abiertos.

## 6. Seguridad y privacidad

- Signal valida la URL de callback contra SSRF, DNS rebinding, redirects y metadata/IP privadas, salvo una excepción privada explícita del despliegue.
- No se envían secretos, credenciales, HTML activo ni contenido completo que la licencia de origen prohíba.
- Oracle sanitiza cualquier contenido antes de presentarlo y conserva procedencia, raw hash y versión de monitor.
- Logs y métricas contienen IDs, estados, latencia e intentos, no body ni firma.
- Los raws tienen acceso restringido y una política de retención que debe acordarse.
- Replay, entrega fuera de orden y crash después de persistir se tratan como escenarios normales e idempotentes.

## 7. Preguntas que debe cerrar Signal

1. Ruta de callback y método para crear/rotar una suscripción.
2. Cabeceras, canonicalización, encoding y versión de firma exactos.
3. Ventana anti-replay, overlap de secretos y algoritmo de rotación.
4. Eventos soportados, schema por evento y política para versiones desconocidas.
5. Límites de body/header, retención, ordering y delivery guarantees.
6. Timeouts, retry schedule, `Retry-After`, máximo de intentos y replay manual.
7. Reglas de licencia para summary, excerpt, URL y raw content.
