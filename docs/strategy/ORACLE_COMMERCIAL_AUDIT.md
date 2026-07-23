# OPN Oracle — Auditoría estratégica y comercial

Diagnóstico sin complacencia desde las cinco perspectivas exigidas. Etiquetas: HECHO / HIPÓTESIS / INFERENCIA / RECOMENDACIÓN.

---

## 1. Scorecard

| Dimensión | Nota 0-10 | Evidencia | Brecha | Acción |
|---|---:|---|---|---|
| Valor potencial | 7 | HECHO: pipeline señal→oportunidad/riesgo→decisión→informe con evidencia real; PLACSP y BORME operativos; usuario externo real (IACELL) | El valor existe pero nadie lo ha traducido a euros para un comprador concreto | Business case tipo con 3 números: horas de analista ahorradas, licitaciones detectadas antes, coste de una oportunidad perdida |
| Claridad del problema | 4 | HECHO: la memoria de producto enumera 5 dolores genéricos ("dispersión", "baja anticipación") sin coste ni comprador | "Información dispersa" no es una partida presupuestaria | Reformular sobre los 3 problemas de alto valor (§ [gap analysis](ORACLE_PRODUCT_GAP_ANALYSIS.md) y [propuesta de valor](ORACLE_VALUE_PROPOSITION.md)) |
| Diferenciación | 6 | HECHO: evidencia auditada con validación estructural de citas (45/45/0 inventadas), grafo BORME, inteligencia de adjudicaciones con UTEs — combinación que ningún competidor español ofrece junta | Diferenciación real pero no comunicada; el revisor semántico está roto (prompt 63) | Convertir "cero citas inventadas, todo auditable" en el mensaje nº1; resolver prompt 63 |
| Facilidad de venta | 3 | HECHO: cero material comercial en el repo; pricing declarado pregunta abierta desde 2026-07-09; sin demo guionizada | Nadie salvo el fundador puede explicar el producto; la tesis genérica exige 30 min de contexto | Pitch 30 s + demo 15 min + one-pager + calculadora ROI (ver [playbook](ORACLE_GTM_AND_SALES_PLAYBOOK.md)) |
| Adopción | 5 | HECHO: flujos reales y cuidados (triaje con ETag, wizard con prefill, digest); INFERENCIA: tenant nuevo arranca vacío hasta configurar monitores | Cold start; el hábito diario depende de que lleguen señales relevantes | Onboarding que precarga PLACSP/BORME del propio cliente el día 1; digest semanal por email como gancho de retorno |
| Escalabilidad | 6 | HECHO: multi-tenant con RLS, seeds idempotentes, releases inmutables con rollback | Onboarding manual; operación y desarrollo en una sola persona; host de 3,7 GiB | Onboarding plantillado por tipo de expediente; runbook delegable; dimensionar infra por tenant |
| Rentabilidad | 7 | HECHO: coste IA ≈ 0 (Ollama local) o <5% del ACV con cloud; infra actual mínima | El riesgo de margen no es técnico: es trabajo manual del fundador no tarifado | Tarifar implantación y servicios de analista; límites de consumo por plan |
| Preparación enterprise | 5 | HECHO: RLS, RBAC, auditoría, CSRF, Argon2, backups con restore validado; HECHO: sin SSO/SAML/OIDC, sin ENS, readiness formal "NO production ready", NO-GO vigente en v0.1.0-rc.1 | SSO es la brecha nº1 para enterprise; ENS lo será para AAPP | No construir SSO todavía (RECOMENDACIÓN): venderlo como hito de Enterprise cuando un contrato lo pague |
| Riesgo de sobreconstrucción | 3 (riesgo alto) | HECHO: 46 prompts de iteración post-MVP, 198 commits/10 días, cero ventas; prompt 63 rompió producción persiguiendo un control que quizá sobra | El producto se perfecciona sin validación de mercado | Congelar funcionalidad no ligada a venta (condición 5 del [veredicto](ORACLE_EXECUTIVE_VERDICT.md)) |

**Media no ponderada: 5,1/10.** El patrón es inequívoco: notas de producto/tecnología altas, notas comerciales bajas. Es el perfil clásico de founder técnico sin motor de venta — recuperable, porque construir material comercial cuesta semanas y construir este producto habría costado años.

---

## 2. Perspectiva del comprador económico

- **Quién firma** — INFERENCIA: en el ICP recomendado (empresa española 50-1.000 empleados que licita al sector público), firma el/la director/a de desarrollo de negocio o el/la director/a general; en consultoras, el socio. No es una compra de IT: IT solo veta.
- **Partida presupuestaria** — HIPÓTESIS: "herramientas comerciales / inteligencia de mercado" o directamente el presupuesto de preparación de ofertas. Ventaja: en empresas que licitan, perder un concurso relevante cuesta cientos de miles de euros; 6.000-15.000 €/año se justifica con una sola licitación detectada a tiempo.
- **Urgencia** — HECHO (mercado): los presupuestos de CI crecen ~24% interanual y el 62% de empresas prevé aumentar gasto; HIPÓTESIS: en España la urgencia real la marca el calendario de licitaciones — cada semana sin vigilancia son concursos no vistos.
- **Riesgo de no comprar** — seguir dependiendo de alertas de correo (Tendios/Licitaciones.es), Excel y la memoria de dos personas; rotación de personal = pérdida de memoria de cuenta (dolor documentado en la propia memoria de producto).
- **Resultado medible que espera** — nº de licitaciones/convocatorias relevantes detectadas y analizadas, tiempo de preparación de informe de competidor/adjudicatario (de días a minutos), asistencia a reuniones con briefing.

