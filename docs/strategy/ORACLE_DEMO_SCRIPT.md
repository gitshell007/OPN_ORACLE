# OPN Oracle — Guion de demo comercial

Principio: una historia con los datos del prospecto, no un paseo por menús. Todo lo usado existe en producto (HECHO), con dos condiciones previas: informe de entidad estabilizado (p63) y un tenant de demo preparado. No usar defensa/grafeno/Iberdrola como caso salvo que el prospecto sea de ese sector.

---

## Preparación (30-45 min, antes de cada demo)

1. Tenant de demo limpio con un expediente del sector del prospecto ("Expansión a [organismo/CCAA]" o "Concurso [CPV del prospecto]").
2. Buscar en el producto: 2 competidores reales del prospecto (ficha de entidad verificada que carga bien), últimas adjudicaciones de su CPV/sector, 1 licitación abierta relevante.
3. Pregenerar: 1 informe ejecutivo y 1 informe competitivo (la generación en directo se lanza, pero se enseña el pregenerado si tarda).
4. Comprobación de humo: login, ficha de entidad, grafo, workspace de licitaciones, detalle de señal. Nada roto en pantalla o no hay demo.

## Demo de 15 minutos

**Caso:** el prospecto quiere ganar más concursos de su sector y llegar mejor preparado a cada oferta. **Usuario que interpretamos:** su responsable de desarrollo de negocio.

| Min | Paso | Pantalla | Qué decir / hacer | Momento wow |
|---|---|---|---|---|
| 0-1 | Encuadre | — | "No os voy a contar qué hace Oracle; vamos a mirar vuestro mercado con él. Este es un expediente para [caso del prospecto]." | — |
| 1-4 | **Tu competencia, por dentro** | Ficha 360º de su competidor real | Administradores, actos BORME, grafo de vínculos, contratos ganados, UTEs. "¿Sabíais que [competidor] comparte administrador con [X]?" | **W1** |
| 4-7 | **Tu mercado público** | Workspace de licitaciones | Adjudicaciones recientes del sector: importes, adjudicatarios, UTEs. Fijar una al expediente. "¿Cuántas de estas visteis a tiempo?" | **W2** |
| 7-10 | **De señal a decisión** | Bandeja de señales del expediente | Abrir una señal triada: score explicado, evidencia, por qué importa. Promoverla a oportunidad con tarea. | **W3** |
| 10-13 | **El informe que no se inventa nada** | Visor de informes | Abrir informe ejecutivo pregenerado; clicar 2 citas hasta la fuente. "Todo lo afirmado está citado; lo que no tiene fuente, no se publica. Y queda auditado qué modelo, qué datos, cuándo." | **W4** |
| 13-14 | **El lunes por la mañana** | Qué ha cambiado + digest | "Esto es lo que vuestro equipo vería cada lunes: 5-10 movimientos que importan, no 200 correos." | **W5** |
| 14-15 | Cierre | — | Preguntas de cierre (abajo) y propuesta de piloto. | — |

**Preguntas al cliente durante la demo** (mantener conversación, no monólogo):
- Tras W1: "¿Quién hace hoy este trabajo en vuestro equipo y cuánto le lleva?"
- Tras W2: "¿Qué concurso os dolió perder el último año?"
- Tras W4: "¿Quién prepara hoy los informes del comité de ofertas?"

**Cierre:** "Propongo un piloto de 8 semanas con 3 expedientes vuestros reales; lo montamos nosotros, vosotros solo revisáis y decidís. 4.500 €, y si seguís, se descuenta del primer año. ¿Qué tres proyectos meteríais?"

## Demo de 45 minutos (para segunda reunión, con usuario final presente)

Los 15' anteriores + tres bloques:

1. **(10') El día a día del analista**: crear un expediente en directo con perfil por tipo; lanzar el asistente "Mejorar con Oracle" (W6) y ejecutar una de sus acciones prefijadas (crear vigilancia). Enseñar el feedback humano sobre una señal (corregir clasificación) — "el sistema aprende de vuestro criterio y queda registrado".
2. **(10') Reuniones y memoria**: briefing de reunión (W7) sobre un actor del expediente; registro de decisiones (W8) — "esto es lo que sigue aquí cuando alguien se va".
3. **(5') Confianza y administración**: auditoría de IA (modelo, evidencias, coste), roles y permisos, aislamiento por cliente. Dirigido al perfil IT/compras si asiste.
4. **(5') Cierre** con business case: calculadora ROI con sus números del discovery.

## Reglas duras de la demo

1. **Nunca** enseñar una función que falle intermitentemente (hoy: no generar informe de entidad en directo hasta cerrar p63; usar la ficha, que es estable).
2. **Nunca** datos sintéticos genéricos ("Coches de Bomberos") con un prospecto real: siempre su sector, sus competidores.
3. La demo la puede dar cualquier persona entrenada con este guion: grabar una ejecución de referencia (vídeo interno) para formación — condición de no depender del fundador.
4. Si algo falla en directo: reconocerlo, seguir con el pregenerado, y enviar el resultado real esa misma tarde (convierte el fallo en seguimiento).
