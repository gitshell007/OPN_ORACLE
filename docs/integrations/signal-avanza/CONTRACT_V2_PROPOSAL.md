# Propuesta de contrato v2 Oracle–Signal para contratación pública

**Estado:** propuesta; no implementada en Signal
**Fecha:** 2026-07-23
**Productor observado:** `opn_signal@8a36860`
**Consumidor:** OPN Oracle

## 1. Dos carriles y regla de verdad

| Entrega | Propietario | Puede avanzar sin el otro carril |
|---|---|---|
| `scope`, compatibilidad de `active`, estado canónico y microcopy honesta | **Solo Oracle** | Sí, sobre el contrato v1 medido |
| Perfil determinista de una empresa comparable | **Solo Oracle** | Sí; fase posterior |
| Taxonomía CPV europea versionada y validación offline | **Solo Oracle** | Sí; fase posterior |
| Wizard, revisión humana, feedback y evaluación | **Solo Oracle** | Sí; fase posterior |
| Archivo de licitaciones, rangos, ordenación y cobertura | **Requiere Signal** | No |
| Reconstrucción/versionado del índice de licitaciones | **Requiere Signal** | No |
| Activación de v2 y contract tests en ambos extremos | **Bilateral** | No |

Oracle no reconstruirá un supuesto orden global mediante dos consultas y una fusión local. Hasta
que Signal demuestre un archivo de pliegos, la experiencia histórica será **award-céntrica**:
adjudicatario, comprador, importe, fecha y CPV, con enlace al expediente original únicamente cuando
el lookup lo resuelva.

## 2. Semántica observada de v1

En `GET /api/v1/registry/tenders`, Signal v1 declara `active=true` por defecto:

- parámetro omitido: solo registros marcados activos;
- `active=true`: solo activos;
- `active=false`: elimina el predicado `is_active`; significa **todo el índice disponible**, no
  «solo inactivas»;
- no existe una consulta nativa de «solo históricas»;
- no hay `published_at`, rangos completos ni ordenación elegible;
- las búsquedas guardadas descartan el filtro temporal y sus ejecuciones fuerzan `active=true`.

Oracle adopta `scope=active|historical|all` y conserva `active` solo como alias deprecado:

| Entrada Oracle | Llamada v1 | Semántica Oracle |
|---|---|---|
| sin `scope` ni `active` | omite `active` | `active` por compatibilidad medida |
| `scope=active` | `active=true` | activas |
| `scope=all` | `active=false` | todo el índice de Signal, sin prometer archivo completo |
| `scope=historical` | no llama; `422` | no disponible en v1 |
| `active=true` | `active=true` | alias de `scope=active` |
| `active=false` | `active=false` | alias de `scope=all`, nunca «inactivas» |
| `scope` y `active` juntos | no llama; `422` | ambiguo |

El alias se mantendrá hasta el **31 de octubre de 2026** y durante al menos dos releases
productivas posteriores a esta corrección. Solo se retirará después de activar v2 y migrar clientes
y búsquedas guardadas.

## 3. Contrato solicitado a Signal

### 3.1 Licitaciones

```http
GET /api/v2/registry/tenders
  ?scope=active|historical|all
  &published_from=YYYY-MM-DD
  &published_to=YYYY-MM-DD
  &deadline_from=YYYY-MM-DD
  &deadline_to=YYYY-MM-DD
  &sort=published_at|deadline_at|updated_at
  &direction=asc|desc
  &limit=20
  &cursor=opaque
```

Requisitos:

- `scope=historical` excluye activas según una regla estable y documentada;
- `scope=all` consulta una única colección ordenada por Signal;
- paginación por cursor con snapshot/version del índice; nunca offset sobre un corpus cambiante;
- `published_at`, `deadline_at`, `updated_at` y `canonical_status` en RFC 3339 UTC;
- desempate estable, por ejemplo `(sort_field, folder_id)`;
- `canonical_status`: `open`, `closed`, `awarded`, `cancelled` o `unknown`;
- `raw_status` preservado para auditoría;
- `coverage` en la respuesta: versión del índice, primera/última fecha válida, recuentos por
  estado/año y anomalías conocidas.

### 3.2 Adjudicaciones

```http
GET /api/v2/registry/awards
  ?awarded_from=YYYY-MM-DD
  &awarded_to=YYYY-MM-DD
  &sort=award_date
  &direction=asc|desc
  &limit=20
  &cursor=opaque
```

Debe declarar normalización y validez de `award_date`, permitir filtrar fechas sentinela o
anómalas, preservar `raw_award_date` y publicar el vínculo al expediente solo cuando esté
demostrado. La ausencia de vínculo no invalida la adjudicación.

### 3.3 Búsquedas guardadas

Signal debe persistir el plan temporal completo, devolverlo sin pérdidas y ejecutar exactamente
esa versión:

```json
{
  "keywords": ["equipos de protección"],
  "scope": "all",
  "published_from": "2024-01-01",
  "published_to": "2026-07-23",
  "sort": "published_at",
  "direction": "desc",
  "contract_version": "registry-v2"
}
```

Mientras v1 siga activo, Oracle solo permite guardar búsquedas `active`.

## 4. Reconstrucción del índice en Signal

La reconstrucción es una tarea asíncrona propiedad de Signal:

1. crear una versión sombra del índice;
2. ingerir y normalizar con checkpoints reanudables;
3. calcular métricas de cobertura y anomalías;
4. ejecutar contract tests y muestras estratificadas;
5. publicar un manifiesto inmutable con versión, ventanas y hashes;
6. cambiar atómicamente el alias de lectura;
7. conservar rollback a la versión anterior.

Oracle consume la versión publicada y puede cachear resultados breves; no replica el corpus PLACSP
ni usa Redis como fuente de verdad. Una reconstrucción no bloquea el índice vigente.

## 5. Estado canónico provisional en Oracle

Oracle solo mapea vocabulario explícitamente conocido. Cualquier código no contratado —incluidos
los observados `PUB` y `EV`— se expone como `unknown` junto al estado bruto. No se infiere estado
por fecha, título ni semejanza textual.

## 6. IA, memoria e invalidación

La búsqueda y el listado ejecutan cero llamadas LLM por licitación. El wizard futuro hará una
llamada por revisión de plan y consultará el índice estructurado. Los resúmenes opcionales serán
jobs explícitos y cacheados; su payload incluirá `content_hash` de la licitación y versión del
prompt, aprovechando la idempotencia existente por `input_hash`.

El feedback se guarda de forma determinista. Una evolución posterior podrá proponer un plan
`v(n+1)` desde `v(n)` más feedback acumulado, mediante una única ejecución explícita y siempre con
revisión humana.

## 7. Criterios bilaterales de aceptación

- contract test para cada combinación de `scope`, rangos y orden;
- `scope=all` mantiene orden global al paginar;
- `scope=historical` nunca devuelve un registro canónicamente `open`;
- búsquedas guardadas preservan y ejecutan el mismo plan;
- cobertura por año y estado reconciliada con el manifiesto de reconstrucción;
- muestra estratificada de expedientes con tasa de resolución publicada;
- Oracle registra cero nuevas filas en `AIUsageLedger` durante una búsqueda/listado;
- despliegue coordinado, compatible y con rollback documentado.
