# OPN Oracle — Hoja de decisión de pricing y packaging

> **DOCUMENTO INTERNO · TARIFA NO APROBADA.** Precio, moneda, impuestos, duración,
> forma de pago, límites, servicios, implantación, descuentos y renovación están
> **POR CONFIRMAR** por el propietario. Este fichero no es una oferta, una tarifa
> publicada ni una autorización para cotizar. Sustituye las cifras históricas de
> julio de 2026, que eran hipótesis de trabajo y no deben reutilizarse con clientes.

**Estado:** **VERSIONADO PARA REVISIÓN** tras auditoría técnica independiente;
pendiente de aprobación escrita y publicación.

## 1. Decisiones que deben quedar firmadas

| Decisión | Estado | Evidencia requerida |
|---|---|---|
| Métrica principal de valor y cobro | **POR CONFIRMAR** | Entrevistas con compradores y facilidad de medición |
| Segmentos y nombres de planes | **POR CONFIRMAR** | ICP aprobado y recorridos realmente disponibles |
| Precio y periodo de cada plan | **POR CONFIRMAR** | Disposición a pagar y unit economics medidos |
| Usuarios, expedientes y consumo incluidos | **POR CONFIRMAR** | Coste real, adopción y límites aplicables en producto |
| Implantación y formación | **POR CONFIRMAR** | Horas, responsables y tarifa interna aprobada |
| Servicios humanos opcionales | **POR CONFIRMAR** | Alcance repetible, capacidad y margen medido |
| Piloto: precio, duración y alcance | **POR CONFIRMAR** | Propuesta de piloto completada y autorizada |
| Renovación, pago y política de descuentos | **POR CONFIRMAR** | Revisión comercial, financiera y contractual |
| Costes externos y exceso de uso | **POR CONFIRMAR** | Ledger, proveedor y mecanismo de autorización |

No se emitirá una cifra al cliente hasta que la fila correspondiente tenga
propietario, fecha y aprobación escrita.

## 2. Estructura que se debe validar

La hipótesis de packaging que se somete a entrevistas —no una decisión— es:

- envolver el producto en una licencia por tenant o tramo;
- relacionar el valor con expedientes/casos de uso activos, evitando penalizar la
  adopción interna únicamente por asiento;
- usar usuarios, expedientes, monitores, señales y generaciones como límites de
  alcance o *fair use* solo cuando el producto pueda medirlos y hacerlos cumplir;
- separar licencia, implantación y trabajo humano para no esconder servicios;
- presupuestar aparte proveedores, búsquedas, fuentes o integraciones de pago;
- vender requisitos aún no existentes —por ejemplo SSO, ENS u on-premise— solo
  como hito futuro expresamente contratado, nunca como capacidad presente.

Todo lo anterior permanece **POR CONFIRMAR**.

## 3. Ficha de plan que debe completarse

Crear una ficha por cada plan autorizado:

| Campo | Valor aprobado |
|---|---|
| Nombre del plan | **POR CONFIRMAR** |
| ICP y problema principal | **POR CONFIRMAR** |
| Recorridos incluidos | **POR CONFIRMAR** |
| Usuarios incluidos | **POR CONFIRMAR** |
| Expedientes activos incluidos | **POR CONFIRMAR** |
| Monitores/fuentes incluidos | **POR CONFIRMAR** |
| Consumo IA/búsqueda incluido | **POR CONFIRMAR** |
| Soporte y formación | **POR CONFIRMAR** |
| Precio, moneda, impuestos y periodo | **POR CONFIRMAR** |
| Implantación | **POR CONFIRMAR** |
| Exceso de uso y servicios adicionales | **POR CONFIRMAR** |
| Duración, renovación y cancelación | **POR CONFIRMAR** |
| SLA y límites técnicos | **POR CONFIRMAR** |

No se incluirá un cupo comercial que el producto no pueda observar y aplicar de
forma fiable.

## 4. Piloto pagado

El vehículo propuesto para validar valor es un piloto acotado, pero todas sus
condiciones están **POR CONFIRMAR**:

| Campo | Decisión |
|---|---|
| Precio y forma de pago | **POR CONFIRMAR** |
| Duración | **POR CONFIRMAR** |
| Expedientes, usuarios y fuentes | **POR CONFIRMAR** |
| Entregables y sesiones | **POR CONFIRMAR** |
| Línea base y criterios de éxito | **POR CONFIRMAR** |
| Fecha y órgano de decisión | **POR CONFIRMAR** |
| Tratamiento si convierte | **POR CONFIRMAR** |
| Descuento o contraprestación | **POR CONFIRMAR** |
| Acceso y salida al terminar | **POR CONFIRMAR** |

La versión emitible se prepara únicamente desde
[ORACLE_PROPUESTA_PILOTO.md](ORACLE_PROPUESTA_PILOTO.md), completando todos los
campos contractuales.

## 5. Reglas de margen y honestidad

- Medir coste de infraestructura, Signal, IA/búsqueda, almacenamiento, soporte,
  implantación y trabajo manual antes de afirmar margen.
- El coste cero de una llamada local no equivale a coste de servicio cero.
- No usar benchmarks de mercado como precio de Oracle ni como prueba de ahorro.
- No atribuir adjudicaciones o ingresos futuros al producto en el ROI.
- No conceder descuentos, devoluciones o imputaciones sin aprobación escrita.
- Todo proveedor o fuente de pago debe estar presupuestado y autorizado.
- La calculadora compara beneficio anual con el **coste total aprobado del primer
  año**, no con el precio aislado de un piloto más corto.

## 6. Gate antes de publicar pricing

- [ ] ICP y recorrido vendible aprobados.
- [ ] Tres o más entrevistas de disposición a pagar documentadas.
- [ ] Coste por tenant medido con el ledger y horas humanas reales.
- [ ] Límites del plan observables y aplicables en producto.
- [ ] Entidad oferente, impuestos, contrato, DPA y términos revisados.
- [ ] Tabla de precios aprobada por escrito por el propietario.
- [ ] One-pager, propuesta, calculadora y web muestran la misma versión.
- [ ] Se registra fecha, aprobador y versión que sustituye este estado.
