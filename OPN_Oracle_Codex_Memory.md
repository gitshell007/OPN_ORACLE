# OPN Oracle - Memoria de producto para Codex

**Proyecto:** OPN Oracle  
**Tipo:** producto independiente dentro del ecosistema OPN  
**Estado:** memoria funcional y técnica inicial  
**Fecha:** 2026-07-09  
**Destino:** Codex / equipo de desarrollo  


## 0. Resumen ejecutivo

OPN Oracle es un producto independiente para convertir proyectos, oportunidades, cuentas estratégicas, convocatorias, mercados, operaciones o iniciativas internas en **expedientes estratégicos vivos**.

Un expediente estratégico no es una carpeta documental ni un CRM. Es una unidad de inteligencia continua que combina:

- monitorización de señales externas e internas mediante **Signal Avanza**;
- capacidades de vigilancia, alerta, prospectiva, auditoría y escenarios procedentes de Risk/Sentinel;
- capacidades de relación, contexto, actores, contactos, memoria y preparación de reuniones procedentes de Nexus;
- generación de informes, briefings, alertas accionables y recomendaciones de siguiente paso.

La tesis de producto es:

> Toda organización tiene proyectos importantes que evolucionan en un entorno cambiante. OPN Oracle convierte información dispersa en inteligencia accionable para anticipar oportunidades, riesgos, alianzas, reuniones y decisiones.

El producto debe ser **genérico para cualquier tipo de cliente**. Defensa, grafeno, Iberdrola o proyectos de I+D+i son casos prácticos, no límites del producto.


## 1. Decisiones ya tomadas

Estas decisiones son vinculantes para el desarrollo inicial salvo cambio explícito posterior.

| Decisión | Resultado |
|---|---|
| Nombre del producto | **OPN Oracle** |
| Naturaleza | Producto independiente, no simple módulo de Sentinel ni de Nexus |
| Unidad principal | **Expediente estratégico** |
| Alcance vertical | Genérico para cualquier sector y cliente |
| Casos de defensa / grafeno | Solo ejemplos o datos de prueba, no foco de posicionamiento |
| Enfoque de producto | Principalmente ofensivo: oportunidades, alianzas, convocatorias, reuniones y decisiones; con capa defensiva de riesgos |
| Base reutilizada | Nexus + Risk/Sentinel |
| Capa obligatoria | Debe usar **Signal Avanza** como motor/capa de señales |
| Promesa | Monitorizar proyectos estratégicos y convertir señales en decisiones |


## 2. Problema que resuelve

Muchas organizaciones trabajan con proyectos estratégicos que se gestionan mediante carpetas, documentos sueltos, reuniones, hojas de cálculo, chats, emails, búsquedas en prensa, LinkedIn, boletines oficiales, herramientas de inteligencia, CRM y conocimiento personal de los equipos.

El problema no es que falte información. El problema es que la información está dispersa y no se transforma a tiempo en decisiones.

OPN Oracle debe resolver cinco dolores:

1. **Dispersión:** la información de un proyecto vive en varias herramientas y formatos.
2. **Baja anticipación:** oportunidades, riesgos y señales débiles se detectan tarde.
3. **Pérdida de memoria:** cada reunión obliga a reconstruir contexto.
4. **Dificultad para priorizar:** no queda claro qué señal importa, qué oportunidad encaja o qué actor es relevante.
5. **Poca trazabilidad:** las conclusiones estratégicas no siempre tienen fuentes, evidencias ni histórico de decisiones.


## 3. Definición de producto

OPN Oracle es una plataforma de inteligencia estratégica que permite a un cliente crear expedientes estratégicos y mantenerlos actualizados mediante señales, actores, oportunidades, riesgos, informes y recomendaciones.

La frase corta de producto:

> OPN Oracle convierte cada proyecto importante en un radar estratégico vivo.

La frase larga:

> OPN Oracle ayuda a equipos directivos, innovación, desarrollo de negocio, asuntos públicos, inversión, operaciones y riesgo a monitorizar proyectos estratégicos, detectar oportunidades y amenazas, mapear actores, preparar reuniones y generar informes accionables con trazabilidad de fuentes.


## 4. Qué es un expediente estratégico

El expediente estratégico es la entidad central de Oracle.

Puede representar cualquiera de estos objetos:

- proyecto corporativo;
- proyecto de I+D+i;
- tecnología o patente;
- cuenta estratégica;
- mercado objetivo;
- país o región;
- convocatoria, licitación o ayuda;
- inversión o adquisición;
- alianza potencial;
- producto en lanzamiento;
- activo crítico;
- operación comercial compleja;
- asunto regulatorio;
- iniciativa de expansión;
- conflicto territorial o reputacional;
- programa público o privado de alto impacto.

Un expediente contiene:

- objetivos estratégicos;
- hipótesis;
- palabras clave;
- entidades vigiladas;
- fuentes;
- señales recibidas;
- oportunidades detectadas;
- riesgos;
- actores y relaciones;
- reuniones;
- informes;
- decisiones;
- tareas;
- feedback humano;
- auditoría de IA y fuentes.

### Principio importante

Nunca se debe modelar Oracle alrededor de sectores concretos como defensa, energía o grafeno. El modelo debe ser abstracto y configurable. Los sectores se representan mediante taxonomías, plantillas y conectores.


## 5. Posicionamiento dentro del ecosistema OPN

OPN Oracle debe convivir con otros productos sin solaparse de forma confusa.

### Sentinel / Risk-Sentinel

Sentinel se orienta a vigilancia de eventos, activos, fuentes abiertas, riesgos reputacionales, seguridad, escenarios y alertas. Oracle reutiliza esas capacidades, pero cambia la unidad principal de trabajo: de evento/activo a expediente estratégico.

