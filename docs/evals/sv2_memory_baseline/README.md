# SV2 · Baseline de recuperación de memoria

Responde con números a: **«¿Es mejor que buscar en la carpeta?»**

Hasta este paquete la única métrica era binaria (4 marcadores del arnés
`sv2_golden_path_check.py`). Eso prueba que *algo* recupera; no cuánto ni qué se
pierde, ni si el sistema se abstiene cuando el hecho no está en el expediente.

## Contenido

| Ruta | Qué es |
|------|--------|
| `v1/eval_set.json` | Set versionado (~18 preguntas) con criterios de acierto verificables |
| `../../fixtures/sv2_memory_baseline/v1/dossier_source_corpus.txt` | Corpus fuente del expediente (chunks) para la comparación «carpeta» |
| `v1/runs/run_*.json` | **Corridas inmutables** (mayor timestamp = vigente) |
| `v1/runs/LATEST.*` | **Solo symlink local** (gitignored) → último `run_*` |
| `v1/FIRST_MEASUREMENT.md` | Nota histórica de la 1ª corrida (53 %); no es la vigente |
| `scripts/sv2_memory_baseline.py` | Corredor ejecutable |

## Cómo medir (repetible)

Desde la raíz del repo Oracle (worktree o checkout con el script):

```bash
# Candado local (misma convención que la suite):
mkdir /tmp/oracle-local-suite.lockdir || exit 1
trap 'rmdir /tmp/oracle-local-suite.lockdir' EXIT

# Medición completa (coste 0 · Titan local vía Signal):
python3 scripts/sv2_memory_baseline.py

# Smoke de 3 preguntas:
python3 scripts/sv2_memory_baseline.py --limit 3

# Subconjunto:
python3 scripts/sv2_memory_baseline.py --ids Q01,Q12,Q16

# Auto-check del scorer (sin red):
python3 scripts/sv2_memory_baseline.py --dry-score
```

Credenciales: se leen de `ORACLE_CREDS_PATH` o, por defecto, vía SSH desde
`root@oracle-dev.opnconsultoria.com:/root/sv2_demo_owner_credentials.txt`.
**No se commitean secretos.**

Variables útiles: `ORACLE_BASE_URL`, `DOSSIER_ID`, `TENANT_ID`, `ASK_TIMEOUT_S`,
`SCORER_FREEZE_SHA` (opcional; por defecto `git rev-parse --short=12 HEAD`).

## Dueño de la cifra (MEDIR-SHA)

Cada corrida escribe en JSON y MD:

| Campo | Origen |
|-------|--------|
| `release_id` | `GET /api/v1/meta` → `release` del entorno medido |
| `release_sha` | SHA embebido en `release` (o campo git del meta) |
| `base_url` | `ORACLE_BASE_URL` |
| `eval_set_id` / `eval_set_version` | del set |
| `measured_at` | marca de tiempo con zona `Europe/Madrid` |
| `scorer_freeze_sha` | commit del scorer usado |
| `statement` | frase lista para propuesta comercial |

Si `/api/v1/meta` no devuelve release, **la corrida aborta** (exit 4). No se mide a ciegas.

### Política LATEST

**Decisión:** `LATEST.json` / `LATEST.md` dejan de ser ficheros de contenido
versionados. El corredor crea symlinks locales (gitignored) al último `run_*`.
La corrida vigente es siempre el `run_*.json` de mayor timestamp. Así un commit
de otro tema (`fix(ai): …`) no puede sobrescribir la cifra en git.

## Qué reporta

- **Tasa de acierto factual** (preguntas no-trampa)
- **Tasa de abstención correcta** en trampas («no consta…», «no hay información
  disponible en las evidencias autorizadas…»)
- **Citas por respuesta** (media y lista)
- **Latencia p50 / p95 / media** del camino Preguntar
- **Comparación carpeta** en las 5 preguntas marcadas `folder_compare: true`
- **Statement** literal con versión y fecha

## Criterios y freeze del scorer

Cada pregunta declara `must_contain` y/o `must_any_groups`. Las trampas ganan
si la respuesta se abstiene. El scorer une `DEFAULT_ABSTENTION_MARKERS` del
corredor con `abstention_markers` de la pregunta.

**Regla:** ampliar el scorer y medir en la misma pasada sin commit intermedio
está prohibido. Congelar (commit), citar el SHA, y entonces medir.

## Expediente

- Dossier: Nexus Ibérica Sistemas S.L. (`ab7bba16-3e55-4f35-ad73-0c84e2850688`)
- Tenant demo: `a6edb3c8-0611-4d7a-a6e1-e882c7460539`
- Camino: POST conversación → mensaje → job → `answer_payload` (`memory_mode=augment`)
- **No tocar** el expediente ITURRI ni los de evidencia de mercado del informe.

## CI

Workflow `.github/workflows/sv2-memory-baseline.yml`:

1. **Siempre** (PR / push paths / manual): tests unitarios del scorer + `--dry-score`.
2. **Manual / schedule** con secretos (`ORACLE_BASELINE_CREDS` + red a oracle-dev):
   corrida viva y upload de `run_*.json` como artefacto.
3. Sin secretos de acceso a oracle-dev, la corrida viva **no es viable en
   `ubuntu-latest` público** (el host no alcanza credenciales SSH del dev ni
   debe guardarlas en el repo). El job unitario sí es verde y gratuito.

## Regresión

Tras cualquier cambio de retrieval / allowlist / prompts de Preguntar, volver a
correr el script y comparar el nuevo `run_*.json` con el anterior inmutable.
El arnés general (`scripts/sv2_golden_path_check.py`) sigue siendo el gate de
camino completo; este baseline es la métrica de **calidad de recuperación**.
