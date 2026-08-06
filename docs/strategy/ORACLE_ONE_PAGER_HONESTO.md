# OPN Oracle — One-pager comercial honesto

**Versión técnica:** 6 de agosto de 2026

**Uso:** discovery, demo y propuesta de piloto.

**Estado:** **VERSIONADO PARA REVISIÓN** tras auditoría técnica independiente; pendiente de aprobación y publicación. Entidad oferente, precio, condiciones y disponibilidad contractual requieren confirmación.

## De una licitación encontrada a una oferta controlada

OPN Oracle organiza contratación pública, documentación y decisiones dentro de un expediente vivo. Ayuda al equipo de ofertas a responder cinco preguntas:

1. ¿Qué licitaciones merecen una primera revisión?
2. ¿Qué exige exactamente el PCAP que hemos aportado?
3. ¿Qué encaja con la capacidad que la empresa ha declarado y qué falta acreditar?
4. ¿Cómo convertimos esos requisitos en un primer borrador revisable?
5. ¿Dónde seguimos la oferta hasta su adjudicación, pérdida o exclusión?

Oracle **no sustituye al equipo**, no presenta ofertas y no garantiza adjudicaciones. Estructura el trabajo, conserva evidencia y hace visibles los vacíos antes de que se conviertan en una sorpresa.

## El recorrido que se puede demostrar

| Paso | Qué aporta Oracle | Qué sigue siendo humano |
|---|---|---|
| Buscar | Consulta contratación pública española y muestra plazo, organismo, CPV e importe publicado cuando constan. | Elegir qué oportunidad merece atención. |
| Fijar | Vincula la licitación a un expediente para trabajar con contexto persistente. | Confirmar el expediente y el caso de uso. |
| Subir PCAP | Procesa el documento aportado y diferencia PCAP completo, procesamiento, extracto parcial y no disponible. | Aportar un documento legítimo y revisar que sea el correcto. |
| Evaluar encaje | Compara CPV, solvencia, lotes y plazo con capacidad declarada; explica condiciones y vacíos. | Confirmar el veredicto y aportar acreditaciones. |
| Preparar borrador | Materializa secciones editables a partir de criterios del PCAP y conserva las ediciones. | Redactar, validar técnica y jurídicamente y aprobar. |
| Exportar | Descarga la versión guardada en Word `.docx` editable. | Completar el documento final y controlar su presentación. |
| Seguir | Registra estado, importe, baja, lotes, garantía, mesa y motivo de exclusión. | Mantener el dato al día y decidir acciones. |

## Dónde está el valor

- **Menos trabajo disperso:** búsqueda, pliego, encaje, borrador y seguimiento permanecen unidos al expediente.
- **Vacíos explícitos:** si algo no está declarado o no consta en la evidencia, se muestra como condición o como no evaluable.
- **Salida utilizable:** el equipo puede editar dentro de Oracle, copiar el contenido y continuar en Word.
- **Memoria operativa:** la decisión no desaparece en un correo o una hoja aislada; queda ligada a la oportunidad.
- **Revisión humana visible:** una propuesta de IA no crea por sí sola la oportunidad ni convierte un borrador en hecho oficial.

## Qué no debe esperarse

- La descarga automática de pliegos es *best effort*: un WAF, un límite HTTP o la ausencia de referencias documentales puede impedirla. El camino fiable es **subir el PCAP**.
- La cobertura descrita aquí es contratación pública española; no equivale a TED ni a todas las plataformas europeas o autonómicas.
- Un veredicto de encaje no es asesoramiento jurídico ni certificación de solvencia.
- El borrador no es un documento presentable sin revisión y aprobación humana.
- Oracle no sustituye una herramienta financiera, un bureau de crédito ni un sistema de presentación electrónica.
- MFA, SSO/SAML, ENS y demás requisitos corporativos deben confirmarse por separado; no se ofrecen como capacidades presentes en este material.

## Para quién encaja mejor

Equipos de licitaciones, desarrollo de negocio y consultoras que:

- revisan oportunidades públicas de forma recurrente;
- ya emplean tiempo en filtrar, leer PCAP, preparar un primer borrador y seguir ofertas;
- pueden aportar su perfil y sus acreditaciones;
- quieren conservar decisiones y fuentes por expediente;
- aceptan un piloto con alcance y criterios de éxito escritos.

No es una buena primera opción si la compra exige desde el día uno ENS, SSO corporativo o un cuestionario formal de seguridad aún no cerrado, si se busca únicamente una alerta barata o si se espera desarrollo a medida sin caso de uso validado.

## Alcance de seguridad y despliegue autorizado

«OPN Oracle dispone de controles de producto verificables en repositorio (aislamiento multi-tenant, RBAC, auditoría, autenticación con hash Argon2id y política mínima de longitud —MFA no disponible—, exports con caducidad). La aptitud para un entorno productivo concreto depende del despliegue, de los features habilitados y del contrato. No afirmamos certificación ISO/SOC/ENS ni readiness global de producción sin evidencia de ese entorno».

La IA está deshabilitada por defecto. Si se habilita, Oracle enruta mediante Signal y proveedor, residencia y tratamiento deben confirmarse para ese entorno. Esta descripción no sustituye un DPA, una revisión jurídica ni la evidencia operativa del despliegue acordado.

## Cómo comprobar el valor sin inventar un ROI

Antes de proponer condiciones se recogen datos del cliente:

- licitaciones revisadas y ofertas preparadas por año;
- horas actuales de filtro, lectura, primer borrador e informes;
- coste hora cargado del equipo;
- pérdidas por retrabajo o información dispersa;
- frecuencia de uso y personas que participarán;
- resultado mínimo que justificaría continuar.

Esos datos alimentan la [calculadora ROI autónoma](ORACLE_ROI_CALCULATOR.html). Sus valores iniciales son ilustrativos y no constituyen promesa de ahorro. El coste que se introduzca debe ser el **coste total aprobado del primer año**, porque las horas y beneficios del modelo son anuales; no se debe comparar directamente un piloto de duración inferior con un beneficio anual.

## Siguiente paso propuesto

Un piloto acotado sobre casos reales del cliente, definido mediante la [plantilla de propuesta](ORACLE_PROPUESTA_PILOTO.md), con:

- entidad oferente y cliente confirmados;
- alcance, duración y precio aprobados por escrito;
- documentos y usuarios autorizados;
- línea base y criterios de éxito acordados;
- revisión periódica y fecha de decisión;
- límites, seguridad, tratamiento de datos y salida documentados.

## Estado técnico de este material

Las capacidades que componen el recorrido buscar → fijar → subir PCAP → encaje → borrador editable → DOCX → seguimiento están verificadas en el baseline `c2acf4e`. El baseline posterior `044e35a8ef696faf53d3d108387d0cbed06a99dc` integra además el contrato OpenAPI completo de G13 y superó el gate backend completo (**1.849 pruebas, 0 skips, cobertura 84,09%**) y la auditoría independiente; todavía no se atribuye al release Dev hasta que exista despliegue y humo del SHA exacto. No existe aún una única prueba de navegador que recorra los siete pasos de extremo a extremo. El último relevo registrado al redactar identifica Dev como `20260806T213657Z-native-c2acf4e`; no se hace ninguna afirmación sobre producción. Antes de cada demo externa es obligatorio ejecutar y fechar el humo completo descrito en el [guion verificable de demo](ORACLE_DEMO_SCRIPT.md).