Oracle no sustituye Sentinel. Oracle usa Sentinel como base de vigilancia y análisis de riesgo cuando el expediente necesita monitorización externa, escenarios o alerta temprana.

### Nexus

Nexus aporta inteligencia relacional: contactos, organizaciones, perfiles, histórico de interacciones, preparación de reuniones, guiones, influencia y simulación. Oracle usa Nexus para entender el mapa de actores del expediente y preparar la acción humana.

Oracle no es un CRM. Puede integrarse con Nexus, pero su unidad no es el contacto ni la oportunidad comercial aislada, sino el expediente estratégico completo.

### Risk / RIES

RIES o Risk Advisor se centran en riesgo operacional, riesgo humano, identidad, anomalías, compliance y seguridad interna. Oracle puede usar capacidades de scoring y auditoría de Risk, pero no debe empezar como herramienta de insider risk ni de vigilancia de empleados.

### Core / Cumplimiento

Core o los módulos de cumplimiento pueden aportar auditoría, trazabilidad, documentación regulatoria y controles. Oracle debe incorporar la lógica de evidencias y auditoría, pero no debe convertirse en un gestor documental de compliance.

### Signal Avanza

Signal Avanza es obligatorio como capa de señales. Oracle debe construir sobre Signal Avanza, no replicarlo.


## 6. Rol de Signal Avanza

### Definición asumida

Como no se ha entregado todavía la especificación técnica exacta de Signal Avanza, Codex debe tratarlo como una capa o servicio de ingesta, normalización, clasificación y entrega de señales.

Signal Avanza debe ser la puerta de entrada de señales hacia Oracle.

### Qué debe hacer Signal Avanza para Oracle

Signal Avanza debe encargarse de:

- recibir configuraciones de vigilancia desde un expediente;
- monitorizar fuentes y consultas;
- deduplicar resultados;
- normalizar señales;
- extraer metadatos básicos;
- clasificar señales por tipo;
- devolver señales con trazabilidad de fuente;
- permitir sincronización incremental;
- permitir simulación/mock mientras la API real no esté cerrada.

### Qué no debe hacer Signal Avanza

Signal Avanza no debe decidir por sí solo la estrategia completa del expediente. Su trabajo es suministrar señales limpias y útiles. Oracle debe ser quien relacione esas señales con objetivos, actores, oportunidades, riesgos, reuniones y decisiones.

### Tipos de señal

Oracle debe aceptar al menos estos tipos:

- `news`: prensa, blogs, publicaciones de medios.
- `official_publication`: BOE, boletines autonómicos, Diario Oficial UE, licitaciones, ayudas.
- `social_signal`: LinkedIn, X, YouTube, TikTok, Telegram u otras fuentes abiertas permitidas.
- `company_signal`: web corporativa, notas de prensa, cambios de equipo, alianzas.
- `market_signal`: informes de mercado, precios, materias primas, competencia.
- `regulatory_signal`: normativa, consulta pública, sanciones, reguladores.
- `tender_or_grant`: licitación, convocatoria, ayuda, subvención, programa.
- `relationship_signal`: interacción, reunión, conversación, contacto, referencia.
- `internal_document`: PDF, transcripción, nota, acta, documento cargado.
- `risk_signal`: amenaza, conflicto, protesta, litigio, reputación, cumplimiento.
- `opportunity_signal`: oportunidad de negocio, partnership, expansión, financiación.

### Interfaz mínima esperada

Codex debe implementar Oracle desacoplado mediante un adaptador.

```ts
export interface SignalAvanzaAdapter {
  createMonitor(input: CreateSignalMonitorInput): Promise<SignalMonitor>;
  updateMonitor(monitorId: string, input: UpdateSignalMonitorInput): Promise<SignalMonitor>;
  syncSignals(input: SyncSignalInput): Promise<SignalSyncResult>;
  getSignal(signalId: string): Promise<ExternalSignal | null>;
}
```

Si la API real no existe todavía, crear `MockSignalAvanzaAdapter` y `HttpSignalAvanzaAdapter` con la misma interfaz.

### Variables de entorno sugeridas

```env
SIGNAL_AVANZA_BASE_URL=
SIGNAL_AVANZA_API_KEY=
SIGNAL_AVANZA_WEBHOOK_SECRET=
SIGNAL_AVANZA_TIMEOUT_MS=30000
```


## 7. Enfoque ofensivo recomendado

La recomendación de producto es que Oracle sea ofensivo por defecto.

Esto significa que la pantalla principal no debe preguntar solo “qué riesgos hay”, sino:

- qué oportunidades han aparecido;
- qué señales merecen atención;
- qué convocatoria encaja;
- qué actor se ha movido;
- qué partner conviene explorar;
- qué reunión conviene preparar;
- qué decisión se puede tomar ahora;
- qué riesgo puede bloquear el avance.

La parte defensiva sigue siendo importante, pero debe actuar como protección del avance estratégico.

### Fórmula conceptual

```text
Oracle = oportunidades + señales + actores + riesgos + reuniones + memoria + decisiones
```


## 8. Usuarios objetivo

Oracle debe servir a múltiples perfiles, no a un único departamento.

### Perfiles principales

- CEO / dirección general.
- Dirección de estrategia.
- Desarrollo de negocio.
- Innovación / I+D+i.
- PMO / dirección de proyectos.
- Asuntos públicos y regulación.
- Seguridad corporativa y riesgo.
- M&A / inversión / corporate development.
- Grandes cuentas / account-based sales.
- Consultoras, despachos y asesores estratégicos.
- Administraciones públicas con proyectos complejos.

