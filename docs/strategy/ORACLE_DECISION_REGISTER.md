# OPN Oracle — Registro de decisiones estratégicas

Decisiones propuestas por esta auditoría (2026-07-20/21). Estado: PROPUESTA hasta que el propietario las ratifique; entonces pasar a ACEPTADA con fecha, o RECHAZADA con motivo. Complementa (no sustituye) el registro técnico `docs/implementation/DECISIONS.md` (D-001–D-039).

| ID | Decisión | Estado | Justificación resumida | Documento |
|---|---|---|---|---|
| E-001 | Veredicto **GO CON CONDICIONES** (5 condiciones) | PROPUESTA | Producto real y barato de operar; negocio inexistente; condiciones cierran la brecha | [Veredicto](ORACLE_EXECUTIVE_VERDICT.md) |
| E-002 | Pivotar el **posicionamiento** a "inteligencia de negocio público y cuentas estratégicas" (cuña PLACSP+BORME+evidencia); el core genérico queda como arquitectura | PROPUESTA | La tesis genérica no nombra comprador ni partida; la cuña sí, y el código ya la sirve | [Propuesta de valor](ORACLE_VALUE_PROPOSITION.md) |
| E-003 | **ICP inicial**: empresas españolas 50-1.000 empleados que licitan (≥10 ofertas/año) o gestionan ≥5 cuentas estratégicas; secundario: consultoras/despachos; evitar defensa/utilities-enterprise/AAPP/fondos el año 1 | PROPUESTA | Matriz de segmentos 29/35; cuentas reales existentes ya apuntan ahí | [ICP](ORACLE_ICP_AND_MARKET_ENTRY.md) |
| E-004 | **Pricing**: Essential 5.900 €/año · Professional 12.900 €/año · Enterprise desde 30.000 €/año · implantación 3.500 € · analista gestionado 1.500-2.900 €/mes · piloto 4.500 €/8 semanas descontable | PROPUESTA | Banda de mercado 10-30 K€; suelo 500 €/mes para no caer en categoría "alertas"; cierra la pregunta abierta nº10 de la memoria (2026-07-09) | [Pricing](ORACLE_PRICING_AND_PACKAGING.md) |
| E-005 | **Prompt 63**: adoptar la opción 3 del STATUS — retirar el revisor semántico de la ruta del informe de entidad, conservar la validación estructural de citas (medida 45/45/0); reevaluar revisor cloud solo si un cliente exige el veredicto semántico | PROPUESTA | Evidencia: 3/3 rechazos falsos del modelo 9B; el control estructural cubre el riesgo real; la demo no puede depender de una función inestable | STATUS.md nota 2026-07-20 |
| E-006 | **Congelar funcionalidad** no trazable a venta/adopción/retención/margen durante 90 días; excepciones: p63, PDF de informes, digest por email, onboarding empaquetado | PROPUESTA | 46 prompts post-MVP sin ventas; patrón de sobreconstrucción | [Roadmap](ORACLE_12_MONTH_ROADMAP.md) |
| E-007 | **No vender** la integración Nexus/Sentinel como existente; retirar del pitch hasta que exista | PROPUESTA | HECHO: no hay código de integración; riesgo de credibilidad | [Gap analysis](ORACLE_PRODUCT_GAP_ANALYSIS.md) |
| E-008 | **SSO y ENS gated por contrato**: no construir hasta que un Enterprise/AAPP lo pague | PROPUESTA | Evita sobreconstrucción; el ICP inicial no lo exige | [Roadmap](ORACLE_12_MONTH_ROADMAP.md) |
| E-009 | **Retirar Horizon** (`/concept-b`) y el escaparate A/B tras la migración documentada | PROPUESTA | Decisión de UI ya tomada (Vector canónica); mantener el prototipo es coste sin retorno | [UX review](ORACLE_UX_COMMERCIAL_REVIEW.md) |
| E-010 | **IACELL primero**: formalizar el uso actual como piloto pagado o contrato con precio fundador (-15%) a cambio de caso de referencia | PROPUESTA | Único usuario externo real; el caso de referencia vale más que el descuento | [Plan 90 días](ORACLE_90_DAY_REVENUE_PLAN.md) |
| E-011 | Regla anti-consultoría: todo servicio humano tarifado; ninguna feature comprometida en venta sin segundo comprador plausible; software >50% de ingresos desde mes 12 | PROPUESTA | Defensa del margen y de la escalabilidad | [GTM](ORACLE_GTM_AND_SALES_PLAYBOOK.md), [Unit economics](ORACLE_UNIT_ECONOMICS.md) |
| E-012 | Levantar el **NO-GO operativo** (fase 15/16: CI remoto, branch protection, copia off-host, UAT) en meses 4-6, antes de superar 5 clientes de pago | PROPUESTA | Los pilotos pueden correr con el estado actual; crecer sin esa higiene no | [Roadmap](ORACLE_12_MONTH_ROADMAP.md) |

## Decisiones pendientes que corresponden al propietario (no resolubles por auditoría)

| ID | Cuestión | Contexto |
|---|---|---|
| DP-01 | Ratificar o vetar el pivot de posicionamiento (E-002) — es la decisión raíz de la que cuelgan las demás | La tesis original era del fundador; esta auditoría propone revisarla con la evidencia del propio uso |
| DP-02 | Disponibilidad real de tiempo del fundador para vender (40% propuesto) o alternativa (¿socio comercial?) | El plan de 90 días asume dedicación mayoritaria a venta |
| DP-03 | Situación contractual/expectativas actuales con IACELL (la auditoría no tiene visibilidad) | Determina si E-010 es piloto o contrato directo |
| DP-04 | Coste interno real de Signal Avanza y acuerdo de imputación entre productos OPN | Afecta al margen contable de Oracle |
