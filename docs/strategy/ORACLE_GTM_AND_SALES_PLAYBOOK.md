# OPN Oracle — Estrategia comercial y playbook de ventas

Objetivo: que Oracle se venda como producto con proceso repetible, no como consultoría artesanal. Etiquetas: HECHO / HIPÓTESIS / RECOMENDACIÓN.

> **Estado 2026-08-07:** los cuatro activos P0 de la tabla están **VERSIONADOS PARA REVISIÓN** tras auditoría técnica independiente; quedan pendientes de aprobación antes de publicarlos o usarlos con clientes. Precio, duración, alcance, forma de pago, descuentos, servicios incluidos e identidad contractual siguen **POR CONFIRMAR** hasta autorización escrita del propietario.

---

## 1. Proceso de venta completo

1. **Selección de cuenta** — Lista de 30 cuentas: clientes y ex-clientes de consultoría de OPN + empresas que licitan recurrentemente en los sectores donde OPN tiene red (energía/industrial/servicios). Criterios ICP: ≥10 ofertas públicas/año o ≥5 cuentas estratégicas, ≥1 persona de BD/ofertas, sin herramienta de CI.
2. **Señal de compra** — Concurso perdido reciente, rotación en ofertas, expansión geográfica, queja sobre ruido de alertas. Fuente: la propia red + PLACSP (Oracle vigilando a sus prospectos: dogfooding y argumento de venta a la vez).
3. **Contacto** — Correo/llamada del fundador con un **regalo de valor**: la ficha 360º de un competidor del prospecto + las 5 últimas adjudicaciones de su sector. Coste: 15 min de trabajo con el propio producto. (Este es el activo que sustituye al SDR que no hay.)
4. **Discovery (30 min)** — Guion abajo. Salida: dolor priorizado, mapa de compra, criterios go/no-go del piloto.
5. **Demo (15 min)** — Recorrido canónico contratación → fijación → PCAP → encaje → borrador → DOCX → seguimiento, descrito en [ORACLE_DEMO_SCRIPT.md](ORACLE_DEMO_SCRIPT.md), con datos públicos reales del prospecto y humo previo en Oracle Dev. Una demo distinta que incluya informe de entidad requiere además cerrar p63 y registrar su validación específica.
6. **Business case** — Una página: horas anuales del proceso actual, beneficio anual modelizado y coste total aprobado del primer año. No comparar el coste de un piloto corto con un beneficio anual ni imputar una adjudicación futura sin evidencia.
7. **Piloto pagado** — Precio, duración, alcance, criterios de éxito, forma de pago y fecha de decisión **POR CONFIRMAR** en una propuesta autorizada por escrito.
8. **Seguridad y compras** — Preparar una versión cliente a partir de la evidencia técnica, usando exclusivamente este alcance: «OPN Oracle dispone de controles de producto verificables en repositorio (aislamiento multi-tenant, RBAC, auditoría, auth con contraseña fuerte, exports con caducidad). La aptitud para un entorno productivo concreto depende del despliegue, de los features habilitados y del contrato. No afirmamos certificación ISO/SOC/ENS ni readiness global de producción sin evidencia de ese entorno». La IA está deshabilitada por defecto; si se habilita, Oracle enruta mediante Signal y proveedor, residencia y tratamiento deben confirmarse para ese entorno.
9. **Contrato** — Duración, pago, renovación, DPA, soporte, SLA, referencias y descuentos **POR CONFIRMAR**; no ofrecer condiciones por inferencia.
10. **Implantación** — Alcance, duración, entregables y tarifa **POR CONFIRMAR**. La plantilla puede incluir expedientes, monitores y formación, pero solo lo aprobado en la propuesta final.
11. **Adopción** — Ritual del lunes: digest + revisión de "Qué ha cambiado" en la reunión de equipo del cliente. Check-in quincenal el primer trimestre.
12. **Renovación y expansión** — QBR al mes 9 con métricas de uso (informes generados, licitaciones detectadas, decisiones registradas); propuesta de expansión (expedientes/analista).

## 2. Guion de discovery (preguntas de diagnóstico)

1. "¿Cuántas ofertas públicas presentasteis el año pasado? ¿Cuántas visteis tarde o descartasteis por falta de tiempo de análisis?"
2. "¿Cómo os enteráis hoy de una licitación? ¿Quién filtra ese correo y cuánto tarda?"
3. "Cuando un competidor gana un concurso que queríais, ¿qué sabéis de él? ¿Quién lo investiga y cuánto tarda?"
4. "¿Qué pasó la última vez que se fue alguien del equipo de ofertas/BD? ¿Qué se perdió?"
5. "¿Cómo se prepara hoy un comité de ofertas? ¿Quién hace el informe y cuántas horas lleva?"
6. "Si mañana detectarais una convocatoria perfecta con 10 días de plazo, ¿llegaríais?"
7. Calificación: presupuesto ("¿tenéis partida para herramientas comerciales?"), autoridad ("¿quién decidiría esto?"), timing ("¿qué concursos importantes vienen este semestre?").

