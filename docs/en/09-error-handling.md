# 09 — Error handling & duplicates

Guiding principle: **fail safe, never lose nor partially publish**. At the slightest
doubt, the item is quarantined with its context, the `ERROR` event is audited, and
an operator decides on the replay.

## 1. Error taxonomy

| Category | Examples | Transient? | Treatment |
|-----------|----------|---------------|------------|
| **Transient IO** | file locked by a third party, share unavailable, disk temporarily full | Yes | bounded retry with backoff, then quarantine |
| **Integrity** | payload/clear hash mismatch | No | quarantine + security alert |
| **Cryptographic** | missing key, invalid signature, decryption KO | No (except recoverable missing key) | quarantine + security alert |
| **Configuration** | unknown alias, target base_folder not found, invalid naming pattern | No | quarantine; often fail-fast at startup |
| **Data** | missing/corrupted metadata, incomplete pair, name too long | No | quarantine after `pair_grace_period` |
| **System** | process crash, power outage, service stop | — | recovered by reconciliation ([16](16-disaster-recovery.md)) |

## 2. Retry strategy

```yaml
# (indicative parameters, configurable)
retry:
  max_attempts: 5
  base_delay_seconds: 2
  backoff: exponential      # 2,4,8,16,32
  jitter: true
```
- Retries apply **only to transient errors** (IO). Integrity, crypto, config
  and data errors are **not** retried (deterministic failure).
- The attempt counter is carried by the audit (successive `ERROR` events with
  `details.attempt`) — no in-memory state lost at crash.
- On attempt exhaustion → quarantine.

## 3. Quarantine

Structure of a quarantined item:
```text
runtime/error/<technical_id>/
├── payload.<ext>           # or source file depending on the step
├── metadata.meta.json      # snapshot if available
└── error.json              # {step, exception_type, message, attempts, ts, context}
```
- **Never auto-deleted** (`retention.error_days: 0` by default): requires a human
  decision.
- The file's audit keeps the terminal `ERROR` event with `quarantine_path`.

## 4. Replay

Administration tool `filerouter replay <technical_id>`:
1. Re-reads `error.json` and the metadata.
2. Puts the item back in `staging/` (outbound) or `processing/` (inbound) with the **same**
   `technical_id`.
3. The pipeline resumes; idempotence guarantees no double publication.
4. A replay `DETECTED`/`RECEIVED_*` audit event is added (with `details.replay:true`).

## 5. Duplicate handling

A duplicate = a file whose **same content** or **same `technical_id`** has already reached
a terminal state.

### 5.1 Detection
- **By `technical_id`**: if a `*.audit.json` already exists with a terminal success
  event, a reappearance is a duplicate (typical case: unintended replay, transport
  re-emission).
- **By content**: key `clear_file_hash` + `base_folder_alias` + `relative_path`. Allows
  spotting a same file detected twice under two paths/timings.

### 5.2 Policy
```yaml
duplicates:
  outbound_policy: skip      # skip | reprocess | error
  inbound_policy: skip       # skip | overwrite | error
  index: runtime/dedup       # lightweight FS index (marker files per hash)
```
- **Outbound**: a same already-routed content is by default **skipped** (`skip`, audited), avoiding
  re-emissions.
- **Inbound**: a delivery whose target file already exists identically (same
  `clear_file_hash`) is **skipped**; if the content differs, `inbound_policy` decides
  (`overwrite` versioned, or `error`/quarantine for arbitration).
- **Database-free dedup index**: a directory `runtime/dedup/<hash[:2]>/<hash>` contains
  marker files (technical_id + timestamp). Atomic `O_EXCL` creation =
  first-come-wins, purged per retention. No database.

### 5.3 Idempotence of inbound deliveries
The final move to the business directory uses `os.replace`; re-delivering the same
content rewrites an identical file (observable no-op). To keep a divergent
version, the `overwrite` policy writes `name (technical_id).ext` and audits the conflict.

## 6. Error boundaries

- Each item is processed in an **isolated context**: an error on one file never
  affects the others.
- A **global** error (invalid config on reload, crypto backend KO) switches the
  service into **degraded/clean-stop** mode rather than processing incorrectly (fail
  safe). The admin is alerted ([08](08-observability.md)).
