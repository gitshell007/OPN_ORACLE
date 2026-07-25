# 91 — Cerrar la deuda de interfaz y publicarla (P1 · API + UX + release)

> Prompt de producto para Codex, **backend + frontend + despliegue**. A diferencia de los
> anteriores, este **no termina en el commit**: termina con la release activa en producción y
> comprobada. Todo lo de abajo está medido hoy en `master`.
>
> Contexto: hay tres commits verificados esperando release (`9986eda`, `f53dc2f`, `2db2b8d`)
> sobre la activa `20260725T001230Z-quick-706b5c1`. Mientras no se despliegue, «Mejorar con
> Oracle» sigue cayendo encima del título del expediente y el matiz «· opcional» sigue en su
> propia línea. Lo que se construya aquí sale en la misma release.

## 1 — El selector de responsables: el hueco que el usuario pidió

En el diálogo de crear informe, `owner_user_ids` se pide como UUIDs escritos a mano. El
usuario lo dijo tal cual: «eso es imposible de saber si no tengo un desplegable». `actor_ids`
ya se resolvió con catálogo elegible; **este queda pendiente porque no hay endpoint**.

Lo medido hoy:

- `GET /api/v1/tenant-admin/members` (`tenants/admin_routes.py:196`) devuelve los miembros del
  tenant activo, pero exige `tenant.users.manage`. Un analista que genera informes tiene
  `report.generate` (`reporting/routes.py:190`), no permisos de administración: **no puede
  usarlo**.
- Además devuelve `email` y `roles`. Un selector no necesita el correo de cada compañero ni
  su rol: exponerlo a todo el que redacte un informe es repartir datos personales sin motivo.

Construye un endpoint de **personas asignables** del tenant activo:

- Solo miembros **activos**, y solo lo que un selector necesita: identificador y nombre
  visible. Nada de correos ni roles.
- Decide y justifica el permiso: tiene que ser uno que un generador de informes ya posea.
  `report.generate` es lo obvio, pero si el selector va a reutilizarse para asignar tareas
  —que también tienen responsable— piénsalo una vez y déjalo razonado.
- Tenant scoping probado en ambas direcciones: un tenant no ve personas de otro.

En el frontend, `owner_user_ids` pasa a ser catálogo elegible con el **mismo patrón ya
construido** para `actor_ids` en `reporting/report-library.tsx` (casillas, `splitIds`,
`toggleId`, y el catálogo cargado al abrir el diálogo, con el fallo tratado como ayuda
opcional, no como error). No inventes un segundo patrón: si hace falta, extrae el existente.

Si la lista puede ser larga, resuelve la búsqueda dentro del selector; y **el campo sigue
siendo opcional**, que es lo que el contrato `action_plan.v1` declara (`owner_user_ids:
"uuid[]?"`).

## 2 — `Retry-After`: el cero que miente

Medido en `packages/api-client/src/transport.ts:94`:

```ts
const retry = Number(response.headers.get("Retry-After"));
… Number.isFinite(retry) ? retry : undefined
```

`Number(null)` es `0`, y `0` es finito: cuando la cabecera **no** viene, `retryAfter` se
guarda como `0` en lugar de `undefined`. Hoy no se nota porque `0` es falsy y el mensaje de
login (`src/components/auth/auth-pages.tsx:103`) cae en la rama «más tarde», pero el tipo
miente y cualquier `if (error.retryAfter)` futuro heredará el fallo.

- Distingue cabecera ausente de valor cero.
- Y remata el motivo por el que lo miramos: el bloqueo de login **sí** envía `Retry-After`
  (`auth/routes.py:216`, con `AUTH_LOCK_SECONDS`), pero el usuario ve «vuelve a probar más
  tarde» sin cuenta atrás. Comprueba si la cabecera llega de verdad al navegador —si un proxy
  la filtra, decláralo— y muestra el tiempo real cuando exista. Hay dos 429 distintos en
  `/login`: el límite de 10/minuto y el bloqueo por credenciales fallidas; el mensaje no debe
  confundirlos.

## 3 — Dependencias sin fijar

