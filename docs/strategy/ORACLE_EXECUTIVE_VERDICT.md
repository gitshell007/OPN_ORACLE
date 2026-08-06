# OPN Oracle — Veredicto ejecutivo

**Fecha:** 2026-07-20 · **Base de evidencia:** auditoría completa de código (backend Flask, frontend Next.js, 20 migraciones, 166 endpoints, 505 tests), documentación (STATUS, DECISIONS D-001–D-039, prompts 17–63, readiness de seguridad) e investigación de mercado con fuentes 2024-2026. Etiquetas: HECHO / HIPÓTESIS / INFERENCIA / RECOMENDACIÓN.

> **ACTUALIZACIÓN 2026-08-07 — prevalece sobre las carencias comerciales históricas de este documento.** Ya están versionados para revisión un [one-pager honesto](ORACLE_ONE_PAGER_HONESTO.md), un [guion de demo verificable](ORACLE_DEMO_SCRIPT.md), una [plantilla de piloto](ORACLE_PROPUESTA_PILOTO.md) y una [calculadora ROI](ORACLE_ROI_CALCULATOR.html), tras auditoría técnica independiente. No equivale a material aprobado, publicado ni en producción. Pricing, entidad oferente, condiciones, residencia, subencargados y compromisos siguen **POR CONFIRMAR**. Las cifras históricas de julio no son una oferta autorizada.

---

## Veredicto

```text
GO CON CONDICIONES
```

Con un matiz esencial: **el "GO" es de producto y el "CON CONDICIONES" es comercial.** La ingeniería no es el problema; hoy no existe negocio alrededor de ella.

## El diagnóstico en cuatro frases

1. **HECHO DE CÓDIGO, NO SELLO DE PRODUCCIÓN** — OPN Oracle es un backend multi-tenant con RLS PostgreSQL, RBAC, auditoría y jobs durables. Dispone de controles de producto verificables en repositorio (aislamiento multi-tenant, RBAC, auditoría, auth con contraseña fuerte, exports con caducidad). La aptitud para un entorno productivo concreto depende del despliegue, de los features habilitados y del contrato. No se afirma certificación ISO/SOC/ENS ni readiness global de producción sin evidencia de ese entorno. La referencia histórica a un usuario externo y a un despliegue debe revalidarse antes de cualquier uso comercial.
2. **HECHO HISTÓRICO A 2026-07-20** — No existía ninguna pieza comercial emitible. **Actualización:** one-pager, guion, propuesta de piloto y calculadora están versionados y auditados técnicamente; siguen pendientes de aprobación comercial, landing publicada, pricing autorizado y caso de éxito.
3. **INFERENCIA** — La tesis declarada ("expediente estratégico genérico para cualquier sector") es invendible tal cual: no nombra comprador, ni partida presupuestaria, ni resultado medible. Pero el producto realmente construido ha derivado hacia una cuña concreta y sí vendible: **inteligencia de contratación pública (PLACSP), inteligencia de entidades (BORME) e informes con evidencia verificada**, guiada por cuentas reales (Iberdrola, CATL, ITURRI, IACELL).
4. **HIPÓTESIS DE MERCADO HISTÓRICA** — La investigación de julio situó referencias de competitive/market intelligence mid-market en una banda de 10.000–30.000 €/año. Esa referencia no autoriza el precio de Oracle. El porcentaje de coste LLM sobre ACV depende de un precio todavía no aprobado y del proveedor realmente usado, por lo que debe medirse con el ledger vigente antes de presentarlo como hecho.

## Qué cambia el veredicto: la tesis revisada

> **Antes (invendible):** "OPN Oracle convierte proyectos importantes en expedientes estratégicos vivos."
>
> **RECOMENDACIÓN (vendible):** "OPN Oracle es la plataforma con la que los equipos de desarrollo de negocio que venden al sector público y a grandes cuentas en España detectan antes licitaciones y oportunidades, conocen a fondo a competidores, socios y adjudicatarios (BORME + PLACSP), y llegan a cada comité y reunión con un informe con evidencia citada — sin depender de la memoria de nadie."

El "expediente estratégico" sigue siendo la unidad interna correcta. Deja de ser el mensaje de venta.

## Las cinco condiciones del GO

