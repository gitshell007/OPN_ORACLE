# 20 — Hacer alcanzable y descubrible el arco señal → oportunidad/riesgo/actor (P1)

> Lee `18_UX_REMEDIATION_OVERVIEW.md` y **ejecuta después del prompt 19** (la promoción depende
> de que la revisión funcione). Severidad **P1**: es el núcleo del "radar ofensivo".

## Problema observado (evidencia de auditoría)

Desde el detalle de una señal (drawer «Inspección contextual») las **únicas** acciones visibles
son «Marcar revisada» y «Descartar». **No hay ninguna acción de promover a oportunidad, riesgo o
actor.** El producto (OPN_Oracle_Codex_Memory.md §7, §9) define Oracle como el arco
señal → oportunidad/riesgo/actor → decisión. Hoy ese arco no es alcanzable desde la señal, así
que la herramienta "no cumple su función": recoge señales pero no las convierte en trabajo
estratégico.

## Estado real del código (importante)

La capacidad **ya existe en backend**, solo está oculta/bloqueada en la experiencia:

- `apps/api/src/opn_oracle/oracle/service.py:502` `promote_signal_link()` crea `Opportunity` o
  `RiskItem` desde la señal, con idempotencia; **exige** `link.status == "reviewed"`
  (línea ~550: «La señal debe revisarse antes de promoverse.»).
- Ruta `apps/api/src/opn_oracle/oracle/routes.py:1195` `POST /signals/<link_id>/promote`
  (permiso `signal.promote`, cabecera `Idempotency-Key` obligatoria).
- Frontend `src/components/dossiers/dossier-intelligence-section.tsx` ya tiene estado de
  promoción (`promotionOpen`, `promotionKind`, `promotionTitle`, `api.dossierSignals.promote`),
  pero solo se alcanza cuando la señal está `reviewed` — y la revisión estaba rota (prompt 19).
- La promoción a **actor** NO va por `promote_signal_link` (que solo hace opportunity/risk):
  las entidades de la señal se convierten en actor por el flujo de **candidatos de actor**
  (`oracle/actor_candidates.py`, rutas `.../actor-candidates`, ver prompt 22).

## Objetivo

Que desde una señal el usuario pueda, en pocos clics y de forma descubrible, **convertirla en
oportunidad, en riesgo o en actor**, con evidencia y trazabilidad; y que el estado de la señal
(`nueva → revisada → promovida`) sea legible.

## Alcance e implementación sugerida

**Frontend (principal):**
1. En el detalle/drawer de la señal, mostrar afordancias claras de **«Promover a oportunidad»**,
   **«Promover a riesgo»** y **«Registrar actor»** (esta última enlazando al flujo de candidatos
   de actor / «Vincular actor» prellenado con las entidades de la señal).
2. Reducir la fricción del arco: permitir **revisar y promover en un paso** cuando el usuario ya
   decide promover (llamar a `review` y luego `promote` de forma encadenada, o habilitar
   «Promover» tras la revisión sin obligar a reabrir el drawer). No obligar a adivinar que hay
   que "revisar" antes.
3. Tras promover, dar feedback y **enlace directo** a la oportunidad/riesgo/actor creado, y
   reflejar el nuevo estado `Promovida` en la lista.
4. Respetar `PermissionGate` (`signal.promote`, `opportunity.write`, `risk.write`,
   `actor.write`): si falta permiso, degradar la UI sin romperla.

**Backend (verificar; cambiar solo si procede):**
- Confirmar que `promote_signal_link` deja `Opportunity`/`RiskItem` con la evidencia y el enlace
  a la señal de origen (procedencia), y con explicación/score inicial coherentes.
- Si se decide permitir "revisar+promover" atómico, valorar un endpoint o secuencia idempotente
  que no rompa la garantía de idempotencia existente (`Idempotency-Key`). Documentar la decisión
  en `DECISIONS.md`.

## Criterios de aceptación

- [ ] Desde una señal revisada, el usuario ve y usa «Promover a oportunidad» y «Promover a
      riesgo»; el recurso aparece en la pestaña correspondiente del expediente.
- [ ] Desde una señal, el usuario puede iniciar el registro del/los actor(es) mencionados
      (enlazado al flujo de candidatos, prompt 22).
- [ ] El arco completo señal→oportunidad y señal→riesgo es ejecutable de punta a punta en un
      recorrido Playwright real contra Flask.
- [ ] La procedencia (señal de origen y su fuente) queda visible en la oportunidad/riesgo creado.
- [ ] Estados de señal legibles en lista y detalle: Nueva / Revisada / Promovida / Descartada.

## Verificación

`apps/api`: `make lint typecheck test` (+ integración). Raíz: `lint typecheck test build`;
`api:client:check`; Playwright del arco señal→oportunidad→(riesgo). Smoke visual del drawer.
Actualiza `STATUS.md` y, si añades endpoint o cambias contrato, OpenAPI/cliente y `DECISIONS.md`.

## No hacer

- No dupliques `promote_signal_link` en Node ni llames a la BD desde el frontend.
- No promuevas automáticamente sin acción humana (contradice el modelo de revisión con evidencia).