**Criterios go/no-go del deal:** GO si (dolor confesado en 1-3) + (acceso al decisor) + (≥10 ofertas/año o equivalente). NO-GO si quieren desarrollo a medida, si no licitan ni gestionan cuentas complejas, o si esperan piloto gratis.

## 3. Calculadora de ROI (estructura)

```text
A. Horas/semana de vigilancia y filtrado × 46 semanas × coste/hora
B. Informes de entidad/competidor al año × horas/informe × coste/hora
C. Comités al año × horas/comité × coste/hora
D. Contribución adicional demostrable (base = 0; no atribuir adjudicaciones hipotéticas)
Beneficio anual modelizado = A + B + C + D
vs Coste total aprobado del primer año = licencia + implantación + servicios + costes externos aplicables
Regla de presentación: beneficio y coste deben cubrir el mismo primer año; D solo entra con evidencia aceptada por el cliente.
```

Ejemplo exclusivamente ilustrativo de volumen: 4 h/semana × 46 + 10 informes × 4 h + 12 comités × 8 h = **320 h/año**. Su valor monetario depende del coste/hora aceptado por el cliente y no acredita ahorro, precio, plan ni cobertura de Oracle.

## 4. Activos comerciales necesarios (los que hacen la venta no-fundador-dependiente)

| Activo | Estado | Prioridad |
|---|---|---|
| [One-pager honesto](ORACLE_ONE_PAGER_HONESTO.md) | Versionado y auditado técnicamente; pendiente de aprobación y publicación | P0 listo para revisión |
| [Guion de demo 15'](ORACLE_DEMO_SCRIPT.md) | Preparado en worktree; humo Dev obligatorio antes de cada demo | P0 listo para revisión y ensayo |
| [Plantilla de propuesta de piloto](ORACLE_PROPUESTA_PILOTO.md) | Preparada en worktree; campos contractuales POR CONFIRMAR | P0 pendiente de completar, revisar y aprobar |
| [Calculadora ROI autónoma](ORACLE_ROI_CALCULATOR.html) | Preparada en worktree; coste del primer año vacío y sin promesa de adjudicación | P0 pendiente de revisión antes de discovery |
| Dossier de seguridad cliente-facing | Contenido existe en docs/security (HECHO); falta redacción cliente | P1, semana 3-4 |
| Landing pública con pricing | No existe | P1, semana 3-6 |
| Caso de referencia con métricas (IACELL) | Por construir durante el piloto | P0, semanas 8-12 |
| Vídeo demo 3' | No existe | P1 |

## 5. Plan para los tres primeros clientes

1. **IACELL** (referencia histórica de uso; debe revalidarse): proponer por escrito una formalización como piloto o contrato. Precio, plan, duración y cualquier contraprestación por referencia quedan **POR CONFIRMAR**. Objetivo: contrato autorizado + caso de éxito con métricas verificadas en 90 días.
2. **Cliente 2 — de la red de consultoría de OPN**: empresa industrial/servicios que licita, con relación previa. Entrada por el "regalo de valor" (ficha de competidor). Objetivo: piloto firmado en 45 días.
3. **Cliente 3 — consultora/despacho amigo**: valida el segmento secundario y el multi-expediente. Objetivo: piloto en 60-90 días.

**Convertir el primero en referencia:** acordar por escrito logo, cita autorizada, tres métricas verificables y disponibilidad para llamadas de referencia. Cualquier descuento o contraprestación requiere aprobación expresa en la propuesta final; publicar solo con consentimiento.

## 6. Cómo evitar que Oracle se venda como consultoría artesanal

- El piloto tiene **alcance cerrado y fecha de decisión**; todo lo extra se presupuesta.
- La demo la hace **el producto**, no un PowerPoint: mismo guion siempre, datos del prospecto, cero funciones "en beta" en pantalla.
- **Ninguna feature comprometida en una venta** sin pasar por el filtro: ¿la pagaría un segundo cliente? Si no, es servicio tarifado o es no.
- Cualquier servicio de analista debe describirse con alcance, horas, responsable y tarifa **POR CONFIRMAR**; no presentarlo como incluido ni como ya comercializado sin una oferta aprobada.
- Métrica de control mensual: % de ingresos por software vs servicios. Objetivo: software >50% desde el mes 12.
