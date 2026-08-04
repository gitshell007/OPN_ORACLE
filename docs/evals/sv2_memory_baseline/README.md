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
| `v1/runs/` | Salidas de cada medición (`run_*.json` / `run_*.md`, `LATEST.*`) |
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
```

Credenciales: se leen de `ORACLE_CREDS_PATH` o, por defecto, vía SSH desde
`root@oracle-dev.opnconsultoria.com:/root/sv2_demo_owner_credentials.txt`.
**No se commitean secretos.**

Variables útiles: `ORACLE_BASE_URL`, `DOSSIER_ID`, `TENANT_ID`, `ASK_TIMEOUT_S`.

## Qué reporta

- **Tasa de acierto factual** (preguntas no-trampa)
- **Tasa de abstención correcta** en trampas («no consta…»)
- **Citas por respuesta** (media y lista)
- **Latencia p50 / p95 / media** del camino Preguntar
- **Comparación carpeta** en las 5 preguntas marcadas `folder_compare: true`:
  grep local del corpus vs respuesta con memoria (síntesis, citas, velocidad)

## Criterios

Cada pregunta declara `must_contain` y/o `must_any_groups` (hechos que están en
`memory.memory_facts` / chunks del demo). Las trampas **no** llevan pista en el
enunciado; el acierto es abstenerse sin inventar.

**No se ajustan prompts ni parámetros para maquillar la primera medición.** Un
número feo es el hallazgo.

## Expediente

- Dossier: Nexus Ibérica Sistemas S.L. (`ab7bba16-3e55-4f35-ad73-0c84e2850688`)
- Tenant demo: `a6edb3c8-0611-4d7a-a6e1-e882c7460539`
- Camino: POST conversación → mensaje → job → `answer_payload` (`memory_mode=augment`)

## Regresión

Tras cualquier cambio de retrieval / allowlist / prompts de Preguntar, volver a
correr el script y comparar `v1/runs/LATEST.json` con la corrida anterior.
El arnés general (`scripts/sv2_golden_path_check.py`) sigue siendo el gate de
camino completo; este baseline es la métrica de **calidad de recuperación**.
