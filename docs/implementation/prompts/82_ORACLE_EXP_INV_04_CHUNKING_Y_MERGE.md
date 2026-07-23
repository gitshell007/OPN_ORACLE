# Prompt 82 · ORACLE-EXP-INV-04 · chunking y merge candidato

## Objetivo

Continuar INV-03 resolviendo el fallo observado de salidas largas y truncadas. La fase debe:

1. dividir las páginas candidatas en trozos pequeños y reproducibles;
2. pedir a Ollama un contrato compacto por trozo, no por documento completo;
3. validar cada trozo contra su texto exacto;
4. fusionar en Python hacia `placsp-participation-candidate/v2`;
5. incluir parámetros de inferencia en fingerprints de caché;
6. ejecutar un smoke real acotado sobre documentos ya autorizados internamente;
7. mantener toda salida como candidata, con revisión humana obligatoria y sin precision/recall.

## Invariantes

- El modelo no fusiona identidades ni decide completitud documental.
- Un trozo no puede citar texto fuera del propio trozo.
- El merge final vuelve a validarse contra páginas físicas.
- Cambiar `num_ctx`, tokens de salida o tamaño de chunk invalida caché.
- Candidatos válidos no promueven actores, participaciones, evidencias ni informes.
- Precision, recall y F1 siguen prohibidos hasta gold A/B adjudicado.

## Gates

- `chunk/v1` solo habilita extracción candidata.
- `candidate/v2` sigue siendo el formato final revisable.
- Si hay citas inválidas, roles débiles o `unknown`, el resultado se conserva para revisión pero no
  se interpreta como hecho.
