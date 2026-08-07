# OPN Oracle — Guion de demo comercial verificable

**Estado documental:** revisión comercial de 7 de agosto de 2026 sobre la base técnica de 6 de agosto

**Estado de esta revisión:** **VERSIONADO PARA REVISIÓN** tras auditoría técnica independiente; pendiente de aprobación y ejecución antes de cada demo externa.

**Entorno autorizado para este guion:** Oracle Dev
**No afirma ni autoriza producción.** Antes de cada demo se debe comprobar de nuevo el release vivo y ejecutar el humo indicado abajo.

## 1. Qué significan los estados

Este documento no usa «hecho» como sinónimo de «desplegado» ni «rama» como sinónimo de `master`:

- **VERIFICADO EN SHA:** el código funcional del recorrido se trazó a `c2acf4e`; esta etiqueta no atribuye al SHA los cambios locales posteriores.
- **VALIDADO EN WORKTREE:** en esta revisión pasaron 70 pruebas API focales (1 omitida), 46 pruebas frontend focales y 9 pruebas del contrato G13 sobre el worktree actual. El resultado no equivale a commit, push, integración ni despliegue.
- **EN ORACLE-DEV REGISTRADO:** `c2acf4e` figura publicado en `origin/oracle-dev` en la referencia local observada al redactar este documento. No equivale a integrado en `master`.
- **EN DEV REGISTRADO:** el último relevo registrado identifica el release Dev `20260806T213657Z-native-c2acf4e`. Este cambio documental no ha reconsultado el servidor; significa *incluido en ese release registrado*, no *recorrido vivo repetido ahora*.
- **PRODUCCIÓN:** deliberadamente fuera de alcance. Ninguna frase de este guion acredita producción.

| Tramo del recorrido | Verificado en `c2acf4e` | Oracle Dev registrado | Evidencia principal |
|---|---|---|---|
| Buscar una licitación y fijarla a un expediente | Sí | Sí, según relevo | Workspace, control «Fijar a expediente» y pruebas de contratación |
| Subir un PCAP manual y mostrar su estado honesto | Sí (`08474ef`) | Sí, según relevo | Panel «Subir PCAP» y pruebas de adquisición |
| Calcular encaje perfil ↔ pliego | Sí (`fc19791`) | Sí, según relevo | Cuatro dimensiones y puerta humana |
| Preparar y editar el borrador | Sí (`ecec580`, `dee1750`) | Sí, según relevo | Borrador durable, edición y control de versión |
| Descargar Word editable | Sí (`09f7fde`, `f86f981`) | Sí, según relevo | Exportación `.docx` del borrador guardado |
| Registrar el ciclo de vida de la oferta | Sí (`bd8aae1`, `4f204d6`) | Sí, según relevo | Estado, importe, baja, lotes, garantía y mesa |

**Límite de contrato:** el flujo UI/runtime anterior está en `c2acf4e`, pero ese SHA conserva un OpenAPI incorrecto para el POST de análisis de oportunidad. La corrección G13 —sin request body, `Idempotency-Key` obligatorio y respuesta `202` tipada— está integrada en el baseline `044e35a8ef696faf53d3d108387d0cbed06a99dc`, auditado y validado por el gate completo; no se atribuye retroactivamente a `c2acf4e`.

**Límite de evidencia:** existe E2E real de encaje y borrador sin interceptar la API (`8a2990b`), pero todavía no hay una única prueba de navegador que recorra los siete pasos de esta demo de principio a fin. La persona que presenta debe hacer el humo completo en Dev antes de la reunión.

## 2. Historia que se cuenta

> «Partimos de una licitación real que vuestro equipo podría valorar. La fijamos a un expediente, aportamos el PCAP que sí vamos a analizar, comparamos sus requisitos con lo que la empresa ha declarado, preparamos un borrador editable y dejamos la oferta en seguimiento. Oracle no presenta la oferta ni sustituye la decisión del equipo.»

El usuario representado es un responsable de licitaciones o *bid manager*. La demo enseña un flujo de trabajo, no un catálogo de menús.

## 3. Preparación obligatoria

