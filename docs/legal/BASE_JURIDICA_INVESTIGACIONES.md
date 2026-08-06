# Base jurídica de investigaciones · personas físicas y fuentes públicas

> **BORRADOR · requiere revisión jurídica y validación del despliegue antes de enviar o firmar**

| Campo | Valor |
|---|---|
| Versión | `0.1.0-g21` |
| Owner | OPN · cumplimiento comercial (borrador producto) |
| Estado | `borrador interno · no es dictamen legal` |
| Fecha | 2026-08-06 |
| Base de código / docs | `d472aeb7ff62a1fb8fff69086c63752fc37e5b39` |

## Alcance

OPN Oracle ayuda a construir **expedientes de inteligencia estratégica** que pueden incluir
referencias a **personas físicas** (cargos societarios, firmantes, contactos, menciones en
fuentes públicas o en documentos del cliente). Este documento orienta el debate legal y comercial.
**No es un dictamen** ni autoriza por sí solo un tratamiento.

Referencias de producto/estrategia usadas como input (no como ley):

- [../strategy/ORACLE_EXP_INVESTIGACIONES.md](../strategy/ORACLE_EXP_INVESTIGACIONES.md)
- Runtime IA y revisión humana: [../operations/AI_RUNTIME.md](../operations/AI_RUNTIME.md)

## 1. Personas físicas: cuándo hay datos personales

| Situación | ¿Datos personales? | Notas |
|---|---|---|
| Nombre de administrador o apoderado ligado a una sociedad | Sí, en principio | Aunque la fuente sea pública |
| Solo razón social y CIF de persona jurídica | En general datos de persona jurídica | Puede arrastrar personas en el mismo informe |
| Email y cuenta de usuario del cliente en la app | Sí | Tratamiento de cuenta (RAT T1) |
| Documento PDF subido con DNI/nóminas | Sí, y de alto riesgo operativo | El cliente controla lo que sube |

## 2. Fuentes públicas y papel de Oracle / Signal

1. El corpus de contratación y registros puede vivir o normalizarse en **Signal Avanza** y
   consumirse desde Oracle (contrato de integración en repo).
2. Oracle **no debe presentarse** como el productor original de registros públicos oficiales.
3. La **licencia y condiciones de cada fuente** en el despliegue concreto están
   **`[POR CONFIRMAR por fuente]`**.
4. «Público» ≠ «libre de RGPD». La publicidad de la fuente no elimina automáticamente obligaciones
   de base jurídica, minimización, exactitud e información.

## 3. Interés legítimo (checklist art. 6.1.f — no conclusión)

Hipótesis de trabajo frecuente en inteligencia comercial B2B sobre cargos y redes societarias:

| Factor de ponderación | Preguntas para LIA del cliente (responsable) |
|---|---|
| Finalidad | ¿Prevenir fraude, evaluar contraparte, preparar oferta pública, compliance interno? |
| Necesidad | ¿Hay medio menos intrusivo? |
| Expectativa | ¿La persona puede esperar el uso en contexto profesional/societario? |
| Impacto | ¿Perfilado, scoring de personas, difusión amplia, categorías especiales? |
| Salvaguardas | Minimización, exactitud, retención corta de cargos cesados, derechos, seguridad |

**Art. 19 LOPDGDD** y regímenes sectoriales: la documentación de estrategia del producto advierte
que **no cubre** por sí sola valoraciones de personas; requiere revisión jurídica local.

**Solvencia / listas:** la práctica de sector citada en docs internos insiste en exactitud,
actualidad y pertinencia — no solo «era verdad en alguna fecha».

## 4. Minimización

Prácticas alineadas con el diseño de producto (a confirmar en cada investigación):

1. Profundidad de grafo limitada (p. ej. 2 niveles por defecto en la metodología documentada).
2. Familias de roles acotadas (gobierno/propiedad vs expansión ruidosa de apoderados).
3. Preferir agregados deterministas sobre prosa libre del modelo.
4. No cargar categorías art. 9 salvo acuerdo explícito.
5. No construir «scoring de personas físicas» como producto de alto riesgo sin marco (línea roja
   documentada en la estrategia de investigaciones).

