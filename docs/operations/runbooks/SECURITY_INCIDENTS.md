# Incidentes de seguridad

## Sospecha de compromiso de sesión

**Síntomas:** sesión/ubicación inesperada, acciones no reconocidas, picos de auth/CSRF, cookie o
token expuesto, cambio de rol/contraseña sospechoso.  
**Confirmación:** abrir incidente restringido, preservar audit/logs con request/correlation IDs,
identificar usuario/sesiones/tenants/ventana y verificar cambios sin acceder a contenido innecesario.
No pedir ni copiar cookies/contraseñas.  
**Contención:** revocar todas las sesiones afectadas, forzar reset seguro, suspender usuario si
procede, rotar secretos comprometidos y limitar vector de entrada. Si afecta `SECRET_KEY` o Redis,
revocar todas las sesiones del entorno.  
**Erradicación/rollback:** corregir causa y desplegar con rollback preparado; revertir cambios de
negocio solo mediante historial/auditoría y aprobación del owner, nunca borrando eventos.  
**Escalado:** security e incident commander inmediato; notificación legal/tenant según clasificación
y plazo confirmado. Cierre con timeline, alcance, rotaciones, pruebas y vigilancia reforzada.

## Sospecha de acceso cross-tenant

**Síntomas:** ID/objeto de tenant B visible bajo A, audit inconsistente, respuesta que infiere B,
storage key cruzada o alerta RLS. Se trata como severidad crítica hasta refutarla.  
**Confirmación:** congelar despliegues, preservar DB/audit/logs/config/imagen, reproducir solo en un
clone aislado con datos sintéticos, identificar endpoint/query/rol/GUC y comprobar app-level más RLS
runtime. No explorar datos de otros tenants para «medir» el impacto.  
**Contención:** deshabilitar ruta/feature o poner producto en mantenimiento; revocar sesiones y
credenciales potencialmente implicadas; bloquear export/download afectados. No modificar policies
RLS en caliente sin revisión dual y prueba de rollback.  
**Erradicación/rollback:** parche mínimo con test A/B que falle antes y pase después; verificar todas
las rutas hermanas, claves storage, caches, exports y backups. Volver a imagen anterior solo si su
schema/policy está confirmado seguro.  
**Escalado:** security, dirección, DPO/legal y owners de tenants según plan de respuesta; preservar
cadena de custodia. No reabrir hasta reauditoría independiente, rotaciones necesarias y matriz
tenant completa verde.