### Patrón común

Todos tienen proyectos importantes que dependen de señales externas, actores, tiempos, riesgos y oportunidades.


## 9. Casos de uso genéricos

### 9.1 Monitorizar un proyecto estratégico

El usuario crea un expediente, carga documentación, define objetivos y activa vigilancia. Oracle mantiene un radar de señales, actores, riesgos y oportunidades.

### 9.2 Detectar convocatorias o licitaciones que encajan

Oracle recibe señales de convocatorias y calcula el grado de encaje con el expediente, mostrando requisitos, fechas, actores, probabilidad, esfuerzo y próximos pasos.

### 9.3 Buscar alianzas estratégicas

Oracle identifica actores que aparecen repetidamente en señales relevantes y los clasifica como potencial partner, competidor, prescriptor, financiador, cliente o riesgo.

### 9.4 Preparar reuniones

Oracle genera un briefing con contexto, mapa de actores, objetivos, estrategia de conversación, preguntas, objeciones esperables, información sensible y tareas posteriores.

### 9.5 Vigilar riesgos de avance

Oracle detecta señales que pueden afectar al proyecto: oposición social, cambios regulatorios, movimientos de competidores, retrasos, dependencia de socios, conflictos territoriales o reputación.

### 9.6 Generar informes periódicos

Oracle produce informes ejecutivos, informes de oportunidad, informes de riesgo, informes de mercado, briefings de reunión y resúmenes de cambio semanal.

### 9.7 Mantener memoria estratégica

Oracle recuerda qué se decidió, por qué, con qué fuente, qué hipótesis estaban activas y qué cambió desde el informe anterior.


## 10. Lo que NO debe ser Oracle

Oracle no debe ser:

- una carpeta de documentos con IA encima;
- un simple generador de informes;
- una copia de Sentinel con otro nombre;
- una copia de Nexus con otro nombre;
- un CRM tradicional;
- un motor de scraping sin estrategia;
- una herramienta sectorial de defensa;
- una herramienta sectorial de grafeno;
- una herramienta solo de vigilancia de riesgos;
- una herramienta de automatización comercial agresiva;
- una plataforma que dé conclusiones sin fuentes.


## 11. Arquitectura funcional

### Capas principales

1. **Expedientes:** gestión de contexto estratégico.
2. **Signal Avanza:** ingesta y normalización de señales.
3. **Clasificación Oracle:** interpretación de señales en relación con expedientes.
4. **Mapa de actores:** organizaciones, personas, relaciones e influencia.
5. **Motor de oportunidades:** detección y scoring de oportunidades.
6. **Motor de riesgos:** detección y scoring de riesgos.
7. **Memoria y decisiones:** histórico, hipótesis, tareas y feedback.
8. **Informes y briefings:** salida accionable para el usuario.
9. **Auditoría:** trazabilidad de fuentes, IA, cambios y acciones.

### Flujo principal

```text
Usuario crea expediente
  -> define objetivo, sector, geografía, actores y fuentes
  -> Oracle crea monitor en Signal Avanza
  -> Signal Avanza entrega señales normalizadas
  -> Oracle clasifica relevancia, oportunidad, riesgo y actores
  -> Oracle actualiza el expediente
  -> Oracle propone acciones, informes y reuniones
  -> usuario valida, descarta o ajusta
  -> la memoria del expediente mejora
```


## 12. Modelo de datos conceptual

### Entidades principales

| Entidad | Descripción |
|---|---|
| `Tenant` | Cliente u organización usuaria |
| `Workspace` | Espacio de trabajo dentro del cliente |
| `StrategicDossier` | Expediente estratégico |
| `DossierObjective` | Objetivo del expediente |
| `Hypothesis` | Hipótesis que Oracle debe vigilar o validar |
| `Watchlist` | Configuración de vigilancia |
| `SignalMonitor` | Monitor creado en Signal Avanza |
| `Signal` | Señal normalizada recibida |
| `Evidence` | Fragmento, URL, documento o fuente que soporta un análisis |
| `Actor` | Organización, persona, institución, competidor, partner |
| `Relationship` | Relación entre actores o entre actor y expediente |
| `Opportunity` | Oportunidad detectada o creada manualmente |
| `RiskItem` | Riesgo detectado o creado manualmente |
| `Insight` | Conclusión generada por IA o por usuario |
| `Meeting` | Reunión asociada al expediente |
| `Briefing` | Preparación de reunión |
| `Report` | Informe generado |
| `Decision` | Decisión estratégica registrada |
| `Task` | Acción recomendada o asignada |
| `Feedback` | Validación humana sobre una señal, insight o scoring |
| `AIAuditLog` | Registro de cada llamada a IA |

### StrategicDossier

```ts
export type DossierType =
  | 'project'
  | 'strategic_account'
  | 'market'
  | 'technology'
  | 'tender_or_grant'
  | 'investment'
  | 'partnership'
  | 'product_launch'
  | 'regulatory_affair'
  | 'risk_watch'
  | 'custom';

export interface StrategicDossier {
  id: string;
  tenantId: string;
  workspaceId: string;
  title: string;
  description?: string;
  type: DossierType;
  status: 'draft' | 'active' | 'paused' | 'archived';
  strategicGoal?: string;
  geography?: string[];
  sectors?: string[];
  languages?: string[];
  ownerUserId: string;
  createdAt: string;
  updatedAt: string;
}
```

### Signal

