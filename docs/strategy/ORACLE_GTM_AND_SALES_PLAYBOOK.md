# OPN Oracle — Estrategia comercial y playbook de ventas

Objetivo: que Oracle se venda como producto con proceso repetible, no como consultoría artesanal. Etiquetas: HECHO / HIPÓTESIS / RECOMENDACIÓN.

---

## 1. Proceso de venta completo

1. **Selección de cuenta** — Lista de 30 cuentas: clientes y ex-clientes de consultoría de OPN + empresas que licitan recurrentemente en los sectores donde OPN tiene red (energía/industrial/servicios). Criterios ICP: ≥10 ofertas públicas/año o ≥5 cuentas estratégicas, ≥1 persona de BD/ofertas, sin herramienta de CI.
2. **Señal de compra** — Concurso perdido reciente, rotación en ofertas, expansión geográfica, queja sobre ruido de alertas. Fuente: la propia red + PLACSP (Oracle vigilando a sus prospectos: dogfooding y argumento de venta a la vez).
3. **Contacto** — Correo/llamada del fundador con un **regalo de valor**: la ficha 360º de un competidor del prospecto + las 5 últimas adjudicaciones de su sector. Coste: 15 min de trabajo con el propio producto. (Este es el activo que sustituye al SDR que no hay.)
4. **Discovery (30 min)** — Guion abajo. Salida: dolor priorizado, mapa de compra, criterios go/no-go del piloto.
5. **Demo (15 o 45 min)** — Guion en [ORACLE_DEMO_SCRIPT.md](ORACLE_DEMO_SCRIPT.md), con datos públicos reales del prospecto.
6. **Business case** — Una página: horas de analista actuales vs con Oracle, valor de 1 licitación detectada, precio del piloto y del año 1. Calculadora abajo.
7. **Piloto pagado** — 4.500 € / 8 semanas, criterios de éxito escritos, fecha de decisión en contrato (ver [pricing](ORACLE_PRICING_AND_PACKAGING.md)).
8. **Seguridad y compras** — Dossier técnico preempaquetado (una vez, reutilizable): arquitectura, aislamiento por tenant, IA local, RGPD/DPA, backups. HECHO: el contenido técnico existe en `docs/security/`; falta la versión cliente.
9. **Contrato** — Anual, pago anticipado, descuento máx. 15% solo por referencia pública.
10. **Implantación** — Estándar 4 semanas, plantillada (3-5 expedientes, monitores, formación). Tarifada siempre.
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
A. Horas/semana en vigilancia + filtrado de alertas        × coste/hora analista
B. Informes de entidad o competidor al año × horas each    × coste/hora
C. Informes de comité al año × horas                        × coste/hora
D. Valor esperado de 1 licitación adicional detectada       (importe medio × margen × prob.)
Ahorro anual = (A+B+C) × 46 semanas + D
vs Coste Oracle año 1 = piloto/implantación + suscripción
Regla de presentación: ignorar D en el cálculo base (credibilidad); mencionarlo como upside.
```

HIPÓTESIS típica mid-market: A≈4h, B≈10×4h, C≈12×8h → ~10-14 K€/año de coste analista sustituible, sin contar D. Cubre Essential y Professional.

## 4. Activos comerciales necesarios (los que hacen la venta no-fundador-dependiente)

| Activo | Estado | Prioridad |
|---|---|---|
| One-pager (problema/solución/precio/prueba) | No existe | P0, semana 1 |
| Guion de demo 15' + entorno de demo con datos reales públicos | No existe (producto sí) | P0, semana 1-2 |
| Plantilla de propuesta de piloto (con criterios de éxito) | No existe | P0, semana 2 |
| Calculadora ROI (hoja de cálculo) | No existe | P0, semana 2 |
| Dossier de seguridad cliente-facing | Contenido existe en docs/security (HECHO); falta redacción cliente | P1, semana 3-4 |
| Landing pública con pricing | No existe | P1, semana 3-6 |
| Caso de referencia con métricas (IACELL) | Por construir durante el piloto | P0, semanas 8-12 |
| Vídeo demo 3' | No existe | P1 |

## 5. Plan para los tres primeros clientes

1. **IACELL** (ya usuario — HECHO): convertir el uso actual en piloto formal pagado o directamente en contrato Essential/Professional con precio fundador (-15% por referencia). Objetivo: contrato + caso de éxito con métricas en 90 días.
2. **Cliente 2 — de la red de consultoría de OPN**: empresa industrial/servicios que licita, con relación previa. Entrada por el "regalo de valor" (ficha de competidor). Objetivo: piloto firmado en 45 días.
3. **Cliente 3 — consultora/despacho amigo**: valida el segmento secundario y el multi-expediente. Objetivo: piloto en 60-90 días.

**Convertir el primero en referencia:** acordar por escrito (a cambio del descuento): logo, cita del director, 3 métricas del piloto, disponibilidad para 2 llamadas de referencia. Publicar el caso en la landing y usarlo en cada propuesta.

## 6. Cómo evitar que Oracle se venda como consultoría artesanal

- El piloto tiene **alcance cerrado y fecha de decisión**; todo lo extra se presupuesta.
- La demo la hace **el producto**, no un PowerPoint: mismo guion siempre, datos del prospecto, cero funciones "en beta" en pantalla.
- **Ninguna feature comprometida en una venta** sin pasar por el filtro: ¿la pagaría un segundo cliente? Si no, es servicio tarifado o es no.
- Los servicios de analista existen y se venden — **con tarifa y horas**, nunca "incluidos".
- Métrica de control mensual: % de ingresos por software vs servicios. Objetivo: software >50% desde el mes 12.
