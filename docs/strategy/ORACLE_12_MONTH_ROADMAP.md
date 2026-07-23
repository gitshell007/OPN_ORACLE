# OPN Oracle — Roadmap 12 meses comercialmente disciplinado

Regla de admisión: cada iniciativa se prioriza por impacto en venta, tiempo hasta valor, retención, expansión o margen — nunca por atractivo técnico. Formato por iniciativa: objetivo comercial · usuario · resultado · KPI · dependencia · esfuerzo (S/M/L) · riesgo · criterio de finalización.

---

## 0-30 días — "Preparar la venta" (casi todo es NO-código)

1. **Estabilizar informe de entidad (decisión p63)** · demo/piloto · analista · informe genera al primer intento · 10/10 generaciones OK en prod · decisión pendiente D-p63 (recomendada: opción 3, retirar revisor semántico de la ruta; mantener validación estructural) · S · riesgo bajo · criterio: 10 informes seguidos sin fallo + STATUS actualizado.
2. **Posicionamiento y mensajes** (docs de propuesta de valor → one-pager + pitch) · venta · fundador · activos listos · usados en ≥5 conversaciones · ninguna · S · — · criterio: one-pager v1 enviado a 5 cuentas.
3. **Entorno y guion de demo** · venta · fundador (luego cualquiera) · demo 15' reproducible · 2 demos ensayadas grabadas · iniciativa 1 · S · — · criterio: vídeo interno de referencia grabado.
4. **Pricing publicado + plantilla de propuesta de piloto** · venta · fundador · 3 propuestas emitibles · propuesta IACELL enviada · ninguna · S · — · criterio: propuesta 1 enviada.
5. **Conversión IACELL** (uso actual → piloto/contrato) · ingresos · IACELL · primer dinero · contrato o piloto firmado · 1-4 · S · riesgo: expectativas no gestionadas · criterio: firma.

## 31-60 días — "Vender y activar"

6. **PDF de informes** · percepción de entregable en comité · directivo cliente · informe descargable maquetado · usado en ≥1 comité real de cliente · `REPORT_PDF_MODE` (renderer deshabilitado hoy — HECHO) · M · riesgo bajo · criterio: PDF de informe ejecutivo y competitivo en prod.
7. **Digest semanal por email** · retención (ritual del lunes) · todos los usuarios · el digest llega sin entrar en la app · ≥60% apertura en pilotos · Graph ya integrado (HECHO) · S-M · — · criterio: envío semanal activo por tenant opt-in.
8. **Onboarding empaquetado anti-cold-start** · adopción piloto · analista cliente · día 1 con PLACSP/BORME del cliente cargados · time-to-first-value <1 día · plantillas existentes · M · riesgo: convertirse en consultoría — plantillar · criterio: runbook de implantación ejecutado en piloto 2 sin improvisar.
9. **2 pilotos más firmados** (red OPN + consultora) · ingresos · — · 3 pilotos activos · firmas · activos 2-4 · — · riesgo: ciclos más largos de lo previsto · criterio: firmas.
10. **Dossier de seguridad cliente-facing** · desbloquear compras · IT del cliente · documento reutilizable · 0 deals parados por seguridad · contenido en docs/security (HECHO) · S · — · criterio: v1 enviada a un cliente.

## 61-90 días — "Convertir y aprender"

11. **Cupos comerciales visibles** (exponer ledger IA/señales como límites por plan) · margen · admin cliente · consumo visible y limitado · 0 clientes fuera de fair-use sin conversación de expansión · ledger existente (HECHO) · M · — · criterio: límites activos por plan en prod.
12. **Caso de referencia IACELL** (métricas del piloto) · venta · — · caso publicable · usado en 100% de propuestas nuevas · piloto en curso · S · riesgo: cliente no acepta publicidad — negociado en el descuento · criterio: caso con 3 métricas aprobado por el cliente.
13. **Decisión de conversión de los 3 pilotos** · ingresos · — · ≥1 contrato anual · ARR ≥ 12 K€ · pilotos · — · — · criterio: decisiones registradas en semana 9 de cada piloto.
14. **Retirada de Horizon + limpieza de escaparate A/B** · foco/margen (menos superficie que mantener) · interno · repo simplificado · — · migración documentada (prevista en AGENTS.md) · S · bajo · criterio: `/concept-b` eliminado con tests verdes.

## Meses 4-6 — "Repetir sin el fundador"

15. **Plantilla go/no-go de licitación** (informe de convocatoria con encaje y decisión) · venta+retención (profundiza la cuña) · responsable de ofertas · decisión go/no-go documentada por concurso · ≥2 go/no-go por cliente/mes · plantillas de informe (HECHO base) · M · — · criterio: plantilla en prod usada por 2 clientes.
16. **Landing pública con pricing y caso** · pipeline entrante · — · primeras leads inbound · ≥5 conversaciones inbound/trimestre · caso de referencia · S · — · criterio: landing publicada.
17. **"Mis pendientes" del analista** (vista transversal de tareas/señales asignadas) · adopción diaria · analista · una pantalla de trabajo · uso ≥2 días/semana · — · M · — · criterio: en prod con telemetría de uso.
18. **Cerrar higiene operativa fase 15/16** (CI verde remoto, branch protection, copia off-host automatizada, UAT formal → levantar el NO-GO) · confianza para crecer · interno · release estable declarado GO · GO documentado · — · M · — · criterio: GO_NO_GO actualizado a GO.
19. **5-8 clientes de pago acumulados** · ingresos · — · ARR 30-50 K€ · — · todo lo anterior · — · — · criterio: contratos.

## Meses 7-12 — "Escalar lo que funciona"

20. **Detección de invalidación de hipótesis** ("este cambio contradice tu hipótesis H2") · retención/wow de renovación · analista+directivo · alerta accionable · ≥1 alerta útil/cliente/mes · hipótesis ya en modelo (HECHO) · L · riesgo de falsos positivos — empezar conservador · criterio: activo en 3 clientes con feedback positivo.
21. **Conector prensa/medios de pago (opcional, cobrado aparte)** · expansión ACV · — · señales de prensa premium · attach ≥30% en Professional · negociación de fuente · M · coste de fuente — solo si el margen lo soporta · criterio: 2 clientes pagándolo.
22. **SSO (solo si un contrato Enterprise lo paga)** · desbloqueo enterprise · IT cliente · login corporativo · contrato Enterprise firmado que lo exige · — · L · construir antes de contrato = sobreconstrucción · criterio: gated por firma.
23. **Primera contratación** (implantación/soporte/analista) · escalar sin fundador · — · fundador libera 30% de tiempo · ≥10 clientes o ≥4 K€/mes en servicios · ingresos · — · — · criterio: persona operando 2 implantaciones sola.
24. **Benchmarks agregados de contratación por sector** (moat de datos) · diferenciación/expansión · directivo cliente · informe sectorial trimestral · usado en renovaciones · ≥10 clientes · L · privacidad entre clientes — solo datos públicos agregados · criterio: primer benchmark publicado.

## Lo que NO está en el roadmap (deliberadamente)

Escenarios ideal/probable/adverso, coach de reuniones, integración Nexus/Sentinel real, comparativa entre expedientes, ENS, on-premise, integraciones CRM/Drive/Teams, modelos sectoriales — **P2 real**: solo entran si ≥2 clientes de pago los piden o un contrato los financia. El criterio del roadmap es ingresos y retención, no completar la visión original.