```ts
export interface Signal {
  id: string;
  tenantId: string;
  dossierId?: string;
  signalAvanzaId?: string;
  title: string;
  summary: string;
  sourceType: SignalSourceType;
  sourceName?: string;
  sourceUrl?: string;
  publishedAt?: string;
  ingestedAt: string;
  language?: string;
  entities: ExtractedEntity[];
  tags: string[];
  categories: SignalCategory[];
  relevanceScore: number;    // 0-100
  noveltyScore: number;      // 0-100
  confidenceScore: number;   // 0-100
  sourceCredibilityScore?: number;
  rawHash?: string;
  status: 'new' | 'reviewed' | 'dismissed' | 'promoted';
}
```

### Opportunity

```ts
export interface Opportunity {
  id: string;
  dossierId: string;
  title: string;
  description: string;
  sourceSignalIds: string[];
  type: 'grant' | 'tender' | 'partner' | 'client' | 'market' | 'investment' | 'media' | 'regulatory' | 'other';
  fitScore: number;
  urgencyScore: number;
  valueScore: number;
  actionabilityScore: number;
  confidenceScore: number;
  overallScore: number;
  recommendedNextAction?: string;
  deadline?: string;
  status: 'candidate' | 'qualified' | 'active' | 'won' | 'lost' | 'dismissed';
}
```

### RiskItem

```ts
export interface RiskItem {
  id: string;
  dossierId: string;
  title: string;
  description: string;
  sourceSignalIds: string[];
  likelihoodScore: number;
  impactScore: number;
  velocityScore: number;
  controllabilityScore: number;
  riskScore: number;
  mitigation?: string;
  ownerUserId?: string;
  status: 'watch' | 'mitigating' | 'accepted' | 'closed';
}
```

### Audit log

```ts
export interface AIAuditLog {
  id: string;
  tenantId: string;
  dossierId?: string;
  userId?: string;
  actionType: string;
  modelProvider?: string;
  modelName?: string;
  inputHash: string;
  outputHash: string;
  sourceIds: string[];
  promptVersion: string;
  createdAt: string;
  latencyMs?: number;
  costEstimate?: number;
  redactionApplied: boolean;
}
```


## 13. Scoring estratégico

Oracle debe puntuar sin ocultar el razonamiento. Cada score debe mostrar:

- valor numérico;
- explicación corta;
- evidencias;
- nivel de confianza;
- fecha de cálculo;
- si fue modificado por feedback humano.

### Score de señal

```text
signal_score =
  0.30 * relevance
+ 0.20 * novelty
+ 0.20 * strategic_impact
+ 0.15 * source_credibility
+ 0.15 * confidence
```

### Score de oportunidad

```text
opportunity_score =
  0.25 * strategic_fit
+ 0.15 * urgency
+ 0.15 * expected_value
+ 0.15 * actionability
+ 0.10 * relationship_leverage
+ 0.10 * timing
+ 0.10 * confidence
- 0.10 * execution_effort
- 0.10 * blocking_risk
```

Los pesos deben ser configurables por expediente o plantilla.

### Score de riesgo

```text
risk_score =
  0.35 * impact
+ 0.25 * likelihood
+ 0.20 * velocity
+ 0.10 * exposure
+ 0.10 * uncertainty
- 0.10 * controllability
```

### Score de actor

```text
actor_priority =
  0.25 * influence
+ 0.20 * relevance_to_dossier
+ 0.15 * relationship_strength
+ 0.15 * accessibility
+ 0.15 * strategic_alignment
+ 0.10 * recent_activity
```


## 14. Agentes de IA

Oracle debe organizar la IA en agentes o servicios con responsabilidades claras. No conviene crear un único prompt gigante.

### 14.1 Intake Agent

Crea o mejora el expediente a partir de una descripción, PDF, URL, acta, transcripción o carpeta.

**Entrada:** documentos iniciales, objetivo del usuario, sector, país, fechas, actores conocidos.  
**Salida:** expediente estructurado, objetivos, hipótesis, watchlist inicial y preguntas abiertas.

### 14.2 Signal Triage Agent

Clasifica señales recibidas desde Signal Avanza.

**Entrada:** señal normalizada, contexto del expediente, histórico.  
**Salida:** relevancia, tipo, explicación, evidencias, entidades, acción sugerida.

Debe devolver JSON validable.

```json
{
  "category": "opportunity_signal",
  "relevanceScore": 86,
  "confidenceScore": 74,
  "summary": "La señal puede encajar con el objetivo de expansión del expediente.",
  "whyItMatters": "Aparece una convocatoria alineada con la tecnología y el plazo.",
  "recommendedAction": "Revisar requisitos y preparar informe de encaje.",
  "evidence": ["source:123#fragment:2"]
}
```

### 14.3 Entity Resolution Agent

Une entidades duplicadas y detecta si una persona, empresa, institución o programa ya existe en Nexus/Oracle.

### 14.4 Opportunity Analyst Agent

Convierte señales en oportunidades cualificadas.

Debe responder:

- qué oportunidad es;
- por qué encaja;
- qué valor puede tener;
- qué deadline existe;
- qué actores intervienen;
- qué requisitos faltan;
- qué hacer ahora.

### 14.5 Risk Analyst Agent

Detecta riesgos que pueden bloquear o alterar el expediente.

Debe distinguir entre riesgo real, ruido, señal débil, incertidumbre y alerta accionable.

### 14.6 Actor & Partnership Agent

Construye el mapa de actores: aliados, decisores, prescriptores, bloqueadores, competidores, financiadores, distribuidores y partners.

### 14.7 Meeting Briefing Agent

Prepara reuniones con actores del expediente.

Debe producir:

- objetivo de la reunión;
- contexto del interlocutor;
- mapa de intereses;
- puntos de conversación;
- preguntas inteligentes;
- objeciones probables;
- información que no conviene revelar;
- propuesta de cierre;
- tareas posteriores.