1. Usar exclusivamente un tenant de demostración y un expediente sin datos internos de QA visibles.
2. Confirmar en `/api/v1/meta` de **Dev** el SHA esperado y anotar hora, release y persona que hizo el humo. Si no coincide con el release ensayado, no improvisar.
3. Elegir una licitación pública relevante para el prospecto. No afirmar que Oracle cubre TED, todas las plataformas autonómicas ni toda Europa.
4. Disponer de un PCAP que pueda tratarse legítimamente. Si lo aporta el prospecto, confirmar autorización y ausencia de secretos que no deban entrar en el entorno de demo.
5. Completar en el expediente el perfil declarado que se quiera comparar —incluidos volumen y referencias si se pretende enseñar solvencia—. Lo no declarado debe poder aparecer como «no evaluable».
6. Ejecutar una vez el análisis y conservar una propuesta válida como respaldo. Si se usa, decir expresamente «resultado pregenerado».
7. Confirmar que el navegador permite portapapeles y descargas, y abrir el `.docx` con Word o LibreOffice antes de la reunión.
8. Tener una oportunidad creada para mostrar seguimiento; la creación siempre requiere confirmación humana.
9. No borrar ni alterar expedientes protegidos, no usar producción y no habilitar proveedores para preparar la demo.

### Humo de cinco minutos

- Login y acceso al tenant correcto.
- `/app/procurement`: una búsqueda devuelve resultados y «Fijar» responde «Referencia fijada al expediente».
- Expediente → **Licitaciones**: el PCAP aparece como «Subido manualmente» o se puede subir sin error.
- Expediente → **Análisis de oportunidad**: existe encaje y se puede abrir el borrador persistente.
- Guardar una edición inocua, descargar el Word y abrirlo.
- Expediente → **Oportunidades**: abrir una oportunidad y cargar «Ciclo de vida de la oferta».
- Deshacer o aislar cualquier dato creado por el humo.

## 4. Demo principal — 15 minutos

| Min | Paso real | Qué hacer en pantalla | Qué decir | Prueba observable |
|---:|---|---|---|---|
| 0–1 | Encuadre | Mostrar el expediente preparado y nombrar la decisión a tomar. | «Hoy no vamos a recorrer Oracle: vamos a decidir si esta licitación merece trabajo.» | Caso y responsable definidos. |
| 1–3 | **Buscar** | Ir a **Contratación pública**, introducir la necesidad y ejecutar «Buscar con Oracle». Revisar plazo, importe publicado, CPV y organismo. | «Oracle busca sobre contratación pública española. El importe se muestra como publicado por PLACSP; no inferimos si incluye IVA cuando el origen no lo dice.» | Resultados reales; sin cobertura inventada. |
| 3–4 | **Fijar** | En la licitación elegida, seleccionar el expediente y pulsar «Fijar». | «La referencia deja de ser un resultado suelto y pasa a formar parte del expediente.» | Mensaje «Referencia fijada al expediente». |
| 4–6 | **Subir PCAP** | Abrir Expediente → **Licitaciones** y pulsar «Subir PCAP». Esperar el estado terminal. | «La descarga automática es *best effort* y puede bloquearla el WAF. El camino comercial fiable es subir el PCAP; Oracle no llama PCAP completo a un extracto parcial.» | Estado «Subido manualmente» y fichero preferido. |
| 6–8 | **Encaje** | Abrir **Análisis de oportunidad** y pulsar «Analizar oportunidad» o usar el resultado pregenerado. Enseñar CPV, solvencia, lotes y plazo. | «El código compara requisitos oficiales con capacidad declarada. Un vacío se muestra como no evaluable; el veredicto sigue pendiente de confirmación humana.» | `GO`, `GO CONDICIONADO` o `NO-GO`, razones y condiciones. |
| 8–11 | **Borrador editable** | Pulsar «Preparar borrador de oferta», cambiar una respuesta, guardar y mostrar la nueva versión. | «Es un borrador declarado, no un hecho oficial ni un documento listo para presentar. Las ediciones humanas persisten y regenerar el análisis no las pisa.» | Estado «Guardado», versión y secciones editables. |
| 11–12 | **DOCX** | Pulsar «Descargar Word (.docx)» y abrir el fichero. | «El equipo sale de Oracle con un Word editable. Solo se exporta la versión guardada; si hay cambios locales, el producto exige guardarlos.» | `.docx` abre y conserva estructura, avisos y citas disponibles. |
| 12–14 | **Seguimiento** | Confirmar la propuesta para crear una oportunidad si procede. En **Oportunidades**, abrirla y editar «Ciclo de vida de la oferta». | «El estado CRM y el estado de la puja son distintos. Aquí registramos preparada, presentada, en evaluación, adjudicada, perdida o excluida, además de importe, baja, lotes, garantía y fecha de mesa.» | Guardado de seguimiento y versión visible. |
| 14–15 | Cierre | Abrir la calculadora ROI con datos del discovery y acordar el siguiente paso. Introducir solo un coste total del primer año ya aprobado; no el precio aislado de un piloto más corto. | «El precio, plazo y alcance del piloto no están aprobados en este guion. Se completan en una propuesta y se aceptan por escrito.» | Variables del cliente y periodo anual comparable, sin cifra comercial inventada. |

