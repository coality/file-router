# 05 — Configuration

All configuration is externalized in **YAML** format. **No business parameter is
hard-coded.** The file is validated at startup against
[`schemas/config.schema.json`](../schemas/config.schema.json); an invalid config aborts
startup (fail-fast). A complete example is provided in
[`examples/config.example.yaml`](../examples/config.example.yaml).

## 1. Configurable sections (overview)

| Section | Role |
|---------|------|
| `instance` | Host identity (site, role), concurrency thresholds. |
| `base_folders` | Business roots (alias + local path). |
| `mappings` | alias↔site/flow tables, inter-server mapping. |
| `exchange` | `exchange_in` / `exchange_out` paths. |
| `runtime` | Location of the `runtime/` tree. |
| `naming` | Technical naming convention. |
| `hashing` | Algorithm (SHA-256) and verification options. |
| `encryption` | OpenPGP backend, keyrings, encryption rules. |
| `inclusion` / `exclusion` | Glob rules for file eligibility. |
| `archival` | Archival policy for outbound sources. |
| `retention` | Retention of `archive/`, `audit/`, `logs/`. |
| `scanning` | Scan frequency, stability, pairing grace. |
| `locking` | Lock TTL, heartbeat interval. |
| `logging` | Log streams, levels, rotation, compression. |
| `recovery` | Reconciliation/recovery parameters. |

## 2. Section detail

### 2.1 `instance`
```yaml
instance:
  site: PARIS            # default source_site for files produced here
  role: both             # outbound | inbound | both
  workers: 8             # worker pool size
  worker_type: thread    # thread | process
```

### 2.2 `base_folders`
An **unlimited** number of roots, each file belonging to exactly one.
```yaml
base_folders:
  - alias: SAP_FR
    path: D:\interfaces\sap\fr
  - alias: CRM_DE
    path: E:\interfaces\crm\de
  - alias: PAYMENT
    path: F:\payments
```
> On another server, the **alias stays identical** but the `path` differs — this is the
> inter-server mapping mechanism. See [00 §4](00-overview.md).

### 2.3 `mappings`
```yaml
mappings:
  flows:                 # alias → flow label for {flow} in naming
    PAYMENT: PAYMENT
    SAP_FR: SAPFR
  routing:               # alias → target site (populates target_site)
    PAYMENT: FRANKFURT
    SAP_FR: PARIS
```

### 2.4 `exchange` & `runtime`
```yaml
exchange:
  out: D:\FileRouter\exchange_out   # flat, no subtree
  in:  D:\FileRouter\exchange_in    # flat, no subtree
runtime:
  root: D:\FileRouter\runtime       # same volume as exchange (atomic publication)
```

### 2.5 `naming`
```yaml
naming:
  pattern: "{flow}_{direction}_{timestamp}_{technical_id}.{extension}"
  timestamp_format: "%Y%m%dT%H%M%S"
  max_length: 120
  technical_id_strategy: ulid
  charset: portable
  meta_suffix: ".meta.json"   # applied to the full technical name
```

### 2.6 `hashing`
```yaml
hashing:
  algorithm: SHA-256       # mandated
  chunk_size_bytes: 1048576
  verify_inbound: true     # replay of the payload then clear verifications
```

### 2.7 `encryption`
```yaml
encryption:
  backend: gnupg           # gnupg | pgpy | noop (noop = no encryption)
  gnupg_home: D:\FileRouter\keys\gnupg
  signing_key_id: "0xCAFEBABE"
  require_signature_inbound: true
  rules:
    - base_folder_alias: SAP_FR
      path_pattern: "confidential/**"
      enabled: true
      recipient_key_ids: ["0xDEADBEEF"]
    - base_folder_alias: PAYMENT
      path_pattern: "**"
      enabled: true
      recipient_key_ids: ["0xDEADBEEF"]
```
Key model, rotation and signing details: [06 — Encryption](06-encryption.md).

### 2.8 `inclusion` / `exclusion`
```yaml
inclusion:
  patterns: ["**/*"]            # eligible by default
exclusion:
  patterns:
    - "**/*.tmp"
    - "**/*.part"
    - "**/~$*"                  # Office temporary files
    - "**/.DS_Store"
```
> Exclusion takes precedence over inclusion. The exchange files (`*.meta.json`) are
> handled implicitly and are never treated as business sources.

### 2.9 `archival` & `retention`
```yaml
archival:
  source_policy: archive        # archive | delete
  archive_layout: "%Y/%m/%d"    # subtree of runtime/archive
retention:
  archive_days: 30
  audit_days: 365
  logs_days: 90
  error_days: 0                 # 0 = never auto-deleted (operator action required)
```

### 2.10 `scanning` & `locking`
```yaml
scanning:
  interval_seconds: 5
  stability_checks: 3
  stability_interval_seconds: 2
  pair_grace_period_seconds: 30
locking:
  lock_ttl_seconds: 300
  heartbeat_interval_seconds: 30
```

### 2.11 `logging`
```yaml
logging:
  format: jsonl
  streams:
    technical:  { level: INFO,    path: logs/technical }
    functional: { level: INFO,    path: logs/functional }
    security:   { level: INFO,    path: logs/security }
    admin:      { level: INFO,    path: logs/admin }
  rotation:
    when: daily            # daily | size
    max_bytes: 104857600   # if when=size
    backup_count: 30
  compression: gzip        # none | gzip
```

### 2.12 `recovery`
```yaml
recovery:
  reconcile_on_start: true
  reconcile_interval_seconds: 300
  temp_orphan_max_age_seconds: 600
```

## 3. Validation & reload
- **Startup validation** against the JSON Schema + semantic checks (unique aliases,
  naming pattern containing `{technical_id}`, existing paths, `runtime`/`exchange` on the
  same volume, encryption keys present in the keyring).
- **Reload**: an administration signal (`SIGHUP` on Linux, a service control
  command on Windows) triggers a revalidation then an atomic swap of the in-memory
  config. An invalid config is **rejected** and the previous one stays active (never a
  startup/reload on a broken config).
