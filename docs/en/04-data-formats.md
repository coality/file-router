# 04 — Data formats

This document defines the **naming convention**, the full structure of the **metadata JSON**
and that of the **audit JSON file**. The machine-checkable schemas are in
[`schemas/`](../schemas/) and reference instances in [`examples/`](../examples/).

## 1. Naming convention

The technical name used in the exchange directories is fully configurable via a
placeholder pattern (see [05 — Configuration](05-configuration.md)).

```yaml
naming:
  pattern: "{flow}_{direction}_{timestamp}_{technical_id}.{extension}"
  timestamp_format: "%Y%m%dT%H%M%S"
  max_length: 120
  technical_id_strategy: ulid   # ulid | uuid4
  charset: portable             # A-Z a-z 0-9 _ - . only
```

### Placeholder catalog

| Placeholder | Source | Example |
|-------------|--------|---------|
| `{flow}` | base_folder alias (or `flow` derived from a mapping) | `PAYMENT` |
| `{direction}` | `OUT` (outbound) / `IN` (inbound) | `OUT` |
| `{timestamp}` | clock at detection, `timestamp_format` format | `20260608T120000` |
| `{technical_id}` | unique identifier (ULID/UUIDv4) | `ABC123` |
| `{extension}` | original extension, without the dot | `csv` |
| `{base_folder_alias}` | raw alias | `PAYMENT` |
| `{source_site}` / `{target_site}` | sites from the config | `PARIS` |

### Constraints
- **Support-readable**; length **controlled** via `max_length` (the render is rejected,
  audited `ERROR`, and the item is quarantined if the name exceeds it).
- **Independent of the business tree**: the business path never appears in the name;
  it is carried by the metadata.
- **Mandatory unique identifier**: `{technical_id}` is required in any pattern (validated at
  startup).
- **Portability**: `charset: portable` forbids the characters that are problematic on Windows
  (`< > : " / \ | ? *`), spaces and reserved names (`CON`, `PRN`, `AUX`, `NUL`, …).
- **Reversibility**: the original name is not derived from the technical name; it is restored
  from `original_filename` in the metadata. The technical name can therefore be purely
  opaque with no loss of information.

### Payload / metadata pairing
The payload and its metadata share the same stem, the metadata adding `.meta.json`:

```text
PAYMENT_OUT_20260608T120000_ABC123.csv
PAYMENT_OUT_20260608T120000_ABC123.csv.meta.json
```

> Variant accepted by the schema: `..._ABC123.meta.json` (without repeating the
> payload extension). The effective format is set by `naming.meta_suffix` in the config. The pair is
> always co-located and moved atomically together.

## 2. Metadata JSON structure

The metadata is a superset of the minimal required fields. Schema:
[`schemas/metadata.schema.json`](../schemas/metadata.schema.json).

```json
{
  "schema_version": "1.0",
  "technical_id": "ABC123",
  "direction": "OUT",
  "source_site": "PARIS",
  "target_site": "FRANKFURT",
  "base_folder_alias": "PAYMENT",
  "relative_path": "clients/contracts/v5/production/2026/06/exports/batch01",
  "original_filename": "file.csv",
  "technical_filename": "PAYMENT_OUT_20260608T120000_ABC123.csv",
  "extension": "csv",
  "encrypted": true,
  "size_bytes": 184320,
  "clear_file_hash":   { "algorithm": "SHA-256", "value": "…64 hex…" },
  "payload_file_hash": { "algorithm": "SHA-256", "value": "…64 hex…" },
  "encryption": {
    "scheme": "OpenPGP",
    "recipient_key_ids": ["0xDEADBEEF"],
    "signing_key_id": "0xCAFEBABE",
    "signed": true,
    "key_epoch": "2026-Q2"
  },
  "naming": {
    "pattern": "{flow}_{direction}_{timestamp}_{technical_id}.{extension}",
    "timestamp": "20260608T120000"
  },
  "creation_date": "2026-06-08T12:00:00Z",
  "producer": { "app": "FileRouter", "version": "1.0.0", "host": "SRV-A" }
}
```

### Required fields (mandated minimum)
`technical_id`, `source_site`, `target_site`, `base_folder_alias`, `relative_path`,
`original_filename`, `encrypted`, `creation_date`, plus `clear_file_hash` and
`payload_file_hash` (mandated by section [07 — Hashing](07-hashing.md)).