## 5. Preguntas que convierten la demo en discovery

- Tras buscar: «¿Cuántas licitaciones revisáis al año y quién hace el primer filtro?»
- Tras el encaje: «¿Dónde conserváis hoy volumen, referencias y demás acreditaciones?»
- Tras el borrador: «¿Cuántas horas empleáis en pasar del PCAP al primer esqueleto revisable?»
- Tras el Word: «¿Quién revisa y aprueba antes de presentar?»
- Tras el seguimiento: «¿En qué hoja o sistema seguís ahora bajas, lotes, mesa y resultado?»

Registrar respuestas, no estimarlas. Son entradas para [la calculadora ROI](ORACLE_ROI_CALCULATOR.html) y [la propuesta de piloto](ORACLE_PROPUESTA_PILOTO.md).

## 6. Frases permitidas y límites

### Se puede decir

- «Busca contratación pública española y permite fijar una referencia a un expediente.»
- «Si subes el PCAP, Oracle lo procesa y distingue el documento completo de un extracto parcial.»
- «Compara requisitos del pliego con capacidad declarada y explica qué falta acreditar.»
- «Prepara un borrador editable, exige revisión humana y lo exporta a Word.»
- «Separa el seguimiento de la oferta del estado general de la oportunidad.»

### No se puede decir

- «Descarga siempre los pliegos automáticamente.»
- «Te garantiza que cumples la solvencia» o «te dice si vas a ganar».
- «Redacta y presenta la oferta por ti.»
- «Cubre toda Europa» o «todas las plataformas».
- «La IA acierta el 100 %» o «toda salida está necesariamente completa».
- «Está probado en producción» por el mero hecho de que figure **EN DEV**.
- «El piloto cuesta X y dura Y» sin propuesta aprobada.

## 7. Plan B honesto

- Si la búsqueda falla, no usar capturas que parezcan vivas: explicar el fallo y continuar con una licitación fijada durante el humo.
- Si el PCAP sigue procesándose, enseñar su estado real y abrir el documento ya procesado de respaldo.
- Si el análisis tarda, abrir el resultado pregenerado y decir cuándo se generó.
- Si el borrador tiene un conflicto de versión, recargar y explicar que Oracle protege las ediciones concurrentes.
- Si el Word no abre, no enviar un PDF como si fuera equivalente: registrar el fallo y entregar después el `.docx` real.
- Si falla seguimiento, no actualizarlo por otra vía durante la demo; continuar con la vista de solo lectura y abrir incidencia.

## 8. Acta mínima después de la demo

```text
Fecha/hora:
Prospecto y asistentes:
Release Dev demostrado:
Humo ejecutado por:
Pasos completados (buscar/fijar/PCAP/encaje/borrador/DOCX/seguimiento):
Pasos mostrados pregenerados:
Incidencias:
Datos del discovery para ROI:
Siguiente decisión y responsable:
```