### 14.8 Report Writer Agent

Genera informes con trazabilidad.

Formatos mínimos:

- informe ejecutivo;
- informe de oportunidad;
- informe de riesgo;
- informe de convocatoria;
- briefing de reunión;
- resumen semanal de cambios;
- informe de actores;
- plan de acción.

### 14.9 Memory Curator Agent

Resume y consolida la memoria del expediente. Su función es evitar que el contexto crezca sin control.

Debe mantener:

- resumen vivo del expediente;
- decisiones tomadas;
- hipótesis vigentes;
- hipótesis descartadas;
- actores clave;
- señales recurrentes;
- próximos hitos.


## 15. Experiencia de usuario

### 15.1 Pantalla de inicio

Debe mostrar:

- expedientes activos;
- señales nuevas relevantes;
- oportunidades calientes;
- riesgos de alta prioridad;
- reuniones próximas;
- cambios desde la última visita;
- tareas pendientes.

### 15.2 Vista de expediente

Debe tener pestañas:

1. **Resumen:** situación actual, objetivo, score, últimos cambios.
2. **Radar:** señales de Signal Avanza y fuentes internas.
3. **Oportunidades:** oportunidades detectadas o creadas.
4. **Riesgos:** riesgos, mitigaciones y escenarios.
5. **Actores:** mapa de organizaciones, personas y relaciones.
6. **Reuniones:** briefings, actas y seguimiento.
7. **Informes:** informes generados y plantillas.
8. **Decisiones:** registro de decisiones y motivos.
9. **Configuración:** watchlists, fuentes, frecuencia, plantillas y permisos.

### 15.3 Inbox de señales

Las señales deben poder:

- revisarse;
- descartarse;
- promoverse a oportunidad;
- promoverse a riesgo;
- asociarse a actor;
- convertir en tarea;
- usarse en informe;
- marcar como no relevante para mejorar el modelo.

### 15.4 Vista “Qué ha cambiado”

Una vista clave debe responder:

> Desde la última revisión, ¿qué cambió y qué debería hacer?

Debe mostrar máximo 5-10 elementos priorizados, no una lista infinita.


## 16. Informes y salidas

Los informes son una parte crítica, pero Oracle no debe reducirse a informes. Los informes son la salida de una memoria viva.

### Plantillas mínimas

1. **Informe ejecutivo de expediente**
   - estado actual;
   - oportunidades principales;
   - riesgos principales;
   - actores clave;
   - decisiones recomendadas;
   - próximos pasos.

2. **Informe de oportunidad**
   - descripción;
   - encaje;
   - valor;
   - requisitos;
   - actores;
   - riesgos;
   - deadline;
   - plan de acción.

3. **Informe de convocatoria / licitación**
   - resumen;
   - entidad convocante;
   - requisitos;
   - elegibilidad;
   - documentación;
   - puntuación de encaje;
   - go/no-go.

4. **Briefing de reunión**
   - contexto;
   - objetivos;
   - interlocutores;
   - estrategia;
   - preguntas;
   - objeciones;
   - cierre esperado.

5. **Resumen semanal**
   - qué señales nuevas llegaron;
   - qué cambió;
   - qué se recomienda hacer;
   - qué queda pendiente.

### Requisito absoluto

Todo informe debe incluir evidencias y fuentes. No se deben generar conclusiones estratégicas sin soporte.


## 17. API sugerida

Los nombres son orientativos. Adaptar al stack existente.

### Dossiers

```http
POST   /api/oracle/dossiers
GET    /api/oracle/dossiers
GET    /api/oracle/dossiers/:id
PATCH  /api/oracle/dossiers/:id
DELETE /api/oracle/dossiers/:id
```

### Watchlists y Signal Avanza

```http
POST   /api/oracle/dossiers/:id/watchlists
PATCH  /api/oracle/watchlists/:watchlistId
POST   /api/oracle/dossiers/:id/signal-avanza/monitors
POST   /api/oracle/dossiers/:id/signal-avanza/sync
GET    /api/oracle/dossiers/:id/signals
POST   /api/oracle/signals/:signalId/review
POST   /api/oracle/signals/:signalId/promote
```

### Oportunidades y riesgos

```http
GET    /api/oracle/dossiers/:id/opportunities
POST   /api/oracle/dossiers/:id/opportunities
PATCH  /api/oracle/opportunities/:opportunityId
GET    /api/oracle/dossiers/:id/risks
POST   /api/oracle/dossiers/:id/risks
PATCH  /api/oracle/risks/:riskId
```

### Actores y relaciones

```http
GET    /api/oracle/dossiers/:id/actors
POST   /api/oracle/dossiers/:id/actors
PATCH  /api/oracle/actors/:actorId
POST   /api/oracle/relationships
```

### Informes y briefings

```http
POST   /api/oracle/dossiers/:id/reports
GET    /api/oracle/dossiers/:id/reports
GET    /api/oracle/reports/:reportId
POST   /api/oracle/dossiers/:id/briefings
```

### Auditoría

```http
GET    /api/oracle/dossiers/:id/audit
GET    /api/oracle/ai-audit-log
```


## 18. Arquitectura técnica recomendada

### Principios

- Producto independiente con namespace propio: `oracle`.
- Integración por adaptadores con Signal Avanza, Nexus y Sentinel.
- Sin acoplamiento fuerte a un sector.
- Multi-tenant desde el inicio.
- Auditoría de IA desde el MVP.
- Evidencias vinculadas a cada insight.
- Colas para ingesta y clasificación de señales.
- JSON schema o Zod para validar salidas de IA.

