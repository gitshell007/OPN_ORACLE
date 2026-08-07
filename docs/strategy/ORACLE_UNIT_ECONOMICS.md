# OPN Oracle — Unit economics medibles

> **DOCUMENTO INTERNO · CIFRAS NO APROBADAS.** Coste de servicio, ACV, margen,
> CAC, payback, LTV, churn, volumen y punto de equilibrio están **POR CONFIRMAR**.
> Las cifras históricas de julio de 2026 no procedían de una cohorte operativa de
> Oracle y quedan retiradas como base para propuestas o previsiones.

**Estado:** **VERSIONADO PARA REVISIÓN** tras auditoría técnica independiente;
pendiente de aprobación y publicación. Este documento define cómo obtener cifras defendibles; no presenta
resultados económicos.

## 1. Unidad de medida

La unidad mínima es **tenant activo por mes**, con una segunda vista por recorrido
intensivo (búsqueda, informe, análisis de oportunidad, borrador y monitorización).
El periodo, el entorno y el SHA de aplicación/Signal deben quedar registrados.

## 2. Coste de servir

| Concepto | Dato requerido | Fuente | Estado |
|---|---:|---|---|
| Infraestructura Oracle | Coste asignado/tenant/mes | Factura y criterio de reparto | **POR MEDIR** |
| Infraestructura Signal | Coste asignado/tenant/mes | Factura y uso real | **POR MEDIR** |
| IA local | GPU/CPU, energía y amortización | Telemetría + criterio financiero | **POR MEDIR** |
| IA o búsqueda de pago | Coste real por tenant | `ai_usage_logs` / `search_usage_logs` | **POR MEDIR** |
| Almacenamiento y copias | GB y coste asignado | Métricas/factura | **POR MEDIR** |
| Correo y servicios externos | Coste real | Factura + uso | **POR MEDIR** |
| Soporte | Horas × coste interno aprobado | Registro de tiempo | **POR MEDIR** |
| Implantación/formación | Horas × coste interno aprobado | Registro de tiempo | **POR MEDIR** |
| Operación e incidencias | Horas × coste interno aprobado | Registro de tiempo | **POR MEDIR** |

**Coste de servicio mensual** = suma de costes variables y asignados del mismo
periodo. Una llamada a Ollama sin factura por token no autoriza a registrar IA,
Signal o infraestructura como coste cero.

## 3. Ingresos y margen

| Métrica | Fórmula | Estado |
|---|---|---|
| Ingreso reconocido por tenant/mes | Importe contractual reconocido en el periodo | **POR MEDIR** |
| Coste de servicio por tenant/mes | Suma de la tabla anterior | **POR MEDIR** |
| Margen bruto | `(ingreso − coste de servicio) / ingreso` | **POR MEDIR** |
| Coste de implantación no recuperado | Coste real − ingreso de implantación reconocido | **POR MEDIR** |
| Margen con servicios | Ingreso y coste de cada servicio, separados del software | **POR MEDIR** |

No se publicará un margen objetivo como margen observado. Precio y ACV dependen
de la hoja [ORACLE_PRICING_AND_PACKAGING.md](ORACLE_PRICING_AND_PACKAGING.md) y
siguen **POR CONFIRMAR**.

## 4. Adquisición, retención y expansión

| Métrica | Definición que debe aprobarse | Estado |
|---|---|---|
| CAC | Venta + marketing + horas atribuibles por cliente adquirido | **POR DEFINIR/MEDIR** |
| Payback CAC | CAC / margen bruto mensual incremental | **POR DEFINIR/MEDIR** |
| Activación | Recorrido y ventana que prueban primer valor | **POR DEFINIR/MEDIR** |
| Conversión de piloto | Contratos anuales / pilotos elegibles | **POR DEFINIR/MEDIR** |
| Churn de logos | Clientes perdidos / clientes al inicio del periodo | **POR DEFINIR/MEDIR** |
| NRR | ARR inicial − bajas − contracción + expansión, sobre ARR inicial | **POR DEFINIR/MEDIR** |
| LTV | Método aprobado y datos de cohorte suficientes | **POR DEFINIR/MEDIR** |

No calcular LTV ni punto de equilibrio con una vida media o un salario supuesto
sin aprobación y sin cohortes suficientes.

## 5. Ledger mínimo por piloto

Registrar al menos:

- tenant, contrato, periodo, entorno y SHA de Oracle/Signal;
- usuarios y expedientes activos;
- ejecuciones, tokens, proveedor/modelo y coste contabilizado;
- búsquedas, fuente y coste contabilizado;
- almacenamiento y entregas;
- horas de venta, implantación, soporte, operación y trabajo analítico;
- incidencias y trabajo excepcional;
- ingreso facturado, cobrado y reconocido por separado;
- criterio de reparto de costes compartidos.

No incluir claves, prompts sensibles ni datos personales en el ledger económico.

## 6. Amenazas al margen que deben vigilarse

| Amenaza | Control comercial/operativo |
|---|---|
| Trabajo manual no tarifado | Registrar horas y separar servicios de licencia |
| Personalización por cliente | Cambio escrito con coste y fecha; no promesa informal |
| Consumo externo no limitado | Presupuesto, alertas y autorización por tenant |
| Soporte abierto | Alcance, canal y horario contractuales |
| Implantación subestimada | Checklist repetible y tiempo real por actividad |
| Fuente o proveedor de pago | Precio/cupo separado y consentimiento previo |
| Requisitos corporativos futuros | Hito contractual pagado; nunca capacidad presente |
| Dependencia de una sola persona | Runbooks, trazabilidad y capacidad antes de vender volumen |

## 7. Gate para afirmar rentabilidad

- [ ] Al menos un periodo completo conciliado con facturas y ledgers.
- [ ] Horas humanas registradas con coste interno aprobado.
- [ ] Costes compartidos repartidos con criterio documentado.
- [ ] Ingresos reconocidos según condiciones firmadas.
- [ ] Software y servicios informados por separado.
- [ ] Muestra, periodo, entorno y SHA acompañan cada cifra.
- [ ] Finanzas/propietario aprueban la lectura y su uso externo.

Hasta cerrar este gate, la única formulación autorizada es: **«la rentabilidad y
el coste de servicio están POR MEDIR; no se presentan como resultados»**.
