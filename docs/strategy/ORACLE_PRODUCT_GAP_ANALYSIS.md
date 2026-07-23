# OPN Oracle — Análisis de brechas de producto (documentado vs real)

Contraste sistemático entre lo escrito (memoria de producto, plan, STATUS) y lo verificado en código. Etiquetas: HECHO / INFERENCIA / HIPÓTESIS.

---

## 1. Qué existe realmente (HECHO, verificado en código)

| Capacidad | Estado real | Evidencia |
|---|---|---|
| Expedientes estratégicos completos (CRUD, objetivos, hipótesis, watchlists, perfiles iniciales por tipo) | **Real** | `oracle/models.py`, `oracle/routes.py` (55 endpoints), perfiles semilla en `src/lib/dossier-starter-profiles.ts` |
| Multi-tenancy con RLS PostgreSQL forzado + RBAC 34 permisos + auditoría append-only | **Real, madurez alta** | Migración `20260710_0002`, `tenants/context.py`, `platform/rbac.py`, `platform/audit.py` |
| Señales: monitores, ingesta con dedupe, triaje IA con evidencia, inbox con revisión/promoción | **Real** | `integrations/signal_avanza.py`, `oracle` triage, `dossier-intelligence-section.tsx` |
| Promoción señal→oportunidad/riesgo/tarea con transiciones gobernadas y concurrencia ETag | **Real** | `OPPORTUNITY_TRANSITIONS`/`RISK_TRANSITIONS`, `version_conflict` manejado en UI |
| Contratación pública PLACSP: adjudicaciones, licitaciones, UTEs, fijado a expediente con evidencia, informe competitivo | **Real y diferenciador** | `integrations/procurement*.py` (23 endpoints proxy + dossier items), prompts 34-43 |
| Inteligencia de entidades BORME: ficha 360º, grafo navegable con cronograma, materialización como actor | **Real y diferenciador** | `integrations/entity_intel*.py`, `entity-dossier.tsx`, grafo Cytoscape |
| Informes IA con plantillas versionadas, citas verificadas estructuralmente, visor con fuentes legibles | **Real** (con la excepción de abajo) | `reporting/`, `ReportTemplateRegistry` v1/v2, medición 45 citadas/45 permitidas/0 inventadas |
| Briefing de reunión, digest semanal, resumen vivo nocturno del expediente | **Real** | `meeting_briefing`, `weekly_change`, Beat 03:15 Europe/Madrid |
| Wizard "Mejorar con Oracle" (diagnóstico por rondas con acciones prefijadas) | **Real** | `dossier-completion-wizard.tsx`, agente `dossier_completion_wizard/v1` |
| 15 agentes IA con prompts versionados, política por tenant, presupuestos, ledger de uso, leases/fencing | **Real** | `ai/service.py`, `ai/prompts/*` |
| Portal superadmin, backups con restore validado, releases inmutables con rollback | **Real** | `/platform/*`, `oracle-control.sh`, evidencia de restore en STATUS |

## 2. Qué está roto o incompleto (HECHO, declarado en el propio repo)

| Elemento | Estado | Consecuencia comercial |
|---|---|---|
| **Informe de entidad con revisor semántico (prompt 63)** | Revertido en producción 2026-07-20; código sigue en `master` sin resolver; el revisor rechazó 3/3 informes | Riesgo de demo letal: la función más vistosa puede fallar en directo. **Decisión pendiente** (recomendación: opción 3 — retirar el revisor de esa ruta; la validación estructural de citas ya cubre el riesgo real) |
| PDF de informes | Deshabilitado por diseño (`REPORT_PDF_MODE=disabled`) | Un comité pide PDF. Necesario para percepción de entregable "de verdad" |
| "Marcar como revisado" en Qué ha cambiado | Deshabilitado (sin registro durable) | Menor; el hábito de revisión pierde cierre |
| Edición de perfil de usuario | Sin PATCH (lectura sí) | Cosmético |
| Copia off-host automatizada, branch protection, CI remoto verde, UAT formal | Fase 15/16 `in_progress`; GO/NO-GO oficial = **NO-GO** | Higiene operativa pendiente; no bloquea pilotos, sí bloquea "producción estable con datos críticos" |
| Métricas Prometheus sin agregar todos los workers; F13-06..10 abiertos | Declarado en readiness | No bloquea venta inicial |

## 3. Qué está solo diseñado o es solo discurso (HECHO por ausencia en código)

