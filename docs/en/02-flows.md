# 02 — Flows

This document specifies the **outbound** and **inbound** pipelines as flow
and sequence diagrams. Each step is annotated with the audit event it emits (see
[04 — Data formats](04-data-formats.md)) and the `runtime/` directory the
file occupies (see [03 — State management](03-state-management.md)).

## 1. Outbound pipeline (business → exchange_out)

```mermaid
flowchart TD
    A[File detected in the business directory] --> B[Identify base_folder<br/>longest prefix]
    B --> C[Compute relative_path<br/>pathlib, POSIX-normalized]
    C --> D[Apply processing rules<br/>inclusion/exclusion, encryption rule]
    D --> E[Compute clear_file_hash<br/>SHA-256, streaming]
    E --> F{Encryption<br/>required?}
    F -- yes --> G[Encrypt + sign<br/>CryptoProvider]
    F -- no --> H[payload = clear file]
    G --> I[Compute payload_file_hash<br/>SHA-256]
    H --> I
    I --> J[Generate JSON metadata]
    J --> K[Generate the technical name]
    K --> L[Atomic move of payload + meta<br/>to exchange_out]
    L --> M[Write audit MOVED_TO_EXCHANGE_OUT]
    M --> N{Source policy}
    N -- archive --> O[Move the source to runtime/archive]
    N -- delete --> P[Delete the source]
    O --> Q[Done]
    P --> Q[Done]
```

### Outbound sequence diagram

```mermaid
sequenceDiagram
    autonumber
    participant SC as Scheduler
    participant OP as OutboundProcessor
    participant LK as LockManager
    participant FS as FileStore
    participant HS as Hashing
    participant CR as CryptoProvider
    participant MD as Metadata
    participant AU as Audit

    SC->>OP: dispatch(detected_file)
    OP->>LK: acquire(source lock)
    Note over OP,AU: audit: DETECTED (technical_id assigned)
    OP->>FS: move source → runtime/staging (atomic)
    OP->>OP: identify base_folder + relative_path
    OP->>HS: clear_file_hash = SHA-256(clear)
    Note over OP,AU: audit: HASH_COMPUTED (clear)
    alt encryption rule applies
        OP->>CR: encrypt+sign(clear) → payload
        Note over OP,AU: audit: ENCRYPTED
    else no rule
        OP->>OP: payload = clear
    end
    OP->>HS: payload_file_hash = SHA-256(payload)
    Note over OP,AU: audit: HASH_COMPUTED (payload)
    OP->>MD: build + validate metadata
    OP->>OP: generate the technical name
    Note over OP,AU: audit: RENAMED
    OP->>FS: temp → exchange_out (atomic rename, payload+meta)
    Note over OP,AU: audit: MOVED_TO_EXCHANGE_OUT
    OP->>FS: source → archive OR delete (per config)
    Note over OP,AU: audit: ARCHIVED (if archive)
    OP->>LK: release(lock)
```

### Step ↔ audit ↔ state mapping (outbound)

| # | Step | Audit event | Runtime state |
|---|-------|-------------------|--------------|
| 1 | Detect, assign `technical_id` | `DETECTED` | `staging/` |
| 2 | Identify base_folder | — | `staging/` |
| 3 | Compute relative_path | — | `staging/` |
| 4 | Apply the rules | — | `processing/` |
| 5 | Clear hash | `HASH_COMPUTED` | `processing/` |
| 6 | Encrypt+sign (if rule) | `ENCRYPTED` | `processing/` |
| 7 | Payload hash | `HASH_COMPUTED` | `processing/` |
| 8 | Build metadata | — | `processing/` |
| 9 | Technical name | `RENAMED` | `processing/` → `temp/` |
| 10 | Move to exchange_out | `MOVED_TO_EXCHANGE_OUT` | `exchange_out/` |
| 11 | Archive/delete source | `ARCHIVED` / — | `archive/` or deleted |

## 2. Inbound pipeline (exchange_in → business)

```mermaid
flowchart TD
    A[Payload + meta detected in exchange_in] --> B[Load + validate metadata]
    B --> C[Verify payload_file_hash<br/>SHA-256 of the payload]
    C --> D{Encrypted?}
    D -- yes --> E[Verify signature + decrypt<br/>CryptoProvider]
    D -- no --> F[clear = payload]
    E --> G[Verify clear_file_hash<br/>SHA-256 of the clear]
    F --> G
    G --> H[Resolve the target base_folder<br/>alias → host-local path]
    H --> I[Recompute the business path<br/>base_path / relative_path]
    I --> J[Restore the original file name]
    J --> K[Create missing parent directories]
    K --> L[Atomic move to the business directory]
    L --> M[Write audit MOVED_TO_BUSINESS_FOLDER]
```

### Inbound sequence diagram

```mermaid
sequenceDiagram
    autonumber
    participant SC as Scheduler
    participant IP as InboundProcessor
    participant LK as LockManager
    participant MD as Metadata
    participant HS as Hashing
    participant CR as CryptoProvider
    participant FS as FileStore
    participant AU as Audit

    SC->>IP: dispatch(exchange_in pair)
    IP->>LK: acquire(technical_id lock)
    IP->>MD: load + validate (schema) the metadata
    Note over IP,AU: audit: RECEIVED_FROM_EXCHANGE_IN
    IP->>FS: move the pair → runtime/processing (atomic)
    IP->>HS: verify SHA-256(payload) == payload_file_hash
    Note over IP,AU: audit: HASH_VALIDATED (payload)
    alt encrypted == true
        IP->>CR: verify signature + decrypt → clear
        Note over IP,AU: audit: DECRYPTED
    else
        IP->>IP: clear = payload
    end
    IP->>HS: verify SHA-256(clear) == clear_file_hash
    Note over IP,AU: audit: HASH_VALIDATED (clear)
    IP->>IP: resolve alias → base_folder path
    IP->>IP: business_path = base_path / relative_path
    IP->>IP: filename = original_filename
    Note over IP,AU: audit: RESTORED
    IP->>FS: mkdir -p parents then temp → business (atomic)
    Note over IP,AU: audit: MOVED_TO_BUSINESS_FOLDER
    IP->>LK: release(lock)
```

### Step ↔ audit ↔ state mapping (inbound)

| # | Step | Audit event | Runtime state |
|---|-------|-------------------|--------------|
| 1 | Detect the pair, lock | `RECEIVED_FROM_EXCHANGE_IN` | `exchange_in/` → `processing/` |
| 2 | Load+validate metadata | — | `processing/` |
| 3 | Verify payload hash | `HASH_VALIDATED` | `processing/` |
| 4 | Verify sig + decrypt | `DECRYPTED` | `processing/` |
| 5 | Verify clear hash | `HASH_VALIDATED` | `processing/` |
| 6 | Resolve base_folder | — | `processing/` |
| 7 | Recompute path + restore name | `RESTORED` | `processing/` → `temp/` |
| 8 | Move to the business directory | `MOVED_TO_BUSINESS_FOLDER` | business tree |

## 3. Error path (both pipelines)

Any uncaught failure at any step:

```mermaid
flowchart LR
    X[Failed step] --> Y[Write audit ERROR<br/>with step + exception]
    Y --> Z[Atomic move of artifacts → runtime/error/&lt;technical_id&gt;/]
    Z --> W[Release the lock]
    W --> V[Item visible to the operator,<br/>never deleted, never half-published]
```

Quarantined items are **never** deleted automatically. Recovery and
replay are covered in [09 — Error handling](09-error-handling.md) and
[16 — Disaster recovery](16-disaster-recovery.md).