### Módulos sugeridos

```text
/src/oracle
  /domain
    dossier.ts
    signal.ts
    opportunity.ts
    risk.ts
    actor.ts
    report.ts
  /adapters
    signal-avanza.adapter.ts
    sentinel.adapter.ts
    nexus.adapter.ts
  /services
    dossier.service.ts
    signal-sync.service.ts
    signal-triage.service.ts
    opportunity.service.ts
    risk.service.ts
    report.service.ts
    briefing.service.ts
    audit.service.ts
  /agents
    intake.agent.ts
    triage.agent.ts
    opportunity.agent.ts
    risk.agent.ts
    meeting-briefing.agent.ts
    report-writer.agent.ts
    memory-curator.agent.ts
  /api
    routes.ts
  /ui
    DossierList.tsx
    DossierDashboard.tsx
    SignalInbox.tsx
    OpportunityBoard.tsx
    ActorMap.tsx
    ReportGenerator.tsx
```

### Base de datos

Si se usa PostgreSQL, considerar:

- JSONB para metadatos flexibles de señales.
- pgvector o motor vectorial equivalente para documentos y memoria.
- índices por tenant, dossier, fecha, score y tipo de señal.
- tabla separada para audit log, no mezclarla con logs técnicos.

### Colas / jobs

Jobs mínimos:

- `oracle.signal.sync`: sincroniza con Signal Avanza.
- `oracle.signal.triage`: clasifica señales.
- `oracle.entity.resolve`: resuelve entidades.
- `oracle.memory.refresh`: consolida memoria del expediente.
- `oracle.report.generate`: genera informes.
- `oracle.alert.evaluate`: decide si una señal merece alerta.


## 19. MVP recomendado

### Objetivo del MVP

Demostrar que Oracle convierte un proyecto estratégico genérico en un expediente vivo que recibe señales, las prioriza, detecta oportunidades/riesgos y genera un informe accionable.

### P0 - imprescindible

- Crear, editar y archivar expedientes estratégicos.
- Cargar documentos iniciales: PDF, texto, transcripción, URL manual.
- Crear watchlist del expediente.
- Integrar Signal Avanza mediante adaptador real o mock.
- Sincronizar señales.
- Inbox de señales con clasificación y scoring.
- Promover señal a oportunidad o riesgo.
- Mapa básico de actores detectados.
- Generar informe ejecutivo y briefing de reunión.
- Registrar auditoría de IA.
- Feedback humano: relevante/no relevante, ajustar tipo y score.

### P1 - siguiente fase

- Conectores oficiales: BOE, BORME, TED/eTendering, boletines regionales, webs corporativas.
- Plantillas por tipo de expediente.
- Alertas configurables por email/Slack/Teams.
- Integración más profunda con Nexus.
- Reuniones con acta, tareas y seguimiento.
- Informes comparativos “qué cambió desde la última semana”.
- Dashboard de portfolio de expedientes.

### P2 - madurez

- Coach de reuniones con simulación avanzada.
- Grafo avanzado de actores.
- Priorización de portfolio.
- Integraciones con Drive/SharePoint/CRM.
- Modelos sectoriales opcionales.
- Automatización de playbooks.
- Modo enterprise/on-prem para clientes regulados.

### Fuera del MVP

- Automatizar contacto comercial externo.
- Scraping agresivo o fuentes de legalidad dudosa.
- Monitorización de empleados tipo RIES.
- Integración completa de WhatsApp/Gmail/calendarios.
- Dark web o fuentes restringidas.
- Modelos sectoriales cerrados.


## 20. Plantillas iniciales de expediente

Oracle debe ser genérico, pero las plantillas ayudan a vender y usar.

### Plantilla: Proyecto estratégico

Campos:

- objetivo;
- geografía;
- stakeholders;
- calendario;
- riesgos;
- señales a vigilar;
- documentos base;
- decisiones pendientes.

### Plantilla: Convocatoria / financiación

Campos:

- programa;
- entidad convocante;
- deadline;
- requisitos;
- elegibilidad;
- consorcio;
- presupuesto;
- documentación;
- go/no-go.

### Plantilla: Cuenta estratégica

Campos:

- cliente;
- decisores;
- pain points;
- oportunidades;
- competidores;
- reuniones;
- relaciones;
- estrategia de entrada.

### Plantilla: Mercado / país

Campos:

- sector;
- país;
- regulación;
- competidores;
- canales;
- partners;
- riesgos;
- oportunidades.

### Plantilla: M&A / inversión

Campos:

- target;
- tesis de inversión;
- stakeholders;
- señales corporativas;
- riesgos;
- competidores;
- documentación;
- reuniones.


## 21. Integración con Nexus

Oracle debe usar Nexus para:

- buscar si un actor ya existe;
- traer histórico de relación;
- enriquecer perfiles de contacto;
- preparar reuniones;
- generar playbooks de relación;
- registrar nuevas interacciones;
- evaluar influencia, accesibilidad y rol del actor.

### Reglas

- No duplicar contactos si ya existen en Nexus.
- Un actor puede aparecer en varios expedientes.
- La relación actor-expediente debe tener contexto propio.
- El scoring relacional debe separarse del scoring estratégico.

### Tipos de rol de actor

- decisor;
- prescriptor;
- aliado;
- bloqueador;
- competidor;
- partner;
- proveedor;
- regulador;
- financiador;
- cliente;
- medio;
- influencer;
- experto técnico;
- desconocido.


## 22. Integración con Sentinel / Risk

Oracle debe usar Sentinel/Risk para:

