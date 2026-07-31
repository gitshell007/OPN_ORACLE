# MEMSOL-10 · Evals, UAT y seguridad

## Evals offline (fixtures)

- Preguntas exactas: CIF, CPV, importes, fechas, nombres
- Citas solo del snapshot
- Insuficiencia de evidencia sin inventar
- Aislamiento tenant A/B
- Inyección en PDF/HTML/email/señal

## UAT checklist

- [ ] Intake market global ISO-2 + accept intent
- [ ] Actividad lista monitores/jobs
- [ ] Pregunta 202 + recarga conserva estado
- [ ] Informe custom brief → pending → (mock) ready
- [ ] Cancel/retry
- [ ] IDOR 404
- [ ] WCAG smoke panel Actividad

## Seguridad

- RLS/tenant en tablas nuevas
- Redacción antes de cloud
- Sin secretos en logs

## Mutaciones obligatorias

tenant filter, CAS claim, enabled=false, no-auto-activate.