Trece dependencias de `package.json` siguen declaradas como `"latest"`: React, React-DOM,
todos los Radix, TanStack Table, zod, sonner, lucide-react, react-hook-form y
`@hookform/resolvers`. `next` y `eslint` ya se fijaron tras dos incidentes —ESLint resolviendo
a la 10, y el aviso de PostCSS que dejó el CI rojo—; el resto sigue igual.

Con `"latest"`, un `npm install` en otra máquina o en el runner puede traer versiones
distintas sin que nadie cambie una línea, y el lockfile deja de significar lo que promete.

- Fija rangos con el mismo criterio que se usó para `next` y `eslint` (`^` sobre la versión
  instalada hoy), sin actualizar de paso: el objetivo es congelar lo que ya funciona, no
  estrenar versiones.
- Verifica que el lockfile no mueve resoluciones y que `npm audit --audit-level=high` sigue
  limpio.

## 4 — Commit, push y release

Esta es la parte que no se salta:

1. Commit por unidades separadas (endpoint + selector, `Retry-After`, dependencias): si algo
   hay que revertir, que se pueda revertir solo eso.
2. Push a `master`.
3. **CI verde para el SHA exacto**: aquí es de disparo manual (`gh workflow run CI`), y
   `release.yml` falla cerrado sin una ejecución `success` para ese SHA.
4. Backup pre-release y **restore aislado válido** — no basta con que el dump exista
   ([RELEASE.md](../../operations/RELEASE.md)).
5. Preparar `/opt/opn-oracle/releases/<release>` con `RELEASE_SHA256SUMS` y activar con
   `sudo oracle-control update <release>`.
6. Confirmar health, HTTPS, Celery con un único beat y smoke funcional.

La release anterior queda disponible para rollback de aplicación; recuerda que el rollback
**no revierte esquema** y que si el fallo ocurre desde `mutation_started` los punteros no
vuelven solos.

## 5 — Comprobar en producción y dar resultado

Con la release viva, verifica **en el navegador con sesión real**, no en local:

- El selector de responsables sale con personas de verdad y el informe se genera con los
  seleccionados.
- «Mejorar con Oracle» está en la fila de pestañas, **no encima del título** (es lo que
  `9986eda` arregla y hoy no está publicado).
- «Horizonte · opcional» y «IDs de responsables · opcional» comparten línea con su rótulo y
  los dos campos quedan a la misma altura.
- «Sin puntuar» no se parte en dos líneas en la tabla de señales.
- Un 429 de login muestra la cuenta atrás real si la cabecera llega.
- Sin errores nuevos en consola.

Y entrega el parte de siempre: release activa, SHA, gates ejecutados uno a uno, lo que **no**
se ejecutó y por qué, riesgos, y el estado de los datos de producción.

## Verificación exigida

- Tests backend del endpoint: solo miembros activos, sin correos ni roles en la respuesta,
  aislamiento entre tenants, y rechazo a quien no tenga el permiso elegido.
- Tests frontend: el selector lista personas, marcar una envía su identificador, y el fallo de
  carga del catálogo no rompe el diálogo.
- Test del parseo de `Retry-After`: cabecera ausente → `undefined`; `"0"` → `0`; valor válido →
  número.
- **Cada test nuevo verificado por mutación**: di qué mutaste y qué test cayó.
- Gates completos de ambos lados nombrados por separado, OpenAPI y cliente regenerados sin
  deriva, y el spec Playwright si el flujo lo toca.

## Qué NO hacer

- No expongas correos ni roles en el selector: es un desplegable de nombres, no un directorio.
- No reutilices `tenant-admin/members` bajando su permiso: ese endpoint es de administración y
  devuelve más de lo que un analista necesita.
- No actualices versiones al fijar dependencias: congelar y actualizar son dos operaciones
  distintas y solo una está pedida aquí.
- No despliegues sin CI verde para el SHA ni sin restore aislado validado.
- No toques el carril de licitaciones ni el backfill de Signal: van por su vía.
- No des por comprobado en producción lo que solo has visto en local; si no hay sesión o
  entorno, decláralo como no verificado en vez de suponerlo.
