# OPN Oracle — Unit economics y rentabilidad

Etiquetas: HECHO / HIPÓTESIS. Benchmarks de referencia (HECHO, 2025): margen bruto SaaS mediana 71-72%; CAC payback mediana degradada a ~20-23 meses; NRR ~101%; churn mid-market objetivo <5% logos/año.

---

## 1. Coste de servir a un cliente (mensual, HIPÓTESIS con base HECHO)

| Concepto | Coste/cliente/mes | Base |
|---|---:|---|
| IA (Ollama local vía Signal) | ~0-5 € | HECHO: modelos locales, coste = amortización de infra compartida; ledger de uso ya mide consumo |
| IA cloud (si se activa para informes largos) | 5-25 € | HECHO (mercado): triaje con modelo pequeño ~3-5 $/mes; informes frontier 10-25 $/mes con caching/batch |
| Infra (parte proporcional de servidor, backups, almacenamiento) | 10-30 € | HECHO: hoy todo corre en un host de 3,7 GiB; escalar a host mayor ≈ 100-300 €/mes total para decenas de tenants |
| Signal Avanza (coste interno OPN) | 0 € contable / real compartido | HIPÓTESIS: coste real de Signal (infra + PLACSP/BORME) debe imputarse; estimar 20-50 €/mes por tenant activo cuando haya contabilidad interna |
| Soporte (sin analista gestionado) | 30-80 € | HIPÓTESIS: 1-2 h/mes de soporte a tarifa interna |
| **Total coste variable software** | **60-160 €/mes** | ≈ **7-19% del ACV Essential**, **6-15% del Professional** |

**Margen bruto software estimado: 80-93%** — por encima del benchmark. El coste de IA no es la amenaza. HECHO estructural favorable: la arquitectura (IA local, presupuestos por tenant, colas) fue diseñada para coste marginal bajo.

## 2. Escenarios a 12 meses (HIPÓTESIS; solo canal directo/red OPN)

| Variable | Conservador | Base | Ambicioso |
|---|---:|---:|---:|
| Pilotos firmados (4.500 €) | 3 | 5 | 8 |
| Conversión a anual | 1 | 3 | 5 |
| Clientes fin de año (Essential/Professional mix) | 2 (1E/1P) | 5 (2E/3P) | 9 (3E/6P) |
| ARR fin de año | ~19 K€ | ~51 K€ | ~95 K€ |
| Ingresos año (pilotos + implantaciones + suscripción prorrateada + servicios) | ~30 K€ | ~75 K€ | ~150 K€ |
| Coste de servir | <5 K€ | <10 K€ | <18 K€ |
| Margen bruto | >80% | >85% | >85% |

Lectura honesta: **el año 1 no paga un salario con software solo.** Paga la validación, las referencias y el derecho a subir precios. Los servicios (pilotos, implantación, analista) son los que sostienen caja el primer año — con la disciplina de que cada hora esté tarifada.

## 3. CAC y ciclo de venta

- HIPÓTESIS: CAC del canal red-de-OPN ≈ coste de tiempo del fundador (10-20 h por cliente cerrado). A tarifa sombra de 100 €/h → CAC 1.000-2.000 €. Payback < 3 meses con implantación cobrada — muy por debajo del benchmark (20+ meses) **mientras dure la red caliente**.
- El CAC real aparecerá en el cliente ~10-15, cuando se agote la red. Ese es el momento de decidir inversión en marketing/canal, no antes.
- Ciclo esperado (HECHO mercado + HIPÓTESIS local): 30-90 días con red caliente y piloto pagado; 3-6 meses en frío.

## 4. LTV y churn

- HIPÓTESIS: churn año 1 alto (pilotos que no convierten ya filtrados); en clientes anuales, objetivo <10% logos (mid-market español, producto con memoria acumulada). Con NRR 105-115% vía expedientes/servicios, LTV Essential ≈ 20-30 K€, Professional ≈ 45-70 K€ (4-5 años de vida media).
- El predictor de churn a vigilar: semanas consecutivas sin entrar en "Qué ha cambiado". Instrumentar desde el piloto 1.

## 5. Amenazas al margen y controles

| Amenaza | Realidad en OPN Oracle | Control |
|---|---|---|
| **Trabajo manual del fundador no tarifado** | La nº1. Todo (dev, ops, venta, soporte) es una persona — HECHO | Tarifar TODO servicio; runbooks delegables; no prometer personalización |
| Personalización por cliente | Riesgo alto por ADN consultora | Plantillas por tipo de expediente (existen — HECHO); "no" por defecto a features de un solo cliente; Enterprise paga roadmap, no excepciones |
| Informes hechos por consultores "para quedar bien" | Riesgo del piloto | El informe lo genera el producto en la sesión con el cliente delante; el analista OPN solo revisa si el servicio está contratado |
| IA ilimitada | Contenida por diseño — HECHO (política por tenant, presupuestos, ledger) | Exponer cupos por plan (P1); alerta de consumo al 80% |
| Señales caras (prensa de pago futura) | No aplica hoy (fuentes públicas) | Cuando llegue: conector premium cobrado aparte, nunca incluido |
| On-premise | Pedirán en Enterprise | Solo con sobreprecio (≥1,5×) y mínimo anual; nunca en Essential/Professional |
| Soporte no tarifado | Riesgo medio | Horas incluidas por plan definidas en contrato |
| Ciclos largos enterprise | Evitados por ICP | Mantener disciplina: no perseguir logos grandes año 1 |
| Dependencia de terceros | Signal Avanza es interno (mitigado); PLACSP/BORME son fuentes públicas estables | Contabilizar coste interno de Signal por tenant; vigilar cambios de formato de fuentes |

## 6. Punto de equilibrio (HIPÓTESIS)

Con coste fijo actual mínimo (infra ~200-400 €/mes + herramientas), el negocio es caja-positiva casi desde el primer cliente **si el tiempo del fundador no se contabiliza**. El punto de equilibrio real (cubrir un salario de mercado del fundador, ~70-90 K€) llega con **~8-12 clientes Professional o equivalente** (≈100-130 K€ de ingresos anuales mixtos) — alcanzable en 18-24 meses en el escenario base. Contratar a la primera persona (implantación/soporte) tiene sentido a partir de ~10 clientes o cuando los servicios gestionados superen ~4.000 €/mes recurrentes.
