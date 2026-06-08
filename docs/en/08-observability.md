# 08 — Observability

## 1. Log streams

Four distinct streams, all in **JSON Lines** format (one JSON line per event),
correlatable by `technical_id`.

| Stream | Content | Audience |
|------|---------|--------|
| **technical** | Execution detail: pipeline steps, timings, sizes, retries, IO. | Dev / L3 |
| **functional** | Business view: file detected/routed/delivered, alias, sites, direction. | Operations / business |
| **security** | Crypto: encryption, signing, verification, key/epoch, integrity failures, access. | CISO / SOC |
| **admin** | Service lifecycle: start/stop, config reload, reconciliation, purges. | Administration |

### Typical log line
```json
{"ts":"2026-06-08T12:00:00.560Z","level":"INFO","stream":"functional","event":"ROUTED_OUT","technical_id":"ABC123","base_folder_alias":"PAYMENT","direction":"OUT","target_site":"FRANKFURT","host":"SRV-A","msg":"file routed to exchange_out"}
```
Common fields: `ts` (UTC ISO-8601 ms), `level`, `stream`, `event`, `technical_id`, `host`,
`msg`, plus specific fields.

## 2. Correlation

The **`technical_id`** is the cross-cutting correlation key: logs (4 streams), metadata and audit
share this key. Reconstructing the history of a file =
`grep <technical_id>` over the logs + reading `runtime/audit/<technical_id>.audit.json`.

> Logs ≠ audit. The **audit** is the durable, structured per-file source of truth (see
> [04](04-data-formats.md)); the **logs** are operational observability (volume,
> diagnostics, security) subject to rotation/retention.

## 3. Rotation, compression, retention

- **Rotation**: by date (`daily`) or by size (`max_bytes`), configurable `backup_count`.
- **Compression**: gzip of the rotated files (`logging.compression`).
- **Retention**: deletion beyond `retention.logs_days` (see [11](11-archival-retention.md)).
- Log writing is **non-blocking** for the pipeline (bounded queue +
  dedicated writer); in case of disk saturation, the **security** stream is prioritized and an
  admin alert is raised.

## 4. Metrics (monitoring)

Exposed via a JSON metrics file periodically refreshed in `runtime/` and/or an
optional local endpoint (Prometheus textfile). No mandated network dependency.

| Metric | Type | Use |
|----------|------|-------|
| `files_processed_total{direction}` | counter | throughput |
| `files_error_total{step}` | counter | error rate per step |
| `quarantine_current` | gauge | items in `error/` (should tend toward 0) |
| `processing_backlog{queue}` | gauge | staging/exchange depth |
| `processing_duration_seconds` | histogram | end-to-end latency |
| `stale_locks_reclaimed_total` | counter | crash signal |
| `last_reconcile_ts` | gauge | reconciliation freshness |
| `oldest_pending_age_seconds` | gauge | stall detection |

## 5. Monitoring policy

| Signal | Alert threshold | Severity | Action |
|--------|----------------|----------|--------|
| Service stopped | absence of admin heartbeat | Critical | restart / on-call |
| `quarantine_current` > 0 | > 0 for N min | Major | analyze `error/`, replay |
| `files_error_total` (integrity/signature) | any occurrence | Critical (security) | SOC investigation |
| `oldest_pending_age_seconds` | > SLA threshold | Major | stall/backlog |
| Disk saturation (runtime/exchange) | < free threshold | Critical | purge/extend |
| `last_reconcile_ts` too old | > 2× interval | Minor | check the loop |
| Key rotation failure / expired key | nearing expiration | Major | rotation ([06](06-encryption.md)) |

### Health check
A lightweight health endpoint (`runtime/health.json` file or exit code of a
`filerouter health` command) returns: service state, crypto backend OK (self-test), backlog,
quarantine, reconciliation freshness. Usable by an external monitoring probe.