## 3. Perspectiva del usuario diario

- **Tarea que sustituye** — HECHO (por diseño del producto): triaje manual de alertas, búsquedas en PLACSP/BORME a mano, montaje de informes en Word, reconstrucción de contexto antes de reuniones.
- **Frecuencia** — objetivo realista: 2-3 sesiones/semana del analista + digest semanal para el directivo. No es (ni debe venderse como) herramienta de uso horario tipo CRM.
- **Qué ve primero** — hoy: dashboard de cartera. RECOMENDACIÓN: "Qué ha cambiado" debe ser la puerta de entrada del usuario recurrente (ya existe con badge de no leídos — HECHO).
- **Por qué volvería mañana** — porque han llegado señales nuevas triadas y explicadas. Ahí está el riesgo: sin monitores bien configurados no llega nada. El onboarding decide la retención.

## 4. Perspectiva de tecnología, seguridad y cumplimiento

- **Objeciones que aparecerán** — "¿dónde están mis datos?" (respuesta fuerte: servidor propio en infraestructura OPN, PostgreSQL no expuesto, IA local sin salida a cloud por defecto — HECHO); "¿SSO?" (no hay — HECHO); "¿ENS?" (no hay; necesario solo para vender a AAPP — pregunta abierta declarada); "¿DPA/RGPD?" (falta paquete documental cliente-facing, aunque la base técnica es sólida).
- **Integraciones obligatorias** — para el ICP inicial, ninguna dura: el valor entra por fuentes públicas (PLACSP, BORME) y Signal. Email saliente ya existe (Microsoft Graph). CRM/Teams son P1-P2, no bloqueo de venta inicial (HIPÓTESIS).
- **Trazabilidad** — punto fuerte real y verificable: AIAuditLog con prompt/modelo/hashes/coste, evidencia obligatoria, feedback humano (HECHO). Es el argumento que desarma la objeción "la IA se lo inventa".

## 5. Perspectiva del equipo comercial de OPN

- **¿Explicable en 30 s?** Hoy no (tesis abstracta). Con el pivot de posicionamiento, sí — ver [propuesta de valor](ORACLE_VALUE_PROPOSITION.md).
- **¿Demostrable en 15 min?** Sí, con la secuencia entidad→adjudicaciones→señal→informe usando datos públicos reales del propio prospecto (ITURRI/Iberdrola demuestran que funciona — HECHO). Guion en [demo script](ORACLE_DEMO_SCRIPT.md). Condición: nada roto en pantalla (prompt 63).
- **¿Vendible sin meses de consultoría previa?** Solo si el onboarding se empaqueta (plantillas por tipo de expediente ya existen — HECHO) y el piloto tiene alcance cerrado.
- **Pruebas para cerrar** — un caso de referencia con métricas (IACELL es el candidato), la demo con datos del prospecto y el argumento de evidencia auditada.

## 6. Perspectiva del propietario / inversor

- **¿Escala?** La plataforma sí (multi-tenant real); el negocio hoy no (todo pasa por el fundador). La palanca es estandarizar onboarding y demo.
- **¿Ingresos recurrentes?** Diseñables desde ya; no existe aún el primer euro (HECHO).
- **Costes que amenazan el margen** — por orden real de riesgo: (1) tiempo del fundador en implantaciones y soporte no tarifados, (2) personalización por cliente, (3) fuentes de datos de pago futuras (prensa), (4) IA cloud si se generaliza sin límites. Los cuatro tienen control conocido (ver [unit economics](ORACLE_UNIT_ECONOMICS.md)).
- **¿Expansión por cuenta?** Sí: más expedientes, más usuarios, más monitores, servicios de analista. El modelo de precios debe dejar espacio (límites por plan).
- **¿Ventaja defendible?** En construcción: memoria acumulada por expediente + evidencia auditada + fuentes españolas integradas. No defendible: la UI y "usar IA". Ver [moat](ORACLE_COMPETITIVE_MOAT.md).

---

## 7. Conclusión de la auditoría

El proyecto está **invertido al revés de lo habitual**: tiene lo difícil (producto real, seguro, barato de operar) y le falta lo "fácil" (mensaje, precio, demo, primer cliente de pago). La consecuencia práctica es que los próximos 90 días deben gastarse en comercial casi al 100%, usando el producto tal cual está — con la única excepción de estabilizar el informe de entidad (prompt 63) y empaquetar el onboarding. Cualquier otra línea de código es procrastinación con aspecto de progreso.
