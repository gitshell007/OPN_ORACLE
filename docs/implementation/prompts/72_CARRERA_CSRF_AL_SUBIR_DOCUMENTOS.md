# 72 — Un 403 de CSRF que no es culpa del usuario (P1 · seguridad y fiabilidad)

> Prompt para Codex. El fallo lo destapó el E2E al conectarlo al CI (prompt 71) y quedó registrado
> en `OPEN_QUESTIONS.md` sin tocar producción, que fue lo correcto. Ahora toca resolverlo.
>
> **Cuidado con la tentación:** este es un fallo de seguridad, y la salida fácil —relajar la
> comprobación— es exactamente la que no se puede tomar. Lee los invariantes antes de nada.

## El síntoma

Playwright pidió un token a `/api/v1/auth/csrf`, lo envió sin modificar en un POST multipart de
subida de documento, y el servidor respondió **`403 csrf_failed`** cuando varias lecturas de la
página seguían en vuelo. La misma subida funciona si se espera a que la página termine de cargar.

Para el usuario esto es: **subir un archivo nada más entrar en la pantalla falla, y volver a
intentarlo funciona.** No hay nada que indique por qué, y parece un fallo aleatorio del producto.

## El mecanismo, ya rastreado (no lo investigues de cero)

Hay dos piezas y ambas están en el repositorio:

**1. El token es único y se rota en cada petición.** `auth/routes.py` expone `GET /csrf`, que llama
a `renew_csrf()` (`auth/runtime.py`), y esa función **genera un token nuevo y sobrescribe
`session["csrf_token"]`**. No hay ventana de gracia ni tokens simultáneos: solo vale el último
escrito.

**2. La validación compara contra ese único valor.** `protect_csrf_and_install_identity` exige que
`X-CSRF-Token` coincida exactamente con `session["csrf_token"]` para todo método mutante.

De ahí sale la carrera: si dos peticiones piden token casi a la vez, la segunda pisa a la primera,
y quien ya tenía el primero en la mano recibe 403 aunque lo haya obtenido legítimamente hace un
segundo.

**Matiz importante que corrige la hipótesis registrada.** En `OPEN_QUESTIONS.md` se apuntó a que
una respuesta concurrente podría persistir una copia antigua de la sesión Redis y sobrescribir el
token nuevo. Eso es posible y hay que comprobarlo, **pero hay una causa más simple y segura que
verificar primero**: no hace falta que se pierda ninguna escritura para que falle. Basta con que
`GET /csrf` se llame dos veces —cosa que el cliente hace, porque `fetchCsrf` en
`packages/api-client/src/transport.ts` pide token sin deduplicar peticiones en vuelo— para que el
primer token quede inválido por diseño.

Empieza por ahí: es más barato de reproducir y, si es la causa, el arreglo es distinto.

## Qué hay que conseguir

Que una subida legítima **no falle por haber pedido el token mientras la página cargaba**, sin
debilitar la protección CSRF.

No te doy la solución. Direcciones razonables, elige y justifica:

- **En el cliente**: deduplicar las peticiones de token en vuelo, de modo que varias llamadas
  concurrentes compartan una sola. Es lo más contenido si la causa es la que apunto arriba.
- **En el servidor**: que `GET /csrf` devuelva el token vigente en lugar de rotarlo siempre, y
  reservar la rotación para los momentos en que de verdad toca (login, cambio de contraseña,
  elevación de privilegios). Si eliges esta vía, **razona explícitamente por qué sigue siendo
  seguro**: la rotación existe por algo y no vale quitarla sin argumento.
- **Aceptar una ventana breve** en la que el token anterior siga siendo válido. Es la opción con
  más superficie de riesgo; si la propones, justifica la duración y el alcance.

Sea cual sea, **verifica antes cuál es la causa real**. Si resulta ser la escritura de sesión que
se pisa —la hipótesis de `OPEN_QUESTIONS.md`—, el arreglo es otro y el cliente no lo resuelve.

## Invariantes que no puedes romper

- **La protección CSRF no se relaja.** Ni excepciones para la subida de documentos, ni endpoints
  exentos nuevos, ni comparaciones laxas. El único `csrf_exempt` que existe hoy es el webhook de
  Signal, y ahí se queda.
- **La comparación sigue siendo en tiempo constante** (`hmac.compare_digest`). No la sustituyas por
  `==`.
- **La rotación en los momentos sensibles se conserva**: tras iniciar sesión y tras cambiar
  credenciales, el token debe cambiar. Si tu arreglo toca `renew_csrf`, comprueba que esos flujos
  siguen rotando.
- **La comprobación de `Origin` se queda como está.**

## Verificación exigida

- Test que **reproduzca la carrera** y falle antes del arreglo: dos peticiones de token
  concurrentes y una mutación con el primero. Si no eres capaz de reproducirla, dilo: significa que
  la causa es otra y hay que volver al diagnóstico.
- Test de que el token **sigue rotando al iniciar sesión** y al cambiar contraseña. Es el
  invariante que más fácil se rompe con este arreglo.
- Test de que una mutación con token inventado o ausente **sigue devolviendo 403**.
- El E2E de subida de documentos debe pasar **sin la espera que se añadió como paliativo** en el
  prompt 71. Retírala: era un parche del test, no del producto, y así lo dejaron dicho.
- **Cada test nuevo verificado por mutación**, localizando la línea exacta antes de mutar.
- `ruff check`, `ruff format --check`, `mypy src` y la suite con integración, nombrados por
  separado. Frontend si tocas el cliente.

## Qué NO hacer

- No relajes CSRF de ninguna forma, ni siquiera «temporalmente».
- No dejes el paliativo del E2E como solución: si el producto sigue fallando y solo el test espera,
  no hemos arreglado nada.
- No amplíes el alcance a otros aspectos de sesión o autenticación que veas de paso: anótalos.
- Si al reproducirlo descubres que la causa es la pérdida de escritura en la sesión Redis, **para y
  repórtalo antes de arreglar**: eso afecta a toda la sesión, no solo al token, y merece decidirse
  con calma.