- capacidad de monitorización externa;
- escenarios ideal/alternativo/pesadilla;
- alertas;
- reputación y riesgo;
- auditoría de llamadas IA;
- lógica de fuentes;
- reducción de trabajo manual;
- riesgo territorial, reputacional, regulatorio u operativo.

### Adaptación conceptual

En Sentinel se habla de eventos y activos. En Oracle se habla de expedientes.

Un expediente puede contener eventos, activos o hitos, pero no debe depender de ellos.

```text
Sentinel event/asset -> Oracle dossier item
Sentinel alert -> Oracle signal/risk/opportunity
Sentinel scenario -> Oracle scenario
Sentinel report -> Oracle report with strategic context
```


## 23. Seguridad, cumplimiento y auditoría

### Principios

- Multi-tenant estricto.
- Trazabilidad de fuentes.
- Registro de llamadas a IA.
- Control de permisos por expediente.
- Separación entre señales públicas, documentos internos y conversaciones.
- Redacción o anonimización si se envían datos a modelos externos.
- Capacidad de exportar auditoría.
- Retención configurable.

### Permisos mínimos

- `owner`: controla expediente y permisos.
- `editor`: puede modificar contexto, señales, informes y tareas.
- `analyst`: puede revisar señales y generar informes.
- `viewer`: solo lectura.
- `auditor`: accede a logs y evidencias.

### Auditabilidad de insight

Cada insight debe poder responder:

- qué fuentes lo soportan;
- qué señales se usaron;
- qué modelo o agente lo generó;
- cuándo se generó;
- qué usuario lo pidió;
- si hubo feedback humano;
- si se modificó después.


## 24. Diseño de memoria

Oracle debe tener memoria persistente, pero controlada.

### Tres niveles de memoria

1. **Memoria documental:** documentos, señales, informes, transcripciones.
2. **Memoria semántica:** resumen vivo, actores clave, hipótesis, objetivos, conceptos.
3. **Memoria decisional:** decisiones tomadas, motivos, descartes, responsabilidades.

### Summary vivo del expediente

Cada expediente debe tener un `livingSummary` actualizado por el Memory Curator Agent.

Debe incluir:

- qué es el expediente;
- objetivo actual;
- estado;
- señales recientes importantes;
- oportunidades principales;
- riesgos principales;
- actores relevantes;
- decisiones recientes;
- próximos hitos;
- preguntas abiertas.


## 25. Requisitos de calidad de IA

Oracle debe ser útil para decisiones reales. Por tanto:

- No debe inventar fuentes.
- No debe ocultar incertidumbre.
- Debe separar hechos, inferencias y recomendaciones.
- Debe mostrar confianza.
- Debe permitir corrección humana.
- Debe conservar el feedback.
- Debe evitar conclusiones tajantes cuando las señales sean débiles.
- Debe detectar contradicciones entre fuentes.
- Debe ofrecer “siguiente mejor acción”.

### Formato recomendado para insights

```json
{
  "title": "Nueva oportunidad detectada",
  "type": "opportunity",
  "confidence": 0.78,
  "summary": "Resumen en una frase.",
  "facts": ["Hecho verificable 1", "Hecho verificable 2"],
  "inferences": ["Inferencia razonada 1"],
  "recommendation": "Acción sugerida",
  "evidenceIds": ["ev_123", "ev_456"],
  "openQuestions": ["Pregunta pendiente"]
}
```


## 26. Métricas de producto

### Métricas de usuario

- número de expedientes activos;
- señales relevantes por expediente;
- porcentaje de señales descartadas;
- oportunidades promovidas;
- riesgos mitigados;
- informes generados;
- reuniones preparadas;
- tareas completadas;
- tiempo ahorrado por informe;
- reducción de herramientas manuales.

### Métricas de calidad

- precisión de clasificación de señales;
- aceptación de recomendaciones;
- ratio de falsos positivos;
- cobertura de fuentes;
- latencia de ingesta;
- latencia de informe;
- porcentaje de insights con evidencia;
- feedback positivo/negativo.


## 27. Demo inicial recomendada

La demo no debe estar centrada en grafeno ni defensa. Debe usar un caso genérico fácil de entender.

### Demo propuesta

**Caso:** una empresa quiere lanzar y financiar un nuevo proyecto estratégico en un sector regulado.

El expediente incluye:

- descripción del proyecto;
- documentos internos;
- actores conocidos;
- países objetivo;
- watchlist;
- señales de convocatorias;
- señales de competidores;
- señales regulatorias;
- un partner potencial;
- un riesgo de oposición o cambio normativo;
- una reunión próxima.

La demo debe mostrar:

1. crear expediente;
2. activar Signal Avanza;
3. recibir señales;
4. priorizarlas;
5. detectar oportunidad;
6. detectar riesgo;
7. mapear actor;
8. generar briefing de reunión;
9. generar informe ejecutivo;
10. ver auditoría y fuentes.


## 28. Riesgos de producto

### Riesgo 1: convertirse en una carpeta con IA

Mitigación: hacer que el radar, scoring, acciones y memoria estén en el centro.

### Riesgo 2: solaparse con Sentinel

Mitigación: diferenciar claramente la unidad principal. Sentinel vigila eventos/activos; Oracle gestiona expedientes estratégicos.

### Riesgo 3: solaparse con Nexus

Mitigación: Nexus es relación/contacto; Oracle es proyecto/estrategia. Oracle llama a Nexus para actores y reuniones.

### Riesgo 4: exceso de fuentes y ruido

Mitigación: Signal Avanza debe deduplicar y Oracle debe priorizar, resumir y permitir feedback.

### Riesgo 5: falta de confianza en IA

