# 42 — Aceptar pliegos oficiales sin antivirus, de forma explícita y trazable (P1)

> Prompt de producto y seguridad para Codex. Decisión tomada por el responsable el 2026-07-17 tras
> la verificación end-to-end en producción. **No es «quitar la comprobación»**: es convertir un
> bloqueo silencioso en una excepción acotada, declarada y visible, hasta que se despliegue ClamAV.

## Contexto: la cadena funciona, y el último gate la para

Verificado en producción (`479f416`) con la adjudicación `EMERGENCIACR2026/671` (ITURRI S.A):

```
GET https://contrataciondelestado.es/FileSystem/servlet/GetDocumentByIdServlet?... → 200 OK
documents: pliego-placsp.pdf | application/pdf | 252755 bytes | status=ready | scan_status=not_configured
/var/lib/oracle-storage: 48K → 296K
background_jobs: failed · "El documento oficial no quedó disponible."
```

**Se descarga un pliego real de la PLACSP y se almacena correctamente.** Tras los prompts 35, 36 y
38, toda la cadena funciona: fijar con `folder_id` con barras → snapshot con `documents` →
Idempotency-Key → descarga real → almacenamiento.

El job falla en `oracle/procurement_report.py:202`:

```python
if document is None or document.status != "ready" or document.scan_status != "clean":
    raise DocumentError("El documento oficial no quedó disponible.")
```

`scan_status = "not_configured"` porque **no hay antivirus desplegado**: `NoopScanner`
(`documents/scanner.py:27`) es el fallback cuando `DOCUMENT_CLAMAV_HOST` está vacío, y no hay
servicio ClamAV en `compose.prod.yml` ni variable en `/etc/opn-oracle/oracle.env`. `ClamAVScanner`
existe y está bien escrito; simplemente nunca se desplegó.

**Esto no era un bug: era el diseño fallando cerrado, y es la decisión correcta.** El sistema se
niega a incorporar al expediente un PDF traído de internet sin escanear. No lo estropees.

## Decisión tomada (2026-07-17)

> **ClamAV se pospone.** Mientras tanto, se aceptan documentos **sin escanear** cuando procedan de
> fuentes oficiales conocidas, marcándolos como no escaneados de forma visible y trazable.

Razón: los pliegos provienen de `contrataciondelestado.es`, la plataforma oficial de contratación
del Estado; el riesgo es bajo y no compensa mantener bloqueada la funcionalidad completa.

**El riesgo residual que hay que documentar sin adornos:** el servidor no es la víctima probable —
es el vector. Estos PDF los descargan analistas en equipos Windows/macOS y se adjuntan como
evidencia a informes. Si un documento fuese malicioso, Oracle sería quien se lo entrega. Además, la
extracción de texto parsea el PDF en el servidor, y los parsers de PDF tienen historial de
vulnerabilidades. Que el riesgo sea bajo no lo convierte en cero, y la decisión debe quedar escrita
como lo que es: **una excepción temporal con riesgo asumido**, no una mejora.

---

## Alcance A — Excepción explícita, acotada y configurable

Permite aceptar un documento con `scan_status = "not_configured"` **solo** si se cumplen todas:

1. Un ajuste de configuración lo autoriza explícitamente (algo como
   `DOCUMENT_ALLOW_UNSCANNED_OFFICIAL_SOURCES`), **por defecto desactivado**. Que haya que
   encenderlo a propósito y quede en el `.env`, no enterrado en el código.
2. El documento procede de una **fuente oficial en lista blanca** (el host de
   `contrataciondelestado.es`; usa el `source_uri` que ya se guarda en `metadata_json`). Un
   documento de cualquier otro origen sigue exigiendo `clean`.
3. `scan_status` es exactamente `not_configured`. Si es `infected` o `error`, **se rechaza
   siempre**, con o sin flag: un antivirus que dice «infectado» no se ignora jamás.

Cuando `DOCUMENT_CLAMAV_HOST` esté configurado, el flag no debe poder relajar nada: si hay
antivirus, manda el antivirus.

## Alcance B — Que se vea que no está escaneado

Un documento aceptado sin escanear no puede parecer uno verificado. Decide el mecanismo y
documéntalo, pero exijo:

- [ ] Queda registrado en el documento (`scan_result` ya es JSONB: el motivo, la fuente y que se
      aceptó bajo excepción).
- [ ] **Se ve en la interfaz** allí donde el usuario vaya a abrir o descargar el documento: un
      distintivo claro tipo «No escaneado · fuente oficial», no un tooltip escondido.
- [ ] Si el documento se cita como evidencia en un informe, la condición de no escaneado viaja con
      la cita. La trazabilidad es el producto (AGENTS.md §9): un PDF sin escanear citado como
      evidencia verificada sería exactamente la clase de mentira que este proyecto no se permite.
- [ ] Un `AuditEvent` por cada aceptación bajo excepción: quién, cuándo, qué documento, qué fuente.

## Alcance C — El mensaje de error miente

«El documento oficial no quedó disponible» es falso: el documento está `ready`, descargado y
disponible. Lo que falta es el antivirus. Con la excepción desactivada (el caso por defecto), el
error debe decir la verdad y ser accionable: que no hay antivirus configurado y que por eso no se
acepta el documento. Distíngelo además de los casos `infected` y `error`, que son cosas muy
distintas y hoy se confunden en el mismo mensaje.

## Alcance D — Dejar ClamAV listo para cuando toque

No lo despliegues ahora, pero deja el camino hecho:

- Documenta en `docs/operations/` cómo añadir ClamAV (servicio en `compose.prod.yml`, variable
  `DOCUMENT_CLAMAV_HOST`, y el coste: la base de firmas pide ~1–1,5 GB de RAM, y el servidor tiene
  3,7 GB totales con ~2,2 GB libres, así que probablemente exija ampliar el plan del host).
- Anota en `OPEN_QUESTIONS.md` la deuda: la excepción del Alcance A debe retirarse cuando ClamAV
  esté en marcha, y quién decide cuándo.

---

## Criterios de aceptación

- [ ] Con el flag activado, el informe documental de `EMERGENCIACR2026/671` **termina `succeeded`**,
      con filas en `documents`, texto extraído y citado.
- [ ] Con el flag desactivado (por defecto), sigue rechazando y el mensaje dice la verdad.
- [ ] Un documento `infected` o `error` se rechaza **con el flag activado**. Test que lo pruebe.
- [ ] Un documento de un host no oficial se rechaza con el flag activado. Test que lo pruebe.
- [ ] La condición de no escaneado se ve en la interfaz y viaja con la evidencia.
- [ ] Decisión y riesgo asumido registrados en `DECISIONS.md`, con la fecha y quién la tomó.
- [ ] `scripts/api-test.sh --unit` **ejecutado** (`uv` está en `~/.local/bin/uv`), más
      lint/typecheck/tests del frontend si lo tocas.

## No hacer

- **No elimines la comprobación de `scan_status`.** La excepción es acotada y por configuración; el
  fallo cerrado sigue siendo el comportamiento por defecto.
- No aceptes `infected` ni `error` bajo ninguna circunstancia.
- No amplíes la lista blanca más allá de las fuentes oficiales de contratación que hoy se usan.
- No presentes un documento sin escanear como verificado en ningún punto del producto.
- No despliegues ClamAV en este prompt: está pospuesto por decisión del responsable.
