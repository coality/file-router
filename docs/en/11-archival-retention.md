# 11 — Archival & retention

## 1. Archival policy for outbound sources

At the end of a successful outbound processing (`MOVED_TO_EXCHANGE_OUT`), the business source is
handled according to `archival.source_policy`:

| Policy | Behavior |
|-----------|--------------|
| `archive` | Atomic move of the source to `runtime/archive/<archive_layout>/<technical_id>__<original_filename>`; `ARCHIVED` event. |
| `delete` | Deletion of the source; no `ARCHIVED` event. |

```yaml
archival:
  source_policy: archive
  archive_layout: "%Y/%m/%d"      # e.g. runtime/archive/2026/06/08/
```

- Archival enables **reprocessing** and **audit**; deletion suits flows where
  the source is already traced elsewhere.
- The archive keeps the `technical_id` in the name for correlation with the audit and the logs.

## 2. Data subject to retention

| Data | Location | Parameter | Default |
|--------|-------------|-----------|--------|
| Archived sources | `runtime/archive/` | `retention.archive_days` | 30 |
| Per-file audit | `runtime/audit/` | `retention.audit_days` | 365 |
| Logs (4 streams) | `logs/` | `retention.logs_days` | 90 |
| Quarantine | `runtime/error/` | `retention.error_days` | 0 (never auto) |
| Dedup | `runtime/dedup/` | `retention.dedup_days` | = archive_days |

> The audit has the longest retention because it constitutes the **legal audit
> trail**. The quarantine is never auto-purged (human action required).

## 3. Purge mechanism (no database)

- **Periodic sweep** (`recovery.reconcile_interval` or a dedicated task) that traverses the
  relevant directories and deletes files whose age (mtime or date in the path)
  exceeds the threshold.
- **Idempotent** and **interruptible** purge: unit-by-unit deletion; a crash during
  the purge has no side effect (relaunched at the next cycle).
- Purges are **audited** in the **admin** stream (number of items, bytes freed, oldest
  retained).
- Purge order under disk pressure: rotated logs > archive > dedup. The audit and
  the quarantine are never purged by disk pressure (only by their explicit
  retention threshold).

## 4. Compliance & exceptions

- Thresholds are **per environment** (a regulated flow may impose `audit_days: 3650`).
- A **legal hold** is achievable by moving the artifacts of a
  `technical_id` to a directory excluded from the purge (`runtime/hold/`), an audited operation.
- No purge deletes an item still referenced by an in-progress processing (lock
  present): the purge ignores active `processing/`/`staging/`.

## 5. Sizing

The spec recommends documenting, per environment: average/peak daily volume,
average file size, and deriving from these the required space =
`Σ(retention_days × daily_volume)` for archive + audit + logs, with a margin for the
quarantine and the peaks. A disk alert (< free threshold) is mandatory
([08 — Monitoring](08-observability.md)).