| Prometido en la memoria/tesis | Realidad |
|---|---|
| Reutilización de **Nexus** (actores, memoria relacional, reuniones) | **No hay integración.** El mapa de actores se nutre de señales y del grafo BORME de Signal. El "Oráculo del expediente" es un patrón inspirado, no una integración (D-015) |
| Reutilización de **Sentinel/Risk** (vigilancia, escenarios, alertas) | **No hay adapter ni código.** Solo mapeo conceptual en la memoria |
| Escenarios ideal/probable/adverso | No implementados |
| Entity Resolution Agent contra Nexus | No existe; hay deduplicación de candidatos de actor desde señales |
| Integraciones Slack/Teams/CRM/Drive | No existen (P1-P2 declarado) |
| SSO/SAML/OIDC | No existe (grep sin resultados) |
| Modelo de cobro | Pregunta abierta desde 2026-07-09, nunca respondida |

**Consecuencia:** el pitch heredado del ecosistema ("Oracle reutiliza Nexus y Sentinel") no debe usarse en venta: describe una arquitectura de grupo, no el producto entregable. Vender lo que existe.

## 4. Qué parece atractivo en demo pero no crea valor comercial (INFERENCIA)

- **Los prototipos `/concept-a` y `/concept-b`**: vistosos, mock sobre `localStorage`, redirigidos en producción. Valor comercial nulo; mantenerlos consume atención. RECOMENDACIÓN: retirar Horizon tras la migración documentada.
- **Cronograma de doble manejador y modo forense del grafo**: técnicamente notable, pero el comprador paga por "¿quién es esta empresa y con quién se relaciona?", no por controles de zoom. No seguir invirtiendo ahí.
- **El revisor semántico universal (prompts 60-63)**: persigue una garantía que el cliente aún no ha pedido, con un modelo local de 9B que produce falsos rechazos. La garantía vendible ya existe (citas estructuralmente validadas).

## 5. La deriva de producto: de radar genérico a inteligencia de entidades y licitaciones (INFERENCIA clave)

Los prompts 34-63 (la mayoría del esfuerzo reciente) se concentraron en PLACSP, BORME e informes de entidad — no en el "motor de oportunidades" genérico de la memoria. Esto **no es un error a corregir: es el mercado hablando a través de las cuentas reales** (Iberdrola, CATL, ITURRI, IACELL). La brecha no es que el código traicione la visión; es que la visión no se ha actualizado para reclamar lo que el código ya sabe hacer.

## 6. Clasificación funcional P0/P1/P2/ELIMINAR

| Función | Problema que resuelve | Comprador | Frecuencia | Venta | Retención | Expansión | Margen | Esfuerzo restante | Prioridad |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| Expediente + señales + promoción | dispersión → acción | BD/dirección | diaria-semanal | alta | alta | media | alto | 0 | **P0** |
| PLACSP (licitaciones + adjudicaciones + informe competitivo) | perder concursos; ceguera competitiva | BD B2G | semanal | **muy alta** | alta | alta | alto | 0 | **P0** |
| Entidades BORME (ficha 360º + grafo) | due diligence manual de socios/competidores | BD/dirección | semanal | **muy alta** | media | media | alto | estabilizar informe (p63) | **P0** |
| Informes con evidencia + visor | horas de analista; confianza en IA | dirección | semanal | alta | alta | media | alto | PDF | **P0** |
| Digest semanal + Qué ha cambiado | hábito de retorno | todos | semanal | media | **muy alta** | baja | alto | envío email del digest | **P0** |
| Wizard "Mejorar con Oracle" | onboarding/activación | analista | al crear | media | alta | baja | alto | 0 | **P1** |
| Briefing de reunión | reuniones mal preparadas | BD | quincenal | media | alta | media | alto | 0 | **P1** |
| Actores/candidatos/relaciones internas | mapa de cuenta | BD | mensual | media | media | media | alto | 0 | **P1** |
| Exportaciones, notificaciones | entrega | todos | mensual | baja | media | baja | alto | 0 | **P1** |
| Alertas configurables por email | anticipación | todos | continuo | media | alta | baja | alto | parcial | **P1** |
| Superadmin/plataforma/backups | operación OPN | interno | — | — | — | — | — | 0 | **P0 interno** |
| Escenarios, coach de reuniones, playbooks | — | — | — | — | — | — | — | alto | **P2** (no construir aún) |
| SSO/ENS | compra enterprise/AAPP | enterprise | — | alta (tardía) | — | — | — | alto | **P2 gated por contrato** |
| Prototipo Horizon (`/concept-b`) | ninguno | nadie | — | — | — | — | — | retirada | **ELIMINAR** |
| Revisor semántico en ruta de entidad | garantía redundante | nadie aún | — | negativa (rompe demo) | — | — | — | — | **ELIMINAR de la ruta** (mantener validación estructural) |

## 7. Síntesis

El gap real no está entre lo diseñado y lo construido (lo construido supera al diseño en las zonas que importan). Está entre **lo construido y lo contado**: el producto ya es una plataforma de inteligencia de licitaciones y entidades con disciplina de evidencia, y nadie — ni la memoria de producto, ni el README, ni ningún material — lo dice.
