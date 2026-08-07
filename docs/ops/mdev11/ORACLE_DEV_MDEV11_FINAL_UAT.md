# MDEV-11 final UAT · Oracle Dev evidence

- Release: `20260802T040823Z-native-4b454e1`
- SHA: `4b454e1c88fc678b443a18b1c4f0a905b0630fb2`
- IC production: **disabled** → `https://signal.opnconsultoria.com/api/v1/oracle`
- IC canary: **active** → `https://signal-dev.opnconsultoria.com`
- DMP canary dossier `726bfb3d-090e-470b-b343-596cf5604ed6`: **shadow** `W/"dmp-mdev10-v1"` v1
- Augment: **not activated** (fail-closed correct given CAS/fencing residual debt + no owner UAT)
- UI `/app`: HTTP 200 login page only; no owner session (A14)
- OpenRouter usage 2h sample: 0
- Services api/web/worker/beat: active
