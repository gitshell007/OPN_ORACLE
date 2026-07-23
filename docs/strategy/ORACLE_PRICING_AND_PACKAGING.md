# OPN Oracle — Pricing y packaging

Base de mercado (HECHO, con fuentes en la investigación): CI mid-market 15-40 K$/año (Crayon, Klue, Contify); suelo transparente Feedly ~19,2 K$/año; media monitoring mediana 25 K$; stakeholder mgmt entrada ~9-12 K€; herramientas de licitaciones españolas 0,6-6 K€/año (categoría de bajo precio a evitar como ancla); Copilot 30 $/usuario/mes como "competidor mental". España paga ~20-30% menos que el benchmark US (HIPÓTESIS). Coste LLM <5% del ACV; con Ollama local ≈ 0 (HECHO).

**Principio rector:** no vender por debajo de ~500 €/mes — te ancla en la categoría "alertas". No vender por usuario como métrica principal — castiga la adopción que necesitamos para retener.

---

## 1. Comparativa de modelos de cobro

| Modelo | Veredicto | Razón |
|---|---|---|
| Por usuario | Secundario | Frena invitar al directivo/equipo; el valor no escala con seats |
| **Por expediente activo** | **Principal** | Alinea precio con valor (proyectos importantes), fácil de entender, expande naturalmente |
| Por volumen de señales | Solo como límite | Métrica interna, no de valor; usar como fair-use por plan |
| Por workspace/tenant (tarifa plana por tramos) | **Envoltorio** | El plan fija tramo de expedientes+usuarios+consumo |
| Por conectores/módulos | P1 | PLACSP/BORME incluidos (son el gancho); conectores premium futuros (prensa de pago, CRM) sí se cobran aparte |
| Licencia + implantación | **Sí** | La implantación se cobra siempre (defensa del margen y del tiempo del fundador) |
| Servicio de inteligencia gestionado | **Sí, opcional** | El modelo Contify demuestra que el cliente necesita 5-10 h/semana de analista; OPN puede venderlas con margen |

## 2. Paquetes

### Oracle Essential — 590 €/mes (facturación anual: 5.900 €/año)
- Comprador: empresa mid-market que licita; primer contacto con la categoría.
- Incluye: 5 usuarios, **5 expedientes activos**, PLACSP + BORME completos, señales con triaje (fair-use: ~500 señales/mes), informes con evidencia (20 generaciones IA/mes), digest semanal, soporte por email.
- No incluye: briefings de reunión IA, informe competitivo de adjudicatario, API, SSO.
- Expansión: pack de expedientes adicionales (+5 → +150 €/mes).

### Oracle Professional — 1.290 €/mes (12.900 €/año)
- Comprador: equipos de BD/ofertas consolidados; consultoras.
- Incluye: 15 usuarios, **20 expedientes activos**, todo Essential + briefings de reunión, informes competitivos de contratación, wizard sin límites, alertas por email, 100 generaciones IA/mes, soporte prioritario, onboarding estándar incluido.
- Expansión: usuarios extra (+25 €/usuario/mes a partir de 15), expedientes (+10 → +250 €/mes).

### Oracle Enterprise — desde 30.000 €/año (a medida)
- Comprador: >1.000 empleados, regulados, o AAPP (futuro).
- Incluye: usuarios/expedientes negociados, SLA, auditoría exportable, retención personalizada, **SSO y opción on-prem/servidor dedicado como compromisos de roadmap por contrato** (HECHO: hoy no existen — venderlos como hito pagado, nunca como presente), formación, gestor de cuenta.
- Regla: no firmar Enterprise sin que el sobrecoste de sus exigencias (SSO, ENS, dedicado) esté cubierto por el precio.

### Implantación (one-off, obligatoria en Professional/Enterprise)
- Estándar: **3.500 €** — configuración de 3-5 expedientes, monitores, carga de actores, 2 sesiones de formación, 4 semanas.
- Ampliada: 6.000-12.000 € — migración de histórico, plantillas propias, formación por roles.

### Servicios gestionados opcionales (recurrente)
- **Analista OPN**: 1.500 €/mes (½ día/semana) o 2.900 €/mes (1 día/semana) — triaje curado, informes revisados, preparación de comités. Margen alto y camino natural desde la consultoría actual de OPN; también el principal riesgo de "volver a ser consultora" — tarifado y acotado siempre.

## 3. Piloto pagado (el vehículo de los 3 primeros clientes)

- **Precio: 4.500 € / 8 semanas** (se descuenta 100% del primer año si convierte).
- Alcance cerrado: 3 expedientes reales, PLACSP+BORME configurados el día 1, digest semanal activo, 1 informe competitivo y 1 informe ejecutivo entregados, 3 sesiones de seguimiento.
- Criterios de éxito escritos en la propuesta (elegir 3): ≥N licitaciones relevantes detectadas y calificadas; informe de entidad en <10 min vs horas; ≥1 oportunidad promovida a acción real; uso semanal por ≥2 personas.
- Anti-piloto-eterno: fecha de decisión en el contrato (semana 9); si no hay decisión, el acceso pasa a solo-lectura 30 días y expira.
- Descuento máximo post-piloto: 15% primer año por caso de referencia público (logo + cita + métricas). Nunca descuento sin contrapartida.

## 4. Justificación de precio por valor

- Coste alternativo hoy: ½ analista dedicado a vigilancia+informes ≈ 15-20 K€/año de coste laboral; una tarde de consultor por informe de entidad; una licitación relevante perdida ≫ ACV completo.
- Coste de servir (ver [unit economics](ORACLE_UNIT_ECONOMICS.md)): infra + IA <5% del ACV → margen bruto objetivo >80% en software.
- Contra Feedly/Crayon: Oracle Essential cuesta ⅓ del suelo de la categoría CI internacional, con fuentes españolas que aquéllos no tienen. Espacio para subir precio con los primeros 10 clientes (RECOMENDACIÓN: revisar +15-20% tras el cliente 5).

## 5. Renovación y expansión

- Contrato anual, pago anual por adelantado (mid-market español acepta; mejora caja).
- Palancas de expansión por cuenta: expedientes (+), usuarios (+), servicios de analista, informe competitivo recurrente, conectores premium (futuro).
- Señal de renovación a vigilar desde el día 1: uso semanal de "Qué ha cambiado" y decisiones registradas (los dos mejores predictores de switching cost — INFERENCIA).

## 6. Límites que protegen el margen (implementar en producto, P1)

- Cupos de generaciones IA por plan (el ledger de uso ya existe — HECHO; falta exponerlo como límite comercial).
- Fair-use de señales/monitores por plan.
- Todo trabajo humano (implantación, analista, informes a medida) con tarifa publicada — nada "incluido de palabra".
