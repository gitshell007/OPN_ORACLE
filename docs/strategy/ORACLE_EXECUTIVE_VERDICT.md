# OPN Oracle — Veredicto ejecutivo

**Fecha:** 2026-07-20 · **Base de evidencia:** auditoría completa de código (backend Flask, frontend Next.js, 20 migraciones, 166 endpoints, 505 tests), documentación (STATUS, DECISIONS D-001–D-039, prompts 17–63, readiness de seguridad) e investigación de mercado con fuentes 2024-2026. Etiquetas: HECHO / HIPÓTESIS / INFERENCIA / RECOMENDACIÓN.

---

## Veredicto

```text
GO CON CONDICIONES
```

Con un matiz esencial: **el "GO" es de producto y el "CON CONDICIONES" es comercial.** La ingeniería no es el problema; hoy no existe negocio alrededor de ella.

## El diagnóstico en cuatro frases

1. **HECHO** — OPN Oracle no es un prototipo: es un backend multi-tenant real con RLS PostgreSQL, RBAC, auditoría append-only, pipeline IA con presupuestos y evidencia obligatoria, jobs durables y despliegue endurecido en producción (`oracle.opnconsultoria.com`), con al menos un usuario externo real (IACELL). Su madurez técnica supera la de muchos SaaS con clientes de pago.
2. **HECHO** — No existe ni una sola pieza comercial: sin pricing (la pregunta "cómo se cobrará" quedó abierta el 2026-07-09 y sigue sin respuesta), sin ICP priorizado, sin demo guionizada, sin landing, sin propuesta, sin caso de éxito. 198 commits en 10 días y cero avance en venta.
3. **INFERENCIA** — La tesis declarada ("expediente estratégico genérico para cualquier sector") es invendible tal cual: no nombra comprador, ni partida presupuestaria, ni resultado medible. Pero el producto realmente construido ha derivado hacia una cuña concreta y sí vendible: **inteligencia de contratación pública (PLACSP), inteligencia de entidades (BORME) e informes con evidencia verificada**, guiada por cuentas reales (Iberdrola, CATL, ITURRI, IACELL).
4. **HECHO (mercado)** — La banda de precio del competitive/market intelligence mid-market es 10.000–30.000 €/año; el coste LLM de servir a un cliente es <5% del ACV; lo comoditizado es el monitoreo y el resumen genérico, y lo defendible es exactamente lo que Oracle tiene: workflow expediente→decisión→evidencia y fuentes españolas.

## Qué cambia el veredicto: la tesis revisada

> **Antes (invendible):** "OPN Oracle convierte proyectos importantes en expedientes estratégicos vivos."
>
> **RECOMENDACIÓN (vendible):** "OPN Oracle es la plataforma con la que los equipos de desarrollo de negocio que venden al sector público y a grandes cuentas en España detectan antes licitaciones y oportunidades, conocen a fondo a competidores, socios y adjudicatarios (BORME + PLACSP), y llegan a cada comité y reunión con un informe con evidencia citada — sin depender de la memoria de nadie."

El "expediente estratégico" sigue siendo la unidad interna correcta. Deja de ser el mensaje de venta.

## Las cinco condiciones del GO

| # | Condición | Plazo | Criterio de cumplimiento |
|---|---|---|---|
| 1 | **Pivotar el posicionamiento a la cuña B2G/entidades** (desarrollo de negocio de empresas que licitan y vigilan cuentas en España), manteniendo el core genérico como arquitectura, no como mensaje | 0-30 días | Frase de categoría, pitch de 30 s y demo de 15 min aprobados y usados en 5 conversaciones reales |
| 2 | **Fiabilidad IA demostrable antes de cualquier demo**: resolver la decisión pendiente del prompt 63 (recomendado: opción 3 — retirar el revisor semántico de la ruta de entidad y confiar en la validación estructural de citas, ya medida en 45/45/0) y estabilizar el informe de entidad | 0-15 días | Informe de entidad genera al primer intento en producción 10/10 veces; ninguna función rota visible en la demo |
| 3 | **Tres pilotos pagados** (IACELL como primero), 4.500 € / 8 semanas, con criterios de éxito escritos y fecha de conversión a suscripción | 0-90 días | 3 pilotos firmados; ≥1 convertido a contrato anual |
| 4 | **Pricing y packaging publicados** (Essential ~5.900 €/año, Professional ~15.000 €/año, Enterprise desde 30.000 €/año + implantación y servicios gestionados tarifados) con límites de consumo IA/señales por plan | 0-30 días | Documento de precios usado en las 3 propuestas de piloto; ningún descuento >20% sin contrapartida |
| 5 | **Congelar la construcción de funcionalidad nueva no ligada a venta**: cada prompt de desarrollo de los próximos 90 días debe trazarse a demo, piloto, adopción o margen. SSO/ENS se abordan solo cuando un contrato lo exija | continuo | Backlog etiquetado; ratio ≥70% de esfuerzo en iniciativas con KPI comercial |

## Lo que NO es el problema

- El coste de IA (Ollama local ≈ 0 €; incluso con cloud, <5% del ACV — HECHO).
- La calidad del código, el multi-tenant o la auditoría (por encima del estándar del segmento — HECHO).
- La competencia directa en España en esta combinación (fragmentada por vertical: Tendios en licitaciones, GovClipping en regulatorio, nadie une entidades+licitaciones+expediente — HECHO/HIPÓTESIS).

## Los tres riesgos que pueden matar el negocio

1. **Bus factor 1 total**: una sola persona desarrolla, opera, despliega y tendría que vender. Sin activos comerciales reutilizables, cada venta será artesanal. (HECHO en el repo; mitigación en el playbook GTM.)
2. **Sobreconstrucción**: 46 prompts de iteración técnica post-MVP sin una venta. El patrón de los últimos 10 días (revisor IA que rompe producción, grafos, cronogramas) es el de un producto que se perfecciona para nadie. (HECHO.)
3. **Cold start del valor**: un tenant nuevo ve señales/oportunidades vacías hasta configurar monitores. Sin onboarding empaquetado con datos públicos del propio prospecto (PLACSP/BORME funcionan sin configuración), la primera semana decepciona. (INFERENCIA sólida.)

## Dónde está el detalle

Cada dimensión se desarrolla en su documento: [auditoría comercial](ORACLE_COMMERCIAL_AUDIT.md), [ICP y mercado de entrada](ORACLE_ICP_AND_MARKET_ENTRY.md), [propuesta de valor](ORACLE_VALUE_PROPOSITION.md), [momentos wow](ORACLE_WOW_MOMENTS.md), [gap de producto](ORACLE_PRODUCT_GAP_ANALYSIS.md), [revisión UX](ORACLE_UX_COMMERCIAL_REVIEW.md), [pricing](ORACLE_PRICING_AND_PACKAGING.md), [unit economics](ORACLE_UNIT_ECONOMICS.md), [playbook de ventas](ORACLE_GTM_AND_SALES_PLAYBOOK.md), [guion de demo](ORACLE_DEMO_SCRIPT.md), [moat](ORACLE_COMPETITIVE_MOAT.md), [roadmap 12 meses](ORACLE_12_MONTH_ROADMAP.md), [plan de ingresos 90 días](ORACLE_90_DAY_REVENUE_PLAN.md), [registro de decisiones](ORACLE_DECISION_REGISTER.md) y [recomendación maestra](ORACLE_MASTER_RECOMMENDATION.md).
