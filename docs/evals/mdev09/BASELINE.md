# MDEV-09 baseline (Oracle view, provisional)

## Status

`unavailable_degraded`

Durable bilateral memory / MDEV-08 productive reports are not green. Oracle release
preflight verifies RT-07/08/09/10(/12/15) hashes against Signal assets but does **not**
claim an observed retrieval baseline.

## Timeout ladder (effective, aligned)

```
provider_attempt (240s)
  < signal_request_deadline / SIGNAL_AI_TIMEOUT (300s)
  < oracle_http_retry_budget (680s)
  < CELERY_TASK_SOFT_TIME_LIMIT (690s)
  < CELERY_TASK_TIME_LIMIT (720s)
  < lease/reconciler (780s = hard + 60)
```

Provider attempt budget is aligned to 240s so the strict ladder holds without inflating
Celery/lease outer timeouts.