### Rules
- `relative_path` is **POSIX-normalized** (`/` separators), without `.`/`..`, never absolute —
  guaranteeing safe transport between Windows and Linux.
- `encryption` is required if `encrypted == true`, forbidden otherwise.
- When `encrypted == false`, `payload_file_hash == clear_file_hash` (the payload is the clear).
- `creation_date` is in **UTC ISO-8601** (`Z`).

## 3. Audit JSON file structure

The audit is in **append-only JSON-Lines**: one JSON line per event, never rewritten.
File: `runtime/audit/<technical_id>.audit.json`. Schema:
[`schemas/audit.schema.json`](../schemas/audit.schema.json).

```json
{"technical_id":"ABC123","seq":1,"event":"DETECTED","ts":"2026-06-08T12:00:00.001Z","direction":"OUT","host":"SRV-A","actor":"OutboundProcessor","details":{"source_abspath":"D:\\interfaces\\...\\file.csv","base_folder_alias":"PAYMENT"}}
{"technical_id":"ABC123","seq":2,"event":"HASH_COMPUTED","ts":"2026-06-08T12:00:00.120Z","host":"SRV-A","details":{"target":"clear","algorithm":"SHA-256","value":"…"}}
{"technical_id":"ABC123","seq":3,"event":"ENCRYPTED","ts":"2026-06-08T12:00:00.480Z","host":"SRV-A","details":{"recipient_key_ids":["0xDEADBEEF"],"signing_key_id":"0xCAFEBABE"}}
{"technical_id":"ABC123","seq":4,"event":"HASH_COMPUTED","ts":"2026-06-08T12:00:00.500Z","host":"SRV-A","details":{"target":"payload","algorithm":"SHA-256","value":"…"}}
{"technical_id":"ABC123","seq":5,"event":"RENAMED","ts":"2026-06-08T12:00:00.520Z","host":"SRV-A","details":{"technical_filename":"PAYMENT_OUT_20260608T120000_ABC123.csv"}}
{"technical_id":"ABC123","seq":6,"event":"MOVED_TO_EXCHANGE_OUT","ts":"2026-06-08T12:00:00.560Z","host":"SRV-A","details":{"path":"D:\\FileRouter\\exchange_out\\PAYMENT_OUT_20260608T120000_ABC123.csv"}}
{"technical_id":"ABC123","seq":7,"event":"ARCHIVED","ts":"2026-06-08T12:00:00.600Z","host":"SRV-A","details":{"archive_path":"runtime/archive/2026/06/08/ABC123__file.csv"}}
```

### Fields of an event
| Field | Type | Description |
|-------|------|-------------|
| `technical_id` | string | Correlation (identical to the file name). |
| `seq` | int | Monotonic per-file sequence number (detects gaps). |
| `event` | enum | See the vocabulary below. |
| `ts` | string | UTC ISO-8601 with milliseconds. |
| `direction` | enum | `OUT` / `IN` (on the first event at minimum). |
| `host` | string | Host that produced the event. |
| `actor` | string | Emitting component. |
| `details` | object | Event-specific payload. |

### Event vocabulary (exhaustive and minimal)
`DETECTED`, `HASH_COMPUTED`, `COMPRESSED`, `ENCRYPTED`, `RENAMED`,
`MOVED_TO_EXCHANGE_OUT`, `RECEIVED_FROM_EXCHANGE_IN`, `HASH_VALIDATED`, `DECRYPTED`,
`DECOMPRESSED`, `RESTORED`, `MOVED_TO_BUSINESS_FOLDER`, `ARCHIVED`, `ERROR`.

> `COMPRESSED` (outbound) and `DECOMPRESSED` (inbound) are emitted only when a
> compression rule applies. The metadata then carries `compressed: true` and
> `compression: { "algorithm": "gzip" }`.

An `ERROR` event carries `details.step`, `details.exception_type`, `details.message` and
`details.quarantine_path`. Any `ERROR` is **terminal** for the current pipeline until
the operator has replayed the item.

### Reconstructibility
The **full history** of a file is reconstructed by re-reading its `*.audit.json` in
`seq` order. The presence of a terminal event (`MOVED_TO_*` or `ARCHIVED` on the
success side, `ERROR` on the failure side) indicates the final state; its absence indicates an interrupted
processing that reconciliation will handle.