## 5. Exactitud y actualización

| Control deseable | Estado en producto |
|---|---|
| Trazar afirmaciones a evidencia/fuente | Capacidad fuerte en diseño (evidencia, citas, allowlist en IA) |
| Fechar el dato | Depende de la fuente y del captura |
| Retirar o degradar cargos cesados antiguos | Orientación de política en docs de estrategia (p. ej. referencia a plazos societarios); **no hay un motor global de caducidad de personas verificado como TTL único** |
| Corregir errores | Edición por usuarios autorizados + procedimiento de soporte |

## 6. Transparencia e información (art. 12–14 — checklist)

- Cuando los datos **no** se obtienen del interesado, el art. 14 plantea deberes de información
  con excepciones tasadas. El cliente (responsable) debe decidir el modelo informativo.
- El paquete comercial **no** sustituye la política de privacidad del cliente ni la del prestador
  en su sitio web (`[POR CONFIRMAR URLs]`).
- Canal de derechos del prestador: **`[POR CONFIRMAR]`**.

## 7. Derechos: acceso, oposición, supresión

| Derecho | Quién responde | Cómo ayuda el producto |
|---|---|---|
| Acceso / rectificación de cuenta de usuario | Prestador + admin tenant | Admin de usuarios; soporte |
| Oposición de un tercero investigado | **Principalmente el cliente como responsable del tratamiento de inteligencia** | Evaluación caso a caso; posible supresión/ocultación en el tenant; coordinación con fuentes |
| Supresión | Depende de roles y excepciones (defensa de reclamaciones, etc.) | Soft-delete documentos; no erasure global automático |

No prometer «borrado en todas las fuentes públicas»: **imposible** respecto de registros oficiales
de terceros.

## 8. Revisión humana y límites de la IA

Capacidades documentadas:

1. Artefactos IA en estado `candidate` hasta revisión humana (accept/reject).
2. Validación de `evidence_ids` contra snapshot del expediente.
3. Auditoría de generación (provider/modelo/métricas/hashes — según runtime).
4. Kill switch y `AI_ENABLED=false` por defecto.

Límites honestos:

- La revisión humana reduce riesgo; **no elimina** errores ni sesgos.
- El modo real depende de Signal/Ollama u otros proveedores aprobados.
- No afirmar cumplimiento del Reglamento de IA de la UE de forma global; usar como checklist
  (transparencia, no uso prohibido, clasificación de riesgo del caso de uso del cliente).

## 9. Límites comerciales (qué no vender)

| Prohibido en discurso | Alternativa honesta |
|---|---|
| «Tratamos personas con base legal ya cerrada para todos los clientes» | «La base la formaliza el cliente con su LIA; aportamos diseño de minimización y controles» |
| «Cumplimos plenamente el RGPD en investigaciones» | «Tenemos borrador de controles y este checklist; requiere revisión jurídica» |
| «La IA no alucina» | «Exigimos evidencia y revisión humana; el error sigue siendo posible» |
| «Borramos a una persona de Internet» | «Podemos actuar sobre el tenant y coordinar; no controlamos registros oficiales ajenos» |

## 10. Acciones pendientes recomendadas (fuera de G-21)

1. LIA plantilla por tipo de investigación (contraparte B2B, red societaria, monitoring).
2. Texto de información a interesados cuando no aplique excepción.
3. Canal y SLA interno de derechos de terceros.
4. Política de retención de cargos cesados **implementada o expresamente aceptada**.
5. Revisión legal de correlación con LOPDGDD y usos de IA.

## Enlaces

- [REGISTRO_ACTIVIDADES_TRATAMIENTO.md](./REGISTRO_ACTIVIDADES_TRATAMIENTO.md)
- [PRIVACIDAD_RETENCION_Y_SUPRESION.md](./PRIVACIDAD_RETENCION_Y_SUPRESION.md)
- [DPA_BORRADOR.md](./DPA_BORRADOR.md)
