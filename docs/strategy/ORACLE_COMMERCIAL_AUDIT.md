# OPN Oracle — Auditoría estratégica y comercial

Diagnóstico sin complacencia desde las cinco perspectivas exigidas. Etiquetas: HECHO / HIPÓTESIS / INFERENCIA / RECOMENDACIÓN.

> **ACTUALIZACIÓN 2026-08-07.** La scorecard conserva el diagnóstico histórico, pero la brecha de activos ya no es “cero material”: la rama de consolidación incorpora [one-pager](ORACLE_ONE_PAGER_HONESTO.md), [demo](ORACLE_DEMO_SCRIPT.md), [propuesta de piloto](ORACLE_PROPUESTA_PILOTO.md) y [calculadora ROI](ORACLE_ROI_CALCULATOR.html). Estado: **VERSIONADO PARA REVISIÓN** tras auditoría técnica independiente; pendiente de aprobación y publicación. No están aprobados ni publicados; pricing, identidad contractual y condiciones permanecen **POR CONFIRMAR**.

---

## 1. Scorecard

| Dimensión | Nota 0-10 | Evidencia | Brecha | Acción |
|---|---:|---|---|---|
| Valor potencial | 7 | HECHO DE REPOSITORIO: pipeline señal→oportunidad/riesgo→decisión→informe y conectores PLACSP/BORME; la referencia histórica a un usuario externo (IACELL) debe revalidarse | El valor existe pero nadie lo ha traducido a euros para un comprador concreto | Business case tipo con tres entradas verificables: horas actuales, resultado operativo y coste total aprobado del primer año |
| Claridad del problema | 4 | HECHO: la memoria de producto enumera 5 dolores genéricos ("dispersión", "baja anticipación") sin coste ni comprador | "Información dispersa" no es una partida presupuestaria | Reformular sobre los 3 problemas de alto valor (§ [gap analysis](ORACLE_PRODUCT_GAP_ANALYSIS.md) y [propuesta de valor](ORACLE_VALUE_PROPOSITION.md)) |
| Diferenciación | 6 | HECHO ACOTADO: en la evaluación registrada de 45 afirmaciones no se detectaron citas inventadas; existen grafo BORME e inteligencia de adjudicaciones con UTEs. Que ningún competidor español reúna la misma combinación sigue siendo una hipótesis de mercado | Diferenciación real pero no comunicada; el revisor semántico afecta solo los recorridos que usan informe de entidad | Comunicar la trazabilidad con la muestra y fecha de medición; no convertir 45/45 en garantía universal; resolver p63 antes de mostrar informe de entidad |
| Facilidad de venta | 5 | HECHO 2026-08-07: one-pager, demo, propuesta y calculadora versionados y auditados técnicamente; pricing y condiciones no aprobados | Falta validar el mensaje con compradores, emitir una oferta autorizada y crear un caso de referencia | Aprobar los activos; completar campos por confirmar solo con autorización; medir conversión |
| Adopción | 5 | HECHO: flujos reales y cuidados (triaje con ETag, wizard con prefill, digest); INFERENCIA: tenant nuevo arranca vacío hasta configurar monitores | Cold start; el hábito diario depende de que lleguen señales relevantes | Onboarding que precarga PLACSP/BORME del propio cliente el día 1; digest semanal por email como gancho de retorno |
| Escalabilidad | 6 | HECHO: multi-tenant con RLS, seeds idempotentes, releases inmutables con rollback | Onboarding manual; operación y desarrollo en una sola persona; host de 3,7 GiB | Onboarding plantillado por tipo de expediente; runbook delegable; dimensionar infra por tenant |
| Rentabilidad | 7 | HIPÓTESIS A MEDIR: la IA puede operar con proveedor local o gobernado por Signal; el coste real depende de proveedor, uso y un ACV todavía **POR CONFIRMAR** | El riesgo de margen incluye trabajo manual no tarifado, personalización y consumo externo sin límites | Medir ledger y coste de servicio antes de afirmar margen; tarificar implantación y servicios; límites de consumo por plan |
| Preparación enterprise | 5 | HECHO: RLS, RBAC, auditoría, CSRF, Argon2, backups con restore validado; HECHO: sin SSO/SAML/OIDC, sin ENS, readiness formal "NO production ready", NO-GO vigente en v0.1.0-rc.1 | SSO es la brecha nº1 para enterprise; ENS lo será para AAPP | No construir SSO todavía (RECOMENDACIÓN): venderlo como hito de Enterprise cuando un contrato lo pague |
| Riesgo de sobreconstrucción | 3 (riesgo alto) | HECHO: 46 prompts de iteración post-MVP, 198 commits/10 días, cero ventas; prompt 63 rompió producción persiguiendo un control que quizá sobra | El producto se perfecciona sin validación de mercado | Congelar funcionalidad no ligada a venta (condición 5 del [veredicto](ORACLE_EXECUTIVE_VERDICT.md)) |

**Media no ponderada: 5,1/10.** El patrón es inequívoco: notas de producto/tecnología altas, notas comerciales bajas. Es el perfil clásico de founder técnico sin motor de venta — recuperable, porque construir material comercial cuesta semanas y construir este producto habría costado años.

---

## 2. Perspectiva del comprador económico