| # | Condición | Plazo | Criterio de cumplimiento |
|---|---|---|---|
| 1 | **Pivotar el posicionamiento a la cuña B2G/entidades** (desarrollo de negocio de empresas que licitan y vigilan cuentas en España), manteniendo el core genérico como arquitectura, no como mensaje | 0-30 días | Frase de categoría, pitch de 30 s y demo de 15 min aprobados y usados en 5 conversaciones reales |
| 2 | **Fiabilidad demostrable por recorrido**: la demo canónica de contratación de 15 minutos exige su humo completo. El prompt 63 y la validación 10/10 bloquean únicamente una demo que incluya el informe de entidad; no bloquean el recorrido canónico que no lo usa | 0-15 días | Humo del recorrido elegido sin funciones rotas; si se enseña informe de entidad, p63 resuelto y medición 10/10 registrada en el entorno autorizado, nunca inferida desde producción |
| 3 | **Tres pilotos pagados** (IACELL como primer candidato), con precio, duración, criterios de éxito y fecha de decisión **POR CONFIRMAR** por escrito | 0-90 días | 3 pilotos firmados; ≥1 convertido a contrato anual |
| 4 | **Pricing y packaging autorizados**: nombres, importes, límites, forma de pago, duración, descuentos e imputación del piloto **POR CONFIRMAR** por el propietario | 0-30 días | Documento de precios aprobado y usado de forma coherente; ningún descuento o compromiso no pactado |
| 5 | **Congelar la construcción de funcionalidad nueva no ligada a venta**: cada prompt de desarrollo de los próximos 90 días debe trazarse a demo, piloto, adopción o margen. SSO/ENS se abordan solo cuando un contrato lo exija | continuo | Backlog etiquetado; ratio ≥70% de esfuerzo en iniciativas con KPI comercial |

## Lo que NO es el problema

- El coste de IA no se considera por sí solo un bloqueo técnico, pero coste, proveedor y porcentaje sobre ACV deben medirse; precio y ACV están **POR CONFIRMAR**.
- El repositorio contiene controles multi-tenant y de auditoría verificables; no se convierte esa evidencia en una comparación universal con otros SaaS ni en un sello de readiness.
- La competencia directa en España en esta combinación (fragmentada por vertical: Tendios en licitaciones, GovClipping en regulatorio, nadie une entidades+licitaciones+expediente — HECHO/HIPÓTESIS).

## Los tres riesgos que pueden matar el negocio

1. **Bus factor 1 total**: una sola persona desarrolla, opera, despliega y tendría que vender. Sin activos comerciales reutilizables, cada venta será artesanal. (HECHO en el repo; mitigación en el playbook GTM.)
2. **Sobreconstrucción**: 46 prompts de iteración técnica post-MVP sin una venta. El patrón de los últimos 10 días (revisor IA que rompe producción, grafos, cronogramas) es el de un producto que se perfecciona para nadie. (HECHO.)
3. **Cold start del valor**: un tenant nuevo ve señales/oportunidades vacías hasta configurar monitores. Sin onboarding empaquetado con datos públicos del propio prospecto (PLACSP/BORME funcionan sin configuración), la primera semana decepciona. (INFERENCIA sólida.)

## Dónde está el detalle

Cada dimensión se desarrolla en su documento: [auditoría comercial](ORACLE_COMMERCIAL_AUDIT.md), [ICP y mercado de entrada](ORACLE_ICP_AND_MARKET_ENTRY.md), [propuesta de valor](ORACLE_VALUE_PROPOSITION.md), [momentos wow](ORACLE_WOW_MOMENTS.md), [gap de producto](ORACLE_PRODUCT_GAP_ANALYSIS.md), [revisión UX](ORACLE_UX_COMMERCIAL_REVIEW.md), [pricing](ORACLE_PRICING_AND_PACKAGING.md), [unit economics](ORACLE_UNIT_ECONOMICS.md), [playbook de ventas](ORACLE_GTM_AND_SALES_PLAYBOOK.md), [guion de demo](ORACLE_DEMO_SCRIPT.md), [moat](ORACLE_COMPETITIVE_MOAT.md), [roadmap 12 meses](ORACLE_12_MONTH_ROADMAP.md), [plan de ingresos 90 días](ORACLE_90_DAY_REVENUE_PLAN.md), [registro de decisiones](ORACLE_DECISION_REGISTER.md) y [recomendación maestra](ORACLE_MASTER_RECOMMENDATION.md).