Mitigación: evidencias, auditoría, confianza, explicación, feedback humano y exportabilidad.

### Riesgo 6: verticalización prematura

Mitigación: mantener core genérico y usar plantillas sectoriales opcionales.


## 29. Criterios de aceptación del MVP

El MVP puede considerarse válido si:

- un usuario puede crear un expediente estratégico genérico;
- el expediente puede configurar un monitor en Signal Avanza o mock;
- Oracle puede recibir y guardar señales;
- cada señal puede clasificarse con score y explicación;
- una señal puede convertirse en oportunidad o riesgo;
- se puede generar un informe ejecutivo con evidencias;
- se puede generar un briefing de reunión;
- el sistema registra auditoría de IA;
- el usuario puede corregir clasificación y score;
- la UI distingue claramente señales, oportunidades, riesgos, actores e informes;
- no hay referencias obligatorias a defensa, grafeno o Iberdrola en el modelo base.


## 30. Instrucciones directas para Codex

### Prioridad de implementación

1. Crear namespace y dominio `oracle`.
2. Implementar modelos base: dossier, watchlist, signal, opportunity, risk, actor, report, audit.
3. Crear `SignalAvanzaAdapter` con mock funcional.
4. Crear CRUD de expedientes.
5. Crear flujo de sincronización de señales.
6. Crear clasificación de señales con salida JSON validada.
7. Crear inbox de señales.
8. Crear promoción de señal a oportunidad/riesgo.
9. Crear generador de informe ejecutivo.
10. Crear auditoría de IA.

### Reglas de implementación

- No hardcodear sectores.
- No hardcodear grafeno, defensa, OTAN, Iberdrola ni S.I.G. en entidades core.
- Usar esos casos solo como fixtures o seeds opcionales.
- Mantener Signal Avanza detrás de adaptador.
- Toda salida de IA relevante debe tener audit log.
- Todo insight debe tener evidencias.
- Usar schemas para validar respuestas IA.
- Permitir feedback humano.
- Diseñar multi-tenant desde el inicio.

### Nombres sugeridos

- Producto: `OPN Oracle`.
- Namespace técnico: `oracle`.
- Entidad principal: `StrategicDossier`.
- Servicio de señales: `SignalAvanzaAdapter`.
- Inbox: `SignalInbox`.
- Dashboard: `DossierDashboard`.
- Memoria: `DossierMemory` o `LivingSummary`.


## 31. Preguntas abiertas

1. Confirmar nombre exacto y API disponible de **Signal Avanza**.
2. Confirmar stack técnico real del producto: Next.js, React, Node, Python, base de datos, colas, etc.
3. Confirmar si Oracle debe integrarse visualmente dentro de la suite OPN existente o tener interfaz propia.
4. Confirmar si la primera demo se hará con datos sintéticos o con un caso real anonimizado.
5. Confirmar fuentes prioritarias de la primera versión.
6. Confirmar si se requiere ENS desde el MVP o solo diseño compatible.
7. Confirmar qué modelos de IA se pueden usar y dónde se alojan.
8. Confirmar política de datos sensibles, especialmente documentos internos y conversaciones.
9. Confirmar si el “Coach” de Nexus entra en P1 o P2.
10. Confirmar cómo se cobrará: por usuario, expediente, señales, conectores o cliente.


## 32. Versión corta para pegar como memoria en el repo

```md
# OPN Oracle - Codex Memory

OPN Oracle is an independent OPN product. Its main object is the Strategic Dossier, not an event, contact, folder or CRM opportunity.

The product must be generic for any client and sector. Defense, graphene, Iberdrola or S.I.G. are only examples/test cases, never hardcoded product scope.

Oracle is offensive by default: it helps clients detect opportunities, partners, tenders, grants, market changes, meetings and strategic next actions. Risk monitoring is included as a protective layer, not the main positioning.

Oracle must use Signal Avanza as the signal layer. Build it behind a SignalAvanzaAdapter. If the real API is not available, implement a mock adapter with the same interface.

Oracle reuses:
- Sentinel/Risk for monitoring, sources, scenarios, alerts, risk logic and AI audit.
- Nexus for actors, relationships, contacts, relational memory and meeting preparation.

Core entities:
- StrategicDossier
- DossierObjective
- Watchlist
- SignalMonitor
- Signal
- Evidence
- Actor
- Relationship
- Opportunity
- RiskItem
- Insight
- Meeting
- Briefing
- Report
- Decision
- Task
- Feedback
- AIAuditLog

MVP priorities:
1. Dossier CRUD.
2. Watchlist configuration.
3. Signal Avanza adapter/mock.
4. Signal sync and inbox.
5. Signal triage with relevance, novelty, confidence and evidence.
6. Promote signal to Opportunity or Risk.
7. Basic actor map.
8. Executive report generator.
9. Meeting briefing generator.
10. AI audit log and human feedback.

Rules:
- Do not hardcode sectors.
- Do not build Oracle as a Sentinel module.
- Do not build Oracle as a Nexus module.
- Do not generate strategic conclusions without evidence.
- Every important AI output must be auditable.
- Always separate facts, inferences and recommendations.
- Keep the Strategic Dossier as the central UX and data model.
```


## 33. Fuentes internas usadas para esta memoria

- Notas de reunión sobre herramienta de vigilancia estratégica de proyectos y ejemplo de grafeno.
- Notas de demostración de Sentinel, RIES, cumplimiento y Mesus.
- Notas del producto Iberdrola, suite de inteligencia y seguridad.
- Notas sobre estrategia comercial, partners y certificaciones ENS.
- Consulta con Fernando Chacón / S.I.G. como caso práctico de proyecto estratégico complejo.