- **Quién firma** — INFERENCIA: en el ICP recomendado (empresa española 50-1.000 empleados que licita al sector público), firma el/la director/a de desarrollo de negocio o el/la director/a general; en consultoras, el socio. No es una compra de IT: IT solo veta.
- **Partida presupuestaria** — HIPÓTESIS: "herramientas comerciales / inteligencia de mercado" o directamente el presupuesto de preparación de ofertas. La investigación histórica aporta referencias de mercado, pero el precio de Oracle y cualquier ahorro atribuible permanecen **POR CONFIRMAR** y deben justificarse con la línea base del cliente.
- **Urgencia** — HECHO (mercado): los presupuestos de CI crecen ~24% interanual y el 62% de empresas prevé aumentar gasto; HIPÓTESIS: en España la urgencia real la marca el calendario de licitaciones — cada semana sin vigilancia son concursos no vistos.
- **Riesgo de no comprar** — seguir dependiendo de alertas de correo (Tendios/Licitaciones.es), Excel y la memoria de dos personas; rotación de personal = pérdida de memoria de cuenta (dolor documentado en la propia memoria de producto).
- **Resultado medible que espera** — nº de licitaciones/convocatorias relevantes detectadas y analizadas, tiempo de preparación de informe de competidor/adjudicatario (de días a minutos), asistencia a reuniones con briefing.

## 3. Perspectiva del usuario diario

- **Tarea que sustituye** — HECHO (por diseño del producto): triaje manual de alertas, búsquedas en PLACSP/BORME a mano, montaje de informes en Word, reconstrucción de contexto antes de reuniones.
- **Frecuencia** — objetivo realista: 2-3 sesiones/semana del analista + digest semanal para el directivo. No es (ni debe venderse como) herramienta de uso horario tipo CRM.
- **Qué ve primero** — hoy: dashboard de cartera. RECOMENDACIÓN: "Qué ha cambiado" debe ser la puerta de entrada del usuario recurrente (ya existe con badge de no leídos — HECHO).
- **Por qué volvería mañana** — porque han llegado señales nuevas triadas y explicadas. Ahí está el riesgo: sin monitores bien configurados no llega nada. El onboarding decide la retención.

## 4. Perspectiva de tecnología, seguridad y cumplimiento

- **Objeciones que aparecerán** — La respuesta autorizada es: «OPN Oracle dispone de controles de producto verificables en repositorio (aislamiento multi-tenant, RBAC, auditoría, auth con contraseña fuerte, exports con caducidad). La aptitud para un entorno productivo concreto depende del despliegue, de los features habilitados y del contrato. No afirmamos certificación ISO/SOC/ENS ni readiness global de producción sin evidencia de ese entorno». La IA está deshabilitada por defecto; si se habilita, Oracle enruta mediante Signal y proveedor, residencia y tratamiento deben confirmarse para ese entorno. SSO/ENS no se ofrecen como capacidades presentes; DPA/RGPD requiere documentación y revisión jurídica cliente-facing.
- **Integraciones obligatorias** — para el ICP inicial, ninguna dura: el valor entra por fuentes públicas (PLACSP, BORME) y Signal. Email saliente ya existe (Microsoft Graph). CRM/Teams son P1-P2, no bloqueo de venta inicial (HIPÓTESIS).
- **Trazabilidad** — punto fuerte real y verificable: AIAuditLog con prompt/modelo/hashes/coste, controles de evidencia y feedback humano (HECHO). Ayuda a responder la objeción «la IA se lo inventa», pero no garantiza corrección universal.

## 5. Perspectiva del equipo comercial de OPN

- **¿Explicable en 30 s?** Hoy no (tesis abstracta). Con el pivot de posicionamiento, sí — ver [propuesta de valor](ORACLE_VALUE_PROPOSITION.md).
- **¿Demostrable en 15 min?** Sí, con la demo canónica contratación → fijación → PCAP → encaje → borrador editable → DOCX → seguimiento descrita en el [guion](ORACLE_DEMO_SCRIPT.md). Exige humo completo en Oracle Dev antes de cada reunión. El prompt 63 bloquea solo una demo alternativa que incluya el informe de entidad; no bloquea este recorrido canónico.
- **¿Vendible sin meses de consultoría previa?** Solo si el onboarding se empaqueta (plantillas por tipo de expediente ya existen — HECHO) y el piloto tiene alcance cerrado.
- **Pruebas para cerrar** — un caso de referencia con métricas (IACELL es el candidato), la demo con datos del prospecto y evidencia acotada con muestra, fecha y entorno.

## 6. Perspectiva del propietario / inversor

- **¿Escala?** La plataforma sí (multi-tenant real); el negocio hoy no (todo pasa por el fundador). La palanca es estandarizar onboarding y demo.
- **¿Ingresos recurrentes?** Diseñables desde ya; no existe aún el primer euro (HECHO).
- **Costes que amenazan el margen** — por orden real de riesgo: (1) tiempo del fundador en implantaciones y soporte no tarifados, (2) personalización por cliente, (3) fuentes de datos de pago futuras (prensa), (4) IA cloud si se generaliza sin límites. Los cuatro tienen control conocido (ver [unit economics](ORACLE_UNIT_ECONOMICS.md)).
- **¿Expansión por cuenta?** Sí: más expedientes, más usuarios, más monitores, servicios de analista. El modelo de precios debe dejar espacio (límites por plan).
- **¿Ventaja defendible?** En construcción: memoria acumulada por expediente + evidencia auditada + fuentes españolas integradas. No defendible: la UI y "usar IA". Ver [moat](ORACLE_COMPETITIVE_MOAT.md).

---

## 7. Conclusión de la auditoría

El proyecto tiene una base de producto y controles verificables, pero la aptitud productiva concreta, el coste de servicio, el precio, el contrato y la validación con compradores siguen abiertos. La consecuencia práctica es priorizar validación comercial, empaquetado de onboarding y fiabilidad del recorrido que vaya a demostrarse. El prompt 63 es condición únicamente para demos que incluyan el informe de entidad; el recorrido canónico de contratación se gobierna por su propio humo.
