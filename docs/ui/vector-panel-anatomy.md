# Anatomía de `.vector-panel` (Vector Command Center)

Contrato opt-in definido por **ORA-UI-PANEL-INSETS**. No aplica a Horizon (`concept-b`).

## Tokens

| Token | Uso | Valor por defecto |
|---|---|---|
| `--vector-panel-pad-x` | Inset horizontal compartido header/cuerpo/strip | `var(--space-4)` (16px) |
| `--vector-panel-pad-y` | Inset vertical del cuerpo | `var(--space-3)` |
| `--vector-panel-pad-y-header` | Inset vertical de cabecera | `var(--space-3)` |

Densidad: `data-density=compact|comfortable` reduce/amplía solo el eje vertical.

## Piezas

| Clase | Rol |
|---|---|
| `.vector-panel > header` | Cabecera con borde inferior e inset horizontal del token |
| `.vector-panel-body` | Cuerpo normal con inset uniforme |
| `.vector-panel-body--stack` | Cuerpo en grid con gap de tokens |
| `.vector-panel-body--flush` | Cuerpo sin padding (tablas, listas edge-to-edge) |
| `.vector-panel-strip` | Franja full-bleed bajo la cabecera; el **texto** sigue el mismo `pad-x` |

El cuerpo normal alinea su inicio horizontal con el contenido de la cabecera.
Los paneles anidados no deben envolver el hijo con un segundo body del padre.

## Excepciones full-bleed (intencionales)

Clasificación de usos productivos que **no** reciben body inset ciego:

| Patrón | Motivo |
|---|---|
| `.full-bleed.vector-panel` (actividad, auditoría IA) | Datatable hasta el borde del panel |
| Listas de filas clickables (attention, change-list, home-compact-row en flush) | Cada fila es una franja edge-to-edge |
| `.actor-discovery-meta` + `.vector-panel-strip` | Banda semántica de intención/tipo |
| Tablas en dossiers-panel / inventory | Superficie de datos densa |
| Métricas / metric tiles fuera de panel o como grid de enlaces | No son cuerpo de texto |

## Migrados a body inset (ORA-UI-PANEL-INSETS)

- `ActorDiscoveryPanel` (empty, lista, avisos, CTA; strip de intención full-bleed)
- `DossierProfilePanel` modo lectura
- `product-dossier` situación
- `DossierOracleSummaryPanel` contenido
- `product-home` onboarding, empty attention, side panels

## Pruebas

Evidencia principal (rutas reales autenticadas, harness E2E):

- `tests/e2e/vector-panel-insets.spec.ts` abre `/app/dossiers/{id}` y
  `/app/dossiers/{id}/actors` con seed `owner@oracle-e2e.test` / Asterion E2E.
- Mide bounding boxes y padding computado (panel, header, body, texto, CTA, strip).
- Capturas en `docs/ui/panel-insets-captures/` nombradas por ruta y viewport
  (`dossier-summary-profile-desktop-1440.png`, etc.).

Auxiliar: el bloque «auxiliary contract fixture» del mismo spec no sustituye
las rutas reales.

CI: el job `frontend-e2e` **no** corre en `push` a `oracle-dev` (solo PR→master
y `workflow_dispatch`). Para evidencia GHA de este E2E hace falta dispatch o PR.

Componentes: body region en profile y actor-discovery (unit).
